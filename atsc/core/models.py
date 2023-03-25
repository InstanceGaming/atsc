from enum import IntEnum, IntFlag
from typing import List
from atsc.core.fundemental import Identifiable, IdentifiedCollection
from atsc.utils import format_fields


class ControlMode(IntEnum):
    UNKNOWN = 0
    OFF = 10
    CET = 20
    NORMAL = 30
    CXT = 40
    LS_FLASH = 50


class ControlState(IntFlag):
    TRANSFERRED        = 0x0001  # 00
    IDLE               = 0x0002  # 01
    ACTUATED           = 0x0004  # 02
    SATURATED          = 0x0008  # 03
    TIME_FREEZE        = 0x0010  # 04
    PREEMPTED          = 0x0020  # 05
    GLOBAL_PED_SERVICE = 0x0040  # 06
    GLOBAL_PED_CLEAR   = 0x0080  # 07
    GLOBAL_FYA_ENABLED = 0x0100  # 08
    DEGRADED           = 0x0200  # 09
    FAULTS             = 0x0400  # 10
    FAULTS_LATCHED     = 0x0800  # 11
    DEBUG              = 0x1000  # 12


class LoadSwitch(Identifiable):

    def __init__(self, id_: int):
        super().__init__(id_)
        self.a = False
        self.b = False
        self.c = False

    def __str__(self):
        return format_fields(self.a, self.b, self.c)


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


class PhaseIndexCollection(IdentifiedCollection):

    def __init__(self, id_: int, phases: List[int]):
        for v in phases:
            if not v:
                raise ValueError('invalid phase index')
        super().__init__(id_, initial=phases)


class Ring(PhaseIndexCollection):
    pass


class Barrier(PhaseIndexCollection):
    pass


class Input:

    @property
    def trigger(self):
        return self._trigger

    @property
    def action(self):
        return self._action

    @property
    def targets(self):
        return self._targets

    @property
    def state(self):
        return self._state

    @property
    def last_state(self):
        return self._last_state

    @property
    def changed(self):
        return self._changed

    def __init__(self,
                 trigger: InputActivation,
                 action: InputAction,
                 targets: List[int],
                 state: bool = False,
                 last_state: bool = False,
                 changed: bool = False):
        self._trigger = trigger
        self._action = action
        self._targets = targets
        self._state = state
        self._last_state = last_state
        self._changed = changed

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

    def update(self, s: bool) -> bool:
        last = self._state
        self._state = s
        self._last_state = last
        self._changed = s != last
        return self._changed

    def __repr__(self):
        return f'<Input {self.trigger.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}' \
               f'{" CHANGED" if self.changed else ""}>'
