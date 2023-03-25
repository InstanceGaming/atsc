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
from typing import Set, Dict, List, Union, Iterable, Optional
from threading import Lock

from atsc.constants import FLOAT_ROUND_PLACES
from atsc.core.fundemental import Identifiable, Tickable
from atsc.core.models import (PhaseState,
                              FlashMode,
                              PHASE_TIMED_STATES,
                              LoadSwitch, PHASE_GO_STATES, Ring, Barrier)
from atsc.utils import cmp_key_args


class ControlPhase(Identifiable):

    @property
    def extend_enabled(self):
        return self._timing[PhaseState.EXTEND] > 0 and not self._extend_inhibit

    @property
    def extend_active(self):
        return self._state == PhaseState.EXTEND

    @property
    def resting(self):
        return self._resting

    @property
    def flash_mode(self) -> FlashMode:
        return self._flash_mode

    @property
    def active(self) -> bool:
        """Is currently timing (excluding MIN_STOP)"""
        return self._state.value > 2

    @property
    def ready(self) -> bool:
        """Can be activated right now"""
        return self._state.value == 0

    @property
    def state(self) -> PhaseState:
        return self._state

    @property
    def time_upper(self):
        return self._time_upper

    @property
    def time_lower(self):
        return self._time_lower

    @property
    def ped_service(self):
        return self._ped_service

    @property
    def vls(self):
        return self._vls

    @property
    def pls(self):
        return self._pls

    def _validate_timing(self):
        if self.active:
            raise RuntimeError('cannot changing timing map while active')
        if self._timing is None:
            raise TypeError('timing map cannot be None')
        keys = self._timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES):
            raise RuntimeError('timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('"STOP" state cannot be in timing map')

    def __init__(self,
                 id_: int,
                 tick: float,
                 timing: Dict[PhaseState, float],
                 flash_mode: FlashMode,
                 ped_clear_enable: bool,
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch]):
        super().__init__(id_)
        self._tick = tick
        self._timing = timing
        self._vls = veh_ls
        self._pls = ped_ls
        self._flash_mode = flash_mode
        self._state: PhaseState = PhaseState.STOP
        self._time_upper: float = 0.0
        self._time_lower: float = 0.0
        self._go_time: float = 0.0
        self._ped_service: bool = False
        self._resting: bool = False
        self._extend_inhibit = False
        self.ped_clear_enable: bool = ped_clear_enable

        self._validate_timing()

    def getFinalGoTime(self) -> float:
        go_time = self._timing[PhaseState.GO]
        if self._ped_service:
            walk_time = self._timing[PhaseState.WALK]
            go_time -= walk_time
            if self.ped_clear_enable:
                go_time -= self._timing[PhaseState.PCLR]
            if go_time < 0:
                go_time = 0.0

        return go_time

    def maxTimeUntilReady(self) -> float:
        remaining = 0

        if self._state in PHASE_GO_STATES:
            remaining += self.getFinalGoTime()

        if self.extend_active:
            remaining += self._timing[PhaseState.EXTEND]
        if self._state == PhaseState.CAUTION:
            remaining += self._timing[PhaseState.CAUTION]
        if self._state == PhaseState.RCLR:
            remaining += self._timing[PhaseState.RCLR]
        if self._state == PhaseState.MIN_STOP:
            remaining += self._timing[PhaseState.MIN_STOP]

        if not self.extend_active:
            remaining -= self._time_lower

        return remaining

    def getNextState(self, ped_service: bool) -> PhaseState:
        if self._state == PhaseState.STOP:
            if ped_service:
                return PhaseState.WALK
            else:
                return PhaseState.GO
        elif self._state == PhaseState.MIN_STOP:
            return PhaseState.STOP
        elif self._state == PhaseState.RCLR:
            return PhaseState.MIN_STOP
        elif self._state == PhaseState.CAUTION:
            self._ped_service = False
            self._extend_inhibit = False
            self._go_time = 0.0
            return PhaseState.RCLR
        elif self._state == PhaseState.EXTEND:
            return PhaseState.CAUTION
        elif self._state == PhaseState.GO:
            if self.extend_enabled:
                return PhaseState.EXTEND
            else:
                return PhaseState.CAUTION
        elif self._state == PhaseState.PCLR:
            return PhaseState.GO
        elif self._state == PhaseState.WALK:
            if self.ped_clear_enable:
                return PhaseState.PCLR
            else:
                return PhaseState.GO
        else:
            raise NotImplementedError()

    def update(self, force_state: Optional[PhaseState] = None):
        next_state = force_state or self.getNextState(self._ped_service)
        tv = self._timing.get(next_state, 0.0)

        self._time_upper = tv
        if next_state == PhaseState.EXTEND:
            self._time_lower = 0.0
        elif next_state == PhaseState.GO:
            self._time_lower = self.getFinalGoTime()
        else:
            self._time_lower = tv
        self._state = next_state

    def changeTiming(self, revised: Dict[PhaseState, float]):
        self._timing = revised
        self._validate_timing()

    def reduce(self):
        if self.extend_active:
            self._time_lower = 0.0
        else:
            raise RuntimeError('cannot reduce, not extending')

    def activate(self, ped_service: bool):
        if self.active:
            raise RuntimeError('cannot activate active phase')

        if self._pls is None and ped_service:
            raise RuntimeError(f'ped service invalid for {self.getTag()}, '
                               f'which does not have a ped load switch defined')

        self._ped_service = ped_service
        self.update()

    def tick(self,
             conflicting_demand: bool,
             flasher: bool) -> bool:
        changed = False
        self._resting = False

        if self._state in PHASE_GO_STATES:
            if self._go_time > self._timing[PhaseState.MAX_GO]:
                if conflicting_demand:
                    # todo: make this condition configurable per phase
                    self.update()
                    return True
            self._go_time += self._tick

        if self.extend_active:
            if self._time_lower > self._timing[PhaseState.EXTEND]:
                if conflicting_demand:
                    self.update()
                    changed = True
                else:
                    self._resting = True
            else:
                self._time_lower += self._tick
        else:
            if self._state != PhaseState.STOP:
                if self._time_lower > self._tick:
                    self._time_lower -= self._tick
                else:
                    if self._time_lower <= self._tick:
                        self._time_lower = 0.0
                    if self._state == PhaseState.WALK:
                        if conflicting_demand:
                            if flasher:
                                self.update()
                                changed = True
                        else:
                            self._resting = True
                        self._extend_inhibit = True
                    else:
                        if self._state == PhaseState.GO or \
                                self._state == PhaseState.EXTEND:
                            if conflicting_demand:
                                self.update()
                                changed = True
                            else:
                                self._resting = True
                        else:
                            self.update()
                            changed = True
            else:
                self._resting = True

        pa = False
        pb = False
        pc = False

        if self._state == PhaseState.STOP or \
                self.state == PhaseState.MIN_STOP or \
                self._state == PhaseState.RCLR:
            self._vls.a = True
            self._vls.b = False
            self._vls.c = False
            pa = True
            pc = False
        elif self._state == PhaseState.CAUTION:
            self._vls.a = False
            self._vls.b = True
            self._vls.c = False
            pa = True
            pc = False
        elif self._state == PhaseState.GO or self._state == PhaseState.EXTEND:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = True
            pc = False
        elif self._state == PhaseState.PCLR:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = flasher
            pc = False
        elif self._state == PhaseState.WALK:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = False
            pc = True

        if self._pls is not None:
            self._pls.a = pa
            self._pls.b = pb
            self._pls.c = pc

        return changed

    def __repr__(self):
        return f'<{self.getTag()} {self.state.name} {self.time_upper: 05.1f}' \
               f' {self.time_lower: 05.1f} V:{str(self._vls)} P:' \
               f'{str(self._pls) if self._pls is not None else "DISABLED"}>'


def phases_by_number(phases: Iterable[ControlPhase],
                     id_: int) -> Optional[ControlPhase]:
    for phase in phases:
        if phase.id == id_:
            return phase
    return None


def ring_by_phase(rings: Iterable[Ring],
                  phase: ControlPhase) -> Ring:
    """
    Get Ring instance by associated ControlPhase instance
    """
    assert isinstance(phase, ControlPhase)
    for r in rings:
        if phase.id in r:
            return r

    raise RuntimeError(f'Failed to get ring by {phase.getTag()}')


def barrier_by_phase(barriers: Iterable[Barrier],
                     phase: ControlPhase) -> Barrier:
    """
    Get Barrier instance by associated ControlPhase instance
    """
    assert isinstance(phase, ControlPhase)
    for b in barriers:
        if phase.id in b:
            return b

    raise RuntimeError(f'Failed to get barrier by {phase.getTag()}')


def does_phase_conflict(rings: Iterable[Ring],
                        barriers: Iterable[Barrier],
                        a: ControlPhase,
                        b: ControlPhase) -> bool:
    """
    Check if two phases conflict based on Ring, Barrier and defined friend
    channels.

    :param rings: Rings iterable
    :param barriers: Barriers iterable
    :param a: ControlPhase to compare against
    :param b: Other ControlPhase to compare
    :return: True if conflict
    """
    if a == b:
        raise RuntimeError('conflict check on the same phase object')

    # verify ControlPhase b is not in the same ring
    if b.id in ring_by_phase(rings, a):
        return True

    # verify ControlPhase b is in ControlPhase a's barrier group
    if b.id not in barrier_by_phase(barriers, a):
        return True

    # todo: consider FYA-enabled phases conflicts for a non-FYA phase

    return False


def phase_partner_column(barriers: Iterable[Barrier],
                         phase: ControlPhase) -> int:
    """
    Get ControlPhase ID that is positioned above/below to ControlPhase a within
    the ring-and-barrier model.

    :param barriers: Barriers
    :param phase: primary ControlPhase
    :return: return a ControlPhase ID
    """
    barrier = barrier_by_phase(barriers, phase)
    phase_index = barrier.index(phase.id)
    half = len(barrier) // 2

    if phase_index < half:
        return barrier[phase_index + 2]
    else:
        return barrier[phase_index - 2]


def phase_partner_diagonal(barriers: Iterable[Barrier],
                           phase: ControlPhase) -> int:
    """
    Get ControlPhase ID that is positioned diagonal to ControlPhase a within the
    ring-and-barrier model.

    :param barriers: Barriers
    :param phase: primary ControlPhase
    :return: return a ControlPhase ID
    """
    barrier = barrier_by_phase(barriers, phase)
    phase_index = barrier.index(phase.id)

    if phase_index == 0:
        return barrier[-1]
    elif phase_index == 1:
        return barrier[2]
    elif phase_index == 2:
        return barrier[1]
    elif phase_index == 3:
        return barrier[0]

    raise RuntimeError('failed to find diagonal partner')


def get_phase_partner(barriers: Iterable[Barrier],
                      phases: Iterable[ControlPhase],
                      active: ControlPhase,
                      idle: bool) -> Optional[ControlPhase]:
    col_phase_id = phase_partner_column(barriers,
                                        active)
    col_phase = phases_by_number(phases, col_phase_id)
    diag_phase_id = phase_partner_diagonal(barriers,
                                           active)
    diag_phase = phases_by_number(phases, diag_phase_id)
    order = [col_phase, diag_phase]

    if idle:
        order = [diag_phase, col_phase]

    for phase in order:
        if phase is not None:
            if phase.ready:
                return phase

    return None


class ControlCall(Tickable, Identifiable):

    @property
    def target(self) -> ControlPhase:
        return self._target

    @property
    def ped_service(self):
        return self._ped_service

    @property
    def age(self) -> float:
        return self._age

    def __init__(self,
                 tick_size: int,
                 id_: int,
                 target: ControlPhase,
                 ped_service: bool,
                 age: Optional[float] = None):
        Tickable.__init__(self, tick_size)
        Identifiable.__init__(self, id_)
        self._target = target
        self._ped_service = ped_service
        self._age: float = age or 0.0

    def tick(self):
        self._age += self.tick_size

    def __lt__(self, other):
        if isinstance(other, ControlCall):
            return self._age < other.age
        return False

    def __repr__(self):
        return f'<{self.getTag()} {self.target.getTag()} A:{self._age:0>5.2f}>'


def call_count_alike(calls: Iterable[ControlCall], call: ControlCall) -> int:
    """Count calls with the same target."""
    count = 0
    for other in calls:
        if other.target == call.target:
            count += 1
    return count


def call_phases(calls: List[ControlCall]) -> Set[ControlPhase]:
    return set([c.target for c in calls])


class CallCollection:
    LOCK_TIMEOUT = 0.15

    @property
    def phases(self) -> Set[ControlPhase]:
        return call_phases(self._calls)

    @property
    def tuple(self):
        return tuple(self._calls)

    def __init__(self,
                 weights: Optional[Dict[str, int]] = None,
                 rings: Optional[Iterable[Ring]] = None,
                 barriers: Optional[Iterable[Barrier]] = None,
                 max_age: Optional[float] = None,
                 initial: Optional[Iterable[ControlCall]] = None):
        self._calls: List[ControlCall] = []
        self._lock = Lock()
        self.weights = weights
        self.rings = rings
        self.barriers = barriers
        self.max_age = max_age

        if initial:
            for item in initial:
                self.add(item)

    def _customSortFunc(self,
                        left: ControlCall,
                        right: ControlCall,
                        active_barrier: Optional[Barrier],
                        saturated: bool) -> int:
        """
        Custom-sort calls by the following rules:

        - Calls are weighted by current age. The older, the higher the priority.
        - Calls in the current barrier are optionally given an advantage.
        - Calls with duplicates are given advantage based on factor.
        - During call saturation, the ControlPhase ID acts as tiebreaker.

        :param left: ControlCall comparator on the left
        :param right: ControlCall comparator on the right
        :return: 0 for equality, < 0 for left, > 0 for right.
        """
        weight = 0

        # prioritize calls by age
        weight -= round(left.age, FLOAT_ROUND_PLACES)
        weight += round(right.age, FLOAT_ROUND_PLACES)

        duplicate_factor = 1
        if self.weights is not None:
            duplicate_factor = self.weights.get('duplicate-factor')
            active_barrier_weight = self.weights.get('active-barrier')
            # prioritize calls within the active barrier, if set
            if active_barrier_weight is not None:
                lb = barrier_by_phase(self.barriers, left.target)
                rb = barrier_by_phase(self.barriers, right.target)
                if active_barrier is not None and lb != rb:
                    if lb == active_barrier:
                        weight -= active_barrier_weight
                    elif rb == active_barrier:
                        weight += active_barrier_weight

        # prioritize by duplicate count * factor
        weight -= call_count_alike(self._calls, left) * duplicate_factor
        weight += call_count_alike(self._calls, right) * duplicate_factor

        if saturated:
            # prioritize by literal sequence ID
            weight += left.target.id
            weight -= right.target.id

        return weight

    def sorted(self,
               active_barrier: Optional[Barrier],
               saturated: bool) -> 'CallCollection':
        self._acquire()
        rv = sorted(self._calls, key=cmp_key_args(self._customSortFunc,
                                                  active_barrier,
                                                  saturated))
        self._release()
        return CallCollection(weights=self.weights,
                              rings=self.rings,
                              barriers=self.barriers,
                              max_age=self.max_age,
                              initial=rv)

    def add(self, call: ControlCall) -> None:
        self._acquire()
        self._calls.append(call)
        self._release()

    def remove(self, o: Union[ControlCall, ControlPhase]) -> int:
        self._acquire()
        if isinstance(o, ControlCall):
            try:
                self._calls.remove(o)
                count = 1
            except ValueError:
                count = 0
        elif isinstance(o, ControlPhase):
            to_remove = []
            for call in self._calls:
                if call.target == o:
                    to_remove.append(call)
            for call in to_remove:
                self._calls.remove(call)
            count = len(to_remove)
        else:
            raise TypeError()
        self._release()
        return count

    def prune(self):
        self._acquire()
        old = []
        for call in self._calls:
            if round(call.age, FLOAT_ROUND_PLACES) > self.max_age:
                old.append(call)
        for call in old:
            self.remove(call)
        self._release()

    def filter(self, by: Union[ControlPhase,
                               Iterable[ControlPhase]]) -> List[ControlCall]:
        self._acquire()
        if isinstance(by, ControlPhase):
            phases = [by]
        elif isinstance(by, Iterable):
            phases = by
        else:
            raise TypeError()

        results = []
        for call in self._calls:
            if call.target in phases:
                results.append(call)
        self._release()
        return results

    def tick(self):
        self._acquire()
        for call in self._calls:
            call.tick()
        self._release()

    def _acquire(self):
        if not self._lock.acquire(blocking=True, timeout=self.LOCK_TIMEOUT):
            raise RuntimeError('failed to acquire call lock in time')

    def _release(self):
        self._lock.release()

    def __getitem__(self, index):
        self._acquire()
        rv = self._calls[index]
        self._release()
        return rv

    def __len__(self):
        return len(self._calls)
