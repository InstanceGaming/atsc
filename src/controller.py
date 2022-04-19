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

import sys
import random
import logging
import network
import serialbus
from core import *
from utils import textToEnum, getIPAddress
from timing import MinuteTimer, SecondTimer, MillisecondTimer, seconds
from typing import Set, Dict, List, Tuple, Iterable, Optional
from bitarray import bitarray
from functools import cmp_to_key
from itertools import cycle
from scheduling import Schedule, Timespan, PhaseTimesheet, ScheduleManager
from collections import Counter
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
                 phase_id_pool: List[int],
                 initial_delay: int):
        self._enabled = configuration_node['enabled']
        self._min = configuration_node['min']  # seconds
        self._max = configuration_node['max']  # seconds
        self._timer = SecondTimer(initial_delay)
        self._pool = phase_id_pool
        sorted(self._pool)

        seed = configuration_node['seed']
        if seed != 0:
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


class Controller:
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
    def gib(self):
        """A copy of the map of global timing bounds
                per interval type (min, max)"""
        return self._gib.copy()

    @property
    def gdi(self):
        """A copy of the list of interval types that are currently disabled"""
        return self._gdi.copy()

    @property
    def idling(self):
        """Is the controller not currently serving any calls"""
        return not self._idle_timer.pause

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
    def first_cycle(self):
        """Has one full iteration of all phases occurred"""
        return self._first_cycle

    @property
    def first_phase(self):
        """Has the controller ever started a phase yet"""
        return self._first_phase

    @property
    def stats(self):
        """Create a copy of the internal statistics counter instance"""
        return self._stats.copy()

    @property
    def calls(self):
        """A copy of the current controller calls stack"""
        return self._calls.copy()

    @property
    def phase_history(self):
        """A copy of the controller's phase history for this cycle"""
        return self._phase_history.copy()

    @property
    def phase_pair(self):
        """A copy of the controller's currently running phase(s)"""
        return self._phase_pair.copy()

    @property
    def active_barrier(self):
        """The current barrier being served"""
        return self._active_barrier

    @property
    def inputs_count(self):
        """Number of input objects"""
        return len(self._inputs.keys())

    @property
    def preempting(self):
        return len(self._preemption_pair) > 0

    def __init__(self, config: dict, tz):
        # controller name (arbitrary)
        self._name = config['device']['name']

        # controller timezone name
        self._tz = tz

        # 1Hz square wave reference clock
        self._flasher = True
        # loop enable flag
        self._running = False

        # local flash transfer relay status
        self._transfer = False

        # has one complete loop of phases been served yet?
        self._first_cycle: bool = True

        # has a phase ever been run yet?
        self._first_phase: bool = False

        # additional delay before continuing to normal op mode
        self._init_red_clearance: int = config['init']['red-clearance']

        # overall statistics about the controller state
        self._stats: Counter = self.getDefaultStatsCounter()

        # operation functionality of the controller
        self._op_mode: OperationMode = textToEnum(OperationMode,
                                                  config['init']['mode'])

        # there are two trigger sources for time freeze: system, input
        # see self.time_freeze for a scalar state
        self._time_freeze_reasons: Set[TimeFreezeReason] = set()

        # globally disabled intervals
        # todo: this may need to be a mapping of intervals to reasons
        self._gdi = []

        # global interval bounds
        self._gib: Dict[IntervalType, Tuple[int, int]] = \
            self.getGlobalIntervalBounds(
                config['global-interval-bounds']
            )

        # signal output channels (load switches)
        self._channels: List[Channel] = self.getChannels(
            config['channels']
        )

        # system scheduling
        schedules = self.getSchedules(
            config['schedules']
        )
        self._sch_manager = ScheduleManager(schedules,
                                            tz)
        self._sch_timer = MinuteTimer(config['scheduler']['minimum-runtime'])
        self._sch_queue: Optional[Tuple[Schedule, Optional[Timespan]]] = None

        # control cycling
        # currently active phases (up to two)
        self._phase_pair: List[Phase] = []
        # previously ran phases for this cycle
        self._phase_history: List[Phase] = []
        # phases conflicting for preemption service
        self._expedited_phases: Set[Phase] = set()
        # last phase from last cycle
        self._last_phase: Optional[Phase] = None
        # cycle instance of barriers
        self._barrier_pool: cycle = self.getBarrierCycler()
        # current barrier
        self._active_barrier: Optional[Barrier] = None

        # 100ms timer
        self._tick_timer: MillisecondTimer = MillisecondTimer(100)
        # 500ms timer counter (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self._half_counter: int = 0
        # no call servicing timer
        self._idle_timer: SecondTimer = SecondTimer(0, pause=True)
        # control entrance transition timer
        self._cet_timer: SecondTimer = SecondTimer(self.getCETSeconds())

        # actuation
        self._calls: List[Call] = []
        self._max_call_age = config['calls']['max-age']
        self._call_weights = config['calls']['weights']

        # inputs data structure instances
        self._inputs: Dict[int, Input] = self.getInputs(config['inputs'])
        # the last input bitfield received from the serial bus used in
        # comparison to the latest for change detection
        self._last_input_field: Optional[bitarray] = None

        # preemption target phases, up to two
        self._preemption_pair: List[Phase] = []

        # communications
        self._bus: Optional[serialbus.Bus] = self.getBus(
            config['bus']
        )
        self._monitor: Optional[network.Monitor] = self.getNetworkMonitor(
            config['network']
        )

        # for software demo and testing purposes
        self._random_calls: RandomCallsManager = RandomCallsManager(
            config['random-calls'],
            list(self.getIndexPhaseMap().keys()),
            5
        )

    def getDefaultStatsCounter(self):
        """Instantiate a new zeroed stats counter with key names populated"""
        return Counter({
            'cycles': 1,
            'skipped_cycles': 0,
            'calls': 0,
            'total_idle_seconds': 0
        })

    def getGlobalIntervalBounds(self,
                                configuration_node: dict) -> Dict[
        IntervalType,
        Tuple[int, int]
    ]:
        """
        Transform global interval bound values from the configuration node
        into a mapping.

        :param configuration_node: configuration data for GIB
        :return: a map of the format interval type: (min, max)
        """
        gib = {}

        if len(IntervalType) != len(configuration_node):
            raise RuntimeError('GIB key size mismatch')

        for interval_text, values in configuration_node.items():
            it = textToEnum(IntervalType, interval_text)
            it_name = it.name
            if len(values) != 2:
                raise RuntimeError(f'GIB {it_name} value not an '
                                   'array of size 2')

            if values[0] < 1:
                raise ValueError(f'GIB {it_name} minimum less than '
                                 'one')

            if values[0] > values[1] and it not in REST_INTERVALS:
                raise ValueError(f'GIB {it_name} minimum greater '
                                 f'than maximum (not a rest interval)')
            gib.update({it: values})

        return gib

    def getChannels(self, configuration_node: list) -> List[Channel]:
        """
        Transform channel settings from the configuration node into
        `Channel` instance.

        :param configuration_node: configuration data for channels
        :return: a list of Channel instances
        """

        channels = []

        for i, c in enumerate(configuration_node, start=1):
            mode = textToEnum(ChannelMode, c['mode'], to_length=3)
            flash_mode = textToEnum(FlashMode, c['flash-mode'])

            channel = Channel(i,
                              mode,
                              flash_mode,
                              getDefaultChannelState(flash_mode))

            channels.append(channel)

        return channels

    def getIndexChannelMap(self) -> Dict[int, Channel]:
        """Get a mapping of `Channel` ID indices in the form index: `Channel`"""
        mapping = {}

        for ch in self._channels:
            mapping.update({ch.id: ch})

        return mapping

    def getSchedules(self,
                     configuration_node: dict) -> FrozenSet[Schedule]:
        """
        Transform schedule settings, channel mappings and ring and barrier
        definitions from configuration node into a set of `Schedule` instances.

        :param configuration_node: configuration data for schedules
        :return: an immutable set of Schedule instances
        """
        schedules = set()

        for node in configuration_node:
            enabled = node['enabled']
            name = node['name']
            mode = textToEnum(OperationMode, node['mode'])
            free = node['free']

            blocks = set()
            blocks_node = node['blocks']

            for ki, bd in enumerate(blocks_node):
                start_text = bd['start']

                try:
                    start = parse_datetime_text(start_text, self._tz)
                except ValueError:
                    raise ValueError(
                        f'Failed to parse start time "{start_text}" '
                        f'(schedule "{name}", block "{ki}")')

                end_text = bd['end']

                try:
                    end = parse_datetime_text(end_text, self._tz)
                except ValueError:
                    raise ValueError(
                        f'Failed to parse start time "{start_text}" '
                        f'(schedule "{name}", block "{ki}")')

                blocks.add(Timespan(start, end))

            rings: List[Ring] = []

            for ri, ring_node in enumerate(node['rings'], start=1):
                ring_indices = sorted(list(set(ring_node['phases'])))
                rings.append(Ring(ri, ring_indices))

            barriers: List[Barrier] = []

            for bi, barrier_node in enumerate(node['barriers'], start=1):
                barrier_indices = sorted(list(set(barrier_node['phases'])))
                preemption_node = barrier_node['preemption']
                preemption_duration = preemption_node['duration']
                singles = barrier_node['singles']
                red_clearance_ms = barrier_node['red-clearance']

                barriers.append(Barrier(bi,
                                        barrier_indices,
                                        preemption_duration,
                                        singles,
                                        red_clearance_ms))

            phases = set()
            timesheets = {}
            channel_index_map = self.getIndexChannelMap()

            for pi, phase_node in enumerate(node['phases'], start=1):
                channels = set()
                channel_indices = phase_node['channels']

                if any(channel_indices) not in range(len(self._channels)):
                    raise ValueError('One or more channel indices defined for '
                                     f'PH{pi:02d} is invalid')

                for ci in channel_indices:
                    channels.add(channel_index_map[ci])

                red_clearance_ms = None
                for b in barriers:
                    if pi in b.phases:
                        red_clearance_ms = b.red_clearance

                phase = Phase(pi,
                              frozenset(channels),
                              MillisecondTimer(red_clearance_ms, pause=True))

                timesheet_node = phase_node['timesheet']
                unset_intervals = list(IntervalType)

                minimums = getDefaultTimeIntervalMap()
                targets = getDefaultTimeIntervalMap()
                maximums = getDefaultTimeIntervalMap()

                for k, v in timesheet_node.items():
                    it = textToEnum(IntervalType, k)
                    global_min = self._gib[it][0]
                    global_max = self._gib[it][1]

                    min_value = global_min
                    target_value = 0
                    max_value = global_max

                    if isinstance(v, int):
                        target_value = v
                        self.LOG.verbose(f'PH{pi:02d} {it.name} relying on '
                                         f'global min and max values')
                    elif isinstance(v, list):
                        if len(v) == 1:
                            raise TypeError(f'PH{pi:02d} {it.name} invalid '
                                            f'type; can only be a integer or '
                                            f'list of size 3')
                        elif len(v) == 3:
                            min_value = v[0]
                            target_value = v[1]
                            max_value = v[2]

                            if global_min > min_value != 0:
                                raise ValueError(f'PH{pi:02d} {it.name} time '
                                                 f'minimum less than global')

                            if global_max < max_value != 0:
                                raise ValueError(f'PH{pi:02d} {it.name} time '
                                                 f'maximum greater than global')

                    if target_value != 0:
                        if target_value < min_value != 0:
                            raise ValueError(f'PH{pi:02d} {it.name} time '
                                             f'target less than minimum')
                        if target_value > max_value != 0:
                            raise ValueError(f'PH{pi:02d} {it.name} time '
                                             f'target greater than maximum')

                    unset_intervals.remove(it)
                    minimums[it] = min_value
                    targets[it] = target_value
                    maximums[it] = max_value

                for uit in unset_intervals:
                    global_min = self._gib[uit][0]
                    global_max = self._gib[uit][1]
                    minimums[uit] = global_min

                    if uit in REST_INTERVALS:
                        targets[uit] = 0
                    else:
                        targets[uit] = global_min

                    maximums[uit] = global_max

                timesheets.update({phase: PhaseTimesheet(
                    minimums,
                    maximums,
                    targets
                )})

                phases.add(phase)

            schedule = Schedule(enabled,
                                name,
                                frozenset(blocks),
                                mode,
                                free,
                                frozenset(phases),
                                rings,
                                barriers,
                                timesheets)

            schedules.add(schedule)

        return frozenset(schedules)

    def getInputs(self, configuration_node: dict) -> Dict[int, Input]:
        """
        Transform input settings from configuration node into a list of `Input`
        instances.

        :param configuration_node: configuration data for inputs
        :return: a list of Input instances
        """
        inputs = {}
        phase_index_map = self.getIndexPhaseMap()

        reserved_slots = []
        for input_node in configuration_node:
            slot = input_node['slot']

            if slot in reserved_slots:
                raise RuntimeError('Input slot redefined')

            ignore = input_node['ignore']
            active = textToEnum(InputActivation, input_node['active'])
            action = textToEnum(InputAction, input_node['action'])
            targets_node = input_node['targets']

            if any(targets_node) not in phase_index_map.keys():
                raise ValueError('One or more phase indices defined for '
                                 f'input using slot {slot} is invalid')

            targets = []
            for target_index in targets_node:
                targets.append(phase_index_map[target_index])

            inputs.update({slot: Input(ignore,
                                       active,
                                       action,
                                       targets)})

        return inputs

    def getBus(self, configuration_node: dict) -> Optional[serialbus.Bus]:
        """Create the serial bus manager thread, if enabled"""
        if configuration_node['enabled']:
            self.LOG.info('Serial bus subsystem ENABLED')
            response_time = configuration_node['response-timeout']
            port = configuration_node['port']
            baud = configuration_node['baud']
            return serialbus.Bus(port,
                                 baud,
                                 frame_timeout=response_time,
                                 inputs_count=self.inputs_count)
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

    def getPhases(self) -> FrozenSet[Phase]:
        """Get a set of `Phase` instances of the current schedule"""
        return self._sch_manager.phases

    def getPhasesOrdered(self) -> List[Phase]:
        """Get an ordered list of `Phase` instances of the current schedule"""
        return sorted(list(self.getPhases()))

    def getRings(self) -> List[Ring]:
        """Get an ordered list of `Ring` instances of the current schedule"""
        return self._sch_manager.rings

    def getBarriers(self) -> List[Barrier]:
        """Get an ordered list of `Barrier` instances of the current schedule"""
        return self._sch_manager.barriers

    def getBarrierCycler(self) -> cycle:
        """Create a `Barrier` cycle instance"""
        return cycle(self.getBarriers())

    def getNextBarrier(self) -> Barrier:
        """Generate the next `Barrier` instance in the cycle"""
        return next(self._barrier_pool)

    def getIndexPhaseMap(self) -> Dict[int, Phase]:
        """Get a mapping of `Phase` ID indices in the form index: `Phase`"""
        mapping = {}

        for ph in self.getPhases():
            mapping.update({ph.id: ph})

        return mapping

    def getPhaseIndexMap(self) -> Dict[Phase, int]:
        """Get a mapping of `Phase` ID indices in the form `Phase`: index"""
        mapping = {}

        for ph in self.getPhases():
            mapping.update({ph: ph.id})

        return mapping

    def getBarrierPhases(self, barrier: Barrier) -> List[Phase]:
        """Map the phase indices defined in a `Barrier` to `Phase` instances"""
        phase_index_map = self.getIndexPhaseMap()
        return [phase_index_map[pi] for pi in barrier.phases]

    def transfer(self):
        """Set the controllers flash transfer relays flag"""
        self.LOG.info('Transferred')
        self._transfer = True

    def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        self.LOG.info('Untransfered')
        self._transfer = False

    def allReady(self) -> bool:
        """Is the current controller state valid to start new phases"""
        if len(self._phase_pair) > 0:
            return False

        for ph in self.getPhases():
            if not ph.is_ready or ph.red_clearance:
                return False

        return True

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
            a_ring = self.getRingByPhase(a)
            if b in self.getRingPhases(a_ring):
                return True

        # verify Phase b is in Phase a's barrier group
        if check_barrier:
            a_barrier = self.getBarrierByPhase(a)
            if b not in self.getBarrierPhases(a_barrier):
                return True

        return False

    def getAvailablePhases(self,
                           phases: Iterable) -> FrozenSet[Phase]:
        """
        Determine what phases from a given pool can run given
        the current controller state.

        :param phases: an iterable of Phases to scrutinize
        :return: an immutable set of available Phases
        """
        results: Set[Phase] = set()

        for phase in phases:
            if len(self._phase_pair) == 1:
                lone_phase = self._phase_pair[0]

                if phase == lone_phase:
                    continue
                elif self.checkPhaseConflict(phase, lone_phase):
                    continue

            if phase in self._phase_history:
                continue

            if phase.red_clearance:
                self.LOG.fine(f'{phase.getTag()} has '
                              f'{phase.rc_timer.getRemaining()}ms remaining '
                              f'red clearance time')
                continue

            unavailable_channels = set()
            for ch in phase.channels:
                if not ch.is_ready:
                    unavailable_channels.add(ch)
                    continue

                remaining_interval = ch.remaining
                minimum = self._gib[ch.state][0]
                if remaining_interval > 0 and minimum > 0:
                    if remaining_interval < minimum:
                        self.LOG.fine(f'{ch.getTag()} has '
                                      f'{remaining_interval}s remaining '
                                      f'minimum {ch.state.name} time '
                                      f'({minimum}s)')
                        unavailable_channels.add(ch)

            if len(unavailable_channels) > 0:
                continue

            results.add(phase)

        return frozenset(results)

    def getAvailableActiveBarrierPhases(self) -> List[Phase]:
        """
        Determine what phases from the active barrier phase pool can run given
        the current controller state.

        :return: an ordered set of available Barrier Phases
        """
        if self._active_barrier is None:
            return []

        barrier_phases = self.getBarrierPhases(self._active_barrier)
        available = self.getAvailablePhases(barrier_phases)
        return sorted(available)

    def getChannelTiming(self, ch: Channel) -> PhaseTimesheet:
        """Get the associated timesheet of a given channel
                from the current schedule"""
        phase = self.getPhaseByChannel(ch)
        return self._sch_manager.timesheets[phase]

    def getCETSeconds(self):
        """Get the control entrance time in seconds for the current schedule"""
        caution = 0

        for ch in self._channels:
            timesheet = self.getChannelTiming(ch)

            if ch.flash_mode == FlashMode.YELLOW:
                caution = timesheet.targets[IntervalType.CAUTION]
                break

        return caution + self._init_red_clearance

    def getPhaseByChannel(self, ch: Channel) -> Phase:
        """Find a `Phase` instance by one of it's associated
                `Channel` instances"""
        for phase in self.getPhases():
            if ch in phase.channels:
                return phase

        raise RuntimeError(f'Failed to get phase for {ch.getTag()}')

    def getRingPhases(self, ring: Ring) -> List[Phase]:
        """Get `Phase` instances associated with a `Ring` instance"""
        phase_index_map = self.getIndexPhaseMap()
        phases = []

        for pi in ring.phases:
            phases.append(phase_index_map[pi])

        return phases

    def getRingByPhase(self, phase: Phase) -> Ring:
        """Find a `Phase` instance by one of it's associated
                `Channel` instances"""
        for r in self.getRings():
            phases = self.getRingPhases(r)
            if phase in phases:
                return r

        raise RuntimeError(f'Failed to get ring for {phase.getTag()}')

    def getDiagonalPhaseInBarrier(self,
                                  phase: Phase,
                                  barrier: Barrier) -> Phase:
        """
        Get Phase that is positioned diagonal to Phase a within barrier within
        a standard ring-and-barrier model.

        :param phase: primary Phase
        :param barrier: a barrier to enumerate for suitable Phases
        :return: currently guaranteed to return a Phase. this will not be the
        case when partial barrier configurations are implemented.
        """
        group = self.getBarrierPhases(barrier)
        phase_index = group.index(phase)

        if phase_index == 0:
            return group[-1]
        elif phase_index == 1:
            return group[2]
        elif phase_index == 2:
            return group[1]
        elif phase_index == 3:
            return group[0]

    def getColumnPhaseInBarrier(self,
                                phase: Phase,
                                barrier: Barrier) -> Phase:
        """
        Get Phase that is positioned in the same column to Phase a within
        a standard ring-and-barrier model.

        :param phase: primary Phase
        :param barrier: a barrier to enumerate for suitable Phases
        :return: currently guaranteed to return a Phase. this will not be the
        case when partial barrier configurations are implemented.
        """
        group = self.getBarrierPhases(barrier)
        phase_index = group.index(phase)
        half = len(group) // 2

        if phase_index < half:
            return group[phase_index + 2]
        else:
            return group[phase_index - 2]

    def getPhaseRanks(self, phases: Iterable) -> Dict[Phase, int]:
        """
        Get the ranks of the given iterable of `Phase` instances by
        associated `Call` priority into a map of `Phase`: rank where
        `sys.maxsize` is the lowest priority.

        :param phases: an iterable of Phase instances
        :return: a map of the form Phase: rank
        """
        ranks = {}

        for phase in phases:
            phase_calls = self.getCallsByPhase(phase)
            lowest = None

            if len(phase_calls) > 0:
                call_indices = [self._calls.index(c) for c in phase_calls]
                if len(call_indices) > 0:
                    lowest = min(call_indices)

            ranks.update({phase: lowest or sys.maxsize})

        return ranks

    def getBarrierByPhase(self, phase: Phase) -> Barrier:
        """Get `Barrier` instance by associated `Phase` instance"""
        phase_index_map = self.getPhaseIndexMap()
        pi = phase_index_map[phase]

        for b in self.getBarriers():
            if pi in b.phases:
                return b

        raise RuntimeError(f'Failed to get barrier by PH{phase.id:02d}')

    def beginPhasing(self, reoccurring=False):
        """Begin non-free phasing by placing reoccurring calls on all phases"""
        if self._active_barrier is None:
            for phase in self.getPhasesOrdered():
                self.placeCall(phase, system=True, reoccurring=reoccurring)
        else:
            raise RuntimeError('Cannot begin phasing when active barrier is '
                               'set')

    def getPriorityBarrier(self) -> Optional[Barrier]:
        """
        Get the barrier with the most priority call or
        None if there are no calls.
        """
        if len(self._calls) > 0:
            target = self._calls[0].target
            barrier = self.getBarrierByPhase(target)
            return barrier
        return None

    def changeBarrier(self, barrier: Barrier):
        """Directly set the active barrier"""
        if not self.allReady():
            raise RuntimeError('Attempted to change barrier when not all-ready')

        self._active_barrier = barrier
        self.LOG.debug(f'Crossed to barrier {barrier.getTag()} (direct)')

    def nextBarrier(self):
        """Change to the next `Barrier` in the barrier cycle instance"""
        if not self.allReady():
            raise RuntimeError('Attempted to cross barrier when not all-ready')

        if not self.idling:
            self._active_barrier = self.getNextBarrier()
            self.LOG.debug(f'Crossed to {self._active_barrier.getTag()}')
        else:
            raise RuntimeError('Cannot change barrier when idling')

    def endCycle(self, premature=False) -> None:
        """End phasing for this control cycle iteration"""
        if not self.allReady():
            raise RuntimeError('Attempted to end cycle before all-ready')

        self._first_cycle = False

        early_text = " (early)" if premature else ""
        self.LOG.debug(f'Ended cycle #{self._stats["cycles"]}{early_text}')

        self._stats['cycles'] += 1
        self._last_phase = self._phase_history[0]
        self._phase_history = []

    def startPhase(self, phase: Phase) -> None:
        """Start timing for a given `Phase` instance"""
        pair_count = len(self._phase_pair)
        ring = self.getRingByPhase(phase)

        if self._active_barrier is not None:
            if phase not in self.getBarrierPhases(self._active_barrier):
                raise RuntimeError(f'Attempted to start {phase.getTag()} '
                                   'out-of-barrier')

        if pair_count > 2:
            raise RuntimeError('More than two phases started')
        elif pair_count == 1:
            other_phase = self._phase_pair[0]
            other_ring = self.getRingByPhase(other_phase)

            if other_ring == ring:
                raise RuntimeError(f'Attempted to start {phase.getTag()} while '
                                   f'{other_phase.getTag()} is running '
                                   '(same ring)')

        timesheet = self._sch_manager.timesheets[phase]
        go_time = timesheet.getTargetOrMin(IntervalType.GO)
        ped_clear_time = timesheet.getTargetOrMin(IntervalType.PED_CLEAR)

        self.LOG.debug(f'Starting {phase.getTag()}')

        for ch in phase.channels:
            if ch.mode == ChannelMode.PEDESTRIAN:
                interval_time = go_time - ped_clear_time
            else:
                interval_time = go_time

            self.setChannel(ch, interval_time, it=IntervalType.GO)

        self._phase_pair.append(phase)
        self._first_phase = True

    def expeditePhase(self, phase: Phase):
        """Ensure phase timing is set to global minimum"""
        self._expedited_phases.add(phase)

        for ch in phase.channels:
            timesheet = self.getChannelTiming(ch)
            if ch.state != IntervalType.STOP:
                minimum_interval = timesheet.minimums[ch.state]
                self.setChannel(ch, minimum_interval)

    def setPhasesToPreemption(self, phases: List[Phase]):
        """Set phase vehicle channels to their preemption duration"""
        preemption_duration = self._active_barrier.preemption_duration
        for phase in phases:
            for ch in phase.channels:
                if ch.mode == ChannelMode.VEHICLE:
                    if ch.state == IntervalType.GO:
                        self.setChannel(ch, preemption_duration)
                    elif ch.state == IntervalType.FYA:
                        self.setChannel(ch, preemption_duration,
                                        it=IntervalType.GO)
                else:
                    self.setChannel(ch, 0, it=IntervalType.STOP)

    def startPreemption(self, phases: List[Phase]) -> bool:
        """
        Begin preemption for the given phase pair. If they are already timing
        together, they're duration will be extended. Otherwise, all other
        timing phases will be expedited.

        :param phases: targets for preemption
        :return: False if we will have to wait for other phases
                 minimum intervals
        """
        phase_count = len(phases)
        if phase_count > 2:
            raise RuntimeError('Maximum of two phases for preemption')
        elif phase_count == 2:
            if self.checkPhaseConflict(phases[0], phases[1]):
                raise RuntimeError('Preemption pair conflicts with each other')

        self._preemption_pair = phases

        # are any of the target phases currently timing?
        active_targets = [ph for ph in phases if ph in self._phase_pair]

        if active_targets == 2:
            self.setPhasesToPreemption(phases)
            return True
        else:
            for timing_phase in self._phase_pair:
                self.expeditePhase(timing_phase)
            return False

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
        system_weight = self._call_weights.get('system')
        active_barrier_weight = self._call_weights.get('active-barrier')

        # prioritize calls by age
        weight -= left.age.getDelta()
        weight += right.age.getDelta()

        # prioritize calls within the active barrier, if set
        if active_barrier_weight is not None:
            lb = self.getBarrierByPhase(left.target)
            rb = self.getBarrierByPhase(right.target)
            if self._active_barrier is not None and lb != rb:
                if lb == self._active_barrier:
                    weight -= active_barrier_weight
                else:
                    weight += active_barrier_weight

        if left.system and right.system:
            # enforce least-to-greatest phase sequencing for system calls
            if left.target.id < right.target.id:
                weight = -left.target.id
            else:
                weight = right.target.id
        else:
            # prioritize system calls, if set
            if system_weight is not None:
                if left.system:
                    weight = -system_weight
                if right.system:
                    weight = system_weight

        self.LOG.sorting(f'Sorting result between {left.getTag()} (target='
                         f'{left.target.getTag()}, age={left.age.getDelta()}) '
                         f'and {right.getTag()} '
                         f'(target={right.target.getTag()}, '
                         f'age={right.age.getDelta()}) = {weight}')
        return weight

    def sortCalls(self):
        """Sort the call stack using custom weights"""
        self._calls.sort(key=cmp_to_key(self._sortCallsKeyFunc))

    def getCallsByPhase(self, phase: Phase) -> List[Call]:
        """Get an ordered list of calls belonging to a `Phase` instance"""
        results = []
        for call in self._calls:
            if call.target == phase:
                results.append(call)
        return results

    def handleCalls(self):
        """Attempt to serve calls and remove expired ones"""
        if len(self._calls) > 0:
            remove = []
            for call in self._calls:
                if call.age.getDelta() > self._max_call_age:
                    self.LOG.debug(f'Call {call.getTag()} has expired')
                    remove.append(call)
                else:
                    if self.serveCall(call):
                        self.LOG.debug(f'Serving call {call.getTag()}')
                        remove.append(call)

                        if call.reoccurring:
                            self.placeCall(call.target,
                                           system=True,
                                           reoccurring=True)
                        break

            for call in remove:
                self._calls.remove(call)

            if len(remove) > 0:
                self.sortCalls()

    def serveCall(self, call: Call) -> bool:
        """Attempt to start the given call's target `Phase`, if possible"""
        call_tag = call.getTag()
        call_target_tag = call.target.getTag()
        pair_size = len(self._phase_pair)
        phase = call.target

        if self._last_phase is not None:
            if phase == self._last_phase:
                self._last_phase = None
                return False

        lone_phase = None
        if not self._active_barrier.singles and pair_size == 1:
            lone_phase = self._phase_pair[0]
            if phase == lone_phase:
                return False
        elif not self.allReady():
            return False

        if phase in self.getAvailableActiveBarrierPhases():
            if lone_phase is not None:
                self.LOG.verbose(f'Call {call_tag} '
                                 f'({call_target_tag}) '
                                 f'was selected as partner to '
                                 f'{lone_phase.getTag()}')

            self.startPhase(phase)
            return True

        return False

    def placeCall(self,
                  target: Phase,
                  system=False,
                  reoccurring=False,
                  input_slot=None):
        """
        Create a new call for traffic service.

        :param target: the desired Phase to service
        :param system: mark call as highest priority
        :param reoccurring: replace call upon servicing
        :param input_slot: associate call with input slot number
        """
        call = Call(self._stats['calls'] + 1,
                    target,
                    SecondTimer(0),
                    system,
                    reoccurring=reoccurring)

        input_text = ''

        if input_slot is not None:
            input_text = f' (from input slot {input_slot})'

        if not system:
            self.LOG.debug(f'Event call {call.getTag()} '
                           f'{target.getTag()}{input_text}')
        else:
            self.LOG.debug(f'Automatic call {call.getTag()} '
                           f'{target.getTag()}{input_text}')
        self._calls.append(call)
        self._stats['calls'] += 1
        self.sortCalls()

    def getNextChannelInterval(self,
                               current_mode: ChannelMode,
                               current_state: IntervalType):
        """Get the next channel state given the current
                channel state, mode and globally disabled interval types"""
        if current_mode == ChannelMode.VEHICLE:
            if current_state == IntervalType.GO:
                return IntervalType.CAUTION
            if current_state == IntervalType.CAUTION:
                return IntervalType.STOP
            if current_state == IntervalType.STOP:
                return IntervalType.GO
        elif current_mode == ChannelMode.PEDESTRIAN:
            if current_state == IntervalType.GO:
                if IntervalType.PED_CLEAR not in self._gdi:
                    return IntervalType.PED_CLEAR
                else:
                    return IntervalType.STOP
            if current_state == IntervalType.PED_CLEAR:
                return IntervalType.STOP
            if current_state == IntervalType.STOP:
                return IntervalType.GO
        raise NotImplementedError()

    def beginIdle(self):
        """Start the idle timer"""

        if self.idling:
            raise RuntimeError('Already idling')

        for ph in self.getPhases():
            if ph.is_timing:
                raise RuntimeError('At least one phase still timing')

        self._idle_timer.reset()
        self._idle_timer.pause = False
        self.LOG.debug(f'Idling...')

    def stopIdle(self):
        """Stop the idle timer"""

        if not self.idling:
            raise RuntimeError('Was not idling')

        idle_seconds = self._idle_timer.getDelta()
        self._stats['total_idle_seconds'] += idle_seconds
        self.LOG.debug(f'Idled for {idle_seconds:04d}s')
        self._idle_timer.pause = True

    def setOperationState(self, new_state: OperationMode):
        """Set controller state for a given `OperationMode`"""
        if not self.allReady():
            raise RuntimeError('Cannot set next operation state, '
                               'not all-ready.')

        if new_state == OperationMode.CET:
            for ch in self._channels:
                ch.dark = False
                timesheet = self.getChannelTiming(ch)

                if ch.flash_mode == FlashMode.YELLOW:
                    interval = timesheet.targets[IntervalType.CAUTION]
                    self.setChannel(ch, interval, it=IntervalType.CAUTION)
                else:
                    self.setChannel(ch, 0, it=IntervalType.STOP)
        elif new_state == OperationMode.NORMAL:
            for ch in self._channels:
                ch.dark = False

            if self._sch_manager.free:
                self.beginIdle()
            else:
                self.beginPhasing(reoccurring=True)

        previous_state = self._op_mode
        self._op_mode = new_state
        self.LOG.info(f'Operation state is now {new_state.name} '
                      f'(was {previous_state.name})')

    def getCallsFromPhases(self, phases: Iterable) -> List[Call]:
        """Filter call stack for calls only associated with `Phase`
                instances in the given iterable"""
        calls = []

        for phase in phases:
            calls.extend(self.getCallsByPhase(phase))

        return calls

    def getPhasesWithCalls(self) -> FrozenSet[Phase]:
        """Get unique `Phase` instances found within the current call stack"""
        phases = set()

        for call in self._calls:
            phases.add(call.target)

        return frozenset(phases)

    def handleRingAndBarrier(self):
        """Determine when to cross barriers and/or end the current cycle"""

        if self._active_barrier is not None:
            barrier_phases = self.getBarrierPhases(self._active_barrier)
            available_barrier_phases = self.getAvailableActiveBarrierPhases()

            # if all phases of barrier are contained in phase history
            c1 = all([ph in self._phase_history for ph in barrier_phases])

            # no available phases left for current barrier
            c2 = len(self.getCallsFromPhases(available_barrier_phases)) == 0

            if c1 or c2:
                if self.allReady():
                    # if the size of phase history is greater or equal to the
                    # current number of phases with calls and there are calls,
                    # then it's time to end the cycle
                    if len(self._calls) > 0 and \
                            len(self._phase_history) >= \
                            len(self.getPhasesWithCalls()):
                        self.endCycle()

                    self.nextBarrier()
        else:
            if len(self._calls) > 0:
                barrier = self.getPriorityBarrier()
                if barrier is not None:
                    self.changeBarrier(barrier)

    def handlePhases(self):
        """Handle phase timers and completed phases"""
        done_phases = set()
        for phase in self.getPhases():
            if phase.is_ready and phase in self._phase_pair:
                done_phases.add(phase)

        for dp in done_phases:
            if dp in self._expedited_phases:
                self._expedited_phases.remove(dp)
            if dp in self._preemption_pair:
                self._preemption_pair.remove(dp)
            self._phase_pair.remove(dp)
            self._phase_history.insert(0, dp)
            dp.rc_timer.reset()
            dp.rc_timer.pause = False

    def updateChannelFields(self):
        """Update field display to match current state"""
        for ch in self._channels:
            if not ch.dark:
                if ch.state == IntervalType.GO:
                    ch.a = False
                    ch.b = False
                    ch.c = True
                if ch.state == IntervalType.CAUTION:
                    ch.a = False
                    ch.b = True
                    ch.c = False
                if ch.state == IntervalType.PED_CLEAR:
                    ch.a = self._flasher
                    ch.c = False
                if ch.state == IntervalType.STOP or ch.mode == \
                        ChannelMode.DISABLED:
                    ch.a = True
                    ch.b = False
                    ch.c = False
            else:
                ch.a = False
                ch.b = False
                ch.c = False

    def setChannel(self, ch: Channel, duration: int, it=None):
        """
        Set channel run duration and optionally interval type
        (will keep existing interval type if not set).

        :param ch: the target Channel to modify
        :param duration: new timing duration of channel in seconds
        :param it: new specific interval type
        """
        if it is None:
            self.LOG.verbose(f'{ch.getTag()} duration overwritten')
            it = ch.state

        ch.duration = duration
        ch.ism = seconds()

        if it in MOVEMENT_INTERVALS:
            marker_value = ch.ism + duration
        else:
            marker_value = 0

        ch.markers.update({it: marker_value})
        ch.state = it

    def setChannelNext(self, ch: Channel, duration: int):
        """
        Set channel run duration (will get next interval type if not set).

        :param ch: the target Channel to modify
        :param duration: new timing duration of channel in seconds
        """
        previous_it = ch.state
        ism = ch.ism

        next_it = self.getNextChannelInterval(ch.mode, ch.state)

        self.setChannel(ch, duration, it=next_it)

        ism_text = ''
        if ism > 0:
            delta = seconds() - ism
            ism_text = f' (was {previous_it.name} for ' \
                       f'{delta:02d}s) '

            if previous_it not in REST_INTERVALS:
                minimum = self._gib[previous_it][0]
                if minimum > 0:
                    if delta < minimum:
                        raise RuntimeError(f'{ch.getTag()} violated minimum '
                                           f'interval bound for '
                                           f'{previous_it.name} '
                                           f'({delta}s < {minimum}s)')
                maximum = self._gib[previous_it][1]
                if maximum > 0:
                    if delta > maximum:
                        raise RuntimeError(f'{ch.getTag()} violated maximum '
                                           f'interval bound for '
                                           f'{previous_it.name} '
                                           f'({delta}s > {maximum}s)')

        self.LOG.fine(f'Set {ch.getTag()} to {next_it.name}{ism_text}')

    def handleChannels(self):
        """Update channel timing and interval type based of the current state"""
        for ch in self._channels:
            timesheet = self.getChannelTiming(ch)

            if ch.is_timing:
                if ch.remaining == 0:
                    if ch.state == IntervalType.GO:
                        phase = self.getPhaseByChannel(ch)
                        if phase in self._expedited_phases:
                            if ch.mode == ChannelMode.PEDESTRIAN:
                                self.setChannel(ch, 0, it=IntervalType.STOP)
                            else:
                                duration = timesheet.minimums[
                                    IntervalType.CAUTION
                                ]
                                self.setChannelNext(ch,
                                                    duration)
                        else:
                            # ensure ped clearance interval always starts on
                            # flasher clock high side
                            flasher_high_wait = False
                            if ch.mode == ChannelMode.PEDESTRIAN:
                                flasher_high_wait = not self._flasher
                                duration = timesheet.getTargetOrMin(
                                    IntervalType.PED_CLEAR)
                            else:
                                duration = timesheet.getTargetOrMin(
                                    IntervalType.CAUTION)

                            if not flasher_high_wait:
                                self.setChannelNext(ch, duration)
                    else:
                        if ch.state in MOVEMENT_INTERVALS:
                            self.setChannelNext(ch, 0)

    def busHealthCheck(self):
        """Ensure bus thread is still running, if enabled"""
        if self.bus_enabled:
            if not self._bus.running:
                self.LOG.error('Bus not running')
                self.shutdown()

    def getChannelStates(self) -> List[FrozenChannelState]:
        frozen_states = []

        for ch in self._channels:
            call_count = len(self.getCallsByPhase(self.getPhaseByChannel(ch)))
            frozen_states.append(FrozenChannelState(
                ch.id,
                ch.a,
                ch.b,
                ch.c,
                ch.duration,
                ch.remaining,
                call_count
            ))

        return frozen_states

    def handleInputs(self):
        """Check on the contents of bus data container for changes"""
        inputs_field = self._bus.inputs_field

        if self._last_input_field is None or \
                inputs_field != self._last_input_field:
            for slot, inp in self._inputs.items():
                try:
                    state = inputs_field[slot - 1]

                    inp.last_state = inp.state
                    inp.state = state

                    if inp.activated():
                        if inp.action == InputAction.CALL:
                            for target in inp.targets:
                                self.placeCall(target, input_slot=slot)
                        elif inp.action == InputAction.PREEMPTION:
                            csv = ', '.join([ph.getTag() for ph in inp.targets])
                            self.LOG.info(f'Preemption requested for {csv}')
                        else:
                            raise NotImplementedError()
                except IndexError:
                    self.LOG.fine('Discarding signal for unused input slot '
                                  f'{slot}')

        self._last_input_field = inputs_field

    def getLastPhasePair(self) -> Optional[Tuple[Phase, Phase]]:
        history_size = len(self._phase_history)

        if history_size >= 2:
            return self._phase_history[0], self._phase_history[1]
        return None

    def tick(self):
        """Polled once every 100ms"""
        if self.bus_enabled:
            self.handleInputs()

        if not self.time_freeze:
            if self._op_mode == OperationMode.NORMAL:
                if len(self._phase_pair) == 0:
                    if len(self._calls) == 0:
                        if not self.idling:
                            self.beginIdle()
                    else:
                        if self.idling:
                            self.stopIdle()

                if not self.idling:
                    self.handleRingAndBarrier()

                if self.preempting:
                    last_pair = self.getLastPhasePair()

                    # are both preemption phases not in the last pair history?
                    c1 = last_pair is None or not \
                        all(ph in last_pair for ph in self._preemption_pair)
                    # are both preemption phases currently timing
                    c2 = all(ph in self._phase_pair for ph in
                             self._preemption_pair)
                    # start the preemption phases if they are not found within
                    # the last pair history and not yet timing
                    if c1 and not c2:
                        for phase in self._preemption_pair:
                            self.startPhase(phase)
                else:
                    if self._active_barrier is not None:
                        self.handleCalls()

                self.handlePhases()
            elif self._op_mode == OperationMode.CET:
                if self._cet_timer.poll():
                    self._cet_timer.reset()
                    self.setOperationState(OperationMode.NORMAL)
            else:
                raise NotImplementedError()

            self.handleChannels()
            self.updateChannelFields()

        channel_states = self.getChannelStates()
        if self.bus_enabled:
            self._bus.sendOutputState(channel_states, self.transferred)

        if self.monitor_enabled:
            self._monitor.broadcastOutputState(channel_states)

        if self._half_counter == 4:
            self._half_counter = 0
            self.halfSecond()
        else:
            self._half_counter += 1

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
                        phase_index_map = self.getIndexPhaseMap()
                        self.placeCall(phase_index_map[random_phase_index])

            if self._sch_queue is None:
                if self._sch_timer.poll():
                    self._sch_timer.reset()
                    self.LOG.verbose(f'Polling for schedule change...')

                    rv = self._sch_manager.getNextSchedule()
                    next_schedule = rv[0]
                    schedule_ts = rv[1]

                    if next_schedule != self._sch_manager.active:
                        self._sch_queue = (next_schedule, schedule_ts)
            else:
                if self.allReady():
                    self._sch_manager.setActive(self._sch_queue[0],
                                                ts=self._sch_queue[1])
                    self._sch_queue = None
                else:
                    # todo: perhaps shorten any resting phases in this
                    #  circumstance after a number of seconds
                    self.LOG.verbose('Schedule change queue waiting on '
                                     'all-ready...')

        if self.monitor_enabled:
            self._monitor.clean()

    def run(self):
        """Begin control loop"""
        self._running = True

        self.LOG.info(f'Controller is named "{self._name}"')

        # noinspection PyUnreachableCode
        if __debug__:
            self.LOG.warning('Controller in DEBUG ENVIRONMENT!')

        self.LOG.debug(f'CET delay set to {self.getCETSeconds()}s')

        self.updateChannelFields()
        self.setOperationState(self._op_mode)

        if self._running:
            if self.monitor_enabled:
                self._monitor.start()

            if self.bus_enabled:
                self._bus.start()

                while not self._bus.running:
                    self.LOG.debug(f'Waiting on bus...')

                self.LOG.debug(f'Bus ready')

            self.transfer()
            while self._running:
                if self._tick_timer.poll():
                    self._tick_timer.reset()
                    self.tick()

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
