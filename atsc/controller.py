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
from typing import Iterable, Set
from atsc.core import *
from atsc import logic, network, serialbus, constants
from loguru import logger
from bitarray import bitarray
from atsc.utils import buildFieldMessage
from jacob.text import post_pend
from atsc.frames import FrameType, DeviceAddress, OutputStateFrame
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
        
        default_timing = self.getDefaultTiming(config['default-timing'])
        self.phases: List[Phase] = self.getPhases(config['phases'], default_timing)
        self.phase_pool: List[Phase] = self.phases.copy()
        self.calls: List[Call] = []
        
        self.rings: List[Ring] = self.getRings(config['rings'])
        self.barriers: List[Barrier] = self.getBarriers(config['barriers'])
        self.barrier: Optional[Barrier] = None
        
        self.cycle_count = 0
        
        self.idle_phases: List[Phase] = self.getIdlePhases(config['idling']['phases'])
        self.idle_serve_delay: float = config['idling']['serve-delay']
        self.idle_timer = logic.Timer(self.idle_serve_delay, step=constants.TIME_INCREMENT)
        self.idle_rising = EdgeTrigger(True)
        
        self.second_timer = logic.Timer(1.0, step=constants.TIME_INCREMENT)
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        self.cet_delay: float = max(yellow_time, config['init']['cet-delay'] - yellow_time)
        self.cet_timer = logic.Timer(self.cet_delay, step=constants.TIME_INCREMENT)
        
        # inputs data structure instances
        self.inputs: Dict[int, Input] = self.getInputs(config.get('inputs'))
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self.last_input_bitfield: Optional[bitarray] = bitarray()
        
        # communications
        self.bus: Optional[serialbus.Bus] = self.getBus(config['bus'])
        self.monitor: Optional[network.Monitor] = self.getNetworkMonitor(config['network'])
        
        # for software demo and testing purposes
        random_config = config['random-actuation']
        random_delay = random_config['delay']
        self.random_enabled = random_config['enabled']
        self.random_min = random_config['min']
        self.random_max = random_config['max']
        self.randomizer = random.Random()
        self.random_timer = logic.Timer(random_delay, step=constants.TIME_INCREMENT)
    
    def getDefaultTiming(self, configuration_node: Dict[str, float]) -> Dict[PhaseState, float]:
        timing = {}
        for name, value in configuration_node.items():
            ps = text_to_enum(PhaseState, name)
            timing.update({ps: value})
        return timing
    
    def getPhases(self,
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
            veh = self.getLoadSwitchById(veh)
            ped = None
            if ped_index is not None:
                ped = self.getLoadSwitchById(ped_index)
            phase = Phase(i, phase_timing, veh, ped, flash_mode)
            phases.append(phase)
        
        return sorted(phases)
    
    def getIdlePhases(self, items: List[int]) -> List[Phase]:
        phases = []
        for item in items:
            phases.append(self.getPhaseById(item))
        return phases
    
    def getRings(self, configuration_node: List[List[int]]) -> List[Ring]:
        rings = []
        for i, n in enumerate(configuration_node, start=1):
            rings.append(Ring(i, n))
        return rings
    
    def getBarriers(self, configuration_node: List[List[int]]) -> List[Barrier]:
        barriers = []
        for i, n in enumerate(configuration_node, start=1):
            barriers.append(Barrier(i, n))
        return barriers
    
    def getInputs(self, configuration_node: dict) -> Dict[int, Input]:
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
                
                targets = [self.getPhaseById(t) for t in targets_node]
                
                if not ignore:
                    assert len(targets)
                
                inputs.update({
                    slot: Input(active, action, targets)
                })
        
        return inputs
    
    def getBus(self, configuration_node: dict) -> Optional[serialbus.Bus]:
        """Create the serial bus manager thread, if enabled"""
        if configuration_node['enabled']:
            logger.info('Serial bus subsystem ENABLED')
            port = configuration_node['port']
            baud = configuration_node['baud']
            return serialbus.Bus(port, baud)
        else:
            logger.info('Serial bus subsystem DISABLED')
        
        return None
    
    def getNetworkMonitor(self, configuration_node: dict) -> Optional[network.Monitor]:
        """Create the network monitor thread, if enabled"""
        if configuration_node['enabled']:
            logger.info('Networking subsystem ENABLED')
            
            if_name = configuration_node['interface'].lower().strip()
            
            monitor_node = configuration_node['monitor']
            if monitor_node['enabled']:
                host = 'localhost'
                
                if if_name != 'localhost' and if_name != 'any':
                    try:
                        auto_ip = network.getIPAddress(if_name)
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
    
    def getBarrierPhases(self, barrier: Barrier) -> List[Phase]:
        """Map the phase indices defined in a `Barrier` to `Phase` instances"""
        return [self.getPhaseById(pi) for pi in barrier.phases]
    
    def getRingByPhase(self, phase: Phase) -> Ring:
        """Find a `Phase` instance by one of it's associated
                `Channel` instances"""
        for ring in self.rings:
            if phase.id in ring.phases:
                return ring
        
        raise RuntimeError(f'Failed to get ring')
    
    def getBarrierByPhase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        assert isinstance(phase, Phase)
        for b in self.barriers:
            if phase.id in b.phases:
                return b
        
        raise RuntimeError(f'Failed to get barrier by {phase.getTag()}')
    
    def getPhaseById(self, i: int) -> Phase:
        for ph in self.phases:
            if ph.id == i:
                return ph
        raise RuntimeError(f'Failed to find phase {i}')
    
    def getLoadSwitchById(self, i: int) -> LoadSwitch:
        for ls in self.load_switches:
            if ls.id == i:
                return ls
        raise RuntimeError(f'Failed to find load switch {i}')
    
    def getActivePhases(self, pool) -> List[Phase]:
        return [phase for phase in pool if phase.active]
    
    def placeCall(self, phases: Iterable[Phase], ped_service: bool = False, note: Optional[str] = None):
        """
        Create a new demand for traffic service.

        :param phases: the desired Phases to service.
        :param ped_service: pedestrian service when True.
        :param note: arbitrary note to be appended to log message
        """
        assert phases
        note_text = post_pend(note, note)
        
        uncalled = sorted(set(phases) - self.getCalledPhases())
        
        if uncalled:
            call = Call(uncalled, ped_service=ped_service)
            logger.debug(f'Call placed for {call.phase_tags_list}{note_text}')
            self.calls.append(call)
        
            for phase in call.phases:
                phase.stats['detections'] += 1
        else:
            logger.debug('ignored call attempt for {}', csl([ph.getTag() for ph in phases]))
    
    def placeAllCall(self):
        """Place calls on all phases"""
        self.placeCall(self.phases, ped_service=True, note='all call')
    
    def detection(self, phases: List[Phase], ped_service: bool = False, note: Optional[str] = None):
        note_text = post_pend(note, note)
        
        if all([phase.state not in PHASE_GO_STATES for phase in phases]):
            self.placeCall(phases, ped_service=ped_service, note=note)
        else:
            for phase in phases:
                if phase.state in PHASE_GO_STATES:
                    logger.debug(f'Detection on {phase.getTag()}{note_text}')
                    
                    if phase.extend_active:
                        phase.gap_reset()
                    
                    phase.stats['detections'] += 1
                else:
                    self.placeCall(phases, ped_service=ped_service, note=note)
    
    def handleInputs(self, bf: bitarray):
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
                                self.placeCall(phases, ped_service=True, note=f'input call, slot {slot}')
                            elif inp.action == InputAction.DETECT:
                                self.detection(phases, ped_service=True, note=f'input detect, slot {slot}')
                            else:
                                raise NotImplementedError()
                        else:
                            logger.debug('No targets defined for input slot {}', slot)
                except IndexError:
                    logger.verbose(f'Discarding signal for unused input slot {slot}')
        
        self.last_input_bitfield = bf
    
    def checkPhaseConflict(self, a: Phase, b: Phase) -> bool:
        """
        Check if two phases conflict based on Ring, Barrier and defined friend
        channels.

        :param a: Phase to compare against
        :param b: Other Phase to compare
        :return: True if conflict
        """
        if a != b:
            if b.id in self.getRingByPhase(a).phases:
                return True
            
            if b.id not in self.getBarrierByPhase(a).phases:
                return True
        
        # future: consider FYA-enabled phases conflicts for a non-FYA phase
        return False
    
    def checkCallConflict(self, phase: Phase, call: Call) -> bool:
        for call_phase in call.phases:
            if self.checkPhaseConflict(phase, call_phase):
                return True
        return False
    
    def canPhaseRun(self, phase: Phase) -> bool:
        if phase.active:
            return False
        
        if phase not in self.getAvailablePhases(self.phase_pool, barrier=self.barrier):
            return False
        
        for other in self.phases:
            if other == phase:
                continue
            if other.active and self.checkPhaseConflict(phase, other):
                return False
        
        return True
    
    def getRingPhases(self, ring: Ring) -> List[Phase]:
        return [self.getPhaseById(i) for i in ring.phases]
    
    def filterPhases(self,
                     pool: Iterable[Phase],
                     barrier: Optional[Barrier] = None,
                     ring: Optional[Ring] = None):
        barrier_phases = []
        if barrier is not None:
            barrier_phases = self.getBarrierPhases(barrier)
        
        ring_phases = []
        if ring is not None:
            ring_phases = self.getRingPhases(ring)
        
        phases = []
        
        for phase in pool:
            if barrier_phases:
                if phase not in barrier_phases:
                    continue
            if ring_phases:
                if phase not in ring_phases:
                    continue
            phases.append(phase)
        
        return phases
    
    def getAvailablePhases(self,
                           pool: List[Phase],
                           barrier: Optional[Barrier] = None,
                           ring: Optional[Ring] = None,
                           called: bool = False) -> List[Phase]:
        filtered = self.filterPhases(pool,
                                     barrier=barrier,
                                     ring=ring)
        
        if called:
            called = self.getCalledPhases()
            filtered = set(filtered).intersection(called)
        
        return filtered
    
    def handleBusFrame(self):
        frame = self.bus.get()
        
        if frame is not None:
            match frame.type:
                case FrameType.INPUTS:
                    bitfield = bitarray()
                    bitfield.frombytes(frame.payload)
                    self.handleInputs(bitfield)
    
    def setOperationState(self, new_state: OperationMode):
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
            
            self.setBarrier(None)
            
            if self.recall_all:
                self.placeAllCall()
            
            self.idle_timer.reset()
        
        previous_state = self.mode
        self.mode = new_state
        logger.info(f'Operation state is now {new_state.name} (was {previous_state.name})')
    
    def updateBusOutputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self.transferred)
        self.bus.sendFrame(osf)
    
    def servePhase(self, phase: Phase, ped_service: bool = False):
        logger.debug(f'Serving phase {phase.getTag()}')
        
        if self.barrier is None:
            barrier = self.getBarrierByPhase(phase)
            logger.debug('{} captured {}',
                         phase.getTag(),
                         barrier.getTag())
            self.setBarrier(barrier)
        
        self.phase_pool.remove(phase)
        phase.activate(ped_service=ped_service)
    
    def getPhasePartner(self, phases: List[Phase], phase: Phase) -> Optional[Phase]:
        for candidate in self.filterPhases(phases, barrier=self.barrier):
            if candidate == phase:
                continue
            if candidate.state in PHASE_GO_STATES:
                break
            if self.canPhaseRun(candidate):
                return candidate
        return None
    
    def getCalledPhases(self) -> Set[Phase]:
        phases = set()
        for call in self.calls:
            for phase in call.phases:
                phases.add(phase)
        return phases
    
    def setBarrier(self, b: Optional[Barrier]):
        if b is not None:
            logger.debug(f'{b.getTag()} active')
        else:
            logger.debug(f'Free barrier')
        
        self.barrier = b
    
    def resetPhasePool(self):
        self.phase_pool = self.phases.copy()
    
    def endCycle(self, note: Optional[str] = None) -> None:
        """End phasing for this control cycle iteration"""
        self.resetPhasePool()
        
        active_count = len(self.getActivePhases(self.phases))
        if not active_count:
            self.cycle_count += 1
            self.setBarrier(None)
        
        note_text = post_pend(note, note)
        logger.debug(f'Ended cycle {self.cycle_count}{note_text}')
    
    def getServableIdlePhases(self):
        if len(self.idle_phases):
            phases = []
            
            for phase in self.idle_phases:
                if self.canPhaseRun(phase):
                    phases.append(phase)
            
            if len(phases):
                ring_slice = phases[:len(self.rings)]
                return ring_slice
        
        return []
    
    def checkPhaseConflictingDemand(self, phase: Phase) -> bool:
        for call in self.calls:
            if self.checkCallConflict(phase, call):
                return True
        return False
    
    def tick(self):
        """Polled once every 100ms"""
        if self.random_timer.poll(self.random_enabled):
            phases = []
            first_phase = self.randomizer.choice(self.phases)
            phases.append(first_phase)
            choose_two = round(self.randomizer.random())
            if choose_two:
                second_phase = self.getPhasePartner(self.phases, first_phase)
                if second_phase is not None:
                    phases.append(second_phase)
            
            next_delay = self.randomizer.randint(self.random_min, self.random_max)
            logger.debug('Random actuation for {}, next in {}s',
                         csl([phase.getTag() for phase in phases]),
                         next_delay)
            
            ped_service = bool(round(self.randomizer.random()))
            self.detection(phases, ped_service=ped_service, note='random actuation')
            self.random_timer.trigger = next_delay
            self.random_timer.reset()
        
        if self.bus is not None:
            self.handleBusFrame()
        
        if self.mode == OperationMode.NORMAL:
            concurrent_phases = len(self.rings)
            active_phases = self.getActivePhases(self.phases)
            
            for phase in self.phases:
                conflicting_demand = self.checkPhaseConflictingDemand(phase)
                rest_inhibit = conflicting_demand or (self.idle_phases and phase not in self.idle_phases)
                
                # for active_phase in active_phases:
                #     if (not self.checkPhaseConflict(phase, active_phase) and
                #             active_phase.state in PHASE_GO_STATES):
                #         rest_inhibit = False
                #         break
                
                if (len(active_phases) < concurrent_phases and phase.state == PhaseState.GO
                        and phase.last_state != PhaseState.STOP):
                    phase.change(state=PhaseState.CAUTION)
                
                if phase.tick(rest_inhibit, phase.primary):
                    if not phase.active:
                        self.idle_timer.reset()
                        logger.debug('{} terminated', phase.getTag())
            
            if not len(self.phase_pool):
                self.endCycle('complete')
            else:
                available = self.getAvailablePhases(self.phase_pool,
                                                    barrier=self.barrier,
                                                    called=True)
                if not len(available):
                    if self.barrier:
                        self.setBarrier(None)
                    else:
                        self.resetPhasePool()
            
            now_serving = []
            for call in self.calls:
                for phase in call.phases:
                    if self.canPhaseRun(phase):
                        self.servePhase(phase, ped_service=call.ped_service)
                        now_serving.append(phase)
                        active_phases = self.getActivePhases(self.phases)
                        if len(active_phases) >= concurrent_phases:
                            break
            
            if len(active_phases) == 1:
                solo = active_phases[0]
                if not self.checkPhaseConflictingDemand(solo):
                    partner = self.getPhasePartner(self.phase_pool, solo)
                    if partner is not None:
                        logger.debug(f'Supplementing {solo.getTag()} '
                                     f'with partner {partner.getTag()}')
                        
                        self.servePhase(partner)
                        now_serving.append(partner)
                        active_phases = self.getActivePhases(self.phases)
            
            for phase in now_serving:
                for call in self.calls:
                    try:
                        call.phases.remove(phase)
                    except ValueError:
                        pass
            
            for call in [c for c in self.calls if not len(c.phases)]:
                self.calls.remove(call)
            
            if self.idle_phases and self.idle_timer.poll(self.idling):
                available = []
                if active_phases == 1:
                    solo = active_phases[0]
                    partner = self.getPhasePartner(self.idle_phases, solo)
                    if partner:
                        available.append(partner)
                elif not active_phases:
                    self.endCycle('idle')
                    available.extend([phase for phase in self.idle_phases if self.canPhaseRun(phase)])
                
                if available:
                    logger.debug('Recall idle phases')
                    cutoff = available[:len(self.rings)]
                    self.placeCall(cutoff, ped_service=True, note='idle')
                
                self.idle_timer.reset()
        elif self.mode == OperationMode.CET:
            for ph in self.phases:
                ph.tick(True, False)
            
            if self.cet_timer.poll(True):
                self.setOperationState(OperationMode.NORMAL)
        
        if self.bus is not None:
            self.updateBusOutputs(self.load_switches)
        
        if self.monitor is not None:
            self.monitor.broadcastControlUpdate(self.phases, self.load_switches)
        
        logger.fields(buildFieldMessage(self.load_switches))
        
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
            
            self.setOperationState(self.mode)
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
