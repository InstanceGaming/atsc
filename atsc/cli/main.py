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
from importlib.util import find_spec

from atsc.constants import START_BANNER
from atsc.rpc import default_connection_string, validate_connection_str
from atsc.utils import default_logger, register_logging_levels


logger = default_logger(20)
register_logging_levels()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=START_BANNER)
    sp = parser.add_subparsers(dest='subparser_name')

    # config validation
    sp_live = sp.add_parser('live',
                            description='Connect to daemon and show the'
                                            'live state of the controller.')
    sp_live.add_argument('-r', '--rpc',
                         default=default_connection_string(),
                         dest='connection_string',
                         help='Connection string for daemon RPC. Defaults to '
                              'loopback.')
    parser_result = parser.parse_args()
    subparser_name = parser_result.subparser_name

    if subparser_name is not None:
        if subparser_name == 'live':
            con_str = parser_result.connection_string

            asciimatics_found = find_spec('asciimatics')
            if not asciimatics_found:
                logger.error('"asciimatics" not found, please install using '
                             'pip first')
                exit(21)

            from atsc.cli import live

            if not validate_connection_str(con_str):
                logger.error('invalid connection string')
                exit(20)

            live.run_tui(con_str)
    else:
        logger.error('subcommand required')
        exit(10)
