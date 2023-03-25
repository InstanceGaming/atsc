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
from threading import main_thread
from atsc.constants import START_BANNER
from atsc.core import validation
from atsc.daemon.config import (CONFIG_SCHEMA_VERSION,
                                validate_dynamic_controller)
from atsc.daemon.controller import Controller
from atsc.rpc import default_connection_string, validate_connection_str
from atsc.utils import (default_logger,
                        register_logging_levels,
                        get_config_schema_path)


PID_FILE = 'atsc.pid'
logger = default_logger(20)
register_logging_levels()


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
    parser.add_argument('-l', '--log-level',
                        type=str,
                        dest='log_level',
                        default=None,
                        choices=['SORT', 'BUS', 'NET', 'TRACE', 'DEBUG',
                                 'INFO', 'WARNING'],
                        help='Set alternate log level.')
    parser.add_argument('--tick-size',
                        dest='tick_size',
                        type=float,
                        default=0.1,
                        help='Set tick speed.')
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

    log_level = cla.log_level

    if log_level is not None:
        logger = default_logger(log_level)
    logger.info(START_BANNER)
    logger.info('logging level {}', log_level)

    main_thread().name = 'Main'

    test_configs = cla.test_configs
    config_paths = cla.config_paths
    config_schema_path = get_config_schema_path()

    if not os.path.exists(config_schema_path):
        logger.fatal('configuration schema missing, installation is likely '
                     'corrupted (looking for "{}")',
                     config_schema_path)
        exit(12)

    schema_validator = validation.FileSchemaValidator(config_schema_path,
                                                      [CONFIG_SCHEMA_VERSION])

    logger.debug('working directory is "{}"', os.getcwd())

    try:
        for cp in config_paths:
            logger.debug('configuration ingest from "{}"', cp)

        config = schema_validator.load(config_paths)
        logger.debug('static validation OK')
    except validation.FileSchemaError as e:
        logger.error('load validation FAIL ({})',
                     e.generic_error.name)
        if len(e.details) > 0:
            logger.error('details:')
            for k, v in e.details.items():
                logger.error('- {} = {}', k, v)
        exit(10)

    dyn_msg = validate_dynamic_controller(
        config,
        schema_validator.version
    )

    if dyn_msg:
        logger.error('dynamic validation FAIL ({})', dyn_msg)
        exit(11)
    else:
        logger.debug('dynamic validation OK')

    if test_configs:
        logger.info('configuration valid')
        exit(0)

    pid_path = cla.pid_path
    pid_disable = cla.pid_disable
    tick_size: float = cla.tick_size

    # noinspection PyUnreachableCode
    if __debug__:
        logger.warning('application in DEBUG ENVIRONMENT!')

    if tick_size < 0:
        logger.error('invalid tick divisor')
        exit(13)

    con_str = cla.connection_string
    if not validate_connection_str(con_str):
        logger.error('invalid connection string')
        exit(15)

    pid = generate_pid(pid_path, pid_disable)

    logger.debug('tick set to {:05.2f}', tick_size)
    controller = Controller(tick_size, con_str, config)
    try:
        controller.run()
    except KeyboardInterrupt:
        controller.stop(0)
    cleanup_pid(pid, pid_disable)


if __name__ == '__main__':
    run()
else:
    print('This file must be ran directly.')
    exit(1)
