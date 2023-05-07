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
import utils
import timing
import argparse
import configfile
import asyncio
from datetime import datetime as dt, timedelta
from dateutil import tz
from threading import main_thread
from controller import Controller

from src.logging import parse_log_level_argument, configure_logger


VERSION = '2.1.0'
PID_FILE = 'atsc.pid'
START_BANNER = f'Actuated Traffic Signal Controller v{VERSION} by Jacob Jewett'
CONFIG_SCHEMA_CHECK = True
CONFIG_LOGIC_CHECK = True
logger = loguru.logger


class GracefulExit(SystemExit):
    code = 0


def get_cli_args():
    parser = argparse.ArgumentParser(description=START_BANNER)
    parser.add_argument('--pid',
                        dest='pid_path',
                        default=[PID_FILE],
                        nargs=1,
                        metavar='FILENAME',
                        help='Path to PID file. Default ' + PID_FILE)
    parser.add_argument('--no-pid',
                        action='store_true',
                        dest='pid_disable',
                        help='For development only. Disable use of PID file.')
    parser.add_argument('-v', dest='verbosity', action='count', default=0, help='Increase verbosity the '
                                                                                'more this flag is defined.')
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
                        metavar='FILENAMES',
                        help='Path to one or more ATSC config files. Their '
                             'contents will be merged.')
    return parser.parse_args()


def generate_pid(filepath, disabled):
    pid = os.getpid()
    path = os.path.abspath(filepath)
    file = None
    
    if disabled:
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


def cleanup_pid(file, disabled):
    if not disabled:
        pid_path = os.path.realpath(file.name)
        if not file.closed:
            file.close()
        try:
            os.remove(pid_path)
        except OSError as e:
            logger.error(f'Could not remove PID file at {pid_path}: {str(e)}')
            exit(6)
        
        logger.info(f'Removed PID file at {pid_path}')


def run():
    global logger
    cla = get_cli_args()
    pid_path = cla.pid_path[0]
    pid_disable = cla.pid_disable
    config_paths = cla.config_paths
    
    log_levels_text = cla.log_levels
    try:
        log_levels = parse_log_level_argument(log_levels_text)
    except (KeyError, ValueError) as e:
        print(f'ERROR: failed to parse log level argument ({str(e)})', file=sys.stderr)
        exit(100)
    
    log_file_raw = cla.log_file
    
    stdout_level = log_levels['stdout']
    stderr_level = log_levels['stderr']
    
    try:
        logger = configure_logger(sys.stdout,
                                  level=stdout_level,
                                  max_level=stderr_level,
                                  color=True)
        logger = configure_logger(sys.stderr, level=stderr_level, color=True,
                                  logger=logger)
        if log_file_raw:
            file_level = log_levels['file']
            log_file = utils.processPath(log_file_raw)
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
            except OSError as e:
                logger.error('failed to make directory structure for log file ({})',
                             str(e))
                exit(101)
            logger = configure_logger(log_file,
                                      level=file_level,
                                      timestamp=True,
                                      logger=logger,
                                      backtrace=True,
                                      rotation=timedelta(days=1),
                                      retention=timedelta(days=7),
                                      compression='gz')
    except (ValueError, TypeError) as e:
        print(f'ERROR: failed to create logging facility ({str(e)})', file=sys.stderr)
        exit(102)
    
    logger.info(START_BANNER)
    logger.info('logging levels set to {}', ','.join([f'{k}={v}' for k, v in log_levels.items()]))
    
    config_schema_path = configfile.get_config_schema_path()
    
    if not os.path.exists(config_schema_path):
        logger.critical(f'Configuration file schema not found at '
                        f'"{config_schema_path}", exiting; '
                        f'this is a developer issue, NOT a user issue!')
        exit(100)
    
    schema_validator = configfile.ConfigValidator(config_schema_path)
    
    pid = generate_pid(pid_path, pid_disable)
    
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
        exit(10)
    
    if CONFIG_LOGIC_CHECK:
        logger.debug('Running dynamic validation analysis...')
        complaint = configfile.validate_config_dynamic(config, schema_validator.version)
        
        if complaint:
            logger.error('Configuration failed dynamic inspection tests: '
                         f'{complaint}')
            exit(11)
        else:
            logger.debug('Dynamic validation analysis passed')
    
    run_timer = timing.SecondTimer(0)
    
    timezone = config['device']['location']['timezone']
    tzo = tz.gettz(timezone)
    logger.info(f'Timezone set to "{timezone}"')
    logger.info(dt.now(tzo).strftime('Started at %I:%M %p %b %d %Y'))
    
    controller = Controller(config, tzo)
    try:
        asyncio.run(controller.run())
    except KeyboardInterrupt:
        pass
    
    ed, eh, em, es = utils.dhmsText(run_timer.getDelta())
    logger.info(f'Runtime of {ed} days, {eh} hours, {em} minutes and {es} seconds')
    
    cleanup_pid(pid, pid_disable)


if __name__ == '__main__':
    main_thread().name = 'Main'
    run()
else:
    print('This file must be ran directly.')
    exit(1)
