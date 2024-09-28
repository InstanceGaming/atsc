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
from enum import Enum, IntEnum, auto


class FieldOutputState(IntEnum):
    OFF = 0
    ON = 1
    FLASHING = 2
    INHERIT = 3
    

class SignalType(IntEnum):
    GENERIC         = 0
    VEHICLE         = 10
    PEDESTRIAN      = 20


class SignalState(IntEnum):
    STOP            = 10
    CAUTION         = 20
    EXTEND          = 25
    GO              = 30
    FYA             = 40
    LS_FLASH        = 50


class RecallState(IntEnum):
    NORMAL = 0
    MINIMUM = 1
    MAXIMUM = 2


class RecallMode(IntEnum):
    OFF = 0
    MINIMUM = 1
    MAXIMUM = 2


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
