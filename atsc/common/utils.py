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
import sys
import loguru
from typing import Optional
from pathlib import Path
from jacob.logging import setup_logger as jacob_setup_logger
from atsc.common.constants import CUSTOM_LOG_LEVELS, ExitCode


def get_program_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.parent
    else:
        return Path(__file__).parent.parent.absolute()


def setup_logger(levels_notation, log_file: Optional[Path] = None):
    try:
        loguru.logger = jacob_setup_logger(levels_notation,
                                     custom_levels=CUSTOM_LOG_LEVELS,
                                     log_file=log_file)
    except ValueError as e:
        print(f'Malformed logging level specification "{levels_notation}":', e)
        return ExitCode.LOG_LEVEL_PARSE_FAIL
    return ExitCode.OK
