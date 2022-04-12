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
from utils import condText, fieldRepr, shortEnumName
from timing import SecondTimer, MillisecondTimer, seconds
from typing import Dict, List, FrozenSet
from dataclasses import dataclass


class IntervalType(IntEnum):
    STOP = 0
    CAUTION = 1
    PED_CLEAR = 2
    GO = 3
    FYA = 4


def getDefaultTimeIntervalMap(value=None) -> Dict[IntervalType, int]:
    mapped = {}

    for it in IntervalType:
        mapped.update({it: value or 0})

    return mapped


REST_INTERVALS = [
    IntervalType.STOP,
    IntervalType.GO,
    IntervalType.FYA
]

MOVEMENT_INTERVALS = [
    IntervalType.CAUTION,
    IntervalType.PED_CLEAR,
    IntervalType.GO,
    IntervalType.FYA
]


class FlashMode(IntEnum):
    DARK = 0
    RED = 1
    YELLOW = 2


class FlasherSource(IntEnum):
    A = 1
    B = 2


class ChannelMode(IntEnum):
    DISABLED = 0
    VEHICLE = 1
    PEDESTRIAN = 2
    FYA = 3


class OperationMode(IntEnum):
    DARK = 0
    CET = 1  # Control entrance transition
    CXT = 2  # Control exit transition
    LS_FLASH = 3
    NORMAL = 4


class InputAction(IntEnum):
    NOTHING = 0
    CALL = 1
    PREEMPTION = 2
    LS_FLASH = 3
    FYA_INHIBIT = 4
    PED_CLEARANCE_INHIBIT = 5
    STOP_RUNNING = 6


@dataclass
class IdentifiableBase:
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


class Channel(IdentifiableBase):

    @property
    def remaining(self) -> int:
        if self.current_goal > 0:
            return abs(self.current_goal - seconds())
        return 0

    @property
    def is_timing(self):
        return self.current_goal != 0 and self.remaining >= 0

    @property
    def has_movement(self):
        return self.state in MOVEMENT_INTERVALS

    @property
    def is_ready(self):
        return not self.has_movement and not self.is_timing

    @property
    def is_resting(self):
        return self.state in REST_INTERVALS and not self.is_timing

    @property
    def current_goal(self):
        return self.markers[self.state]

    def __init__(self,
                 channel_id: int,
                 mode: ChannelMode,
                 flash_mode: FlashMode,
                 default_state: IntervalType):
        self.id = channel_id
        self.mode = mode
        self.flash_mode = flash_mode
        self.state = default_state
        self.markers = getDefaultTimeIntervalMap()
        self.ism = 0

        # convenience property exclusively for monitor
        self.duration = 0

        self.dark = True
        self.a = False
        self.b = False
        self.c = False

    def __repr__(self):
        attrib = []

        if self.is_ready:
            attrib.append('READY')

        if self.is_resting:
            attrib.append('RESTING')

        if self.is_timing:
            attrib.append('TIMING')

        field_repr = fieldRepr(self.a, self.b, self.c)
        return f'<{self.getTag()} {shortEnumName(self.mode)} {field_repr} ' \
               f'{self.state.name} {" ".join(attrib)}' \
               f'{condText(self.remaining, prefix=" R", postfix="s")}>'


@dataclass(frozen=True)
class FrozenChannelState(FrozenIdentifiableBase):
    a: bool
    b: bool
    c: bool
    duration: int
    interval_time: int
    calls: int


def getDefaultChannelState(fm: FlashMode):
    if fm.RED:
        return IntervalType.STOP
    elif fm.YELLOW:
        return IntervalType.CAUTION
    raise NotImplementedError()


@dataclass(frozen=True)
class Phase(FrozenIdentifiableBase):
    @property
    def is_timing(self):
        for ch in self.channels:
            if ch.is_timing:
                return True
        return False

    @property
    def is_ready(self):
        for ch in self.channels:
            if not ch.is_ready:
                return False
        return True

    @property
    def is_resting(self):
        for ch in self.channels:
            if ch.is_resting:
                return True
        return False

    @property
    def red_clearance(self):
        return self.rc_timer.getRemaining() > 0

    channels: FrozenSet[Channel]
    rc_timer: MillisecondTimer

    def __repr__(self):
        attrib = []

        if self.is_ready:
            attrib.append('READY')

        if self.is_resting:
            attrib.append('RESTING')

        if self.is_timing:
            attrib.append('TIMING')

        return f'<{self.getTag()} {" ".join(attrib)}>'


@dataclass
class Call(IdentifiableBase):
    target: Phase
    age: SecondTimer
    system: bool
    reoccurring: bool = False

    def __lt__(self, other):
        if isinstance(other, Call):
            return self.age < other.age
        return False

    def __repr__(self):
        return f'<Call #{self.id:02d} PH{self.target.id:02d} ' \
               f'A{self.age.getDelta():04d}>'


class InputActivation(IntEnum):
    LOW = 0
    HIGH = 1
    RISING = 2
    FALLING = 3


@dataclass
class Input:
    ignore: bool
    active: InputActivation
    action: InputAction
    targets: List[Phase]

    # update states and changed together
    state: bool = False
    last_state: bool = False
    changed: bool = False

    def activated(self) -> bool:
        if self.active == InputActivation.LOW:
            if not self.state and not self.last_state:
                return True
        elif self.active == InputActivation.HIGH:
            if self.state and self.last_state:
                return True
        elif self.active == InputActivation.RISING:
            if self.state and not self.last_state:
                return True
        elif self.active == InputActivation.FALLING:
            if not self.state and self.last_state:
                return True
        return False

    def __repr__(self):
        return f'<Input {self.active.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}' \
               f'{" CHANGED" if self.changed else ""}>'
