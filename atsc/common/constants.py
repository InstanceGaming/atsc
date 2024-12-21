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
import os
from enum import Enum, IntEnum, auto


RPC_ADDRESS = 'localhost'
RPC_PORT = 7833
FLOAT_PRECISION_TIME = 1
DAEMON_SHUTDOWN_TIMEOUT = 5.0


if os.getenv('LOOSEN_RPC_WATCHDOG'):
    RPC_CALL_DEADLINE_POLL = None
    RPC_CALL_TIMEOUT = None
else:
    RPC_CALL_DEADLINE_POLL = 10.0
    RPC_CALL_TIMEOUT = 10.0


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
