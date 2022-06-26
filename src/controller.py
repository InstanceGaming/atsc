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
import finelog  # will break if omitted! must be imported in its entirety.
import time
import random
import logging
import network
import serialbus
from core import *
from utils import textToEnum, getIPAddress
from frames import FrameType, DeviceAddress, OutputStateFrame
from timing import SecondTimer
from typing import Set, Iterable, FrozenSet
from bitarray import bitarray
from functools import cmp_to_key, lru_cache
from itertools import cycle
from threading import Timer
from ringbarrier import Ring, Barrier
from dateutil.parser import parse as _dt_parser


def parse_datetime_text(text: str, tz):
    rv = _dt_parser(text, dayfirst=False, fuzzy=True)
    return rv.replace(tzinfo=tz)


class RandomCallsManager:
    LOG = logging.getLogger('atsc.demo')

    @property
    def enabled(self):
        return self._enabled

    @property
    def min(self):
        return self._min

    @property
    def max(self):
        return self._max

    def __init__(self,
                 configuration_node: dict,
                 phase_id_pool: List[int]):
        self._enabled = configuration_node['enabled']
        self._min = configuration_node['min']  # seconds
        self._max = configuration_node['max']  # seconds
        self._timer = SecondTimer(configuration_node['delay'])
        self._pool = phase_id_pool
        sorted(self._pool)

        seed = configuration_node.get('seed')
        if seed is not None and seed > 0:
            # global pseudo-random generator seed
            random.seed(seed)

    def getPhaseIndex(self) -> Optional[int]:
        choice = None

        if self._enabled:
            if self._timer.poll():
                choice = random.choice(self._pool)
                delay = random.randrange(self._min,
                                         self._max)
                self.LOG.info(f'Random calls: picking {choice}, next in '
                              f'{delay}')
                self._timer.trigger = delay
                self._timer.reset()

        return choice


class TimeFreezeReason(IntEnum):
    SYSTEM = 0
    INPUT = 1


class PhaseStatus(IntEnum):
    INACTIVE = 0
    NEXT = 1
    LEADER = 2
    SECONDARY = 3


class Controller:
    PHASE_COUNT = 8
    LS_COUNT = 12
    INCREMENT = 0.1
    LOG = logging.getLogger('atsc.controller')

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
    def name(self):
        """Name of the controller"""
        return self._name

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
    def active_barrier(self):
        """The current barrier being served"""
        return self._active_barrier

    @property
    def inputs_count(self):
        """Number of input objects"""
        return len(self._inputs.keys())

    def __init__(self, config: dict, tz):
        # controller name (arbitrary)
        self._name = config['device']['name']

        # should place calls on all phases when started?
        self._recall_all = config['init']['recall-all']

        # controller timezone name
        self._tz = tz

        # 1Hz square wave reference clock
        self._flasher = True

        # loop enable flag
        self._running = False

        # local flash transfer relay status
        self._transfer = False

        # operation functionality of the controller
        self._op_mode: OperationMode = textToEnum(OperationMode,
                                                  config['init']['mode'])

        # there are two trigger sources for time freeze: system, input
        # see self.time_freeze for a scalar state
        self._time_freeze_reasons: Set[TimeFreezeReason] = set()

        self._load_switches: List[LoadSwitch] = [
            LoadSwitch(1),
            LoadSwitch(2),
            LoadSwitch(3),
            LoadSwitch(4),
            LoadSwitch(5),
            LoadSwitch(6),
            LoadSwitch(7),
            LoadSwitch(8),
            LoadSwitch(9),
            LoadSwitch(10),
            LoadSwitch(11),
            LoadSwitch(12),
        ]

        default_timing = self.getDefaultTiming(config['default-timing'])
        self._phases: List[Phase] = self.getPhases(config['phases'],
                                                   default_timing)

        self._rings: List[Ring] = self.getRings(config['rings'])
        self._barriers: List[Barrier] = self.getBarriers(config['barriers'])

        # cycle instance of barriers
        self._barrier_pool: cycle = cycle(self._barriers)

        # phases ran for current barrier
        self._barrier_phase_count: int = 0

        # barrier served no phases before crossing
        self._barrier_skip_counter: int = 0

        # current barrier
        self._active_barrier: Optional[Barrier] = None

        # total cycle counter
        self._cycle_count = 1

        # cycle tracking window
        self._cycle_window: List[Phase] = []

        # 500ms timer counter (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self._half_counter: int = 0

        # control entrance transition timer
        self._cet_time: int = config['init']['cet-delay']
        self._cet_timer: Timer = Timer(self._cet_time,
                                       self.endControlEntranceTransition)

        # actuation
        self._call_counter: int = 0
        self._calls: Set[Call] = set()
        self._max_call_age = config['calls']['max-age']
        self._call_weights = config['calls']['weights']

        # inputs data structure instances
        self._inputs: Dict[int, Input] = self.getInputs(config.get('inputs'))
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self._last_input_bitfield: Optional[bitarray] = bitarray()

        # communications
        self._bus: Optional[serialbus.Bus] = self.getBus(
            config['bus']
        )
        self._monitor: Optional[network.Monitor] = self.getNetworkMonitor(
            config['network']
        )
        if self._monitor is not None:
            self._monitor.setControlInfo(self.name,
                                         self._phases,
                                         self.getPhaseLoadSwitchIndexMapping())

        # for software demo and testing purposes
        self._random_calls: RandomCallsManager = RandomCallsManager(
            config['random-actuation'],
            [ph.id for ph in self._phases]
        )

    def getDefaultTiming(self, configuration_node: Dict[str, float]) -> \
            Dict[PhaseState, float]:
        timing = {}
        for name, value in configuration_node.items():
            ps = textToEnum(PhaseState, name)
            timing.update({ps: value})
        return timing

    def getPhases(self,
                  configuration_node: List[Dict],
                  default_timing: Dict[PhaseState, float]) -> List[Phase]:
        phases = []

        for i, node in enumerate(configuration_node, start=1):
            flash_mode_text = node['flash-mode']
            flash_mode = textToEnum(FlashMode, flash_mode_text)
            phase_timing: Dict[PhaseState, float] = default_timing.copy()
            timing_data = node.get('timing')

            if timing_data is not None:
                for name, value in timing_data.items():
                    ps = textToEnum(PhaseState, name)
                    phase_timing.update({ps: value})

            ls_node = node['load-switches']
            veh = ls_node['vehicle']
            ped_index = ls_node.get('ped')
            veh = self.getLoadSwitchById(veh)
            ped = None
            if ped_index is not None:
                ped = self.getLoadSwitchById(ped_index)
            phase = Phase(i,
                          self.INCREMENT,
                          phase_timing,
                          veh,
                          ped,
                          flash_mode)
            phases.append(phase)

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

    def buildMockPhase(self, timing, i: int, vi, pi=None) -> Phase:
        veh = self._load_switches[vi - 1]
        ped = None
        if pi is not None:
            ped = self._load_switches[pi - 1]
        return Phase(i,
                     self.INCREMENT,
                     timing,
                     veh,
                     ped,
                     FlashMode.RED)

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
                    action = textToEnum(InputAction, input_node['action'])
                active = textToEnum(InputActivation, input_node['active'])
                targets_node = input_node['targets']

                targets = []
                for target_index in targets_node:
                    target = self._phases[target_index - 1]
                    targets.append(target)

                inputs.update({slot: Input(active,
                                           action,
                                           targets)})

        return inputs

    def getBus(self, configuration_node: dict) -> Optional[serialbus.Bus]:
        """Create the serial bus manager thread, if enabled"""
        if configuration_node['enabled']:
            self.LOG.info('Serial bus subsystem ENABLED')
            port = configuration_node['port']
            baud = configuration_node['baud']
            return serialbus.Bus(port,
                                 baud)
        else:
            self.LOG.info('Serial bus subsystem DISABLED')

        return None

    def getNetworkMonitor(self, configuration_node: dict) -> Optional[
        network.Monitor
    ]:
        """Create the network monitor thread, if enabled"""
        if configuration_node['enabled']:
            self.LOG.info('Networking enabled')

            if_name = configuration_node['interface'].lower().strip()

            monitor_node = configuration_node['monitor']
            if monitor_node['enabled']:
                host = 'localhost'

                if if_name != 'localhost' and if_name != 'any':
                    try:
                        auto_ip = getIPAddress(if_name)
                        host = auto_ip
                    except Exception as e:
                        self.LOG.warning(f'Failed to get address of network '
                                         f'interface: {str(e)}')
                elif if_name == 'any':
                    host = '0.0.0.0'

                self.LOG.info(f'Using IP address {host}')

                monitor_port = monitor_node['port']
                return network.Monitor(self, host, monitor_port)
            else:
                self.LOG.info('Network monitor disabled')

        self.LOG.info('Networking disabled')
        return None

    def getBarrierPhases(self, barrier: Barrier) -> List[Phase]:
        """Map the phase indices defined in a `Barrier` to `Phase` instances"""
        return [self.getPhaseById(pi) for pi in barrier.phases]

    def transfer(self):
        """Set the controllers flash transfer relays flag"""
        self.LOG.info('Transferred')
        self._transfer = True

    def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        self.LOG.info('Untransfered')
        self._transfer = False

    @lru_cache(maxsize=16)
    def checkPhaseConflict(self,
                           a: Phase,
                           b: Phase,
                           check_ring=True,
                           check_barrier=True) -> bool:
        """
        Check if two phases conflict based on Ring, Barrier and defined friend
        channels.

        :param a: Phase to compare against
        :param b: Other Phase to compare
        :param check_ring: If True, conflict Phase in same Ring
        :param check_barrier: If True, conflict Phase in different Barrier
        :return: True if conflict
        """
        if a == b:
            raise RuntimeError('Conflict check on the same phase object')

        # verify Phase b is not in the same ring
        if check_ring:
            if b.id in self.getRingByPhase(a).phases:
                return True

        # verify Phase b is in Phase a's barrier group
        if check_barrier:
            if b.id not in self.getBarrierByPhase(a).phases:
                return True

        # future: consider FYA-enabled phases conflicts for a non-FYA phase

        return False

    def getAvailablePhases(
            self,
            phases: Iterable,
            active: List[Phase]) \
            -> FrozenSet[Phase]:
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

            if any([self.checkPhaseConflict(phase,
                                            act,
                                            check_barrier=False)
                    for act in active]):
                continue

            if phase.state == PhaseState.MIN_STOP:
                continue

            results.add(phase)

        return frozenset(results)

    @lru_cache(maxsize=8)
    def getRingByPhase(self, phase: Phase) -> Ring:
        """Find a `Phase` instance by one of it's associated
                `Channel` instances"""
        for ring in self._rings:
            if phase.id in ring.phases:
                return ring

        raise RuntimeError(f'Failed to get ring')

    @lru_cache(maxsize=16)
    def getDiagonalPartner(self,
                           phase: Phase) -> Phase:
        """
        Get Phase that is positioned diagonal to Phase a within barrier within
        a standard ring-and-barrier model.

        :param phase: primary Phase
        :return: currently guaranteed to return a Phase. this will not be the
        case when partial barrier configurations are implemented.
        """
        barrier = self.getBarrierByPhase(phase)
        group = self.getBarrierPhases(barrier)
        phase_index = barrier.phases.index(phase.id)

        if phase_index == 0:
            return group[-1]
        elif phase_index == 1:
            return group[2]
        elif phase_index == 2:
            return group[1]
        elif phase_index == 3:
            return group[0]

        raise RuntimeError('Failed to find diagonal partner')

    @lru_cache(maxsize=16)
    def getColumnPartner(self,
                         phase: Phase) -> Phase:
        """
        Get Phase that is positioned in the same column to Phase a within
        a standard ring-and-barrier model.

        :param phase: primary Phase
        :return: currently guaranteed to return a Phase. this will not be the
        case when partial barrier configurations are implemented.
        """
        barrier = self.getBarrierByPhase(phase)
        group = self.getBarrierPhases(barrier)
        phase_index = barrier.phases.index(phase.id)
        half = len(group) // 2

        if phase_index < half:
            return group[phase_index + 2]
        else:
            return group[phase_index - 2]

    def getPriorityPhase(self, phases: List[Phase]) -> Optional[Phase]:
        """
        Get the ranks of the given iterable of `Phase` instances by
        associated `Call` priority, returning the top choice.

        :param phases: a list of Phase instances
        :return: top choice Phase or None if list was empty
        """
        if len(phases) > 0:
            phase_calls = self.getRankedCalls(phases)
            return phase_calls[0].target
        return None

    @lru_cache(maxsize=2)
    def getBarrierByPhase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        assert isinstance(phase, Phase)
        for b in self._barriers:
            if phase.id in b.phases:
                return b

        raise RuntimeError(f'Failed to get barrier by {phase.getTag()}')

    def recallAll(self, ped_service=False):
        """Place calls on all phases"""
        for phase in self._phases:
            self.recall(phase, ped_service=ped_service)

    def getPriorityBarrier(self) -> Optional[Barrier]:
        """
        Get the barrier with the most priority phase, if there is one.
        """
        priority_phase = self.getPriorityPhase(self._phases)
        if priority_phase is not None:
            return self.getBarrierByPhase(priority_phase)
        return None

    def changeBarrier(self, barrier: Barrier):
        """Change to the next `Barrier` in the barrier cycle instance"""
        self._barrier_phase_count = 0
        self._active_barrier = barrier
        self.LOG.debug(f'Crossed to {barrier.getTag()}')

    def endCycle(self, early=True) -> None:
        """End phasing for this control cycle iteration"""
        self._cycle_count += 1
        self._cycle_window = []
        self.LOG.debug(f'Ended cycle {self._cycle_count}'
                       f'{" (early)" if early else ""}')

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
        active = []
        for ph in self._phases:
            if ph.active:
                active.append(ph)
        return active

    def _sortCallsKeyFunc(self, left: Call, right: Call) -> int:
        """
        Custom-sort calls by the following rules:

        - Calls are weighted by current age. The older, the higher the priority.
        - Calls in the current barrier are optionally given an advantage.
        - System calls are optionally given an advantage.
        - System calls are sorted least-to-greatest against other system calls.

        :param left: Phase comparator on the left
        :param right: Phase comparator on the right
        :return: 0 for equality, < 0 for left, > 0 for right.
        """
        weight = 0
        active_barrier_weight = self._call_weights.get('active-barrier')
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

        # prioritize calls within the active barrier, if set
        if active_barrier_weight is not None:
            lb = self.getBarrierByPhase(left.target)
            rb = self.getBarrierByPhase(right.target)
            if self._active_barrier is not None and lb != rb:
                if lb == self._active_barrier:
                    weight -= active_barrier_weight
                elif rb == self._active_barrier:
                    weight += active_barrier_weight

        self.LOG.sorting(f'Sorting result between {left.getTag()} (target='
                         f'{left.target.getTag()}, age={left.age:0.1f}, '
                         f'duplicates={left.duplicates}) '
                         f'and {right.getTag()} '
                         f'(target={right.target.getTag()}, '
                         f'age={right.age:0.1f}, '
                         f'duplicates={right.duplicates}) = {weight:0.1f}')
        return weight

    def getRankedCalls(self, phases=None) -> List[Call]:
        unordered_calls = list(self._calls)

        if phases is not None:
            to_remove = []
            for uc in unordered_calls:
                if uc.target not in phases:
                    to_remove.append(uc)
            for tr in to_remove:
                unordered_calls.remove(tr)

        ordered_calls = sorted(unordered_calls,
                               key=cmp_to_key(self._sortCallsKeyFunc))

        return ordered_calls

    def handleCalls(self,
                    existing: List[Phase],
                    available: FrozenSet[Phase],
                    lone_phase: Optional[Phase]) -> Optional[Phase]:
        """Attempt to serve calls and remove expired ones"""
        choice: Optional[Call] = None

        for call in self._calls:
            call.tick()

            if self.serveCall(call,
                              existing,
                              available,
                              lone_phase):
                choice = call
                self._calls.remove(call)
                break

            if call.age > self._max_call_age:
                self.LOG.debug(f'Call {call.getTag()} has expired')
                self._calls.remove(call)

        return choice

    def serveCall(self,
                  call: Call,
                  existing: List[Phase],
                  available: Optional[FrozenSet[Phase]],
                  lone: Optional[Phase]) -> bool:
        """Attempt to start the given call's target `Phase`, if possible"""
        phase = call.target

        if phase in existing:
            return False

        if available is not None and phase in available or available is None:
            if lone is None:
                if not self.allPhasesInactive():
                    return False

                if self._active_barrier is None:
                    self.changeBarrier(self.getBarrierByPhase(phase))
            else:
                if phase == lone:
                    return False

                self.LOG.verbose(f'{phase.getTag()} was selected as partner to '
                                 f'{lone.getTag()}')

            self.LOG.debug(f'Recall {call.getTag()}')
            self._barrier_phase_count += 1
            self._barrier_skip_counter = 0
            return True
        return False

    def getAssociatedCall(self, phase: Phase) -> Optional[Call]:
        for call in self._calls:
            if call.target == phase:
                return call
        return None

    def removeAssociatedCall(self, phase: Phase) -> bool:
        to_remove = None
        for call in self._calls:
            if call.target == phase:
                to_remove = call
        if to_remove is not None:
            self._calls.remove(to_remove)
            return True
        return False

    def recall(self,
               target: Phase,
               ped_service=False,
               input_slot=None):
        """
        Create a new call for traffic service.

        :param target: the desired Phase to service
        :param ped_service: activate ped signal with vehicle
        :param input_slot: associate call with input slot number
        """
        input_text = ''

        if ped_service:
            input_text = f' (ped service)'

        if input_slot is not None:
            input_text = f' (input #{input_slot})'

        for call in self._calls:
            if call.target == target:
                call.duplicates += 1
                self.LOG.debug(f'Adding to duplicate score for '
                               f'{call.getTag()} ({target.getTag()}), '
                               f'now {call.duplicates}{input_text}')
                self._call_counter += 1
                break
        else:
            call = Call(self._call_counter + 1,
                        self.INCREMENT,
                        target,
                        ped_service=ped_service)

            self.LOG.debug(f'Call {call.getTag()} '
                           f'{target.getTag()}{input_text}')
            self._calls.add(call)
            self._call_counter += 1

    def detection(self, phase: Phase, ped_service=False, input_slot=None):
        input_text = ''

        if input_slot is not None:
            input_text = f' (input #{input_slot})'

        if phase.extend_active:
            self.LOG.debug(f'Detection on {phase.getTag()}{input_text}')
            phase.reduce()
        elif phase.state not in PHASE_GO_STATES:
            self.recall(phase, ped_service=ped_service, input_slot=input_slot)

    def setOperationState(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            for ph in self._phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.update(force_state=PhaseState.CAUTION)

            self._cet_timer = Timer(self._cet_time,
                                    self.endControlEntranceTransition)
            self._cet_timer.start()
        elif new_state == OperationMode.NORMAL:
            if self._recall_all:
                self.recallAll()

        previous_state = self._op_mode
        self._op_mode = new_state
        self.LOG.info(f'Operation state is now {new_state.name} '
                      f'(was {previous_state.name})')

    def getPhasesWithCalls(self, barrier: Optional[Barrier] = None) -> \
            FrozenSet[Phase]:
        """
        Get phases that have at least one call.

        :param barrier: optionally omit phases not belonging to specific barrier
        """
        phases = set()

        for call in self._calls:
            phase = call.target
            if barrier is not None:
                if phase.id not in barrier.phases:
                    continue

            phases.add(phase)

        return frozenset(phases)

    def allPhasesInactive(self) -> bool:
        for ph in self._phases:
            if ph.active:
                return False
        return True

    def waitingOnRedClearance(self):
        """Are any phases timing mandatory red clearance"""
        for ph in self._phases:
            if ph.state == PhaseState.RCLR:
                return True
        return False

    def getDemand(self, active: List[Phase]) -> int:
        demand = 0

        for call in self._calls:
            phase = call.target
            for ap in active:
                if phase != ap:
                    if self.checkPhaseConflict(phase,
                                               ap,
                                               check_barrier=False):
                        demand += 1

        return demand

    def handleRingAndBarrier(self,
                             available: FrozenSet[Phase],
                             with_calls: FrozenSet[Phase],
                             barrier_phases: List[Phase]) -> bool:
        # no available phases for barrier
        c1 = len(available) == 0

        # there are no calls for available phases
        c2 = len(self.getRankedCalls(phases=available)) == 0

        if c1 or c2:
            if self.allPhasesInactive():
                if len(self._cycle_window) == len(self._phases):
                    self.endCycle()

                next_barrier = next(self._barrier_pool)

                if self._barrier_phase_count < 1:
                    self._barrier_skip_counter += 1
                    self.LOG.verbose(f'Barrier skip counter is now '
                                     f'{self._barrier_skip_counter}')
                else:
                    if not self.waitingOnRedClearance():
                        # if only available phase has no calls, prematurely
                        # end cycle as it will cause deadlock otherwise
                        no_calls = set(barrier_phases) - with_calls

                        if len(available - no_calls) == 0:
                            self.LOG.debug(
                                f'{self._active_barrier.getTag()} had calls '
                                f'on only unavailable phases'
                            )
                            next_barrier = self.getPriorityBarrier()
                            self.endCycle(early=True)

                if self._barrier_skip_counter >= len(self._barriers) * 2:
                    self.LOG.debug(f'Barrier thrashing detected')
                    self._active_barrier = None
                    return True
                else:
                    self.changeBarrier(next_barrier)
        return False

    def handlePhases(self,
                     active: List[Phase],
                     choice: Optional[Call],
                     barrier_pool: Optional[List[Phase]] = None):
        """Handle phase ticking and completed phases"""
        for ph in self._phases:
            if choice is not None:
                if ph == choice.target:
                    if ph.active:
                        raise RuntimeError('Phase already active')

                    if barrier_pool is not None:
                        if ph not in barrier_pool:
                            raise RuntimeError(
                                f'Attempted to start phase out-of-barrier')

                    ph.activate(ped_inhibit=not choice.ped_service)
            demand = self.getDemand(active)
            if ph.tick(demand, self.flasher):
                if ph.state == PhaseState.STOP:
                    self._cycle_window.insert(0, ph)

    def busHealthCheck(self):
        """Ensure bus thread is still running, if enabled"""
        if self.bus_enabled:
            if not self._bus.running:
                self.LOG.error('Bus not running')
                self.shutdown()

    def handleInputs(self, bf: bitarray):
        """Check on the contents of bus data container for changes"""

        if self._last_input_bitfield is None or \
                bf != self._last_input_bitfield:
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
                                self.recall(target,
                                            ped_service=True,
                                            input_slot=slot)
                        elif inp.action == InputAction.DETECT:
                            for target in inp.targets:
                                self.detection(target,
                                               ped_service=True,
                                               input_slot=slot)
                        else:
                            raise NotImplementedError()
                except IndexError:
                    self.LOG.fine('Discarding signal for unused input slot '
                                  f'{slot}')

        self._last_input_bitfield = bf

    def endControlEntranceTransition(self):
        self.setOperationState(OperationMode.NORMAL)
        self._cet_timer.cancel()

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

    def tick(self):
        """Polled once every 100ms"""

        if self.bus_enabled:
            self.handleBusFrame()

        if not self.time_freeze:
            if self._op_mode == OperationMode.NORMAL:
                active = self.getActivePhases()
                thrashing = False

                barrier_pool = None
                if self._active_barrier is not None:
                    barrier_pool = self.getBarrierPhases(self._active_barrier)
                    with_calls = self.getPhasesWithCalls(self._active_barrier)
                    available = self.getAvailablePhases(
                        barrier_pool,
                        active
                    )
                    thrashing = self.handleRingAndBarrier(available,
                                                          with_calls,
                                                          barrier_pool)
                else:
                    available = self.getAvailablePhases(self._phases, active)

                lone_phase = active[0] if len(active) > 0 else None
                if thrashing:
                    choice = self.getRankedCalls()[0]
                    self.serveCall(choice, active, None, lone_phase)
                else:
                    choice = self.handleCalls(active,
                                              available,
                                              lone_phase)
                self.handlePhases(active, choice, barrier_pool)
            elif self._op_mode == OperationMode.CET:
                for ph in self._phases:
                    ph.tick(0, self._flasher)

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
                call = self.getAssociatedCall(ph)
                score = call.duplicates + 1 if call is not None else 0
                pmd.append((0, score))

            self._monitor.broadcastControlUpdate(self._phases,
                                                 pmd,
                                                 self._load_switches)

    def halfSecond(self):
        """Polled once every 500ms"""
        self._flasher = not self._flasher

        if not self.time_freeze:
            if self._flasher:
                self.second()

        self.busHealthCheck()

    def second(self):
        """Polled once every 1000ms"""
        if not self.time_freeze:
            if self._op_mode == OperationMode.NORMAL:
                if self._random_calls.enabled:
                    random_phase_index = self._random_calls.getPhaseIndex()

                    if random_phase_index:
                        self.detection(self.getPhaseById(random_phase_index),
                                       ped_service=True)

        if self.monitor_enabled:
            self._monitor.clean()

    def run(self):
        """Begin control loop"""
        self._running = True

        self.LOG.info(f'Controller is named "{self._name}"')

        # noinspection PyUnreachableCode
        if __debug__:
            self.LOG.warning('Controller in DEBUG ENVIRONMENT!')

        self.LOG.debug('CET delay set to 3s')

        if self._running:
            if self.monitor_enabled:
                self._monitor.start()

            if self.bus_enabled:
                self._bus.start()

                while not self._bus.running:
                    self.LOG.debug(f'Waiting on bus...')

                self.LOG.debug(f'Bus ready')

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
            self.LOG.info('Stopping bus')
            self._bus.shutdown()
            self._bus.join(timeout=1)

        if self.monitor_enabled:
            self.LOG.info('Stopping network monitor')
            self._monitor.shutdown()
            self._monitor.join(timeout=1)

        self.LOG.info('Shutdown complete')
