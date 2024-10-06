#  Copyright 2024 Jacob Jewett
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
from enum import Enum, IntEnum, IntFlag, auto


class FieldOutputState(IntEnum):
    OFF = 0
    ON = 1
    FLASHING = 2
    INHERIT = 3
    

class SignalType(IntEnum):
    GENERIC         = 0
    VEHICLE         = 1
    PEDESTRIAN      = 2
    
    
class TrafficMovement(IntEnum):
    THRU            = 0
    PROTECTED_TURN  = 1
    PERMISSIVE_TURN = 2


class SignalState(IntEnum):
    DARK            = 0
    STOP            = 1
    CAUTION         = 2
    EXTEND          = 3
    GO              = 4
    FYA             = 5
    LS_FLASH        = 6


class RecallMode(IntEnum):
    OFF = 0
    MINIMUM = 1
    MAXIMUM = 2


class ServiceConditions(IntFlag):
    UNSET               = 0b00000000
    IGNORE_ONCE         = 0b00000010
    WITH_VEHICLE        = 0b00000100
    WITH_PEDESTRIAN     = 0b00001000
    WITH_ANY            = 0b00010000
    WITH_DEMAND         = 0b00000001


class ServiceModifiers(IntFlag):
    UNSET               = 0b00000000
    BEFORE_VEHICLE      = 0b00000001


class PhaseCyclerMode(IntEnum):
    PAUSE = 0
    SEQUENTIAL = 1
    CONCURRENT = 2


class CallSource(Enum):
    UNKNOWN = auto()
    SYSTEM = auto()
    RECALL = auto()
    FIELDBUS = auto()
    NETWORK = auto()


class InputAction(Enum):
    NOTHING = auto()
    CALL = auto()
    DETECT = auto()
    PREEMPTION = auto()
    TIME_FREEZE = auto()
    
    PED_CLEAR_INHIBIT = auto()
    FYA_INHIBIT = auto()
    CALL_INHIBIT = auto()
    REDUCE_INHIBIT = auto()
    
    MODE_DARK = auto()
    MODE_NORMAL = auto()
    MODE_LS_FLASH = auto()


class InputActivation(Enum):
    LOW = auto()
    HIGH = auto()
    RISING = auto()
    FALLING = auto()
