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

import finelog  # will break if omitted! must be imported in its entirety.
import os
import utils
import timing
import logging
import argparse
import configfile
from datetime import datetime as dt
from dateutil import tz
from threading import main_thread
from controller import Controller


VERSION = '2.0.1'
CONFIG_FILE = 'config.toml'
DEVICE_FILE = 'device.toml'
PID_FILE = 'atsc.pid'
WELCOME_MSG = f'Actuated Traffic Signal Controller v{VERSION} by Jacob Jewett'
CONFIG_SCHEMA_CHECK = True
CONFIG_LOGIC_CHECK = True

LOG = logging.getLogger('atsc')
utils.configureLogger(LOG)


def get_cli_args():
    parser = argparse.ArgumentParser(description=WELCOME_MSG)
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
    parser.add_argument('-v',
                        dest='verbosity',
                        action='count',
                        default=0,
                        help='Increase verbosity the '
                             'more this flag is defined.')
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
        LOG.info(f'PID {pid} (file disabled)')
    else:
        try:
            file = open(path, 'x')
        except FileExistsError:
            LOG.error(f'Already running ({path})')
            exit(4)
        except OSError as e:
            LOG.error(f'Could not create PID file at {path}: {str(e)}')
            exit(5)

        file.write(str(pid))
        file.flush()

        LOG.info(f'PID {pid} ({path})')

    return file


def cleanup_pid(file, disabled):
    if not disabled:
        pid_path = os.path.realpath(file.name)
        if not file.closed:
            file.close()
        try:
            os.remove(pid_path)
        except OSError as e:
            LOG.error(f'Could not remove PID file at {pid_path}: {str(e)}')
            exit(6)

        LOG.info(f'Removed PID file at {pid_path}')


def run():
    cla = get_cli_args()

    pid_path = cla.pid_path[0]
    pid_disable = cla.pid_disable
    config_paths = cla.config_paths
    verbosity = cla.verbosity

    if verbosity == 0:
        LOG.setLevel(logging.INFO)
    elif verbosity == 1:
        LOG.setLevel(finelog.CustomLogLevels.VERBOSE)
    elif verbosity == 2:
        LOG.setLevel(finelog.CustomLogLevels.FINE)
    elif verbosity == 3:
        LOG.setLevel(finelog.CustomLogLevels.BUS)
    elif verbosity >= 4:
        LOG.setLevel(finelog.CustomLogLevels.SORTING)

    LOG.info(WELCOME_MSG)
    LOG.info(f'Logging level {LOG.level}')

    config_schema_path = configfile.get_config_schema_path()

    if not os.path.exists(config_schema_path):
        LOG.fatal(f'Configuration file schema not found at '
                  f'"{config_schema_path}", exiting; '
                  f'this is a developer issue, NOT a user issue!')
        exit(100)

    schema_validator = configfile.ConfigValidator(config_schema_path)

    pid = generate_pid(pid_path, pid_disable)

    config = None
    try:
        for cp in config_paths:
            cp = os.path.abspath(cp)
            LOG.info(f'Configuration ingest from "{cp}"')

        if CONFIG_SCHEMA_CHECK:
            LOG.debug('Running static validation analysis...')
            config = schema_validator.load(config_paths)
    except configfile.ConfigError as e:
        LOG.error('Failed to load configuration file(s): '
                  f'{e.generic_error.name}')
        if len(e.details) > 0:
            LOG.debug('Details:')
            for k, v in e.details.items():
                LOG.debug(f'- {k} = {v}')
        exit(10)

    if CONFIG_LOGIC_CHECK:
        LOG.debug('Running dynamic validation analysis...')
        complaint = configfile.validate_config_dynamic(config,
                                                       schema_validator.version)

        if complaint:
            LOG.error('Configuration failed dynamic inspection tests: '
                      f'{complaint}')
            exit(11)
        else:
            LOG.debug('Dynamic validation analysis passed')

    run_timer = timing.SecondTimer(0)

    timezone = config['device']['location']['timezone']
    tzo = tz.gettz(timezone)
    LOG.info(f'Timezone set to "{timezone}"')
    LOG.info(dt.now(tzo).strftime('Started at %I:%M %p %b %d %Y'))

    controller = Controller(config, tzo)
    try:
        controller.run()
    except KeyboardInterrupt:
        controller.shutdown()

    ed, eh, em, es = utils.dhmsText(run_timer.getDelta())
    LOG.info(f'Runtime of {ed} days, {eh} hours, {em} minutes and {es} seconds')

    cleanup_pid(pid, pid_disable)


if __name__ == '__main__':
    main_thread().name = 'Main'
    run()
else:
    print('This file must be ran directly.')
    exit(1)
