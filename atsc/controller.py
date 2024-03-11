#  Copyright 2022 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import time
import random
from atsc.core import *
from atsc import logic, network, constants, serialbus
from loguru import logger
from typing import Set, Iterable
from bitarray import bitarray
from atsc.utils import build_field_message
from jacob.text import post_pend
from atsc.frames import FrameType, DeviceAddress, OutputStateFrame
from collections import defaultdict
from jacob.enumerations import text_to_enum


class Controller:
    
    @property
    def idling(self):
        return not len(self.calls)
    
    def __init__(self, config: dict):
        # controller name (arbitrary)
        self.name = config['device']['name']
        
        # should place calls on all phases when started?
        self.recall_all = config['init']['recall-all']
        
        # loop enable flag
        self.running = False
        
        # local flash transfer relay status
        self.transferred = False
        
        # operation functionality of the controller
        self.mode: OperationMode = text_to_enum(OperationMode, config['init']['mode'])
        
        self.load_switches: List[LoadSwitch] = [LoadSwitch(1), LoadSwitch(2), LoadSwitch(3), LoadSwitch(4),
                                                LoadSwitch(5), LoadSwitch(6), LoadSwitch(7), LoadSwitch(8),
                                                LoadSwitch(9), LoadSwitch(10), LoadSwitch(11), LoadSwitch(12)]
        
        default_timing = self.get_default_timing(config['default-timing'])
        self.phases: List[Phase] = self.get_phases(config['phases'], default_timing)
        self.phase_pool: List[Phase] = self.phases.copy()
        
        self.calls: List[Call] = []
        
        self.rings: List[Ring] = self.get_rings(config['rings'])
        self.barriers: List[Barrier] = self.get_barriers(config['barriers'])
        self.barrier: Optional[Barrier] = None
        self.friend_matrix: Dict[int, List[int]] = self.generate_friend_matrix(self.rings, self.barriers)
        self.cycle_count = 0
        
        self.idle_phases: List[Phase] = self.get_idle_phases(config['idling']['phases'])
        self.idle_serve_delay: float = config['idling']['serve-delay']
        self.idle_timer = logic.Timer(self.idle_serve_delay, step=constants.TIME_INCREMENT)
        self.idle_rising = EdgeTrigger(True)
        
        self.second_timer = logic.Timer(1.0, step=constants.TIME_INCREMENT)
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        cet_delay: float = max(yellow_time, config['init']['cet-delay'] - 1) + 1
        self.cet_timer = logic.Timer(cet_delay, step=constants.TIME_INCREMENT)
        
        # inputs data structure instances
        self.inputs: Dict[int, Input] = self.get_inputs(config.get('inputs'))
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self.last_input_bitfield: Optional[bitarray] = bitarray()
        
        # communications
        self.bus: Optional[serialbus.Bus] = self.get_bus(config['bus'])
        self.monitor: Optional[network.Monitor] = self.get_network_monitor(config['network'])
        
        # for software demo and testing purposes
        random_config = config['random-actuation']
        random_delay = random_config['delay']
        self.random_enabled = random_config['enabled']
        self.random_min = random_config['min']
        self.random_max = random_config['max']
        self.randomizer = random.Random()
        self.random_timer = logic.Timer(random_delay, step=constants.TIME_INCREMENT)
    
    def get_default_timing(self, configuration_node: Dict[str, float]) -> Dict[PhaseState, float]:
        timing = {}
        for name, value in configuration_node.items():
            ps = text_to_enum(PhaseState, name)
            timing.update({ps: value})
        return timing
    
    def get_phases(self,
                   configuration_node: List[Dict],
                   default_timing: Dict[PhaseState, float]) -> List[Phase]:
        phases = []
        
        for i, node in enumerate(configuration_node, start=1):
            flash_mode_text = node['flash-mode']
            flash_mode = text_to_enum(FlashMode, flash_mode_text)
            phase_timing: Dict[PhaseState, float] = default_timing.copy()
            timing_data = node.get('timing')
            
            if timing_data is not None:
                for name, value in timing_data.items():
                    ps = text_to_enum(PhaseState, name)
                    phase_timing.update({ps: value})
            
            ls_node = node['load-switches']
            veh = ls_node['vehicle']
            ped_index = ls_node.get('ped')
            veh = self.get_load_switch_by_id(veh)
            ped = None
            if ped_index is not None:
                ped = self.get_load_switch_by_id(ped_index)
            phase = Phase(i, phase_timing, veh, ped, flash_mode)
            phases.append(phase)
        
        return sorted(phases)
    
    def get_rings(self, configuration_node: List[List[int]]) -> List[Ring]:
        rings = []
        for i, n in enumerate(configuration_node, start=1):
            rings.append(Ring(i, n))
        return rings
    
    def get_barriers(self, configuration_node: List[List[int]]) -> List[Barrier]:
        barriers = []
        for i, n in enumerate(configuration_node, start=1):
            barriers.append(Barrier(i, n))
        return barriers
    
    def get_bus(self, configuration_node: dict) -> Optional[serialbus.Bus]:
        """Create the serial bus manager thread, if enabled"""
        if configuration_node['enabled']:
            logger.info('Serial bus subsystem ENABLED')
            port = configuration_node['port']
            baud = configuration_node['baud']
            return serialbus.Bus(port, baud)
        else:
            logger.info('Serial bus subsystem DISABLED')
        
        return None
    
    def get_network_monitor(self, configuration_node: dict) -> Optional[network.Monitor]:
        """Create the network monitor thread, if enabled"""
        if configuration_node['enabled']:
            logger.info('Networking subsystem ENABLED')
            
            if_name = configuration_node['interface'].lower().strip()
            
            monitor_node = configuration_node['monitor']
            if monitor_node['enabled']:
                host = 'localhost'
                
                if if_name != 'localhost' and if_name != 'any':
                    try:
                        auto_ip = network.get_net_address(if_name)
                        host = auto_ip
                    except Exception as e:
                        logger.warning(f'Failed to get address of network '
                                       f'interface: {str(e)}')
                elif if_name == 'any':
                    host = '0.0.0.0'
                
                logger.info(f'Using IP address {host}')
                
                monitor_port = monitor_node['port']
                return network.Monitor(host, monitor_port, self.name, self.phases)
            else:
                logger.info('Network monitor disabled')
        
        logger.info('Networking disabled')
        return None
    
    def generate_friend_matrix(self, rings: List[Ring], barriers: Iterable[Barrier]) -> Dict[int, List[int]]:
        matrix = defaultdict(list)
        ring_indices = defaultdict(int)
        
        for ring in rings:
            for phase in ring.phases:
                assert isinstance(phase, int) and phase > 0
                ring_indices[phase] = rings.index(ring)
        
        for barrier in barriers:
            for phase in barrier.phases:
                assert isinstance(phase, int) and phase > 0
                ring = rings[ring_indices[phase]]
                other_phases = [o for o in barrier.phases if o not in ring.phases]
                matrix[phase].extend(other_phases)
        
        return matrix
    
    def get_phase_by_id(self, i: int) -> Phase:
        for ph in self.phases:
            if ph.id == i:
                return ph
        raise RuntimeError(f'Failed to find phase {i}')
    
    def get_load_switch_by_id(self, i: int) -> LoadSwitch:
        for ls in self.load_switches:
            if ls.id == i:
                return ls
        raise RuntimeError(f'Failed to find load switch {i}')
    
    def get_active_phases(self, pool) -> List[Phase]:
        return [phase for phase in pool if phase.active]
    
    def get_barrier_phases(self, barrier: Barrier) -> List[Phase]:
        """Map the phase indices defined in a `Barrier` to `Phase` instances"""
        return [self.get_phase_by_id(pi) for pi in barrier.phases]
    
    def get_inputs(self, configuration_node: dict) -> Dict[int, Input]:
        """
        Transform input settings from configuration node into a list of `Input`
        instances.

        :param configuration_node: configuration data for inputs
        :return: a list of Input instances
        """
        inputs = {}
        reserved_slots = []
        
        if configuration_node is not None:
            for input_node in configuration_node:
                slot = input_node['slot']
                
                if slot in reserved_slots:
                    raise RuntimeError('Input slot redefined')
                
                ignore = input_node['ignore']
                if ignore:
                    action = InputAction.NOTHING
                else:
                    action = text_to_enum(InputAction, input_node['action'])
                active = text_to_enum(InputActivation, input_node['active'])
                targets_node = input_node['targets']
                
                targets = [self.get_phase_by_id(t) for t in targets_node]
                
                if not ignore:
                    assert len(targets)
                
                inputs.update({
                    slot: Input(active, action, targets)
                })
        
        return inputs
    
    def get_idle_phases(self, items: List[int]) -> List[Phase]:
        phases = []
        for item in items:
            phases.append(self.get_phase_by_id(item))
        return phases
    
    def get_called_phases(self) -> Set[Phase]:
        phases = set()
        for call in self.calls:
            for phase in call.phases:
                phases.add(phase)
        return phases
    
    def sort_calls(self, calls: Iterable[Call]) -> List[Call]:
        return sorted(calls, key=lambda c: c.sorting_weight)
    
    def place_call(self, phases: Iterable[Phase], ped_service: bool = False, note: Optional[str] = None):
        """
        Create a new demand for traffic service.

        :param phases: the desired Phases to service.
        :param ped_service: pedestrian service when True.
        :param note: arbitrary note to be appended to log message
        """
        assert phases
        note_text = post_pend(note, note)
        
        phases = set(phases)
        merged = set()
        for call in self.calls:
            for call_phase in call.phases:
                for up in phases:
                    if up.id in self.friend_matrix[call_phase.id]:
                        if len(call.phases) < len(self.rings):
                            logger.debug('Merging {} into existing call with {}',
                                         up.get_tag(),
                                         csl([p.get_tag() for p in call.phases]))
                            call.phases.append(up)
                            merged.add(up)
                        else:
                            break
                if len(call.phases) >= len(self.rings):
                    break
        
        remaining = sorted(phases - merged)
        if remaining:
            call = Call(remaining, ped_service=ped_service)
            logger.debug(f'Call placed for {call.phase_tags_list}{note_text}')
            self.calls.append(call)
        
        for phase in phases:
            phase.stats['detections'] += 1
        
        self.sort_calls(self.calls)
    
    def place_all_call(self):
        """Place calls on all phases"""
        self.place_call(self.phases, ped_service=True, note='all call')
        if self.idle_phases:
            self.place_call(self.idle_phases, ped_service=True, note='idle phases')
    
    def detection(self, phases: List[Phase], ped_service: bool = False, note: Optional[str] = None):
        note_text = post_pend(note, note)
        
        if all([phase.state not in PHASE_GO_STATES for phase in phases]):
            self.place_call(phases, ped_service=ped_service, note=note)
        else:
            for phase in phases:
                if phase.state in PHASE_GO_STATES:
                    logger.debug(f'Detection on {phase.get_tag()}{note_text}')
                    
                    if phase.extend_active:
                        phase.gap_reset()
                    
                    phase.stats['detections'] += 1
                else:
                    self.place_call(phases, ped_service=ped_service, note=note)
    
    def handle_inputs(self, bf: bitarray):
        """Check on the contents of bus data container for changes"""
        
        if self.last_input_bitfield is None or bf != self.last_input_bitfield:
            for slot, inp in self.inputs.items():
                if inp.action == InputAction.NOTHING:
                    continue
                
                try:
                    state = bf[slot - 1]
                    
                    inp.last_state = inp.state
                    inp.state = state
                    
                    if inp.activated():
                        if len(inp.targets):
                            phases = inp.targets
                            if inp.action == InputAction.CALL:
                                self.place_call(phases, ped_service=True, note=f'input call, slot {slot}')
                            elif inp.action == InputAction.DETECT:
                                self.detection(phases, ped_service=True, note=f'input detect, slot {slot}')
                            else:
                                raise NotImplementedError()
                        else:
                            logger.debug('No targets defined for input slot {}', slot)
                except IndexError:
                    logger.verbose(f'Discarding signal for unused input slot {slot}')
        
        self.last_input_bitfield = bf
    
    def get_ring_phases(self, ring: Ring) -> List[Phase]:
        return [self.get_phase_by_id(i) for i in ring.phases]
    
    def check_phase_demand(self, phase: Phase) -> bool:
        for call in self.calls:
            if phase in call.phases:
                return True
        return False
    
    def get_available_phases(self, active: Iterable[Phase]) -> List[Phase]:
        available = []
        
        for phase in self.phase_pool:
            if not phase.active:
                if active:
                    if phase.state in PHASE_PARTNER_INHIBIT_STATES:
                        continue
                    
                    conflict = False
                    for active_phase in active:
                        if active_phase.id not in self.friend_matrix[phase.id]:
                            conflict = True
                            break
                    
                    if conflict:
                        continue
                
                if not self.check_phase_demand(phase):
                    continue
                
                available.append(phase)
        
        return available
    
    def handle_bus_frame(self):
        frame = self.bus.get()
        
        if frame is not None:
            match frame.type:
                case FrameType.INPUTS:
                    bitfield = bitarray()
                    bitfield.frombytes(frame.payload)
                    self.handle_inputs(bitfield)
    
    def set_operation_state(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            self.cet_timer.reset()
            for ph in self.phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.change(state=PhaseState.CAUTION)
        
        elif new_state == OperationMode.NORMAL:
            self.second_timer.reset()
            
            for ph in self.phases:
                ph.change(state=PhaseState.STOP)
            
            self.set_barrier(None)
            
            if self.recall_all:
                self.place_all_call()
            
            self.idle_timer.reset()
        
        previous_state = self.mode
        self.mode = new_state
        logger.info(f'Operation state is now {new_state.name} (was {previous_state.name})')
    
    def update_bus_outputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self.transferred)
        self.bus.send_frame(osf)
    
    def get_barrier_by_phase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        assert isinstance(phase, Phase)
        for b in self.barriers:
            if phase.id in b.phases:
                return b
        
        raise RuntimeError(f'Failed to get barrier by {phase.get_tag()}')
    
    def get_phase_partners(self, phase: Phase) -> List[Phase]:
        return [self.get_phase_by_id(i) for i in self.friend_matrix[phase.id]]
    
    def select_phase_partner(self, phase: Phase, pool: Optional[Iterable[Phase]] = None) -> Optional[Phase]:
        candidates = [partner for partner in self.get_phase_partners(phase) if not partner.active]
        
        for candidate in sorted(candidates, key=lambda c: c.interval_elapsed, reverse=True):
            if pool and candidate not in pool:
                continue
            return candidate
        return None
    
    def check_phase_conflict(self, active: Iterable[Phase], phase: Phase) -> bool:
        for active_phase in active:
            if active_phase.id not in self.friend_matrix[phase.id]:
                return True
        return False
    
    def check_conflicting_demand(self, active: Iterable[Phase], phase: Phase) -> bool:
        for other_phase in self.phases:
            if other_phase == phase:
                pass
            if self.check_phase_demand(other_phase) and self.check_phase_conflict(active, phase):
                return True
        return False
    
    def set_barrier(self, b: Optional[Barrier]):
        if b is not None:
            logger.debug(f'{b.get_tag()} active')
        else:
            logger.debug(f'Free barrier')
        
        self.barrier = b
    
    def reset_phase_pool(self):
        self.phase_pool = self.phases.copy()
    
    def end_cycle(self, note: Optional[str] = None) -> None:
        """End phasing for this control cycle iteration"""
        self.reset_phase_pool()
        
        active_count = len(self.get_active_phases(self.phases))
        if not active_count:
            self.cycle_count += 1
            self.set_barrier(None)
        
        note_text = post_pend(note, note)
        logger.debug(f'Ended cycle {self.cycle_count}{note_text}')
    
    def serve_phase(self,
                    phase: Phase,
                    ped_service: bool,
                    go_override: Optional[float] = None,
                    extend_inhibit: bool = False):
        logger.debug(f'Serving phase {phase.get_tag()}')
        
        if self.barrier is None:
            barrier = self.get_barrier_by_phase(phase)
            logger.debug('{} captured {}',
                         phase.get_tag(),
                         barrier.get_tag())
            self.set_barrier(barrier)
        
        try:
            self.phase_pool.remove(phase)
        except ValueError:
            pass
        
        phase.go_override = go_override
        phase.extend_inhibit = extend_inhibit
        phase.activate(ped_service)
    
    def tick(self):
        """Polled once every 100ms"""
        if self.random_timer.poll(self.random_enabled):
            phases = []
            first_phase = self.randomizer.choice(self.phases)
            phases.append(first_phase)
            choose_two = round(self.randomizer.random())
            if choose_two:
                second_phase = self.select_phase_partner(first_phase)
                if second_phase is not None:
                    phases.append(second_phase)
            
            next_delay = self.randomizer.randint(self.random_min, self.random_max)
            logger.debug('Random actuation for {}, next in {}s',
                         csl([phase.get_tag() for phase in phases]),
                         next_delay)
            
            ped_service = bool(round(self.randomizer.random()))
            self.detection(phases, ped_service=ped_service, note='random actuation')
            self.random_timer.trigger = next_delay
            self.random_timer.reset()
        
        if self.bus is not None:
            self.handle_bus_frame()
        
        if self.mode == OperationMode.NORMAL:
            concurrent_phases = len(self.rings)
            active_phases = self.get_active_phases(self.phases)
            
            for phase in self.phases:
                conflicting_demand = self.check_conflicting_demand(active_phases, phase)
                idle_phase = self.idle_phases and phase not in self.idle_phases
                rest_inhibit = conflicting_demand or idle_phase
                
                partners = self.get_phase_partners(phase)
                for active_phase in active_phases:
                    if active_phase.state in PHASE_SYNC_STATES:
                        if (active_phase in partners and active_phase in self.idle_phases
                                and not active_phase.resting):
                            if not phase.extend_enabled:
                                active_phase.extend_inhibit = True
                            rest_inhibit = False
                            break
                
                if (len(active_phases) < concurrent_phases and phase.state == PhaseState.GO
                        and PhaseState.STOP not in phase.previous_states):
                    phase.change(state=PhaseState.CAUTION)
                
                if phase.tick(rest_inhibit, idle_phase):
                    if not phase.active:
                        self.idle_timer.reset()
                        logger.debug('{} terminated', phase.get_tag())
                        if phase in self.idle_phases:
                            self.place_call([phase], ped_service=True, note='idle recall')
            
            if not active_phases:
                if not len(self.phase_pool):
                    self.end_cycle('complete')
                else:
                    available = self.get_available_phases(active_phases)
                    if not len(available):
                        if self.barrier:
                            self.set_barrier(None)
                        else:
                            self.reset_phase_pool()
            
            available = self.get_available_phases(active_phases)
            now_serving = []
            for call in self.calls:
                for phase in call.phases:
                    if phase in available:
                        if len(active_phases) >= concurrent_phases:
                            break
                        
                        self.serve_phase(phase, call.ped_service)
                        now_serving.append(phase)
                        active_phases = self.get_active_phases(self.phases)
                        available = self.get_available_phases(active_phases)
            
            for phase in active_phases:
                if 0 < len(active_phases) < concurrent_phases:
                    if phase.state in PHASE_SUPPLEMENT_STATES:
                        partner = self.select_phase_partner(phase, self.phase_pool)
                        if partner is not None:
                            go_override = phase.estimate_remaining()
                            if go_override > partner.minimum_service:
                                logger.debug('Running {} with {} (modified service {})',
                                             partner.get_tag(),
                                             phase.get_tag(),
                                             go_override)
                                self.serve_phase(partner,
                                                 False,
                                                 go_override=go_override,
                                                 extend_inhibit=True)
                                now_serving.append(partner)
                                active_phases = self.get_active_phases(self.phases)
                            else:
                                logger.verbose('Could not run {} with {} ({} < {})',
                                               partner.get_tag(),
                                               phase.get_tag(),
                                               go_override,
                                               partner.minimum_service)
            
            for phase in now_serving:
                for call in self.calls:
                    try:
                        call.phases.remove(phase)
                    except ValueError:
                        pass
            
            for call in [c for c in self.calls if not len(c.phases)]:
                self.calls.remove(call)
            
            if self.idle_phases and self.idle_timer.poll(self.idling):
                self.idle_timer.reset()
        elif self.mode == OperationMode.CET:
            for ph in self.phases:
                ph.tick(True, False)
            
            if self.cet_timer.poll(True):
                self.set_operation_state(OperationMode.NORMAL)
        
        if self.bus is not None:
            self.update_bus_outputs(self.load_switches)
        
        if self.monitor is not None:
            self.monitor.broadcast_control_update(self.phases, self.load_switches)
        
        logger.fields(build_field_message(self.load_switches))
        
        if self.second_timer.poll(True):
            if self.bus is not None:
                if not self.bus.ready:
                    logger.error('Bus not running')
                    self.shutdown()
            
            if self.monitor is not None:
                self.monitor.clean()
    
    def transfer(self):
        """Set the controllers flash transfer relays flag"""
        logger.info('Transferred')
        self.transferred = True
    
    def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        logger.info('Untransfered')
        self.transferred = False
    
    def run(self):
        """Begin control loop"""
        self.running = True
        
        logger.info(f'Controller is named "{self.name}"')
        
        # noinspection PyUnreachableCode
        if __debug__:
            logger.warning('Controller in DEBUG ENVIRONMENT!')
        
        logger.debug('CET trigger set to 3s')
        
        if self.running:
            if self.monitor is not None:
                self.monitor.start()
            
            if self.bus is not None:
                self.bus.start()
                
                while not self.bus.ready:
                    logger.info(f'Waiting on bus...')
                    time.sleep(constants.TIME_BASE)
                
                logger.info(f'Bus ready')
            
            self.set_operation_state(self.mode)
            self.transfer()
            while True:
                self.tick()
                time.sleep(constants.TIME_BASE)
    
    def shutdown(self):
        """Run termination tasks to stop control loop"""
        self.untransfer()
        self.running = False
        
        if self.bus is not None:
            logger.info('Stopping bus')
            self.bus.shutdown()
            self.bus.join(timeout=1)
        
        if self.monitor is not None:
            logger.info('Stopping network monitor')
            self.monitor.shutdown()
            self.monitor.join(timeout=1)
        
        logger.info('Shutdown complete')
