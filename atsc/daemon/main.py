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
import argparse
import sys
from datetime import timedelta
from json import JSONDecodeError
from threading import main_thread

import loguru

from atsc.constants import START_BANNER, ExitCode
from atsc.core import validation
from atsc.daemon.config import (CONFIG_SCHEMA_VERSION,
                                validate_dynamic_controller)
from atsc.daemon.context import RunContext
from atsc.daemon.controller import Controller
from atsc.logging import parse_log_level_argument, configure_logger
from atsc.rpc import default_connection_string, validate_connection_str
from atsc.utils import process_path, get_schema


PID_FILE = 'atsc.pid'
logger = loguru.logger


def get_cli_args():
    parser = argparse.ArgumentParser(description=START_BANNER)
    parser.add_argument('--pid',
                        dest='pid_path',
                        default=PID_FILE,
                        metavar='FILENAME',
                        help='Path to PID file. Default ' + PID_FILE)
    parser.add_argument('--no-pid',
                        action='store_true',
                        dest='pid_disable',
                        help='For development only. Disable use of PID file.')
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
    parser.add_argument('--td',
                        dest='tick_delay',
                        type=float,
                        default=0.1,
                        help='Set tick sleep() delay.')
    parser.add_argument('--tps',
                        type=int,
                        dest='tps',
                        default=10,
                        help='Set ticks per second.')
    parser.add_argument('-T', '--test',
                        action='store_true',
                        dest='test_configs',
                        help='Validate configuration files and exit.')
    parser.add_argument('-r', '--rpc',
                        default=default_connection_string(),
                        dest='connection_string',
                        help='RPC connection string to listen on.'
                             'Defaults to loopback.')
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
        logger.info('PID {} (file disabled)', pid)
    else:
        try:
            file = open(path, 'x')
        except FileExistsError:
            logger.error('already running ({})', path)
            exit(4)
        except OSError as e:
            logger.error('could not create PID file at {}: {}',
                         path,
                         str(e))
            exit(5)

        file.write(str(pid))
        file.flush()

        logger.info('PID {} ({})', pid, path)

    return file


def cleanup_pid(file, disabled):
    if not disabled:
        pid_path = os.path.realpath(file.name)
        if not file.closed:
            file.close()
        try:
            os.remove(pid_path)
        except OSError as e:
            logger.error('could not remove PID file at {}: {}',
                         pid_path,
                         str(e))
            exit(6)

        logger.info('removed PID file at {}', pid_path)


def run():
    global logger
    cla = get_cli_args()

    log_levels_text = cla.log_levels
    try:
        log_levels = parse_log_level_argument(log_levels_text)
    except (KeyError, ValueError) as e:
        print(f'ERROR: failed to parse log level argument ({str(e)})', file=sys.stderr)
        exit(ExitCode.LOGGER_INVALID)

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
            log_file = process_path(log_file_raw)
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
            except OSError as e:
                logger.error('failed to make directory structure for log file ({})',
                             str(e))
                exit(ExitCode.LOGGER_FILE_CREATION_FAILED)
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
        exit(ExitCode.LOGGER_INVALID)

    logger.info(START_BANNER)
    logger.info('logging levels set to {}', ','.join([f'{k}={v}' for k, v in log_levels.items()]))

    main_thread().name = 'Main'

    test_configs = cla.test_configs
    config_paths = cla.config_paths
    config_schema_path = get_schema('controller_config')

    if not os.path.exists(config_schema_path):
        logger.critical('configuration schema missing, installation is likely '
                        'corrupted (looking for "{}")',
                        config_schema_path)
        exit(ExitCode.SCHEMA_ERROR)

    try:
        schema_validator = validation.FileSchemaValidator(config_schema_path,
                                                          [CONFIG_SCHEMA_VERSION])
    except JSONDecodeError as e:
        logger.critical('failed to parse config schema, installation is likely corrupted ({})',
                        str(e))
        exit(ExitCode.SCHEMA_ERROR)
    except OSError as e:
        logger.critical('failed to read config schema, installation is likely corrupted ({})',
                        str(e))
        exit(ExitCode.SCHEMA_ERROR)

    logger.debug('working directory is "{}"', os.getcwd())

    try:
        processed_paths = []
        for cp in config_paths:
            processed_paths.append(process_path(cp))
            logger.debug('using configuration "{}"', cp)

        config = schema_validator.load(processed_paths)
        logger.debug('static validation OK')
    except validation.FileSchemaError as e:
        logger.error('load validation FAIL ({})',
                     e.generic_error.name)
        if len(e.details) > 0:
            logger.error('details:')
            for k, v in e.details.items():
                logger.error('- {} = {}', k, v)
        exit(ExitCode.CONFIG_INVALID_SCHEMA)

    dyn_msg = validate_dynamic_controller(
        config,
        schema_validator.version
    )

    if dyn_msg:
        logger.error('dynamic validation FAIL ({})', dyn_msg)
        exit(ExitCode.CONFIG_INVALID_DATA)
    else:
        logger.debug('dynamic validation OK')

    if test_configs:
        logger.info('configuration valid')
        exit(ExitCode.OK)

    pid_path = cla.pid_path
    pid_disable = cla.pid_disable
    tick_delay: float = cla.tick_delay
    tps: int = cla.tps

    # noinspection PyUnreachableCode
    if __debug__:
        logger.warning('application in DEBUG ENVIRONMENT!')

    if tick_delay < 0:
        logger.error('invalid tick delay')
        exit(13)

    if tps < 1:
        logger.error('invalid tps')
        exit(14)

    rpc_connection = cla.connection_string
    if not validate_connection_str(rpc_connection):
        logger.error('invalid connection string')
        exit(15)

    pid = generate_pid(pid_path, pid_disable)

    logger.debug('tick_delay={:05.2f}, tps={:05.2f}', tick_delay, tps)
    context = RunContext(tick_delay, tps)

    controller_node = config['controller']
    controller = Controller.deserialize(controller_node, context=context)
    controller.setup_rpc(rpc_connection)

    try:
        with logger.catch(exclude=KeyboardInterrupt):
            controller.run()
    except KeyboardInterrupt:
        controller.stop(0)

    cleanup_pid(pid, pid_disable)


if __name__ == '__main__':
    run()
else:
    print('This file must be ran directly.')
    exit(1)
