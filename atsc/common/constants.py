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
from enum import IntEnum
from jacob.logging import CustomLevel


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


DEFAULT_LEVELS = 'info,warning;stderr=error,critical;file=info,critical'
DEBUG_LEVELS = 'verbose,warning;stderr=error,critical;file=debug,critical'


class ExitCode(IntEnum):
    DIRECT_CALL_REQUIRED = 1
    LOG_LEVEL_PARSE_FAIL = 2
    LOG_FILE_STRUCTURE_FAIL = 3
    LOG_FACILITY_FAIL = 4
    PID_CREATE_FAIL = 5
    PID_EXISTS = 6
    PID_REMOVE_FAIL = 7
