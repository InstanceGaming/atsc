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
