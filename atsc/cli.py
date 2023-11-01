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
import os
import sys
import loguru
import argparse
from jacob import logging
from atsc.controller import Controller
from jacob.filesystem import fix_path, fix_paths
from atsc.common.constants import ExitCode


DEFAULT_LOG_LEVELS = 'INFO,stderr=ERROR,file=WARNING'


def get_default_pid_path():
    return os.path.join(os.getcwd(), 'atsc.pid')


def get_cli_args():
    root = argparse.ArgumentParser(description='Actuated Traffic Signal SimpleController CLI tool.')
    subparsers = root.add_subparsers(dest='subsystem')
    
    root.add_argument('-L', '--levels',
                      type=str,
                      dest='log_levels',
                      default=DEFAULT_LOG_LEVELS,
                      help='Define logging levels.')
    
    root.add_argument('-l', '--log',
                      type=str,
                      dest='log_file',
                      default=None,
                      help='Define log file path.')
    
    control = subparsers.add_parser('control', description='Control server.')
    
    default_pid_path = get_default_pid_path()
    control.add_argument('--pid',
                         dest='pid_file',
                         const=None,
                         default=default_pid_path,
                         help=f'Define PID file location. Default is "{default_pid_path}".')
    
    control.add_argument(dest='config_files',
                         nargs='+',
                         help='Path to one or more ATSC controller config files whose '
                              'contents will be merged.')
    
    fieldbus = subparsers.add_parser('bus', description='Field bus server.')
    networking = subparsers.add_parser('net', description='Network server.')
    
    return vars(root.parse_args())


def run():
    cla = get_cli_args()
    
    try:
        log_levels = logging.parse_log_level_shorthand(loguru.logger, cla['log_levels'])
    except (KeyError, ValueError) as e:
        print(f'ERROR: failed to parse log level argument ({str(e)})', file=sys.stderr)
        exit(ExitCode.LOG_LEVEL_PARSE_FAIL)
    
    log_file = fix_path(cla.get('log_file'))
    logger = logging.setup_logger(log_levels, log_file)
    
    # loguru provides a global logger variable ease of use in other files.
    # overwrite it now to ensure the global logger is configured as desired.
    loguru.logger = logger
    
    pid_path = fix_path(cla['pid_path'])
    config_names = fix_paths(cla['config_names'])
    
    # the logger is still passed to daemon instance as it will bind context vars
    Controller(logger, pid_path=pid_path).start()


if __name__ == '__main__':
    run()
else:
    print('This file must be ran directly.')
    exit(1)
