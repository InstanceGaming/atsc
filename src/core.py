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
from enum import IntEnum
from typing import Dict, List, Optional
from dataclasses import dataclass


class IdentifiableBase:

    @property
    def id(self) -> int:
        return self._id

    def __init__(self, id_: int):
        self._id = id_

    def __hash__(self) -> int:
        return self._id

    def __eq__(self, other) -> bool:
        if other is None:
            return False
        return self._id == other.id

    def __lt__(self, other) -> bool:
        return self._id < other.id

    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'

    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


@dataclass(frozen=True)
class FrozenIdentifiableBase:
    id: int

    def __hash__(self) -> int:
        return self.id

    def __eq__(self, other):
        return self.id == other.id

    def __lt__(self, other):
        return self.id < other.id

    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'

    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class FlashMode(IntEnum):
    RED = 1
    YELLOW = 2


class TrafficType(IntEnum):
    VEHICLE = 1
    PEDESTRIAN = 2


class OperationMode(IntEnum):
    DARK = 0
    CET = 1  # Control entrance transition
    CXT = 2  # Control exit transition
    LS_FLASH = 3
    NORMAL = 4


class LoadSwitch(IdentifiableBase):

    def __init__(self, id_: int):
        super().__init__(id_)
        self.a = False
        self.b = False
        self.c = False


class PhaseState(IntEnum):
    STOP = 0
    MIN_STOP = 2
    RCLR = 4
    CAUTION = 6
    EXTEND = 8
    GO = 10
    PCLR = 12
    WALK = 14
    MAX_GO = 32


PHASE_REST_STATES = [
    PhaseState.STOP,
    PhaseState.GO,
    PhaseState.WALK,
]

PHASE_TIMED_STATES = [
    PhaseState.MIN_STOP,
    PhaseState.RCLR,
    PhaseState.CAUTION,
    PhaseState.EXTEND,
    PhaseState.GO,
    PhaseState.PCLR,
    PhaseState.WALK,
    PhaseState.MAX_GO
]

PHASE_GO_STATES = [
    PhaseState.EXTEND,
    PhaseState.GO,
    PhaseState.PCLR,
    PhaseState.WALK
]


class Phase(IdentifiableBase):
    FYA_LOCAL = -1
    FYA_PED = -2

    @property
    def ped_enabled(self) -> bool:
        return self._pls is not None

    @property
    def ped_service(self) -> bool:
        return not self._ped_inhibit and self.ped_enabled

    @property
    def extend_enabled(self):
        return self._timing[PhaseState.EXTEND] > 0

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
        return self._state.value > 2

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
    def veh_ls(self) -> LoadSwitch:
        return self._vls

    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls

    def _validate_timing(self):
        if self.active:
            raise RuntimeError('Cannot changing timing map while active')
        if self._timing is None:
            raise TypeError('Timing map cannot be None')
        keys = self._timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES):
            raise RuntimeError('Timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('STOP cannot be in timing map')

    def __init__(self,
                 id_: int,
                 time_increment: float,
                 timing: Dict[PhaseState, float],
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 flash_mode: FlashMode = FlashMode.RED,
                 ped_clear_enable: bool = True):
        super().__init__(id_)
        self._increment = time_increment
        self._timing = timing
        self._vls = veh_ls
        self._pls = ped_ls
        self._flash_mode = flash_mode
        self._state: PhaseState = PhaseState.STOP
        self._time_lower: float = 0
        self._time_upper: float = 0
        self._max_time: float = 0
        self._ped_inhibit: bool = True
        self._ped_cycle: bool = False
        self._resting: bool = False
        self.ped_clear_enable: bool = ped_clear_enable

        self._validate_timing()

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
        next_state = force_state or self.getNextState(self.ped_service)
        tv = self._timing.get(next_state, 0.0)

        if tv > 1.0:
            tv -= self._increment

        self._time_upper = tv
        if next_state == PhaseState.STOP:
            self._ped_inhibit = True
            self._ped_cycle = False
            self._max_time = 0
        elif next_state == PhaseState.EXTEND:
            self._time_lower = 0.0
        elif next_state == PhaseState.GO:
            if self._ped_cycle:
                go_time = self._timing[PhaseState.GO]
                walk_time = self._timing[PhaseState.WALK]
                self._time_lower = go_time - walk_time
                if self.ped_clear_enable:
                    self._time_lower -= self._timing[PhaseState.PCLR]
                if self._time_lower < 0:
                    self._time_lower = 0
            else:
                self._time_lower = tv
        else:
            if next_state == PhaseState.WALK:
                self._ped_cycle = True
            self._time_lower = tv
        self._state = next_state

    def changeTiming(self, revised: Dict[PhaseState, float]):
        self._timing = revised
        self._validate_timing()

    def reduce(self):
        if self.extend_active:
            self._time_lower = 0.0
        else:
            raise RuntimeError('Cannot reduce, not extending')

    def activate(self, ped_inhibit: bool = True):
        if self.active:
            raise RuntimeError('Cannot activate active phase')

        self._ped_inhibit = ped_inhibit
        self.update()

    def tick(self,
             total_demand: int,
             flasher: bool) -> bool:
        changed = False
        self._resting = False
        if self.extend_active:
            if self._time_lower >= self._timing[PhaseState.EXTEND]:
                if total_demand > 0:
                    self.update()
                    changed = True
                else:
                    self._resting = True
            else:
                self._time_lower += self._increment
        else:
            if self._state != PhaseState.STOP:
                if self._state in PHASE_GO_STATES:
                    self._max_time += self._increment

                    if self._max_time > self._timing[PhaseState.MAX_GO]:
                        self.update(force_state=PhaseState.CAUTION)

                if self._time_lower > 0:
                    self._time_lower -= self._increment
                    if self._time_lower < 0:
                        self._time_lower = 0
                else:
                    if self._state == PhaseState.WALK:
                        if flasher:
                            self.update()
                            changed = True
                    else:
                        if self.extend_enabled:
                            self.update()
                            changed = True
                        else:
                            if self._state == PhaseState.GO or \
                                    self._state == PhaseState.WALK:
                                if total_demand > 0:
                                    self.update()
                                    changed = True
                                else:
                                    self._resting = True
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
               f' {self.time_lower: 05.1f}>'


@dataclass(frozen=True)
class FrozenPhaseSetup:
    vehicle_ls: int
    ped_ls: int
    flash_mode: FlashMode
    fya_setting: int


class Call(IdentifiableBase):

    @property
    def target(self) -> Phase:
        return self._target

    @property
    def ped_service(self):
        return self._ped_service

    @property
    def age(self) -> float:
        return self._age

    def __init__(self,
                 id_: int,
                 increment: float,
                 target: Phase,
                 ped_service=False):
        super().__init__(id_)
        self._target = target
        self._age: float = 0.0
        self._increment = increment
        self._ped_service = ped_service
        self.duplicates: int = 0

    def tick(self):
        self._age += self._increment

    def __lt__(self, other):
        if isinstance(other, Call):
            return self._age < other.age
        return False

    def __repr__(self):
        return f'<Call #{self._id:02d} A{self._age:0>5.2f}>'


class InputAction(IntEnum):
    NOTHING = 0
    CALL = 1
    DETECT = 2
    PREEMPTION = 3
    TIME_FREEZE = 4

    PED_CLEAR_INHIBIT = 5
    FYA_INHIBIT = 6
    CALL_INHIBIT = 7
    REDUCE_INHIBIT = 8

    MODE_DARK = 9
    MODE_NORMAL = 10
    MODE_LS_FLASH = 11


class InputActivation(IntEnum):
    LOW = 1
    HIGH = 2
    RISING = 3
    FALLING = 4


@dataclass
class Input:
    trigger: InputActivation
    action: InputAction
    targets: List[Phase]

    # update states and changed together
    state: bool = False
    last_state: bool = False
    changed: bool = False

    def activated(self) -> bool:
        if self.trigger == InputActivation.LOW:
            if not self.state and not self.last_state:
                return True
        elif self.trigger == InputActivation.HIGH:
            if self.state and self.last_state:
                return True
        elif self.trigger == InputActivation.RISING:
            if self.state and not self.last_state:
                return True
        elif self.trigger == InputActivation.FALLING:
            if not self.state and self.last_state:
                return True
        return False

    def __repr__(self):
        return f'<Input {self.trigger.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}' \
               f'{" CHANGED" if self.changed else ""}>'
