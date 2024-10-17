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


CYCLER_SERVICE_POLL_RATE = 0.1
PHASE_SERVICE_POLL_RATE = 0.1


class FieldOutputState(IntEnum):
    OFF                 = 0
    ON                  = 1
    FLASHING            = 2
    INHERIT             = 3
    

class SignalType(IntEnum):
    GENERIC             = 0
    VEHICLE             = 1
    PEDESTRIAN          = 2
    
    
class TrafficMovement(IntEnum):
    THRU                = 0
    PROTECTED_TURN      = 1
    PERMISSIVE_TURN     = 2


class SignalState(IntEnum):
    DARK                = 0
    STOP                = 1
    CAUTION             = 2
    EXTEND              = 3
    GO                  = 4
    FYA                 = 5
    LS_FLASH            = 6


FYA_SIGNAL_ACTIVATION_STATES = [SignalState.GO]
FYA_SIGNAL_DEACTIVATION_STATES = [SignalState.CAUTION, SignalState.STOP]


class FYAState(IntFlag):
    INACTIVE            = 0
    ACTIVE              = 1
    TERMINATING         = 2
    SERVICE             = 4
    CONTINUE            = 8


class ExtendMode(IntEnum):
    OFF                 = 0
    MINIMUM_SKIP        = 1
    MAXIMUM_SKIP        = 2


class RecallMode(IntEnum):
    OFF                 = 0
    MINIMUM             = 1
    MAXIMUM             = 2


class ServiceConditions(IntFlag):
    UNSET               = 0
    WITH_DEMAND         = 1
    WITH_VEHICLE        = 2
    WITH_ANY            = 4
    LEADING_ONLY        = 8
    LAGGING_ONLY        = 16
    NEVER               = 32


class ServiceModifiers(IntFlag):
    UNSET               = 0
    BEFORE_VEHICLE      = 1


class PhaseCyclerMode(IntEnum):
    PAUSE               = 0
    SEQUENTIAL          = 1
    CONCURRENT          = 2


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
