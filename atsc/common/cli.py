#  Copyright 2024 Jacob Jewett
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
from pathlib import Path
from argparse import ArgumentParser
from jacob.filesystem import fix_path
from atsc.common.structs import CommonCommandLineArguments
from atsc.common.constants import (
    RPC_PORT,
    RPC_ADDRESS,
    DEBUG_LEVELS,
    DEFAULT_LEVELS,
    DEFAULT_TICK_RATE,
    DEFAULT_TICK_SCALE
)


def arg_port_number_type(v: str) -> int:
    port = int(v)
    if 1 > port > 65535:
        raise ValueError('port argument out of range (0-65535)')
    return port


def arg_context_value_type(v: str) -> float:
    value = float(v)
    if 0.01 > value > 1000.00:
        raise ValueError('context value out of range (0.01-1000.00)')
    return value


def parse_common_cla(description: str,
                     is_daemon: bool,
                     partial=False):
    root = ArgumentParser(description=description)
    
    if __debug__:
        log_levels = DEBUG_LEVELS
    else:
        log_levels = DEFAULT_LEVELS
    
    root.add_argument('-L', '--levels',
                      type=str,
                      dest='log_levels',
                      default=log_levels,
                      help='Define logging levels.')
    root.add_argument('-l', '--log',
                      type=Path,
                      dest='log_path',
                      default=None,
                      help='Define log file path.')
    if is_daemon:
        root.add_argument('--pid',
                          type=Path,
                          dest='pid_path',
                          help=f'Use PID file at this path.')
        root.add_argument('--tick-rate',
                          type=arg_context_value_type,
                          dest='tick_rate',
                          default=DEFAULT_TICK_RATE,
                          help=f'Tick rate. Default is {DEFAULT_TICK_RATE}.')
        root.add_argument('--tick-scale',
                          type=arg_context_value_type,
                          dest='tick_scale',
                          default=DEFAULT_TICK_SCALE,
                          help=f'Tick scale. Default is {DEFAULT_TICK_SCALE}.')
    root.add_argument('-a', '--rpc-address',
                      type=str,
                      default=RPC_ADDRESS,
                      dest='rpc_address',
                      help='Address for RPC server to bind or listen on. '
                           f'Default is {RPC_ADDRESS}.')
    root.add_argument('-p', '--rpc-port',
                      type=arg_port_number_type,
                      default=RPC_PORT,
                      dest='rpc_port',
                      help='TCP port number for RPC server to bind to. '
                           f'Default is port {RPC_PORT}.')
    
    if partial:
        known_args = root.parse_known_args()[0]
        cla = vars(known_args)
    else:
        cla = vars(root.parse_args())
    
    return CommonCommandLineArguments(
        log_levels_notation=cla['log_levels'],
        rpc_address=cla['rpc_address'],
        rpc_port=cla['rpc_port'],
        log_path=fix_path(cla.get('log_path')),
        pid_path=fix_path(cla.get('pid_path')),
        tick_rate=cla.get('tick_rate'),
        tick_scale=cla.get('tick_scale')
    ), root
