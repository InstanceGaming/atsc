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
import loguru
import argparse
from jacob.logging import RECOMMENDED_LEVELS, setup_logger
from atsc.common.constants import CUSTOM_LOG_LEVELS
from atsc.common.structs import Context
from atsc.controller.implementations import Controller
from jacob.filesystem import fix_path


logger = loguru.logger


def get_default_pid_path():
    return os.path.join(os.getcwd(), 'atsc.pid')


def get_cli_args():
    root = argparse.ArgumentParser(description='Actuated Traffic Signal SimpleController CLI tool.')
    subparsers = root.add_subparsers(dest='subsystem', required=True)
    
    root.add_argument('-L', '--levels',
                      type=str,
                      dest='log_levels',
                      default=RECOMMENDED_LEVELS,
                      help='Define logging levels.')
    
    root.add_argument('-l', '--log',
                      type=str,
                      dest='log_file',
                      default=None,
                      help='Define log file path.')
    
    control = subparsers.add_parser('control', description='Control server.')
    
    control.add_argument('--pid',
                         dest='pid_file',
                         help=f'Use PID file at this path.')
    
    # control.add_argument(dest='config_files',
    #                      nargs='+',
    #                      help='Path to one or more ATSC controller config files whose '
    #                           'contents will be merged.')
    
    fieldbus = subparsers.add_parser('bus', description='Field bus server.')
    networking = subparsers.add_parser('net', description='Network server.')
    
    return vars(root.parse_args())


def run():
    cla = get_cli_args()
    
    log_file = fix_path(cla.get('log_file'))
    levels_notation = cla['log_levels']
    try:
        loguru.logger = setup_logger(levels_notation,
                                     custom_levels=CUSTOM_LOG_LEVELS,
                                     log_file=log_file)
    except ValueError as e:
        print(f'Malformed logging level specification "{levels_notation}":', e)
        return 5
    
    subsystem = cla['subsystem']
    match subsystem.lower():
        case 'control':
            pid_path = fix_path(cla['pid_file'])
            # config_names = fix_paths(cla['config_names'])
            
            context = Context(10.0, 1.0)
            
            # the logger is still passed to daemon instance as it will bind context vars
            Controller(context, pid_file=pid_path).start()


if __name__ == '__main__':
    run()
else:
    print('This file must be ran directly.')
    exit(1)
