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
from atsc import network, serialbus
from loguru import logger
from typing import Set, FrozenSet
from bitarray import bitarray
from itertools import cycle
from atsc.utils import buildFieldMessage
from atsc.frames import FrameType, DeviceAddress, OutputStateFrame
from atsc.ringbarrier import Ring, Barrier
from jacob.enumerations import text_to_enum


class RandomActuation:
    
    def __init__(self, configuration_node: dict, phase_id_pool: List[int]
                 ):
        self._enabled = configuration_node['enabled']
        self._min = configuration_node['min']  # seconds
        self._max = configuration_node['max']  # seconds
        self._counter = configuration_node['delay']  # seconds
        self._pool = sorted(phase_id_pool)
        
        seed = configuration_node.get('seed')
        if seed is not None and seed > 0:
            # global pseudo-random generator seed
            random.seed(seed)
    
    def poll(self) -> Optional[int]:
        if self._counter > 0:
            self._counter -= 1
        elif self._counter == 0 and self._enabled:
            delay = random.randrange(self._min, self._max)
            self._counter = delay
            return self.getPhaseIndex()
        
        return None
    
    def getPhaseIndex(self) -> int:
        return random.choice(self._pool)


class Controller:
    INCREMENT = 0.1
    
    @property
    def bus_enabled(self):
        """Is the serial bus enabled"""
        return self._bus is not None
    
    @property
    def monitor_enabled(self):
        """Is the network monitor enabled"""
        return self._monitor is not None
    
    @property
    def time_freeze(self):
        """If the controller is currently freezing time"""
        return self._time_freeze
    
    @property
    def name(self):
        """Name of the controller"""
        return self._name
    
    @property
    def flasher(self):
        """1Hz square wave reference"""
        return self._flasher
    
    def __init__(self, config: dict):
        # controller name (arbitrary)
        self._name = config['device']['name']
        
        # should place calls on all phases when started?
        self._recall_all = config['init']['recall-all']
        
        # 1Hz square wave reference clock
        self._flasher = True
        
        # loop enable flag
        self._running = False
        
        # local flash transfer relay status
        self._transfer = False
        
        # operation functionality of the controller
        self._op_mode: OperationMode = text_to_enum(OperationMode, config['init']['mode'])
        
        # there are two trigger sources for time freeze: system, input
        # see self.time_freeze for a scalar state
        self._time_freeze: bool = False
        
        self._load_switches: List[LoadSwitch] = [LoadSwitch(1), LoadSwitch(2), LoadSwitch(3), LoadSwitch(4),
                                                 LoadSwitch(5), LoadSwitch(6), LoadSwitch(7), LoadSwitch(8),
                                                 LoadSwitch(9), LoadSwitch(10), LoadSwitch(11), LoadSwitch(12)]
        
        default_timing = self.getDefaultTiming(config['default-timing'])
        self._phases: List[Phase] = self.getPhases(config['phases'], default_timing)
        self._idle_phases: List[Phase] = self.getIdlePhases(config['idle-phases'])
        
        self._rings: List[Ring] = self.getRings(config['rings'])
        self._barriers: List[Barrier] = self.getBarriers(config['barriers'])
        
        # cycle instance of barriers
        self._barrier_pool: cycle = cycle(self._barriers)
        
        # current barrier
        self._active_barrier: Optional[Barrier] = None
        
        # total cycle counter
        self._cycle_count = 0
        
        self._cycle_pool: Set[Phase] = set(self._phases)
        
        # 500ms timer counter (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self._half_counter: int = 0
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        self._cet_time: int = config['init']['cet-delay'] + yellow_time
        self._cet_counter: float = self._cet_time
        
        # inputs data structure instances
        self._inputs: Dict[int, Input] = self.getInputs(config.get('inputs'))
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self._last_input_bitfield: Optional[bitarray] = bitarray()
        
        # communications
        self._bus: Optional[serialbus.Bus] = self.getBus(config['bus'])
        self._monitor: Optional[network.Monitor] = self.getNetworkMonitor(config['network'])
        if self._monitor is not None:
            self._monitor.setControlInfo(self.name, self._phases, self.getPhaseLoadSwitchIndexMapping())
        
        # for software demo and testing purposes
        self._random_actuation: RandomActuation = RandomActuation(config['random-actuation'],
                                                                  [ph.id for ph in self._phases])
    
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
        
        for ph in self._phases:
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
                    target = self._phases[target_index - 1]
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
        for ring in self._rings:
            if phase.id in ring.phases:
                return ring
        
        raise RuntimeError(f'Failed to get ring')
    
    def getBarrierByPhase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        assert isinstance(phase, Phase)
        for b in self._barriers:
            if phase.id in b.phases:
                return b
        
        raise RuntimeError(f'Failed to get barrier by {phase.getTag()}')
    
    def getPhaseById(self, i: int) -> Phase:
        for ph in self._phases:
            if ph.id == i:
                return ph
        raise RuntimeError(f'Failed to find phase {i}')
    
    def getLoadSwitchById(self, i: int) -> LoadSwitch:
        for ls in self._load_switches:
            if ls.id == i:
                return ls
        raise RuntimeError(f'Failed to find load switch {i}')
    
    def getActivePhases(self) -> List[Phase]:
        return [ph for ph in self._phases if ph.active]
    
    def placeCall(self, phase: Phase, input_slot=None, system=False):
        """
        Create a new call for traffic service.

        :param phase: the desired Phase to service.
        :param input_slot: associate call with input slot number
        :param system: mark call as placed by system
        :returns: False when ignored (due to phase being active)
        """
        input_text = ''
        
        if input_slot is not None:
            input_text = f' (input #{input_slot})'
            
        if system:
            input_text += ' (system)'
        
        if not phase.demand:
            logger.debug(f'Demand for {phase.getTag()}{input_text}')
            phase.demand = True
    
    def placeAllCall(self):
        """Place calls on all phases"""
        for phase in self._phases:
            self.placeCall(phase, system=True)
    
    def detection(self, phase: Phase, input_slot=None, system=False):
        postfix = ''
        
        if input_slot is not None:
            postfix = f' (input #{input_slot})'
        
        if system:
            postfix += ' (system)'
        
        if phase.state in PHASE_GO_STATES:
            logger.debug(f'Detection on {phase.getTag()}{postfix}')
            if phase.extend_active:
                phase.gap_reset()
        else:
            self.placeCall(phase, input_slot=input_slot, system=system)
    
    def setOperationState(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            for ph in self._phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.update(force_state=PhaseState.CAUTION)
            
            self._cet_counter = self._cet_time
        elif new_state == OperationMode.NORMAL:
            for ph in self._phases:
                ph.update(force_state=PhaseState.STOP)
            if self._recall_all:
                self.placeAllCall()
        
        previous_state = self._op_mode
        self._op_mode = new_state
        logger.info(f'Operation state is now {new_state.name} '
                      f'(was {previous_state.name})')
    
    def getPhasesWithDemand(self, barrier: Optional[Barrier] = None) -> FrozenSet[Phase]:
        """
        Get phases that have at least one call.

        :param barrier: optionally omit phases not belonging to specific barrier
        """
        phases = set()
        
        for phase in self._phases:
            if barrier is not None:
                if phase.id not in barrier.phases:
                    continue
            
            if phase.demand:
                phases.add(phase)
        
        return frozenset(phases)
    
    def handleInputs(self, bf: bitarray):
        """Check on the contents of bus data container for changes"""
        
        if self._last_input_bitfield is None or bf != self._last_input_bitfield:
            for slot, inp in self._inputs.items():
                if inp.action == InputAction.NOTHING:
                    continue
                
                try:
                    state = bf[slot - 1]
                    
                    inp.last_state = inp.state
                    inp.state = state
                    
                    if inp.activated():
                        if inp.action == InputAction.CALL:
                            for target in inp.targets:
                                self.placeCall(target, input_slot=slot)
                        elif inp.action == InputAction.DETECT:
                            for target in inp.targets:
                                self.detection(target, input_slot=slot)
                        else:
                            raise NotImplementedError()
                except IndexError:
                    logger.fine('Discarding signal for unused input slot '
                                  f'{slot}')
        
        self._last_input_bitfield = bf
    
    def endCycle(self, early: bool) -> None:
        """End phasing for this control cycle iteration"""
        self._cycle_count += 1
        self._cycle_pool = set(self._phases)
        
        for barrier in self._barriers:
            barrier.phases_served = 0
        
        logger.debug(f'Ended cycle {self._cycle_count}{" (early)" if early else ""}')
    
    def setBarrier(self, b: Optional[Barrier]):
        if b != self._active_barrier:
            self._active_barrier = b
            if b is not None:
                logger.debug(f'Crossed to {b.getTag()}')
            else:
                logger.debug(f'Free barrier')
    
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
    
    def canPhaseRun(self, phase: Phase, pool: FrozenSet[Phase]) -> bool:
        assert not phase.active
        
        if not phase.ready:
            return False
        
        if phase not in pool:
            return False
        
        for other in self._phases:
            if other == phase:
                continue
            if other.active and self.checkPhaseConflict(phase, other):
                return False
            
        return True
    
    def getCurrentPhasePool(self) -> FrozenSet[Phase]:
        if self._active_barrier is not None:
            return frozenset(self.getBarrierPhases(self._active_barrier))
        else:
            return frozenset(self._cycle_pool)
    
    def handleBusFrame(self):
        frame = self._bus.get()
        
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
    
    def updateBusOutputs(self, lss: List[LoadSwitch]):
        osf = OutputStateFrame(DeviceAddress.TFIB1, lss, self._transfer)
        self._bus.sendFrame(osf)
    
    def servePhase(self, phase: Phase):
        if self._active_barrier is not None:
            self._active_barrier.phases_served += 1
        
        logger.debug(f'Serving phase {phase.getTag()}')
        phase.activate()
        phase.demand = False
    
    def tick(self):
        """Polled once every 100ms"""
        
        if self.bus_enabled:
            self.handleBusFrame()
        
        if not self.time_freeze:
            if self._op_mode == OperationMode.NORMAL:
                phase_pool = self.getCurrentPhasePool()
                concurrent_phases = len(self._rings)
                
                for phase in self.getPhasesWithDemand(barrier=self._active_barrier):
                    if not phase.active:
                        if self.canPhaseRun(phase, phase_pool):
                            self.servePhase(phase)
                            if len(self.getActivePhases()) >= concurrent_phases:
                                break
                        phase_pool = self.getCurrentPhasePool()
                
                if not len(self.getActivePhases()):
                    demand_phases = self.getPhasesWithDemand(barrier=self._active_barrier)
                    if not len(demand_phases):
                        count = 0
                        for ip in self._idle_phases:
                            if not ip.active and not ip.demand:
                                if self.canPhaseRun(ip, phase_pool):
                                    logger.debug(f'{ip.getTag()} idler')
                                    self.detection(ip, system=True)
                                    count += 1
                            if count >= concurrent_phases:
                                break
                    else:
                        if not len(self._cycle_pool):
                            self.endCycle(False)
                            self.setBarrier(next(self._barrier_pool))
                        else:
                            ready_phases = set([p for p in self._cycle_pool if p.ready])
                            available = ready_phases - demand_phases
                            if not len(available):
                                self.endCycle(True)
                                self.setBarrier(None)
                
                for phase in self._phases:
                    conflicting_demand = False
                    
                    for other_phase in self._phases:
                        if phase != other_phase and self.checkPhaseConflict(phase, other_phase):
                            conflicting_demand = True
                            break
                    
                    idle_override = self._idle_phases and (phase not in self._idle_phases) or phase.ped_ls is None
                    
                    if phase.tick(self.flasher, conflicting_demand or idle_override):
                        if phase.state in PHASE_STOP_STATES:
                            if phase in self._cycle_pool:
                                self._cycle_pool.remove(phase)
            elif self._op_mode == OperationMode.CET:
                for ph in self._phases:
                    ph.tick(self._flasher, True)
                
                if self._cet_counter > self.INCREMENT:
                    self._cet_counter -= self.INCREMENT
                else:
                    self.setOperationState(OperationMode.NORMAL)
            
            if self._half_counter == 4:
                self._half_counter = 0
                self.halfSecond()
            else:
                self._half_counter += 1
        
        if self.bus_enabled:
            self.updateBusOutputs(self._load_switches)
        
        if self.monitor_enabled:
            pmd = []
            
            for ph in self._phases:
                pmd.append((0, 0))
            
            self._monitor.broadcastControlUpdate(self._phases, pmd, self._load_switches)
        
        logger.fields(buildFieldMessage(self._load_switches))
    
    def busHealthCheck(self):
        """Ensure bus thread is still running, if enabled"""
        if self.bus_enabled:
            if not self._bus.ready:
                logger.error('Bus not running')
                self.shutdown()
    
    def halfSecond(self):
        """Polled once every 500ms"""
        self.busHealthCheck()
        
        self._flasher = not self._flasher
        
        if not self.time_freeze:
            if self._flasher:
                self.second()
    
    def second(self):
        """Polled once every 1000ms"""
        if self.monitor_enabled:
            self._monitor.clean()
        
        if not self.time_freeze:
            if self._op_mode == OperationMode.NORMAL:
                choice = self._random_actuation.poll()
                if choice is not None:
                    self.detection(self.getPhaseById(choice), system=True)
    
    def transfer(self):
        """Set the controllers flash transfer relays flag"""
        logger.info('Transferred')
        self._transfer = True
    
    def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        logger.info('Untransfered')
        self._transfer = False
    
    def run(self):
        """Begin control loop"""
        self._running = True
        
        logger.info(f'Controller is named "{self._name}"')
        
        # noinspection PyUnreachableCode
        if __debug__:
            logger.warning('Controller in DEBUG ENVIRONMENT!')
        
        logger.debug('CET delay set to 3s')
        
        if self._running:
            if self.monitor_enabled:
                self._monitor.start()
            
            if self.bus_enabled:
                self._bus.start()
                
                while not self._bus.ready:
                    logger.info(f'Waiting on bus...')
                    time.sleep(self.INCREMENT)
                
                logger.info(f'Bus ready')
            
            self.setOperationState(self._op_mode)
            self.transfer()
            while True:
                self.tick()
                time.sleep(self.INCREMENT)
    
    def shutdown(self):
        """Run termination tasks to stop control loop"""
        self.untransfer()
        self._running = False
        
        if self.bus_enabled:
            logger.info('Stopping bus')
            self._bus.shutdown()
            self._bus.join(timeout=1)
        
        if self.monitor_enabled:
            logger.info('Stopping network monitor')
            self._monitor.shutdown()
            self._monitor.join(timeout=1)
        
        logger.info('Shutdown complete')
