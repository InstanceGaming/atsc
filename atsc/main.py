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
from atsc import constants, configfile
from typing import TextIO, Optional
from pathlib import Path
from datetime import datetime as dt
from threading import main_thread
from jacob.logging import CustomLevel, setup_logger
from atsc.controller import Controller
from jacob.filesystem import fix_path, fix_paths
from jacob.datetime.timing import seconds
from jacob.datetime.formatting import format_dhms


VERSION = '2.0.1'
PID_FILE = 'atsc.pid'
WELCOME_MSG = f'Actuated Traffic Signal Controller v{VERSION} by Jacob Jewett'
CONFIG_SCHEMA_CHECK = True
CONFIG_LOGIC_CHECK = True
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

logger = loguru.logger
DEFAULT_LEVELS = 'debug,warning;stderr=error,critical;file=info,critical'


def get_cli_args():
    parser = argparse.ArgumentParser(description=WELCOME_MSG)
    parser.add_argument('--pid',
                        dest='pid_path',
                        help='PID file path.')
    parser.add_argument('-l', '--levels',
                        dest='log_levels',
                        default=DEFAULT_LEVELS,
                        help='Specify logging levels.')
    parser.add_argument('-L', '--log',
                        dest='log_file',
                        help='Specify log file.')
    parser.add_argument('-t', '--time-base',
                        type=float,
                        dest='time_base',
                        help='Specify a alternate loop speed.')
    parser.add_argument(dest='config_paths',
                        nargs='+',
                        metavar='FILENAMES',
                        help='Path to one or more ATSC config files. Their '
                             'contents will be merged.')
    return vars(parser.parse_args())


def generate_pid(path: Optional[Path]) -> Optional[TextIO]:
    pid = os.getpid()
    file = None
    
    if path is None:
        logger.info(f'PID {pid} (file disabled)')
    else:
        try:
            file = open(path, 'x')
        except FileExistsError:
            logger.error(f'Already running ({path})')
            exit(4)
        except OSError as e:
            logger.error(f'Could not create PID file at {path}: {str(e)}')
            exit(5)
        
        file.write(str(pid))
        file.flush()
        
        logger.info(f'PID {pid} ({path})')
    
    return file


def cleanup_pid(path: Optional[Path], pid_file: Optional[TextIO]):
    if path is not None:
        try:
            if not pid_file.closed:
                pid_file.close()
            os.remove(path)
        except OSError as e:
            logger.error(f'Could not remove PID file at {path}: {str(e)}')
            exit(6)
        
        logger.info(f'Removed PID file at {path}')


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
    
    pid_path = fix_path(cla.get('pid_path'))
    config_paths = fix_paths(cla['config_paths'])
    
    logger.info(WELCOME_MSG)
    logger.info(f'Logging levels {levels_notation}')
    
    time_base = cla.get('time_base')
    if time_base:
        if abs(constants.TIME_BASE - time_base) > 0.001:
            logger.warning('Running with an altered time base {}', time_base)
        constants.TIME_BASE = time_base
    
    config_schema_path = configfile.get_config_schema_path()
    
    if not os.path.exists(config_schema_path):
        logger.critical(f'Configuration file schema not found at '
                        f'"{config_schema_path}", exiting; this '
                        f'is a developer issue, NOT a user issue!')
        return 100
    
    schema_validator = configfile.ConfigValidator(config_schema_path)
    
    pid_file = generate_pid(pid_path)
    
    config = None
    try:
        for cp in config_paths:
            cp = os.path.abspath(cp)
            logger.info(f'Configuration ingest from "{cp}"')
        
        if CONFIG_SCHEMA_CHECK:
            logger.debug('Running static validation analysis...')
            config = schema_validator.load(config_paths)
    except configfile.ConfigError as e:
        logger.error('Failed to load configuration file(s): '
                     f'{e.generic_error.name}')
        if len(e.details) > 0:
            logger.debug('Details:')
            for k, v in e.details.items():
                logger.debug(f'- {k} = {v}')
        return 10
    
    if CONFIG_LOGIC_CHECK:
        logger.debug('Running dynamic validation analysis...')
        complaint = configfile.validate_config_dynamic(config, schema_validator.version)
        
        if complaint:
            logger.error('Configuration failed dynamic inspection tests: '
                         f'{complaint}')
            return 11
        else:
            logger.debug('Dynamic validation analysis passed')
    
    start_marker = seconds()
    logger.info(dt.now().strftime('Started at %b %d %Y %I:%M %p'))
    
    controller = Controller(config)
    try:
        controller.run()
    except KeyboardInterrupt:
        controller.shutdown()
    
    run_delta = seconds() - start_marker
    ed, eh, em, es = format_dhms(run_delta)
    logger.info(f'Runtime of {ed} days, {eh} hours, {em} minutes and {es} seconds')
    
    cleanup_pid(pid_path, pid_file)


if __name__ == '__main__':
    main_thread().name = 'Main'
    exit(run())
else:
    print('This file must be ran directly.')
    exit(1)
