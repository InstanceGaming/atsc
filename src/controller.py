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
import utils
import random
import network
import serialbus
import asyncio
from loguru import logger
from core import *
from frames import FrameType, DeviceAddress, OutputStateFrame
from typing import Set, Iterable, FrozenSet
from bitarray import bitarray
from functools import lru_cache, cmp_to_key
from dateutil.parser import parse as _dt_parser

from src.fundemental import ATSCObject


def parse_datetime_text(text: str, tz):
    rv = _dt_parser(text, dayfirst=False, fuzzy=True)
    return rv.replace(tzinfo=tz)


class RandomActuation:
    
    @property
    def enabled(self):
        return self._enabled
    
    @property
    def min(self):
        return self._min
    
    @property
    def max(self):
        return self._max
    
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


class TimeFreezeReason(IntEnum):
    SYSTEM = 0
    INPUT = 1


class PhaseStatus(IntEnum):
    INACTIVE = 0
    NEXT = 1
    LEADER = 2
    SECONDARY = 3


class Controller(ATSCObject):
    PHASE_COUNT = 8
    LS_COUNT = 12
    INCREMENT = 0.1
    
    @property
    def name(self):
        return self._name
    
    @property
    def running(self):
        """Is the controller running"""
        return self._running
    
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
        return len(self._time_freeze_reasons) > 0
    
    @property
    def operation_mode(self):
        """Current operation mode of the controller"""
        return self._op_mode
    
    @property
    def transferred(self):
        """Has the controller transferred the flash transfer relays"""
        return self._transfer
    
    @property
    def flasher(self):
        """1Hz square wave reference"""
        return self._flasher
    
    @property
    def calls(self):
        """A copy of the current controller calls stack"""
        return self._calls.copy()
    
    @property
    def inputs_count(self):
        """Number of input objects"""
        return len(self._inputs.keys())
    
    def __init__(self, config: dict, tz):
        super().__init__('controller')
        
        self._name = config['device']['name']
        
        # should place calls on all phases when started?
        self._recall_all = config['init']['recall-all']
        
        # controller timezone tag
        self._tz = tz
        
        # 1Hz square wave reference clock
        self._flasher = True
        
        # loop enable flag
        self._running = False
        
        # local flash transfer relay status
        self._transfer = False
        
        # operation functionality of the controller
        self._op_mode: OperationMode = utils.textToEnum(OperationMode, config['init']['mode'])
        
        # there are two trigger sources for time freeze: system, input
        # see self.time_freeze for a scalar state
        self._time_freeze_reasons: Set[TimeFreezeReason] = set()
        
        self._load_switches: List[LoadSwitch] = [LoadSwitch(1), LoadSwitch(2), LoadSwitch(3), LoadSwitch(4),
                                                 LoadSwitch(5), LoadSwitch(6), LoadSwitch(7), LoadSwitch(8),
                                                 LoadSwitch(9), LoadSwitch(10), LoadSwitch(11), LoadSwitch(12)]
        
        default_timing = self.getDefaultTiming(config['default-timing'])
        self._phases: List[Phase] = self.getPhases(config['phases'], default_timing)
        self._idle_phases: List[Phase] = self.getIdlePhases(config['idle-phases'])
        
        self._rings: FrozenSet[Ring] = self.getRings(config['rings'])
        self._barrier: ATSCBarrier = ATSCBarrier((1, 3), len(self._rings))
        
        # total cycle counter
        self._cycle_count = 1
        
        # 500ms timer counter (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self._half_counter: int = 0
        
        # control entrance transition timer
        yellow_time = default_timing[PhaseState.CAUTION]
        self._cet_time: int = config['init']['cet-delay'] + yellow_time
        self._cet_counter: float = self._cet_time
        
        # actuation
        self._call_counter: int = 0
        self._calls: Set[Call] = set()
        self._mvp_call: Optional[Call] = None
        self._max_call_age = config['calls']['max-age']
        self._call_weights = config['calls']['weights']
        self._last_call_count: int = 0
        
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
    
    def getDefaultTiming(self, configuration_node: Dict[str, float]
                         ) -> Dict[PhaseState, float]:
        timing = {}
        for name, value in configuration_node.items():
            ps = utils.textToEnum(PhaseState, name)
            timing.update({ps: value})
        return timing
    
    def getPhases(self, configuration_node: List[Dict], default_timing: Dict[PhaseState, float]
                  ) -> List[Phase]:
        phases = []
        
        for i, node in enumerate(configuration_node, start=1):
            flash_mode_text = node['flash-mode']
            flash_mode = utils.textToEnum(FlashMode, flash_mode_text)
            phase_timing: Dict[PhaseState, float] = default_timing.copy()
            timing_data = node.get('timing')
            
            if timing_data is not None:
                for name, value in timing_data.items():
                    ps = utils.textToEnum(PhaseState, name)
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
    
    def getRings(self, configuration_node: List[List[int]]) -> FrozenSet[Ring]:
        rings = set()
        for i, pids in enumerate(configuration_node, start=1):
            phases = [self.getPhaseById(pid) for pid in pids]
            rings.add(Ring(i, phases))
        return frozenset(rings)
    
    def getBarriers(self, configuration_node: List[int]) -> List[int]:
        unique_indices = frozenset(configuration_node)
        rv = sorted(unique_indices)
        assert len(rv) < len(self._phases)
        return rv
    
    def buildMockPhase(self, timing, i: int, vi, pi=None) -> Phase:
        veh = self._load_switches[vi - 1]
        ped = None
        if pi is not None:
            ped = self._load_switches[pi - 1]
        return Phase(i, self.INCREMENT, timing, veh, ped)
    
    @lru_cache(maxsize=8)
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
                    action = utils.textToEnum(InputAction, input_node['action'])
                active = utils.textToEnum(InputActivation, input_node['active'])
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
                        auto_ip = utils.getIPAddress(if_name)
                        host = auto_ip
                    except Exception as e:
                        logger.warning(f'Failed to get address of network '
                                         f'interface: {str(e)}')
                elif if_name == 'any':
                    host = '0.0.0.0'
                
                logger.info(f'Using IP address {host}')
                
                monitor_port = monitor_node['port']
                return network.Monitor(self, host, monitor_port)
            else:
                logger.info('Network monitor disabled')
        
        logger.info('Networking disabled')
        return None
    
    def getBarrierOffset(self, pos: int, offset: int) -> Optional[int]:
        index = self._barrier.index(pos)
        try:
            return self._barrier.positions[index + offset]
        except IndexError:
            return None

    @lru_cache(maxsize=4)
    def getBarrierRange(self, pos: int) -> range:
        previous_pos = self.getBarrierOffset(pos, -1)
        return range(previous_pos, pos)
    
    @lru_cache(maxsize=4)
    def getBarrierPhases(self, pos: int) -> List[Phase]:
        """Get the phases left of a `Barrier`"""
        barrier_range = self.getBarrierRange(pos)
        phases = []
        for ring in self._rings:
            for i, phase in enumerate(ring.phases):
                if i in barrier_range:
                    phases.append(phase)
        return phases
    
    @lru_cache(maxsize=16)
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
        
        if b.id not in self.getBarrierPhases(self.getBarrierByPhase(a)):
            return True
        
        # future: consider FYA-enabled phases conflicts for a non-FYA phase
        
        return False
    
    def getAvailablePhases(self,
                           phases: Iterable,
                           active: List[Phase]) -> FrozenSet[Phase]:
        """
        Determine what phases from a given pool can run given
        the current controller state.

        :param phases: an iterable of Phases to scrutinize
        :param active: currently active phases for iteration
        :return: an immutable set of available Phases
        """
        results: Set[Phase] = set()
        
        for phase in phases:
            if phase in active:
                continue
            
            if any([self.checkPhaseConflict(phase, act) for act in active]):
                continue
            
            if phase.state == PhaseState.MIN_STOP:
                continue
            
            results.add(phase)
        
        return frozenset(results)
    
    @lru_cache(maxsize=16)
    def getRingByPhase(self, phase: Phase) -> Ring:
        for ring in self._rings:
            if phase.id in ring.phases:
                return ring
        
        raise RuntimeError('Failed to get ring')

    def getPhaseRingIndex(self, phase: Phase) -> Optional[int]:
        for ring in self._rings:
            if phase in ring.phases:
                return ring.getPhaseIndex(phase)
        return None

    def getPriorityPhase(self, phases: List[Phase]) -> Optional[Phase]:
        """
        Get the ranks of the given iterable of `Phase` instances by
        associated `Call` priority, returning the top choice.

        :param phases: a list of Phase instances
        :return: top choice Phase or None if list was empty
        """
        if len(phases) > 0:
            phase_calls = self.rankCalls(self.filterCallsByPhases(self._calls, phases))
            if len(phase_calls) > 0:
                return phase_calls[0].target
        return None
    
    def filterCallsByPhases(self, calls: Iterable[Call], phases: Iterable[Phase]) -> List[Call]:
        return [c for c in calls if c.target in phases]
    
    def filterCallsByBarrier(self, calls: Iterable[Call], barrier: int) -> List[Call]:
        return [c for c in calls if c.target.id in self.getBarrierPhases(barrier)]
    
    @lru_cache(maxsize=16)
    def getBarrierByPhase(self, phase: Phase) -> int:
        phase_ring_index = self.getPhaseRingIndex(phase)
        for pos in self._barrier.positions:
            barrier_range = self.getBarrierRange(pos)
            if phase_ring_index in barrier_range:
                return pos
        raise RuntimeError('failed to get barrier for phase')
    
    def placeAllCall(self, ped_service=False):
        """Place calls on all phases"""
        for phase in self._phases:
            self.placeCall(phase, ped_service=ped_service)
    
    def getPriorityBarrier(self) -> Optional[int]:
        """
        Get the pos with the most priority phase, if there is one.
        """
        priority_phase = self.getPriorityPhase(self._phases)
        if priority_phase is not None:
            return self.getBarrierByPhase(priority_phase)
        return None
    
    def nextBarrier(self):
        """Change to the next `Barrier` in the pos cycle instance"""
        self._barrier.next()
    
    @lru_cache(maxsize=8)
    def getPhaseById(self, i: int) -> Phase:
        for ph in self._phases:
            if ph.id == i:
                return ph
        raise RuntimeError(f'Failed to find phase {i}')
    
    @lru_cache(maxsize=12)
    def getLoadSwitchById(self, i: int) -> LoadSwitch:
        for ls in self._load_switches:
            if ls.id == i:
                return ls
        raise RuntimeError(f'Failed to find load switch {i}')
    
    def getActivePhases(self) -> List[Phase]:
        return [ph for ph in self._phases if ph.active]
    
    def getInactivePhases(self) -> List[Phase]:
        return [ph for ph in self._phases if not ph.active]
    
    def _sortCallsKeyFunc(self, left: Call, right: Call) -> int:
        """
        Custom-sort calls by the following rules:

        - Calls are weighted by current age. The older, the higher the priority.
        - Calls in the current pos are optionally given an advantage.
        - Calls with duplicates are given advantage based on factor.

        :param left: Phase comparator on the left
        :param right: Phase comparator on the right
        :return: 0 for equality, < 0 for left, > 0 for right.
        """
        weight = 0
        active_barrier_weight = self._call_weights.get('active-pos')
        duplicate_factor = self._call_weights.get('duplicate-factor')
        
        # prioritize by literal sequence ID
        weight -= left.target.id
        weight += right.target.id
        
        # prioritize calls by age
        weight -= round(left.age)
        weight += round(right.age)
        
        # prioritize by duplicate count * factor
        if duplicate_factor is not None:
            weight -= left.duplicates * duplicate_factor
            weight += right.duplicates * duplicate_factor
        
        # prioritize calls within the active pos, if set
        if active_barrier_weight is not None:
            lb = self.getBarrierByPhase(left.target)
            rb = self.getBarrierByPhase(right.target)
            if lb != rb:
                if lb == self._barrier.active:
                    weight -= active_barrier_weight
                elif rb == self._barrier.active:
                    weight += active_barrier_weight
        
        return weight
    
    def rankCalls(self, calls: List[Call]) -> List[Call]:
        calls.sort(key=cmp_to_key(self._sortCallsKeyFunc), reverse=True)
        
        ocs = len(calls)
        if ocs >= 1:
            logger.sorting(f'Call sorting 1st place {calls[0].getTag()}')
        if ocs >= 2:
            logger.sorting(f'Call sorting 2nd place {calls[0].getTag()}, '
                             f'{calls[1].getTag()}')
        
        return calls
    
    def getAssociatedCall(self, phase: Phase) -> Optional[Call]:
        for call in self._calls:
            if call.target == phase:
                return call
        return None
    
    def placeCall(self,
                  target: Phase,
                  ped_service=False,
                  input_slot=None,
                  system=False) -> bool:
        """
        Create a new call for traffic service.

        :param target: the desired Phase to service
        :param ped_service: activate ped signal with vehicle
        :param input_slot: associate call with input slot number
        :param system: mark call as placed by system
        :returns: False when ignored (due to phase being active)
        """
        input_text = ''
        
        if ped_service:
            input_text = f' (ped service)'
        
        if input_slot is not None:
            input_text = f' (input #{input_slot})'
        
        if system:
            if target in self.getPhasesWithCalls():
                return False
            input_text += ' (system)'
        
        if not target.active:
            for call in self._calls:
                if call.target == target:
                    if system:
                        return False
                    call.duplicates += 1
                    self._call_counter += 1
                    logger.debug(f'Adding to existing call {call.getTag()} '
                                   f'({target.getTag()}), now {call.duplicates}'
                                   f'{input_text}')
                    return True
            else:
                call = Call(self._call_counter + 1, self.INCREMENT, target, ped_service=ped_service)
                
                self._calls.add(call)
                self._call_counter += 1
                logger.debug(f'Call {call.getTag()} '
                               f'{target.getTag()}{input_text}')
                return True
        return False
    
    def detection(self, phase: Phase, ped_service=False, input_slot=None, system=False):
        postfix = ''
        
        if input_slot is not None:
            postfix = f' (input #{input_slot})'
        
        if system:
            postfix += ' (system)'
        
        if phase.state in PHASE_GO_STATES:
            logger.debug(f'Detection on {phase.getTag()}{postfix}')
            if phase.extend_active:
                phase.reduce()
        else:
            self.placeCall(phase, ped_service=ped_service, input_slot=input_slot, system=system)
    
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
                self.placeAllCall(ped_service=True)
        
        previous_state = self._op_mode
        self._op_mode = new_state
        logger.info(f'Operation state is now {new_state.name} '
                      f'(was {previous_state.name})')
    
    def getPhasesWithCalls(self, barrier: Optional[int] = None) -> FrozenSet[Phase]:
        """
        Get phases that have at least one call.

        :param barrier: optionally omit phases not belonging to specific pos
        """
        phases = set()
        
        for call in self._calls:
            phase = call.target
            if barrier is not None:
                if phase.id not in self.getBarrierPhases(barrier):
                    continue
            
            phases.add(phase)
        
        return frozenset(phases)
    
    def allPhasesInactive(self) -> bool:
        for ph in self._phases:
            if ph.active:
                return False
        return True
    
    def serveCall(self, call: Call):
        self.servePhase(call.target, ped_service=call.ped_service)
        self._calls.remove(call)
    
    def servePhase(self, phase: Phase, ped_service: bool = False):
        logger.debug(f'Serving phase {phase.getTag()}')
        phase.activate(ped_service=ped_service)
    
    async def busHealthCheck(self):
        """Ensure bus thread is still running, if enabled"""
        if self.bus_enabled:
            if not self._bus.ready:
                logger.error('Bus not running')
                await self.shutdown()
    
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
                                self.placeCall(target, ped_service=True, input_slot=slot)
                        elif inp.action == InputAction.DETECT:
                            for target in inp.targets:
                                self.detection(target, ped_service=True, input_slot=slot)
                        else:
                            raise NotImplementedError()
                except IndexError:
                    logger.fine('Discarding signal for unused input slot '
                                  f'{slot}')
        
        self._last_input_bitfield = bf
    
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
    
    def canPhaseRunAsPartner(self, phase: Phase, active: List[Phase]) -> bool:
        for act in active:
            if phase == act:
                return False
            if self.checkPhaseConflict(phase, act):
                return False
            if act.state not in PHASE_PARTNER_START_STATES:
                return False
            # if len(self._cycle_window):
            #     if phase == self._cycle_window[0]:
            #         return False
        return True
    
    def getStaleStopPhase(self, phases: Iterable[Phase]) -> Phase:
        mapping = [(p, p.max_time) for p in phases if p.state == PhaseState.STOP]
        ranked = sorted(mapping, key=lambda m: m[1], reverse=True)
        return ranked[0][0]
    
    async def halfSecondTask(self):
        while True:
            self._flasher = not self._flasher
            await asyncio.sleep(500)
    
    async def secondTask(self):
        while True:
            if not self.time_freeze:
                if self._op_mode == OperationMode.NORMAL:
                    choice = self._random_actuation.poll()
                    if choice is not None:
                        self.detection(self.getPhaseById(choice), ped_service=True, system=True)
            
            # if self.monitor_enabled:
            #     self._monitor.clean()
            await asyncio.sleep(1000)

    async def tickTask(self):
        while True:
            if self.bus_enabled:
                self.handleBusFrame()
        
            if not self.time_freeze:
                if self._op_mode == OperationMode.NORMAL:
                    active = self.getActivePhases()
                    
                    for call in self._calls:
                        call.tick()
                elif self._op_mode == OperationMode.CET:
                    for ph in self._phases:
                        ph.tick(False, self._flasher)
                
                    if self._cet_counter > self.INCREMENT:
                        self._cet_counter -= self.INCREMENT
                    else:
                        self.setOperationState(OperationMode.NORMAL)
            
            # if self.bus_enabled:
            #     self.updateBusOutputs(self._load_switches)
        
            # if self.monitor_enabled:
            #     pmd = []
            #
            #     for ph in self._phases:
            #         call = self.getAssociatedCall(ph)
            #         score = call.duplicates + 1 if call is not None else 0
            #         pmd.append((0, score))
            #
            #     self._monitor.broadcastControlUpdate(self._phases, pmd, self._load_switches)
        
            field_text = ''
            for ls in self._load_switches:
                ft = utils.formatFields(ls.a, ls.b, ls.c)
                field_text += f'{ls.id:02d}{ft} '
            logger.field(field_text)
            
            await asyncio.sleep(self.INCREMENT)

    async def transfer(self):
        """Set the controllers flash transfer relays flag"""
        logger.info('Transferred')
        self._transfer = True

    async def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        logger.info('Untransfered')
        self._transfer = False

    async def shutdown(self):
        """Run termination tasks to stop control loop"""
        logger.info('beginning shutdown sequence...')
        
        asyncio.get_event_loop().close()
        
        logger.info('shutdown complete')
    
    async def runAsync(self):
        logger.info(f'controller is named "{self._name}"')
    
        # noinspection PyUnreachableCode
        if __debug__:
            logger.warning('controller in DEBUG ENVIRONMENT!')

        # if self.monitor_enabled:
        #     self._monitor.start()
        #
        # if self.bus_enabled:
        #     self._bus.start()
        #
        #     while not self._bus.ready:
        #         logger.info(f'waiting on bus...')
        #
        #     logger.info(f'bus ready')
        #
        # self.setOperationState(self._op_mode)
        # await self.transfer()
        
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.tickTask(), name='tick')
            tg.create_task(self.halfSecondTask(), name='half_second')
            tg.create_task(self.secondTask(), name='second')
