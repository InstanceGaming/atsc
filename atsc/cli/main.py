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

import argparse
import sys
from importlib.util import find_spec

import loguru

from atsc.constants import START_BANNER
from atsc.logging import configure_logger
from atsc.rpc import default_connection_string, validate_connection_str


logger = loguru.logger


def run():
    global logger
    parser = argparse.ArgumentParser(description=START_BANNER)
    parser.add_argument('-L', '--log-level',
                        type=int,
                        default=20,
                        dest='log_level',
                        help='Set log level.')
    sp = parser.add_subparsers(dest='subparser_name')
    sp_live = sp.add_parser('live',
                            description='Connect to daemon and show the'
                                        'live initial_state of the daemon.')
    sp_live.add_argument('-r', '--rpc',
                         default=default_connection_string(),
                         dest='connection_string',
                         help='Connection string for daemon RPC. Defaults to '
                              'loopback.')
    parser_result = parser.parse_args()
    log_level = parser_result.log_level
    subparser_name = parser_result.subparser_name

    logger = configure_logger(sys.stdout,
                              level=log_level,
                              color=True)
    
    if subparser_name is not None:
        if subparser_name == 'live':
            con_str = parser_result.connection_string
            
            if not validate_connection_str(con_str):
                logger.error('invalid connection string')
                exit(20)

            asciimatics_found = find_spec('asciimatics')
            if not asciimatics_found:
                logger.error('"asciimatics" module not found, please install '
                             'to use this feature')
                exit(21)

            from atsc.cli import live
            
            try:
                live.run_tui(con_str)
            except KeyboardInterrupt:
                pass
    else:
        logger.error('subcommand required')
        exit(10)


if __name__ == '__main__':
    run()
