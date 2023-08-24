#  Copyright 2022 Jacob Jewett
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
import argparse
from threading import main_thread
import loguru
from atsc.constants import get_default_pid_path, ExitCode
from atsc.logging import parse_log_level_shorthand, setup_logger
from atsc.programs import Daemon
from atsc.utils import fix_path, fix_paths


def get_cli_args():
    default_pid_path = get_default_pid_path()
    parser = argparse.ArgumentParser(description='Actuated traffic controller.')
    parser.add_argument('--pid',
                        dest='pid_path',
                        const=None,
                        default=default_pid_path,
                        metavar='PID_PATH',
                        help=f'Path to PID file. Default is "{default_pid_path}".')
    parser.add_argument('-L', '--log-levels',
                        type=str,
                        dest='log_levels',
                        default=None,
                        help='Set log levels.')
    parser.add_argument('-l', '--log',
                        type=str,
                        dest='log_file',
                        default=None,
                        help='Set log file output path.')
    parser.add_argument(dest='config_paths',
                        nargs='+',
                        metavar='config_names',
                        help='Path to one or more ATSC config files. Their '
                             'contents will be merged.')
    return parser.parse_args()


def run():
    cla = get_cli_args()
    
    # -L trace,stderr=error,file=warn
    
    try:
        log_levels = parse_log_level_shorthand(cla.log_levels)
    except (KeyError, ValueError) as e:
        print(f'ERROR: failed to parse log level argument ({str(e)})', file=sys.stderr)
        exit(ExitCode.LOG_LEVEL_PARSE_FAIL)
    
    log_file = fix_path(cla.log_file)
    logger = setup_logger(log_levels, log_file)
    
    # loguru provides a global logger variable ease of use in other files.
    # overwrite it now to ensure the global logger is configured as desired.
    loguru.logger = logger

    pid_path = fix_path(cla.pid_path)
    config_names = fix_paths(cla.config_names)
    
    # the logger is still passed to daemon instance as it will bind context vars
    Daemon(logger, pid_path=pid_path).start()


if __name__ == '__main__':
    main_thread().name = 'Main'
    run()
else:
    print('This file must be ran directly.')
    exit(1)
