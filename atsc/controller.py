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
from typing import Set, Iterable, Dict
from bitarray import bitarray
from itertools import chain
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

        self.rings: List[Ring] = self.get_rings(config['rings'])
        self.barriers: List[Barrier] = self.get_barriers(config['barriers'])
        self.friend_matrix: Dict[int, List[int]] = self.generate_friend_matrix(self.rings, self.barriers)
        
        self.barrier: Optional[Barrier] = None
        
        self.calls: List[Call] = []
        self.cycle_count = 0
        self.idle_phases: List[Phase] = self.get_idle_phases(config['idling']['phases'])
        
        # control entrance transition timer
        cet_delay: float = max(default_timing.caution, config['init']['cet-delay'])
        self.cet_timer = logic.Timer(cet_delay)
        
        # inputs data structure instances
        self.input_bitfield = bitarray()
        self.inputs: Dict[int, Input] = self.get_inputs(config.get('inputs'))
        self.phase_inputs: Dict[Phase, Set[Input]] = self.get_phase_inputs()
        
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
        self.random_timer = logic.Timer(random_delay)
    
    def get_default_timing(self, node: Dict[str, float]) -> PhaseTiming:
        service_clear = node['service-clear']
        service_min = node['service-min']
        service_max = node['service-max']
        caution = node['caution']
        gap = node['gap']
        gap_reduce = node['gap-reduce']
        gap_min = node['gap-min']
        gap_max = node['gap-max']
        walk_min = node['walk-min']
        walk_max = node['walk-max']
        ped_clear = node['ped-clear']
        
        return PhaseTiming(service_clear=service_clear,
                           service_min=service_min,
                           service_max=service_max,
                           caution=caution,
                           gap=gap,
                           gap_reduce=gap_reduce,
                           gap_min=gap_min,
                           gap_max=gap_max,
                           walk_min=walk_min,
                           walk_max=walk_max,
                           ped_clear=ped_clear)
    
    def get_phases(self,
                   configuration_node: List[Dict],
                   default_timing: PhaseTiming) -> List[Phase]:
        phases = []
        
        for i, node in enumerate(configuration_node, start=1):
            flash_mode_text = node['flash-mode']
            flash_mode = text_to_enum(FlashMode, flash_mode_text)
            timing_node = node.get('timing')
            
            if timing_node is not None:
                service_clear = timing_node.get('service-clear',
                                                default_timing.service_clear)
                service_min = timing_node.get('service-min',
                                              default_timing.service_min)
                service_max = timing_node.get('service-max',
                                              default_timing.service_max)
                caution = timing_node.get('caution',
                                          default_timing.caution)
                gap = timing_node.get('gap',
                                      default_timing.gap)
                gap_reduce = timing_node.get('gap-reduce',
                                             default_timing.gap_reduce)
                gap_min = timing_node.get('gap-min',
                                          default_timing.gap_min)
                gap_max = timing_node.get('gap-max',
                                          default_timing.gap_max)
                walk_min = timing_node.get('walk-min',
                                           default_timing.walk_min)
                walk_max = timing_node.get('walk-max',
                                           default_timing.walk_max)
                ped_clear = timing_node.get('ped-clear',
                                            default_timing.ped_clear)
            
                timing = PhaseTiming(service_clear=service_clear,
                                     service_min=service_min,
                                     service_max=service_max,
                                     caution=caution,
                                     gap=gap,
                                     gap_reduce=gap_reduce,
                                     gap_min=gap_min,
                                     gap_max=gap_max,
                                     walk_min=walk_min,
                                     walk_max=walk_max,
                                     ped_clear=ped_clear)
            else:
                timing = default_timing
            
            ls_node = node['load-switches']
            veh = ls_node['vehicle']
            ped_index = ls_node.get('ped')
            veh = self.get_load_switch_by_id(veh)
            ped = None
            if ped_index is not None:
                ped = self.get_load_switch_by_id(ped_index)
            phase = Phase(i, timing, veh, ped, flash_mode)
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
    
    def get_phases_by_id(self, indices: List[int]) -> List[Phase]:
        phases = []
        for i in indices:
            phases.append(self.get_phase_by_id(i))
        return phases
    
    def get_load_switch_by_id(self, i: int) -> LoadSwitch:
        for ls in self.load_switches:
            if ls.id == i:
                return ls
        raise RuntimeError(f'Failed to find load switch {i}')
    
    def get_barrier_phases(self, barrier: Barrier) -> List[Phase]:
        """Map the phase indices defined in a `Barrier` to `Phase` instances"""
        return self.get_phases_by_id(barrier.phases)
    
    def get_inputs(self, config: Optional[dict]) -> Dict[int, Input]:
        """
        Transform input settings from configuration node into a list of `Input`
        instances.

        :param config: configuration data for inputs
        :return: a list of Input instances
        """
        inputs = {}
        
        if config is not None:
            for node in config:
                id_ = node['id']
                
                if id_ in inputs:
                    raise RuntimeError(f'input {id_} already defined')
                
                action = text_to_enum(InputAction, node['action'])
                
                del node['id']
                del node['action']
                
                inputs.update({id_: Input(id_, action, **node)})
        
        return inputs
    
    def get_phase_inputs(self) -> Dict[Phase, Set[Input]]:
        mapping = defaultdict(set)
        
        for input_ in self.inputs.values():
            if input_.action == InputAction.RECALL:
                for phase in self.get_phases_by_id(input_.targets):
                    mapping[phase].add(input_)
        
        return mapping
    
    def get_idle_phases(self, items: List[int]) -> List[Phase]:
        phases = []
        for item in items:
            phases.append(self.get_phase_by_id(item))
        return phases
    
    def sort_calls(self, calls: Iterable[Call]) -> List[Call]:
        return sorted(calls, key=lambda c: min([p.id for p in c.phases]))
    
    def clean_calls(self):
        for call in [c for c in self.calls if not len(c.phases)]:
            self.calls.remove(call)
    
    def recall(self, phases: Iterable[Phase], ped_service: bool = False, note: Optional[str] = None):
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
                            logger.debug('Recall {} merged with {}',
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
            logger.debug(f'Recalling {call.phase_tags_list}{note_text}')
            self.calls.append(call)
        
        for phase in phases:
            phase.stats['detections'] += 1
        
        self.clean_calls()
        self.sort_calls(self.calls)
    
    def place_all_call(self):
        """Place calls on all phases"""
        self.recall(self.phases, ped_service=True, note='all call')
    
    def detect(self, phases: List[Phase], ped_service: bool = False, note: Optional[str] = None):
        note_text = post_pend(note, note)
        
        if all([phase.interval not in PHASE_GO_INTERVALS for phase in phases]):
            self.recall(phases, ped_service=ped_service, note=note)
        else:
            for phase in phases:
                if phase.interval in PHASE_GO_INTERVALS:
                    logger.debug(f'Detection on {phase.get_tag()}{note_text}')
                    
                    if phase.interval == PhaseInterval.GAP:
                        phase.gap_reset()
                    
                    phase.stats['detections'] += 1
                else:
                    self.recall(phases, ped_service=ped_service, note=note)
    
    def check_phase_demand(self, phase: Phase) -> bool:
        for call in self.calls:
            if phase in call.phases:
                return True
        return False
    
    def get_available_phases(self, active_phases: Iterable[Phase]) -> Set[Phase]:
        available = set()
        
        pool = self.phase_pool
        if self.barrier:
            barrier_pool = self.get_barrier_phases(self.barrier)
            pool = set(pool).intersection(barrier_pool)
        
        for phase in pool:
            if not phase.active:
                # if phase.interval in (PhaseInterval.CAUTION, PhaseInterval.GAP):
                #     continue
                
                conflict = False
                for active_phase in active_phases:
                    if active_phase.id not in self.friend_matrix[phase.id]:
                        conflict = True
                        break
                
                if conflict:
                    continue
                
                if not self.check_phase_demand(phase):
                    continue
                
                available.add(phase)
        
        return available
    
    def get_phase_partners(self, phase: Phase) -> List[Phase]:
        rv = self.get_phases_by_id(self.friend_matrix[phase.id])
        return sorted(rv, key=lambda c: c.interval_elapsed, reverse=True)
    
    def check_phase_conflict(self, a: Phase, b: Phase) -> bool:
        """Check weather phase B conflicts with phase A."""
        if a.id == b.id:
            return False
        
        return b.id not in self.friend_matrix[a.id]
    
    def check_conflicting_demand(self, phase: Phase, pool: Iterable[Phase] = None) -> bool:
        for other_phase in pool or self.phases:
            if other_phase == phase:
                pass
            if self.check_phase_demand(other_phase) and self.check_phase_conflict(phase, other_phase):
                return True
        return False
    
    def set_barrier(self, b: Optional[Barrier]):
        if b is not None:
            logger.debug(f'{b.get_tag()} activated')
        
        self.barrier = b
    
    def get_active_phases(self) -> List[Phase]:
        return [phase for phase in self.phases if phase.active]
    
    def reset_phase_pool(self):
        self.phase_pool = self.phases.copy()
    
    def end_cycle(self) -> None:
        """End phasing for this control cycle iteration"""
        self.reset_phase_pool()
        self.cycle_count += 1
        self.set_barrier(None)
        
        logger.debug(f'Ended cycle {self.cycle_count}')
    
    def get_barrier_by_phase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        assert isinstance(phase, Phase)
        for b in self.barriers:
            if phase.id in b.phases:
                return b
        
        raise RuntimeError(f'Failed to get barrier by {phase.get_tag()}')
    
    def serve_phase(self,
                    phase: Phase,
                    ped_service: bool,
                    go_override: float = 0.0,
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
        
        phase.ped_service = ped_service
        phase.service_override = go_override
        phase.gap_inhibit = extend_inhibit
        phase.activate()
    
    def get_called_phases(self):
        return chain(*[call.phases for call in self.calls])
    
    def remove_phase_call(self, phase: Phase) -> bool:
        for call in self.calls:
            try:
                call.phases.remove(phase)
                return True
            except ValueError:
                pass
        return False
    
    def get_next_phases(self) -> List[Phase]:
        next_phases = []
        
        if len(self.calls):
            return self.calls[0].phases
        
        return next_phases
    
    def poll_inputs(self):
        """Process the bus input bitfield"""
        input_: Input
        for bit_value, input_ in zip(self.input_bitfield, self.inputs.values()):
            status = input_.poll()
            
            match status:
                case 1:
                    logger.verbose('Input {} rising (was low for {}s)',
                                   input_.id,
                                   round(input_.low_elapsed, 1))
                    if input_.action == InputAction.RECALL:
                        phases = self.get_phases_by_id(input_.targets)
                        self.detect(phases,
                                    ped_service=True,
                                    note=f'input {input_.id}')
                case -1:
                    logger.verbose('Input {} falling (was high for {}s)',
                                   input_.id,
                                   round(input_.high_elapsed, 1))
                    if input_.action == InputAction.RECALL:
                        if input_.recall_type == RecallType.MAINTAIN:
                            phases = self.get_phases_by_id(input_.targets)
                            for phase in phases:
                                logger.debug('Removing phase {} from calls', phase.get_tag())
                                self.remove_phase_call(phase)
            
            if input_.action != InputAction.IGNORE:
                input_.signal = bool(bit_value)
    
    def poll_bus(self):
        frame = self.bus.get()
        
        if frame is not None:
            match frame.type:
                case FrameType.INPUTS:
                    bf = bitarray()
                    bf.frombytes(frame.payload)
                    self.input_bitfield = bf
    
    def update_bus_outputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self.transferred)
        self.bus.send_frame(osf)
    
    def set_operation_state(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            self.cet_timer.reset()
            for ph in self.phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.change(interval=PhaseInterval.CAUTION)
        
        elif new_state == OperationMode.NORMAL:
            for ph in self.phases:
                ph.change(interval=PhaseInterval.STOP)
            
            self.set_barrier(None)
            
            if self.recall_all:
                self.place_all_call()
            
            if self.idle_phases:
                self.recall(self.idle_phases, ped_service=True, note='idle phases')
        
        previous_state = self.mode
        self.mode = new_state
        logger.info(f'Operation state is now {new_state.name} (was {previous_state.name})')
    
    def tick(self):
        """Polled once every 100ms"""
        if self.bus is not None:
            self.poll_bus()
        
        self.poll_inputs()
        
        if self.random_timer.poll(self.random_enabled):
            phases = []
            first_phase = self.randomizer.choice(self.phases)
            phases.append(first_phase)
            choose_two = round(self.randomizer.random())
            if choose_two:
                partners = self.get_phase_partners(first_phase)
                if partners:
                    second_phase = partners[0]
                    if second_phase is not None:
                        phases.append(second_phase)
            
            next_delay = self.randomizer.randint(self.random_min, self.random_max)
            logger.debug('Random actuation for {}, next in {}s',
                         csl([phase.get_tag() for phase in phases]),
                         next_delay)
            
            ped_service = bool(round(self.randomizer.random()))
            self.detect(phases, ped_service=ped_service, note='random actuation')
            self.random_timer.trigger = next_delay
            self.random_timer.reset()
        
        if self.mode == OperationMode.NORMAL:
            for phase in self.phases:
                if phase.tick():
                    if not phase.active:
                        logger.debug('{} terminated', phase.get_tag())
                        if phase in self.idle_phases:
                            self.recall([phase], ped_service=True, note='idle recall')
                        inputs = self.phase_inputs[phase]
                        for input_ in inputs:
                            if input_.signal:
                                self.recall([phase],
                                            ped_service=phase.ped_service,
                                            note=f'input {input_.id}')
            
            concurrent_phases = len(self.rings)
            active_phases = self.get_active_phases()
            
            for phase in self.phases:
                last_interval = phase.previous_intervals[0] if phase.previous_intervals else None
                if (len(active_phases) < concurrent_phases and
                        phase.interval == PhaseInterval.GO and
                            last_interval != PhaseInterval.STOP):
                    phase.change(interval=PhaseInterval.CAUTION)
                
                rest_inhibit = self.check_conflicting_demand(phase)
                if len(active_phases) and self.barrier:
                    # if there are still phases left to run in the current barrier
                    phase_pool = set(self.phase_pool).intersection(self.get_barrier_phases(self.barrier))
                    if phase_pool:
                        partners = self.get_phase_partners(phase)
                        for partner in partners:
                            if partner.interval == PhaseInterval.GO:
                                if not self.check_conflicting_demand(partner, partners):
                                    # partner.gap_inhibit = not phase.extend_enabled
                                    rest_inhibit = False
                                    break
                
                # idle_phase = self.idle_phases and phase in self.idle_phases
                # phase.supress_maximum = idle_phase or (not self.idle_phases and not rest_inhibit)
                phase.rest_inhibit = rest_inhibit
            
            available = self.get_available_phases(active_phases)
            if len(active_phases):
                if len(active_phases) < concurrent_phases and self.barrier:
                    barrier_phases = self.get_barrier_phases(self.barrier)
                    called_phases = set(self.get_called_phases())
                    # called phases only within the active barrier
                    if called_phases.issubset(barrier_phases):
                        # but called phases are not in the available pool
                        if not called_phases.issubset(available):
                            logger.debug('Resetting phase pool because the only '
                                         'remaining calls are within the active '
                                         'barrier while phases are active')
                            self.reset_phase_pool()
                            available = self.get_available_phases(active_phases)
            else:
                if not len(self.phase_pool):
                    self.end_cycle()
                elif not len(available):
                    self.reset_phase_pool()
                    self.set_barrier(None)
                    available = self.get_available_phases(active_phases)
            
            now_serving = []
            for call in self.calls:
                for phase in call.phases:
                    if phase in available:
                        if len(active_phases) >= concurrent_phases:
                            break
                        
                        self.serve_phase(phase, call.ped_service)
                        now_serving.append(phase)
                        active_phases = self.get_active_phases()
                        available = self.get_available_phases(active_phases)
            
            for phase in active_phases:
                if 0 < len(active_phases) < concurrent_phases:
                    if phase.interval in PHASE_GO_INTERVALS:
                        partners = self.get_phase_partners(phase)
                        if partners:
                            for partner in partners:
                                if partner.active:
                                    break
                                
                                go_override = phase.estimate_remaining()
                                if go_override and go_override >= partner.timing.fixed_interval_total:
                                    logger.debug('Running {} with {} (modified service {})',
                                                 partner.get_tag(),
                                                 phase.get_tag(),
                                                 go_override)
                                    self.serve_phase(partner,
                                                     phase.ped_service,
                                                     go_override=go_override,
                                                     extend_inhibit=True)
                                else:
                                    logger.verbose('Could not run {} with {} ({} < {})',
                                                   partner.get_tag(),
                                                   phase.get_tag(),
                                                   go_override,
                                                   partner.timing.fixed_interval_total)
                                
                                now_serving.append(partner)
                                break
                        active_phases = self.get_active_phases()
            
            if self.barrier:
                if not set(self.get_barrier_phases(self.barrier)).issuperset(active_phases):
                    raise RuntimeError('phases active not part of active barrier')
            
            for phase in now_serving:
                for call in self.calls:
                    try:
                        call.phases.remove(phase)
                    except ValueError:
                        pass
            
            self.clean_calls()
        elif self.mode == OperationMode.CET:
            for ph in self.phases:
                ph.tick()
            
            if self.cet_timer.poll(True):
                self.set_operation_state(OperationMode.NORMAL)
        
        if self.bus is not None:
            self.update_bus_outputs(self.load_switches)
            
            if not self.bus.ready:
                logger.error('Bus not running')
                self.shutdown()
        
        if self.monitor is not None:
            self.monitor.broadcast_control_update(self.phases, self.load_switches)
            self.monitor.clean()
        
        logger.fields(build_field_message(self.load_switches))
    
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
