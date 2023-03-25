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
import random
from concurrent import futures

import grpc
from loguru import logger
from typing import Set, Dict, List, Tuple, Union, Iterable, Optional, FrozenSet
from datetime import datetime
from dateutil import tz
from itertools import cycle

from atsc import utils
from atsc.core.fundemental import Tickable
from atsc.core.models import (OperationMode,
                              LoadSwitch,
                              Ring,
                              Barrier,
                              PhaseState, FlashMode, PHASE_GO_STATES)
from atsc.core.parallel import ThreadedTickable
from atsc.core.timing import SystemTimer, seconds
from atsc.daemon.models import (ControlPhase,
                                CallCollection,
                                does_phase_conflict,
                                ring_by_phase,
                                get_phase_partner,
                                barrier_by_phase, phases_by_number, ControlCall)
from atsc.daemon.rpcserver import (register_controller_service,
                                   ControllerServicer)
from atsc.utils import text_to_enum


BARRIER_COUNT = 2
PHASE_COUNT = 8
LS_COUNT = 12
FLASH_COUNT = 4
LOCK_TIMEOUT = 0.05
BASE_TICK = 0.1
LOG_MSG_DT_FORMAT = '%I:%M %p %b %d %Y'


class RandomCallsManager(Tickable):

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
                 tick_size: float,
                 configuration_node: dict,
                 pool_size: int):
        super().__init__(tick_size)
        self._enabled = configuration_node['enabled']
        self._delay = configuration_node['delay']  # seconds
        self._min = configuration_node['min']  # seconds
        self._max = configuration_node['max']  # seconds
        self._time = 0
        self._pool = range(1, pool_size)

        seed = configuration_node.get('seed')
        if seed is not None and seed > 0:
            # global pseudo-random generator seed
            random.seed(seed)

    def next(self) -> Tuple[int, int]:
        choice = random.choice(self._pool)
        delay = random.randrange(self._min, self._max)
        return choice, delay

    def getPhaseIndex(self) -> Optional[int]:
        choice = None

        if self._enabled:
            if self._delay < self.tick_size:
                if self._time < self.tick_size:
                    choice, delay = self.next()
                    self._time = delay
                    logger.debug('random calls: picking {}, next in {}',
                                 choice, delay)

        return choice

    def tick(self):
        if self._time > self.tick_size:
            self._time = self._time - self.tick_size
        if self._delay > self.tick_size:
            self._delay = self._delay - self.tick_size


class Controller(ThreadedTickable):

    @property
    def name(self):
        """Name of the daemon"""
        return self._name

    @property
    def operation_mode(self):
        """Current operation mode of the daemon"""
        return self._op_mode

    @property
    def transferred(self):
        """Has the daemon transferred the flash transfer relays"""
        return self._transfer

    @property
    def transfer_count(self):
        return self._transfer_count

    @property
    def runtime(self) -> int:
        return seconds() - self._run_marker

    @property
    def control_time(self) -> int:
        return seconds() - self._control_marker

    @property
    def avg_demand(self):
        return 0

    @property
    def peek_demand(self):
        return 0

    @property
    def saturated(self):
        return len(self._calls.phases) == len(self._phases)

    @property
    def idle(self):
        return len(self._calls) == 0

    @property
    def flasher(self):
        """1Hz square wave reference"""
        return self._flasher

    @property
    def calls(self):
        """An immutable copy of the current daemon calls stack"""
        return self._calls.tuple

    @property
    def active_barrier(self):
        """The current barrier being served"""
        return self._active_barrier

    def __init__(self,
                 tick_size: float,
                 con_str: str,
                 config: dict):
        super().__init__(tick_size)

        # daemon timezone
        tz_name = config['device']['location']['timezone']
        self._tzo = tz.gettz(tz_name)

        # daemon name (arbitrary)
        self._name: str = config['device']['name']

        # start records
        self._start_dt: datetime = datetime.now(self._tzo)
        self._run_marker: int = 0

        # should place calls on all phases when started?
        self._recall_all: bool = config['init']['recall-all']

        # 1Hz square wave reference clock
        self._flasher = True

        # control loop enable flag
        self._running = False

        # local flash transfer relay status
        self._transfer = False
        self._transfer_count: int = 0
        self._control_marker: int = 0

        # timing pause state
        self._timing_freeze = False

        # operation functionality of the daemon
        self._op_mode: OperationMode = text_to_enum(OperationMode,
                                                    config['init']['mode'])

        self._load_switches: List[LoadSwitch] = self.getLoadSwitches()

        default_timing = self.getDefaultTiming(config['default-timing'])
        self._phases: List[ControlPhase] = self.getPhases(config['phases'],
                                                          default_timing)

        self._rings: List[Ring] = self.getRings(config['rings'])
        self._barriers: List[Barrier] = self.getBarriers(config['barriers'])
        assert len(self._barriers) == BARRIER_COUNT

        # cycle instance of barriers
        self._barrier_pool: cycle = cycle(self._barriers)

        # phases ran for current barrier
        self._barrier_phase_count: int = 0

        # barrier served no phases before crossing
        self._barrier_skip_counter: int = 0

        # barrier cannot serve any more phases until first serving other
        self._serve_lockout: bool = False

        # current barrier
        self._active_barrier: Optional[Barrier] = None

        # barrier tick status
        self._barrier_status = -1

        # total cycle counter
        self._cycle_count = 1

        # overall phase tracking window
        self._phase_window: List[ControlPhase] = []

        # 500ms timer counter (0-4)
        # don't try and use an actual timer here,
        # that always results in erratic ped signal
        # countdowns in the least.
        self._half_counter: int = 0

        # control entrance transition timer
        self._cet_delay: int = config['init']['cet-delay']
        self._cet_timer = SystemTimer(seconds, self._cet_delay)

        # actuation
        self._call_counter: int = 0
        call_weights = config['calls']['weights']
        max_call_age = config['calls']['max-age']
        self._calls = CallCollection(weights=call_weights,
                                     rings=self._rings,
                                     barriers=self._barriers,
                                     max_age=max_call_age)

        # for software demo and testing purposes
        self._random_calls: RandomCallsManager = RandomCallsManager(
            BASE_TICK,
            config['random-actuation'],
            len(self._phases)
        )

        thread_pool = futures.ThreadPoolExecutor(max_workers=4)
        self._rpc_service = ControllerServicer(self)
        self._rpc_server: grpc.Server = grpc.server(thread_pool)
        register_controller_service(self._rpc_service, self._rpc_server)
        self._rpc_server.add_insecure_port(con_str)

    def getDefaultTiming(self, configuration_node: Dict[str, float]) -> \
            Dict[PhaseState, float]:
        timing = {}
        for name, value in configuration_node.items():
            ps = text_to_enum(PhaseState, name)
            timing.update({ps: value})
        return timing

    def getLoadSwitches(self) -> List[LoadSwitch]:
        ls = []
        for n in range(1, LS_COUNT + 1):
            ls.append(LoadSwitch(n))
        return ls

    def getPhases(self,
                  configuration_node: List[Dict],
                  default_timing: Dict[PhaseState, float]) -> \
            List[ControlPhase]:
        phases = []

        for n, node in enumerate(configuration_node, start=1):
            phase_timing: Dict[PhaseState, float] = default_timing.copy()
            timing_data = node.get('timing')

            if timing_data is not None:
                for name, value in timing_data.items():
                    ps = text_to_enum(PhaseState, name)
                    phase_timing.update({ps: value})

            flash_mode_text = node['flash-mode']
            flash_mode = text_to_enum(FlashMode, flash_mode_text)

            ped_clear_enabled = node['pclr-enable']

            ls_node = node['load-switches']
            veh_num = ls_node['vehicle']
            ls_numbers = [veh_num]
            ped_num = ls_node.get('ped')
            veh = self.getLoadSwitchByNumber(veh_num)
            ped = None
            if ped_num is not None:
                ped = self.getLoadSwitchByNumber(ped_num)
                ls_numbers.append(ped_num)

            phase = ControlPhase(n,
                                 BASE_TICK,
                                 phase_timing,
                                 flash_mode,
                                 ped_clear_enabled,
                                 veh,
                                 ped)
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

    def getBarrierPhases(self, barrier: Barrier) -> List[ControlPhase]:
        """
        Map the phase indices defined in a `Barrier` to `ControlPhase` instances
        """
        return [self.getPhaseByNumber(pi) for pi in barrier]

    def transfer(self):
        """Set the controllers flash transfer relays flag"""
        logger.info('transferred')
        self._transfer = True
        self._transfer_count += 1
        self._control_marker = seconds()

    def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        logger.info('untransfered')
        self._transfer = False

    def phaseConflictsWith(self,
                           a: ControlPhase,
                           b: ControlPhase) -> bool:
        """
        Check if two phases conflict based on Ring, Barrier and defined friend
        channels.

        :param a: ControlPhase to compare against
        :param b: Other ControlPhase to compare
        :return: True if conflict
        """
        return does_phase_conflict(self._rings, self._barriers, a, b)

    def getAvailablePhases(self,
                           called: Iterable[ControlPhase],
                           active: Iterable[ControlPhase],
                           barrier: Optional[Barrier],
                           history: Iterable[ControlPhase]) -> \
            FrozenSet[ControlPhase]:
        """
        Determine what phases can run given the current daemon state.

        :param called: phases with calls
        :param active: currently active phases for iteration
        :param barrier: limit to this Barrier pool
        :param history: exclude previously ran phases from this pool
        :return: an immutable set of available Phases
        """
        results: Set[ControlPhase] = set()

        for phase in called:
            if not phase.ready:
                continue

            if phase in active:
                continue

            if barrier is not None:
                if phase.id in barrier:
                    continue

            if any([self.phaseConflictsWith(phase, a) for a in active]):
                continue

            if history is not None:
                if phase in history:
                    continue

            results.add(phase)

        return frozenset(results)

    def getRingByPhase(self, phase: ControlPhase) -> Ring:
        """
        Get Ring instance by associated ControlPhase instance
        """
        return ring_by_phase(self._rings, phase)

    def getDiagonalPartner(self,
                           phase: ControlPhase) -> ControlPhase:
        """
        Get ControlPhase that is positioned diagonal to ControlPhase a within
        barrier within a standard ring-and-barrier model.

        :param phase: primary ControlPhase
        :return: currently guaranteed to return a ControlPhase. this will not be
        the case when partial barrier configurations are implemented.
        """
        barrier = self.getBarrierByPhase(phase)
        group = self.getBarrierPhases(barrier)
        phase_index = barrier.index(phase.id)

        if phase_index == 0:
            return group[-1]
        elif phase_index == 1:
            return group[2]
        elif phase_index == 2:
            return group[1]
        elif phase_index == 3:
            return group[0]

        raise RuntimeError('failed to find diagonal partner')

    def getColumnPartner(self,
                         phase: ControlPhase) -> ControlPhase:
        """
        Get ControlPhase that is positioned in the same column to ControlPhase a
        within a standard ring-and-barrier model.

        :param phase: primary ControlPhase
        :return: currently guaranteed to return a ControlPhase. this will not be
        the case when partial barrier configurations are implemented.
        """
        barrier = self.getBarrierByPhase(phase)
        group = self.getBarrierPhases(barrier)
        phase_index = barrier.index(phase.id)
        half = len(group) // 2

        if phase_index < half:
            return group[phase_index + 2]
        else:
            return group[phase_index - 2]

    def getPhasePartner(self, active: ControlPhase) -> \
            Optional[ControlPhase]:
        """
        Choose which of the two partners should be activated in conjunction
        with the primary phase.

        :param active: primary ControlPhase choice
        :return: top choice partner ControlPhase
        """
        return get_phase_partner(self._barriers,
                                 self._calls.phases,
                                 active,
                                 self.idle)

    def getBarrierByPhase(self, phase: ControlPhase) -> Barrier:
        """
        Get Barrier instance by associated ControlPhase instance
        """
        return barrier_by_phase(self._barriers, phase)

    def recallAll(self, ped_service=False):
        """Place calls on all phases"""
        for phase in self._phases:
            self.recall(phase.id, ped_service=ped_service)

    def nextBarrier(self):
        """Change to the next `Barrier` in the barrier cycle instance"""
        self._serve_lockout = False
        self._barrier_phase_count = 0
        self._active_barrier = next(self._barrier_pool)
        logger.debug('crossed to {}', self._active_barrier.getTag())

    def endCycle(self) -> None:
        """End phasing for this control cycle iteration"""
        self._cycle_count += 1
        logger.debug('ended cycle {}', self._cycle_count)

    def getPhaseByNumber(self, num: int) -> ControlPhase:
        return phases_by_number(self._phases, num)

    def getLoadSwitchByNumber(self, num: int) -> LoadSwitch:
        for n, ls in enumerate(self._load_switches, start=1):
            if n == num:
                return ls
        raise RuntimeError('failed to find load switch {}', num)

    def getActivePhases(self) -> List[ControlPhase]:
        active = []
        for ph in self._phases:
            if ph.active:
                active.append(ph)
        return active

    def _phaseOrNumber(self, o: Union[int, ControlPhase]) -> ControlPhase:
        if isinstance(o, int):
            phase = self.getPhaseByNumber(o)
        elif isinstance(o, ControlPhase):
            phase = o
        else:
            raise TypeError()
        return phase

    def recall(self,
               o: Union[int, ControlPhase],
               ped_service: bool,
               input_slot=None):
        """
        Create a new call for traffic service.

        :param o: the desired ControlPhase or ControlPhase number to service
        :param ped_service: activate ped signal with vehicle
        :param input_slot: associate call with input slot number
        """
        target = self._phaseOrNumber(o)
        input_text = ''

        if ped_service:
            input_text = f' (ped service)'

        if input_slot is not None:
            input_text = f' (input #{input_slot})'

        number = self._call_counter + 1
        call = ControlCall(self.tick_size,
                           number,
                           target,
                           ped_service)
        self._calls.add(call)
        self._call_counter += 1
        logger.debug(f'call {call.getTag()} {target.getTag()}{input_text}')

        if self._active_barrier is not None:
            if not self._serve_lockout:
                if self.getBarrierByPhase(target) != self._active_barrier:
                    active = self.getActivePhases()
                    if len(active):
                        self._serve_lockout = True
                        logger.debug('serve lockout set')

    def detection(self,
                  o: Union[int, ControlPhase],
                  ped_service: bool,
                  input_slot=None):
        phase = self._phaseOrNumber(o)
        input_text = ''

        if input_slot is not None:
            input_text = f' (input #{input_slot})'

        logger.debug('detection on {}{}', phase.getTag(), input_text)

        if phase.state in PHASE_GO_STATES:
            if phase.extend_active:
                phase.reduce()
        else:
            self.recall(phase, ped_service, input_slot=input_slot)

    def setOperationState(self, new_state: OperationMode):
        """Set daemon state for a given `OperationMode`"""
        if new_state == OperationMode.CET:
            for ph in self._phases:
                if ph.flash_mode == FlashMode.YELLOW:
                    ph.update(force_state=PhaseState.CAUTION)

            self._cet_timer.reset()
        elif new_state == OperationMode.NORMAL:
            if self._recall_all:
                self.recallAll(ped_service=True)

        previous_state = self._op_mode
        self._op_mode = new_state
        logger.info('operation state is now {} (was {})',
                    new_state.name,
                    previous_state.name)

    def allPhasesInactive(self) -> bool:
        for ph in self._phases:
            if ph.active:
                return False
        return True

    def matchPhasesUnordered(self,
                             a: List[ControlPhase],
                             b: List[ControlPhase]) -> bool:
        size = len(a)
        segment = b if len(b) < size else b[:size]
        matches = sum([p in segment for p in a])
        return matches >= size

    def handleBarrierAndCycle(self, available: FrozenSet[ControlPhase]) -> int:
        """
        Determine when to cross barriers and end cycles.

        :param available: currently available phases for active barrier
        :returns: -1 no phases ran, 0 no change, 1 next
        """

        # no available phases left
        c1 = len(available) == 0

        # all phases of active barrier are found within the last n objects of
        # the phase window where n is the length of the active barrier phase
        # array
        c2 = self.matchPhasesUnordered(
            self.getBarrierPhases(self._active_barrier),
            self._phase_window
        )

        # serve lockout set
        c3 = self._serve_lockout

        if c1 or c2 or c3:
            if self.allPhasesInactive():
                if len(self._phase_window) % len(self._phases) == 0:
                    self.endCycle()

                if self._barrier_phase_count == 0:
                    self._active_barrier = None
                    return -1
                else:
                    self.nextBarrier()
                    return 1
        return 0

    def activatePhase(self,
                      choice: ControlPhase,
                      ped_service=False):
        if not choice.ready:
            raise RuntimeError(f'{choice.getTag()} not ready')

        self._barrier_phase_count += 1
        self._barrier_skip_counter = 0

        if choice.pls is None:
            ped_service = False

        choice.activate(ped_service)

    def hasConflictingDemand(self,
                             pool: Iterable[ControlPhase],
                             ph: ControlPhase) -> bool:
        for phase in pool:
            if ph != phase:
                if self.phaseConflictsWith(ph, phase):
                    return True
        return False

    def pickCall(self, active: List[ControlPhase]) -> Optional[ControlCall]:
        calls: CallCollection = self._calls.sorted(self._active_barrier,
                                                   self.saturated)

        if self._active_barrier is None or len(calls.phases) < 1:
            history = None
        else:
            history = self._phase_window
        available = self.getAvailablePhases(calls.phases,
                                            active,
                                            self._active_barrier,
                                            history)

        choice = None
        if len(available):
            first_ph = active[0] if len(active) == 1 else None
            for call in calls:
                c1 = self._active_barrier is None
                c2 = not first_ph and self.allPhasesInactive()
                c3 = first_ph and first_ph.state != PhaseState.CAUTION

                if c1 or c2 or c3:
                    if call.target in available:
                        logger.debug('serving call {} ({})',
                                     call.getTag(),
                                     call.target.getTag())
                        choice = call
                        break

        return choice

    def tick(self):
        """Polled once every 100ms"""

        if not self._timing_freeze:
            self._calls.tick()

            if self._op_mode == OperationMode.NORMAL:
                rnd_phase_num = self._random_calls.getPhaseIndex()
                if rnd_phase_num is not None:
                    self.detection(rnd_phase_num, ped_service=True)
                self._random_calls.tick()

                for ph in self._phases:
                    conflicting_demand = self.hasConflictingDemand(
                        self._calls.phases,
                        ph
                    )
                    if ph.tick(conflicting_demand, self.flasher):
                        if ph.state == PhaseState.STOP:
                            self._phase_window.insert(0, ph)
                            if len(self._phase_window) > len(self._phases):
                                popped = self._phase_window.pop()
                                logger.trace('popped last phase {} from window',
                                             popped.getTag())

                if not self._serve_lockout:
                    force_secondary = False
                    before = self.getActivePhases()
                    choice1 = self.pickCall(before)
                    if choice1 is not None:
                        primary = choice1.target
                        self._calls.remove(primary)
                        if self._active_barrier is None:
                            self._active_barrier = self.getBarrierByPhase(
                                primary
                            )
                        self.activatePhase(primary,
                                           ped_service=choice1.ped_service)
                        after = self.getActivePhases()
                        choice2 = self.pickCall(after)
                        if choice2:
                            secondary = choice2.target
                            self._calls.remove(secondary)
                            self.activatePhase(secondary,
                                               ped_service=choice2.ped_service)
                        else:
                            force_secondary = True

                    last = self.getActivePhases()
                    last_count = len(last)
                    if last_count == 1:
                        force_secondary = True
                    elif last_count > 2:
                        raise RuntimeError('more than two active phases')

                    if force_secondary:
                        primary = last[0]
                        secondary = self.getPhasePartner(primary)
                        if secondary is not None:
                            self._calls.remove(secondary)
                            self.activatePhase(secondary)

                if self._active_barrier is not None:
                    active = self.getActivePhases()
                    available = self.getAvailablePhases(self._calls.phases,
                                                        active,
                                                        self._active_barrier,
                                                        self._phase_window)
                    self._barrier_status = self.handleBarrierAndCycle(available)
            elif self._op_mode == OperationMode.CET:
                for ph in self._phases:
                    ph.tick(False, self._flasher)
                if self._cet_timer.poll():
                    self.setOperationState(OperationMode.NORMAL)

            if self._half_counter == FLASH_COUNT:
                self._half_counter = 0
                self._flasher = not self._flasher
            else:
                self._half_counter += 1

        # field_text = ''
        # for ls in self._load_switches:
        #     ft = utils.format_fields(ls.a, ls.b, ls.c, colored=True)
        #     field_text += f'{ls.id:02d}{ft} '
        # logger.opt(ansi=True).trace(field_text)

    def before_run(self):
        self._rpc_server.start()
        self._run_marker = seconds()
        self._start_dt = datetime.now(self._tzo)
        logger.info('run start at {}',
                    self._start_dt.strftime(LOG_MSG_DT_FORMAT))

        logger.debug('control entrance transition delay set to {}',
                     self._cet_delay)
        self.setOperationState(self._op_mode)
        self.transfer()

    def after_run(self, code: int):
        self.untransfer()
        self._rpc_server.stop(1)
        logger.info(f'shutdown with exit code {code}')
        ed, eh, em, es = utils.format_dhms(self.runtime)
        logger.info('runtime of {} days, {} hours, {} minutes and {} seconds',
                    ed, eh, em, es)
