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
from enum import Enum, auto


DEFAULT_APP_STYLESHEET_PATH = 'tui/css/app.tcss'
POLL_RATE = 0.1


if os.getenv('LOOSEN_RPC_WATCHDOG'):
    RPC_CALL_DEADLINE_POLL = 3600.0
    RPC_CALL_TIMEOUT = 3600.0
else:
    RPC_CALL_DEADLINE_POLL = 0.4
    RPC_CALL_TIMEOUT = 0.4


class FieldOutputStyle(Enum):
    GENERIC = auto()
    STOP = auto()
    CAUTION = auto()
    GO = auto()
    DONT_WALK = auto()
    WALK = auto()
