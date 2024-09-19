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
from jacob.logging import CustomLevel


LOGGING_LEVELS = {
    CustomLevel(3, 'FIELD', '<d>'),
    CustomLevel(6, 'TIMING', '<d>'),
    CustomLevel(7, 'VERB', '<c>')
}


SHUTDOWN_POLL_RATE = 0.1
ABSOLUTE_MAXIMUM_RATE = 100.0
MINIMUM_INPUTS_RATE = 1.0
MAXIMUM_INPUTS_RATE = 40.0
MINIMUM_BUS_RATE = 1.0
MAXIMUM_BUS_RATE = 20.0
MINIMUM_NETWORK_RATE = 1.0
MAXIMUM_NETWORK_RATE = 40.0
MINIMUM_FLASH_RATE = 54.0
MAXIMUM_FLASH_RATE = 66.0


class FlashChannel(Enum):
    RED = auto()
    YELLOW = auto()


class OperationMode(Enum):
    DARK = auto()
    CET = auto()
    CXT = auto()
    LS_FLASH = auto()
    NORMAL = auto()


class FieldState(Enum):
    OFF = auto()
    ON = auto()
    FLASHING = auto()
    INHERIT = auto()


class SignalState(IntEnum):
    STOP = 1
    CAUTION = 2
    GO = 3
    FYA = 4
    LS_FLASH = 5
    

class PhaseCyclerMode(Enum):
    PAUSE = auto()
    SEQUENTIAL = auto()
    CONCURRENT = auto()


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
