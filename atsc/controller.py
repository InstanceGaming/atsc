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
from atsc import constants
from atsc.core import *
from atsc import logic, network, serialbus
from loguru import logger
from bitarray import bitarray
from atsc.utils import buildFieldMessage
from jacob.text import post_pend
from atsc.frames import FrameType, DeviceAddress, OutputStateFrame
from jacob.enumerations import text_to_enum


class Controller:
    
    @property
    def safe(self):
        return not self.barrier or self.barrier.safe
    
    def __init__(self, config: dict):
        # controller name (arbitrary)
        self.name = config['device']['name']
        
        # should place calls on all phases when started?
        self.recall_all = config['init']['recall-all']
        
        # loop enable flag
        self.running = False
        
        # local flash transfer relay status
        self.transferred = False
        
        self.cycle_count = 0
        
        # operation functionality of the controller
        self.mode: OperationMode = text_to_enum(OperationMode, config['init']['mode'])
        
        self.load_switches: List[LoadSwitch] = [LoadSwitch(1), LoadSwitch(2), LoadSwitch(3), LoadSwitch(4),
                                                LoadSwitch(5), LoadSwitch(6), LoadSwitch(7), LoadSwitch(8),
                                                LoadSwitch(9), LoadSwitch(10), LoadSwitch(11), LoadSwitch(12)]
        
        default_timing = self.getDefaultTiming(config['default-timing'])
        self.phases: List[Phase] = self.getPhases(config['phases'], default_timing)
        self.cycle_phases: Set[Phase] = set()
        self.recall_phases = self.getIdlePhases(config['idling']['recall'])
        
        self.calls: List[Call] = []
        
        self.rings: List[Ring] = self.getRings(config['rings'])
        self.barriers: List[Barrier] = self.getBarriers(config['barriers'])
        self.barrier: Optional[Barrier] = None
        
        self.second_timer = logic.Timer(1.0, step=TIME_INCREMENT)
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        self.cet_delay: float = max(yellow_time, config['init']['cet-delay'] - yellow_time)
        self.cet_timer = logic.Timer(self.cet_delay, step=TIME_INCREMENT)
        
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
        self.random_timer = logic.Timer(random_delay, step=TIME_INCREMENT)
    
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
            phases = [self.getPhaseById(i) for i in n]
            rings.append(Ring(i, phases, 1.0))
        return rings
    
    def getBarriers(self, configuration_node: List[List[int]]) -> List[Barrier]:
        barriers = []
        for i, n in enumerate(configuration_node, start=1):
            phases = {self.getPhaseById(i) for i in n}
            barriers.append(Barrier(i, phases, self.rings))
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
                
                targets = []
                for target_index in targets_node:
                    target = self.phases[target_index - 1]
                    targets.append(target)
                
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
    
    def getRingByPhase(self, phase: Phase) -> Ring:
        for ring in self.rings:
            if phase in ring.phases:
                return ring
        
        raise RuntimeError(f'Failed to get ring')
    
    def getBarrierByPhase(self, phase: Phase) -> Barrier:
        assert isinstance(phase, Phase)
        for b in self.barriers:
            if phase in b.phases:
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
    
    def placeCall(self, phases: List[Phase], note: Optional[str] = None):
        """
        Create a new demand for traffic service.

        :param phases: the desired Phases to service.
        :param note: arbitrary note to be appended to log message
        """
        assert phases
        note_text = post_pend(note, note)
        
        exists = any([phase in call for call in self.calls for phase in phases])
        if not exists:
            call = Call(phases)
            logger.debug(f'Call placed for {call.phase_tags_list}{note_text}')
            self.calls.append(call)
            
            for phase in call.phases:
                phase.stats['detections'] += 1
    
    def placeAllCall(self):
        """Place calls on all phases"""
        self.placeCall(self.phases.copy(), 'all call')
    
    def detection(self, phases: List[Phase], note: Optional[str] = None):
        assert phases
        note_text = post_pend(note, note)
        
        if all([phase.state not in PHASE_GO_STATES for phase in phases]):
            self.placeCall(phases, note)
        else:
            for phase in phases:
                if phase.state in PHASE_GO_STATES:
                    logger.debug(f'Detection on {phase.getTag()}{note_text}')
                    
                    if phase.extend_active:
                        phase.gap_reset()
                    
                    phase.stats['detections'] += 1
                else:
                    self.placeCall(phases, note)
    
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
                        if inp.action == InputAction.CALL:
                            for target in inp.targets:
                                self.placeCall([target], f'input call, slot {slot}')
                        elif inp.action == InputAction.DETECT:
                            self.detection(inp.targets, f'input detect, slot {slot}')
                        else:
                            raise NotImplementedError()
                except IndexError:
                    logger.verbose(f'Discarding signal for unused input slot {slot}')
        
        self.last_input_bitfield = bf
    
    def handleBusFrame(self):
        frame = self.bus.get()
        
        if frame is not None:
            size = len(frame.data)
            if size >= 3:
                type_number = frame.data[2]
                try:
                    ft = FrameType(type_number)
                except ValueError:
                    ft = FrameType.UNKNOWN
                
                if ft == FrameType.INPUTS:
                    bitfield = bitarray()
                    bitfield.frombytes(frame.data[3:])
                    self.handleInputs(bitfield)
    
    def setOperationState(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            self.cet_timer.reset()
            for ph in self.phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.change(force_state=PhaseState.CAUTION)
        
        elif new_state == OperationMode.NORMAL:
            self.second_timer.reset()
            
            for ph in self.phases:
                ph.change(force_state=PhaseState.STOP)
            
            if self.recall_all:
                self.placeAllCall()
                
            self.newCycle()
        
        previous_state = self.mode
        self.mode = new_state
        logger.info(f'Operation state is now {new_state.name} (was {previous_state.name})')
    
    def updateBusOutputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self.transferred)
        self.bus.sendFrame(osf)
        
    def getPhasesInCalls(self, calls: Iterable[Call]) -> Set[Phase]:
        phases = set()
        
        for call in calls:
            for phase in call.phases:
                phases.add(phase)
        
        return phases
    
    def getPhaseCalls(self, phases: Iterable[Phase]) -> Dict[Phase, Call]:
        mapping = {}
        
        for phase in phases:
            for call in self.calls:
                if phase in call.phases:
                    mapping.update({phase: call})
                    break
        
        return mapping
    
    def checkPhaseConflict(self, a: Phase, b: Phase) -> bool:
        """
        Check if two phases conflict based on Ring, Barrier and defined friend
        channels.

        :param a: Phase to compare against
        :param b: Other Phase to compare
        :return: True if conflict
        """
        if a != b:
            if b in self.getRingByPhase(a).phases:
                return True
            
            if b not in self.getBarrierByPhase(a).phases:
                return True
        
        # future: consider FYA-enabled phases conflicts for a non-FYA phase
        return False
    
    def checkPhaseConflictingDemand(self, phase: Phase) -> bool:
        for call in self.calls:
            for other_phase in call.phases:
                if self.checkPhaseConflict(phase, other_phase):
                    return True
        return False
    
    def checkBarrierConflictingDemand(self, barrier: Barrier) -> bool:
        for other_barrier in self.barriers:
            if other_barrier == barrier:
                continue
            return len(self.getPhaseCalls(other_barrier.phases)) > 0
        return False
    
    def resetRings(self, barrier: Barrier):
        for ring in self.rings:
            offset = barrier.getRingPosition(ring)
            ring.cycle(offset)
    
    def newCycle(self, next_barrier: Optional[Barrier] = None, note: Optional[str] = None):
        note_text = post_pend(note, note)
        if self.barrier is not None:
            self.cycle_count += 1
            self.cycle_phases = set()
            logger.debug('ended cycle {}{}', self.cycle_count, note_text)
            if all([ring.safe for ring in self.rings]):
                self.resetRings(self.barrier)
                self.barrier.reset()
        
        if next_barrier is None:
            if len(self.calls):
                next_call = self.calls[0]
                next_phase = next_call.phases[0]
                next_barrier = self.getBarrierByPhase(next_phase)
        
        self.barrier = next_barrier
    
    def tick(self):
        """Polled once every 100ms"""
        if self.random_timer.poll(self.random_enabled):
            phases = []
            first_phase = self.randomizer.choice(self.phases)
            phases.append(first_phase)
            choose_two = round(self.randomizer.random())
            if choose_two:
                barrier = self.getBarrierByPhase(first_phase)
                second_phase = barrier.getPhasePartner(first_phase)
                if second_phase is not None:
                    phases.append(second_phase)
            
            next_delay = self.randomizer.randint(self.random_min, self.random_max)
            logger.debug('Random actuation for {}, next in {}s',
                         csl([phase.getTag() for phase in phases]),
                         next_delay)
            
            self.detection(phases, 'random actuation')
            self.random_timer.trigger = next_delay
            self.random_timer.reset()
        
        if self.bus is not None:
            self.handleBusFrame()
            self.updateBusOutputs(self.load_switches)
        
        if self.monitor is not None:
            self.monitor.broadcastControlUpdate(self.phases, self.load_switches)
        
        logger.fields(buildFieldMessage(self.load_switches))
        
        if self.second_timer.poll(True):
            self.second_timer.reset()
            
            if self.bus is not None:
                if not self.bus.ready:
                    logger.error('Bus not running')
                    self.shutdown()
            
            if self.monitor is not None:
                self.monitor.clean()
        
        if self.mode == OperationMode.NORMAL:
            for barrier in self.barriers:
                only_secondaries = all([phase.secondary for phase in barrier.active_phases])
                barrier_demand = self.checkBarrierConflictingDemand(barrier)
                for phase in barrier.phases:
                    rest_inhibit = barrier_demand or only_secondaries
                    
                    if not rest_inhibit:
                        rest_inhibit = self.checkPhaseConflictingDemand(phase)
                    
                    if phase.tick(rest_inhibit):
                        if phase.safe:
                            self.cycle_phases.add(phase)

            for ring in self.rings:
                ring.tick()
            
            if self.barrier is not None:
                calls_unserviceable = set()
                empty_calls = set()
                
                phase_count = len(self.barrier.active_phases)
                if phase_count < len(self.barrier.rings):
                    barrier_calls = self.getPhaseCalls(self.barrier.phases)
                    choices = {}
                    
                    # allow other rows in this column get filled after the first
                    # phase is served in this column.
                    additional = -1 if phase_count else 0
                    
                    for call in barrier_calls.values():
                        selected = []
                        phases_unserviceable = set()
                        
                        for phase in call.phases:
                            if not phase.safe:
                                continue
                            
                            for active_phase in self.barrier.active_phases:
                                if self.checkPhaseConflict(phase, active_phase):
                                    break
                            else:
                                if phase in self.barrier.phases:
                                    ring = self.getRingByPhase(phase)
                                    # prevent issuing phases to rings in red-clearance
                                    if ring.safe:
                                        if ring not in choices.keys():
                                            if ring.getPosition(phase) > self.barrier.depth + additional:
                                                choices.update({ring: phase})
                                                selected.append(phase)
                                                continue
                            
                            phases_unserviceable.add(phase)
                        
                        for phase in selected:
                            call.phases.remove(phase)
                        
                        if not len(call.phases):
                            empty_calls.add(call)
                        else:
                            if len(phases_unserviceable) == len(call.phases):
                                calls_unserviceable.add(call)
                    
                    if choices:
                        serve_phases = choices.values()
                        should_recall = any([phase not in self.recall_phases for phase in serve_phases])
                        
                        if should_recall:
                            recall_phases = self.recall_phases[:len(self.rings)]
                            self.placeCall(recall_phases, 'recall')
                        
                        self.barrier.serve(serve_phases)
                
                for call in empty_calls:
                    self.calls.remove(call)
                
                if self.safe:
                    barrier_calls = self.getPhaseCalls(self.barrier.phases)
                    phases_in_calls = self.getPhasesInCalls(calls_unserviceable)
                    
                    if len(phases_in_calls) >= len(barrier_calls):
                        self.newCycle(note='unserviceable calls')
                    
                    if self.barrier.exhausted:
                        self.newCycle(note='barrier exhausted')
                    else:
                        if len(self.cycle_phases) == len(self.phases):
                            self.newCycle(note='cycle complete')
        elif self.mode == OperationMode.CET:
            for phase in self.phases:
                phase.tick(True)
            
            if self.cet_timer.poll(True):
                self.setOperationState(OperationMode.NORMAL)
    
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
