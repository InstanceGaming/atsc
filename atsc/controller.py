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
from jacob.text import post_pend
from atsc.core import *
from atsc import network, serialbus, logic
from loguru import logger
from typing import Iterable
from bitarray import bitarray
from atsc.utils import buildFieldMessage
from atsc.frames import FrameType, DeviceAddress, OutputStateFrame
from atsc.ringbarrier import Ring, Barrier
from jacob.enumerations import text_to_enum


class Controller:
    INCREMENT = 0.1
    
    def __init__(self, config: dict):
        # controller name (arbitrary)
        self.name = config['device']['name']
        
        # should place calls on all phases when started?
        self.recall_all = config['init']['recall-all']
        
        # 1Hz square wave reference clock
        self.flasher = True
        
        # loop enable flag
        self.running = False
        
        # local flash transfer relay status
        self.transferred = False
        
        # operation functionality of the controller
        self.mode: OperationMode = text_to_enum(OperationMode, config['init']['mode'])
        
        # there are two trigger sources for time freeze: system, input
        # see self.time_freeze for a scalar state
        self.freeze: bool = False
        
        self.load_switches: List[LoadSwitch] = [LoadSwitch(1), LoadSwitch(2), LoadSwitch(3), LoadSwitch(4),
                                                LoadSwitch(5), LoadSwitch(6), LoadSwitch(7), LoadSwitch(8),
                                                LoadSwitch(9), LoadSwitch(10), LoadSwitch(11), LoadSwitch(12)]
        
        default_timing = self.getDefaultTiming(config['default-timing'])
        self.phases: List[Phase] = self.getPhases(config['phases'], default_timing)
        self.idle_phases: List[Phase] = self.getIdlePhases(config['idle-phases'])
        self.phase_pool: List[Phase] = self.phases.copy()
        self.calls: List[Call] = []
        
        self.rings: List[Ring] = self.getRings(config['rings'])
        self.barriers: List[Barrier] = self.getBarriers(config['barriers'])
        self.barrier: Optional[Barrier] = None
        
        self.cycle_count = 0
        self.phase_count = 0
        
        self.serve_timer = logic.Timer(5, step=-1)
        
        # 500ms timer elapsed (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self.half_counter: int = 0
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        self.cet_time: int = config['init']['cet-delay'] + yellow_time
        self.cet_counter: float = self.cet_time
        
        # inputs data structure instances
        self.inputs: Dict[int, Input] = self.getInputs(config.get('inputs'))
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self.last_input_bitfield: Optional[bitarray] = bitarray()
        
        # communications
        self.bus: Optional[serialbus.Bus] = self.getBus(config['bus'])
        self.monitor: Optional[network.Monitor] = self.getNetworkMonitor(config['network'])
        if self.monitor is not None:
            self.monitor.setControlInfo(self.name, self.phases, self.getPhaseLoadSwitchIndexMapping())
        
        # for software demo and testing purposes
        random_config = config['random-actuation']
        random_delay = random_config['delay']
        self.random_enabled = random_config['enabled']
        self.random_min = random_config['min']
        self.random_max = random_config['max']
        self.randomizer = random.Random()
        self.random_timer = logic.Timer(random_delay, step=-1)
    
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
            phase = Phase(i, self.INCREMENT, phase_timing, veh, ped, flash_mode)
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
    
    def getPhaseLoadSwitchIndexMapping(self) -> Dict[Phase, List[int]]:
        mapping = {}
        
        for ph in self.phases:
            indices = [ph.veh_ls.id - 1]
            if ph.ped_ls is not None:
                indices.append(ph.ped_ls.id - 1)
            mapping.update({ph: indices})
        
        return mapping
    
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
                return network.Monitor(host, monitor_port)
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
    
    def getActivePhaseCount(self) -> int:
        count = 0
        for phase in self.phases:
            if phase.active:
                count += 1
        return count
    
    def placeCall(self, phases: List[Phase], note: Optional[str] = None):
        """
        Create a new demand for traffic service.

        :param phases: the desired Phases to service.
        :param note: arbitrary note to be appended to log message
        """
        note_text = post_pend(note, note)
        
        exists = any([phase in self.calls for phase in phases])
        if not exists:
            call = Call(phases,  self.getActivePhaseCount(), len(self.calls))
            logger.debug(f'Call placed for {call.phase_tags_list}{note_text}')
            self.calls.append(call)
    
    def placeAllCall(self):
        """Place calls on all phases"""
        for phase in self.phases:
            self.placeCall([phase], 'all call')
    
    def detection(self, phases: List[Phase], note: Optional[str] = None):
        note_text = post_pend(note, note)
        
        if all([phase.state not in PHASE_GO_STATES for phase in phases]):
            self.placeCall(phases, note)
        else:
            for phase in phases:
                if phase.state in PHASE_GO_STATES:
                    logger.debug(f'Detection on {phase.getTag()}{note_text}')
                    
                    if phase.extend_active:
                        phase.gap_reset()
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
                    logger.fine('Discarding signal for unused input slot '
                                f'{slot}')
        
        self.last_input_bitfield = bf
    
    def checkPhaseConflict(self, a: Phase, b: Phase) -> bool:
        """
        Check if two phases conflict based on Ring, Barrier and defined friend
        channels.

        :param a: Phase to compare against
        :param b: Other Phase to compare
        :return: True if conflict
        """
        if a == b:
            raise RuntimeError('Conflict check on the same phase object')
        
        # verify Phase b is not in the same ring
        if b.id in self.getRingByPhase(a).phases:
            return True
        
        if b.id not in self.getBarrierByPhase(a).phases:
            return True
        
        # future: consider FYA-enabled phases conflicts for a non-FYA phase
        
        return False
    
    def canPhaseRun(self,
                    phase: Phase,
                    pool: Iterable[Phase],
                    as_partner: bool) -> bool:
        if not phase.ready:
            return False
        
        if as_partner and phase.state not in PHASE_PARTNER_START_STATES:
            return False
        
        if phase not in pool:
            return False
        
        for other in self.phases:
            if other == phase:
                continue
            if other.active and self.checkPhaseConflict(phase, other):
                return False
        
        return True
    
    def getCurrentPhasePool(self) -> List[Phase]:
        if self.barrier is not None:
            return self.getBarrierPhases(self.barrier)
        else:
            return self.phase_pool
    
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
            for ph in self.phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.update(force_state=PhaseState.CAUTION)
            
            self.cet_counter = self.cet_time
        elif new_state == OperationMode.NORMAL:
            for ph in self.phases:
                ph.update(force_state=PhaseState.STOP)
            
            self.setBarrier(None)
            
            if self.recall_all:
                self.placeAllCall()
        
        previous_state = self.mode
        self.mode = new_state
        logger.info(f'Operation state is now {new_state.name} (was {previous_state.name})')
    
    def updateBusOutputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self.transferred)
        self.bus.sendFrame(osf)
    
    def servePhase(self, phase: Phase):
        logger.debug(f'Serving phase {phase.getTag()}')
        self.serve_timer.reset()
        phase.activate()
    
    def getPhasePartner(self,
                        phase: Phase,
                        barrier: Optional[Barrier] = None) -> Optional[Phase]:
        if self.barrier is not None:
            pool = self.getBarrierPhases(barrier or self.barrier)
        else:
            pool = self.phase_pool
        
        for candidate in pool:
            if candidate == phase:
                continue
            if candidate.ready:
                if not self.checkPhaseConflict(phase, candidate):
                    return candidate
        return None
    
    def getAllCallPhases(self) -> List[Phase]:
        phases = []
        for call in self.calls:
            phases.extend(call.phases)
        return phases
    
    def setBarrier(self, b: Optional[Barrier]):
        if b is not None:
            logger.debug(f'Crossed to {b.getTag()}')
        else:
            logger.debug(f'Free barrier')
        
        self.barrier = b
    
    def endCycle(self, early: bool) -> None:
        """End phasing for this control cycle iteration"""
        self.cycle_count += 1
        self.phase_pool = self.phases.copy()
        
        for barrier in self.barriers:
            barrier.serve_count = 0
        
        self.setBarrier(None)
        early_text = post_pend('early', early)
        logger.debug(f'Ended cycle {self.cycle_count}{early_text}')
        
    def getServableIdlePhases(self):
        if len(self.idle_phases):
            phases = []
            
            pool = self.getCurrentPhasePool()
            for phase in self.idle_phases:
                if self.canPhaseRun(phase, pool, False):
                    phases.append(phase)
            
            if len(phases):
                ring_slice = phases[:len(self.rings)]
                return ring_slice
        
        return []
    
    def tick(self):
        """Polled once every 100ms"""
        
        if self.bus is not None:
            self.handleBusFrame()
        
        if not self.freeze:
            if self.mode == OperationMode.NORMAL:
                concurrent_rings = len(self.rings)
                active_count = self.getActivePhaseCount()
                
                if not len(self.calls) and len(self.idle_phases):
                    idle_phases = self.getServableIdlePhases()
                    if idle_phases:
                        self.placeCall(idle_phases, 'idle')
                    else:
                        if not active_count:
                            self.endCycle(True)
                
                if not active_count:
                    if not len(self.phase_pool):
                        self.endCycle(False)
                    
                    if self.barrier is not None:
                        ready_phases = {p for p in self.phase_pool if p.ready}
                        barrier_phases = self.getBarrierPhases(self.barrier)
                        available = ready_phases.intersection(barrier_phases)
                        has_demand = available.intersection(self.getAllCallPhases())
                        if not len(has_demand):
                            logger.debug('{} exhausted', self.barrier.getTag())
                            self.setBarrier(None)
                            self.endCycle(True)
                
                satisfied = []
                for call in self.calls:
                    if len(call.phases) == 1:
                        alone = not call.active_count and call.queue_size == 1
                        if alone:
                            solo = call.phases[0]
                            partner = self.getPhasePartner(solo)
                            if partner is not None:
                                logger.debug(f'Inserting partner {partner.getTag()} '
                                             f'to serve with {solo.getTag()}')
                                call.phases.append(partner)
                    
                    phase_pool = self.getCurrentPhasePool()
                    serve_count = 0
                    for phase in call.phases:
                        if self.canPhaseRun(phase, phase_pool, active_count > 0):
                            barrier = self.getBarrierByPhase(phase)
                            if self.barrier is None:
                                logger.debug('{} captured {}',
                                             phase.getTag(),
                                             barrier.getTag())
                                self.setBarrier(barrier)
                            
                            self.servePhase(phase)
                            barrier.serve_count += 1
                            serve_count += 1
                            
                            phase_pool = self.getCurrentPhasePool()
                            active_count = self.getActivePhaseCount()
                            
                            if active_count >= concurrent_rings:
                                break
                    
                    if serve_count:
                        satisfied.append(call)
                
                for call in satisfied:
                    self.calls.remove(call)
                
                for phase in self.phases:
                    conflicting_demand = False
                    
                    for call in self.calls:
                        for other_phase in call.phases:
                            if other_phase != phase and self.checkPhaseConflict(phase, other_phase):
                                conflicting_demand = True
                                break
                        if conflicting_demand:
                            break
                    
                    idle_override = self.idle_phases and (phase not in self.idle_phases) or phase.secondary
                    
                    if phase.tick(self.flasher, conflicting_demand or idle_override):
                        if phase.state in PHASE_STOP_STATES:
                            if phase in self.phase_pool:
                                self.phase_count += 1
                                self.phase_pool.remove(phase)
                                logger.debug('{} terminated', phase.getTag())
            elif self.mode == OperationMode.CET:
                for ph in self.phases:
                    ph.tick(self.flasher, True)
                
                if self.cet_counter > self.INCREMENT:
                    self.cet_counter -= self.INCREMENT
                else:
                    self.setOperationState(OperationMode.NORMAL)
            
            if self.half_counter == 4:
                self.half_counter = 0
                self.halfSecond()
            else:
                self.half_counter += 1
        
        if self.bus is not None:
            self.updateBusOutputs(self.load_switches)
        
        if self.monitor is not None:
            pmd = []
            
            for _ in self.phases:
                pmd.append((0, 0))
            
            self.monitor.broadcastControlUpdate(self.phases, pmd, self.load_switches)
        
        logger.fields(buildFieldMessage(self.load_switches))
    
    def halfSecond(self):
        """Polled once every 500ms"""
        if not self.freeze:
            if not self.flasher:
                self.second()
        
            self.flasher = not self.flasher
    
    def second(self):
        """Polled once every 1000ms"""
        if self.bus is not None:
            if not self.bus.ready:
                logger.error('Bus not running')
                self.shutdown()
        
        if self.monitor is not None:
            self.monitor.clean()
            
        if self.mode == OperationMode.NORMAL:
            call_count = len(self.calls)
            serve_timer_time = call_count and not self.getActivePhaseCount()
            if self.serve_timer.poll(serve_timer_time):
                logger.warning('has not served phase within timeout with {} '
                               'pending calls', call_count)
                if __debug__:
                    breakpoint()
                self.serve_timer.reset()
            
            if self.random_timer.poll(self.random_enabled):
                phases = []
                uncalled = list(set(self.phases).difference(self.getAllCallPhases()))
                first_phase = self.randomizer.choice(uncalled)
                phases.append(first_phase)
                choose_two = round(self.randomizer.random())
                if choose_two:
                    second_phase = self.getPhasePartner(first_phase,
                                                        self.getBarrierByPhase(first_phase))
                    if second_phase is not None:
                        phases.append(second_phase)
                
                next_delay = self.randomizer.randint(self.random_min, self.random_max)
                logger.debug('Random actuation for {}, next in {}s',
                             csl([phase.getTag() for phase in phases]),
                             next_delay)
                
                self.detection(phases, 'random actuation')
                self.random_timer.delay = next_delay
                self.random_timer.reset()
                
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
        
        logger.debug('CET delay set to 3s')
        
        if self.running:
            if self.monitor is not None:
                self.monitor.start()
            
            if self.bus is not None:
                self.bus.start()
                
                while not self.bus.ready:
                    logger.info(f'Waiting on bus...')
                    time.sleep(self.INCREMENT)
                
                logger.info(f'Bus ready')
            
            self.setOperationState(self.mode)
            self.transfer()
            while True:
                self.tick()
                time.sleep(self.INCREMENT)
    
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
