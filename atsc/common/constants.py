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
from enum import IntEnum, Enum, auto
from jacob.logging import CustomLevel


RPC_ADDRESS = 'localhost'
RPC_PORT = 7833
FLOAT_PRECISION_TIME = 1
DEFAULT_TICK_RATE = 10.0
DEFAULT_TICK_SCALE = 1.0
DAEMON_SHUTDOWN_TIMEOUT = 5.0
DEFAULT_LEVELS = 'info,warning;stderr=error;file=info,error'
DEBUG_LEVELS = 'verbose,warning;stderr=error;file=debug,error'


CUSTOM_LOG_LEVELS = {
    CustomLevel(10, 'bus_tx'),
    CustomLevel(11, 'bus_rx'),
    CustomLevel(12, 'bus'),
    CustomLevel(20, 'net'),
    CustomLevel(25, 'fields'),
    CustomLevel(35, 'verbose'),
    CustomLevel(40, 'debug'),
    CustomLevel(50, 'info'),
    CustomLevel(90, 'warning'),
    CustomLevel(100, 'error'),
    CustomLevel(200, 'critical')
}


class ExitCode(IntEnum):
    OK = 0
    DIRECT_CALL_REQUIRED = 1
    LOG_LEVEL_PARSE_FAIL = 2
    LOG_FILE_STRUCTURE_FAIL = 3
    LOG_FACILITY_FAIL = 4
    PID_CREATE_FAIL = 5
    PID_EXISTS = 6
    PID_REMOVE_FAIL = 7
    RPC_BIND_FAILED = 8


class EdgeType(Enum):
    RISING = auto()
    FALLING = auto()
