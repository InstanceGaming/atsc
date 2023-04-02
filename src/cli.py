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
import enum
import json
import argparse
import configfile


PROGRAM_DESCRIPTION = """
A CLI utility to validate configuration file sets and
manage parameters of the controller daemon
"""
PRINT_STDOUT = True


def cprint(*args):
    # conditional print
    if PRINT_STDOUT:
        print(*args)


def node_unknown(e, key) -> str:
    value = e.details.get(key)
    return str(value) if value is not None else '(unknown)'


class ReturnCode(enum.IntEnum):
    OK = 0
    NO_WORK = 1
    INVALID_CONFIG_PATHS = 2
    CONFIG_NOT_FOUND = 3
    CONFIG_NOT_READABLE = 4
    NO_PATHS = 5
    CONFIG_PARSE_ERROR = 6
    CONFIG_STATIC_ERROR = 7
    CONFIG_DYNAMIC_ERROR = 8
    NOT_RUNNING = 9
    CANNOT_CONNECT = 10
    DEVELOPER_ISSUE = 11


def rce(code: ReturnCode):
    exit(code.numerator)


def validate_configs(args):
    global PRINT_STDOUT
    
    source_daemon = args.daemon
    json_enabled = args.json
    error_abort = args.error_abort
    invalid_paths = []
    sources = args.config_paths
    paths = []
    
    if json_enabled:
        PRINT_STDOUT = False
    
    config_schema_path = configfile.get_config_schema_path()
    
    if not os.path.exists(config_schema_path):
        cprint(f'configuration file schema not found at '
               f'"{config_schema_path}", exiting; '
               f'this is a developer issue, NOT a user issue!')
        rce(ReturnCode.DEVELOPER_ISSUE)
    
    schema_validator = configfile.ConfigValidator(config_schema_path)
    
    if not source_daemon and sources is None:
        cprint('no work')
        rce(ReturnCode.NO_WORK)
    
    if source_daemon:
        cprint('evaluating configuration from paths last known by the running '
               'daemon:')
        raise NotImplementedError()
    
    if len(sources) > 0:
        cprint('evaluating configuration from the following files:')
    
    for item in sources:
        if os.path.exists(item):
            abs_path = os.path.abspath(item)
            paths.append(abs_path)
            cprint('- {}'.format(abs_path))
            continue
        invalid_paths.append(item)
    
    if len(invalid_paths) > 0:
        cprint('the following argument paths are invalid or do not exist:')
        for ia in invalid_paths:
            cprint('- {}'.format(ia))
        if error_abort:
            rce(ReturnCode.INVALID_CONFIG_PATHS)
    
    config = None
    try:
        config = schema_validator.load(paths)
    except configfile.ConfigError as e:
        if e.generic_error == configfile.ErrorType.NO_PATHS:
            cprint('no file paths provided')
            rce(ReturnCode.NO_PATHS)
        elif e.generic_error == configfile.ErrorType.NOT_FOUND:
            file_path = node_unknown(e, 'file')
            cprint(f'not found: {file_path}')
            rce(ReturnCode.CONFIG_NOT_FOUND)
        elif e.generic_error == configfile.ErrorType.CANNOT_READ:
            file_path = node_unknown(e, 'file')
            cprint(f'not readable: {file_path}')
            rce(ReturnCode.CONFIG_NOT_READABLE)
        elif e.generic_error == configfile.ErrorType.MIXING_VERSIONS:
            file_path = node_unknown(e, 'file')
            cprint(f'mixed config file versions: {file_path}')
            rce(ReturnCode.CONFIG_DYNAMIC_ERROR)
        elif e.generic_error == configfile.ErrorType.UNKNOWN_VERSION:
            file_path = node_unknown(e, 'file')
            cprint(f'unknown config file version in {file_path}')
            rce(ReturnCode.CONFIG_DYNAMIC_ERROR)
        elif e.generic_error == configfile.ErrorType.DUPLICATE_ROOT_NODE:
            node_name = node_unknown(e, 'node_name')
            cprint(f'multiple root nodes in config file(s) {node_name}')
            rce(ReturnCode.CONFIG_STATIC_ERROR)
        elif e.generic_error == configfile.ErrorType.INVALID_BY_SCHEMA:
            message = node_unknown(e, 'message')
            node_path = node_unknown(e, 'node_path')
            cprint(f'violates schema: {message} at {node_path}')
            rce(ReturnCode.CONFIG_STATIC_ERROR)
        elif e.generic_error == configfile.ErrorType.SCHEMA_INVALID:
            message = node_unknown(e, 'message')
            cprint(f'schema invalid: {message}')
            rce(ReturnCode.DEVELOPER_ISSUE)
        else:
            cprint(f'unhandled error type {e.generic_error.name}')
            cprint('details:')
            if len(e.details) > 0:
                for k, v in e.details.items():
                    cprint('\t{}={}'.format(k, v))
            rce(ReturnCode.CONFIG_PARSE_ERROR)
    
    result = configfile.validate_config_dynamic(config, schema_validator.version)
    
    if result is not None:
        cprint(f'failed dynamic validation: {result}')
        rce(ReturnCode.CONFIG_DYNAMIC_ERROR)
    
    cprint(f'configuration version: {schema_validator.version}')
    cprint('validation passed')
    
    if json_enabled:
        print(json.dumps(config))
    
    rce(ReturnCode.OK)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=PROGRAM_DESCRIPTION)
    sp = parser.add_subparsers(dest='subparser_name')
    
    # config validation
    sp_validate = sp.add_parser('validate', aliases=['val', 'vd'], description='Validate one or more files as one'
                                                                               ' configuration object.')
    sp_validate.add_argument('-d',
                             '--daemon',
                             dest='daemon',
                             action='store_true',
                             help='validate config from paths last known by the'
                                  ' running daemon')
    sp_validate.add_argument('-a',
                             '--abort',
                             dest='error_abort',
                             action='store_true',
                             help='exit upon encountering first error')
    sp_validate.add_argument('--json', dest='json', action='store_true', help='upon success, print the overall '
                                                                              'configuration to STDOUT as JSON')
    sp_validate.add_argument(dest='config_paths',
                             type=str,
                             nargs='*',
                             metavar='FILENAME',
                             help='Path to one or more ATSC config files. Their'
                                  ' contents will be merged.')
    sp_validate.set_defaults(func=validate_configs)
    parser_result = parser.parse_args()
    subparser_name = parser_result.subparser_name
    
    if subparser_name is not None:
        parser_result.func(parser_result)
    else:
        cprint('no subcommand specified')
        rce(ReturnCode.NO_WORK)
