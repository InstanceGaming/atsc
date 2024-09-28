from pathlib import Path
from argparse import ArgumentParser
from jacob.filesystem import fix_path
from atsc.common.structs import CommonCommandLineArguments
from atsc.common.constants import (DEBUG_LEVELS,
                                   DEFAULT_LEVELS,
                                   DEFAULT_TICK_RATE,
                                   DEFAULT_TICK_SCALE,
                                   CONTROLLER_RPC_PORT)


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
        root.add_argument('-r', '--tick-rate',
                          type=arg_context_value_type,
                          dest='tick_rate',
                          default=DEFAULT_TICK_RATE,
                          help=f'Tick rate. Default is {DEFAULT_TICK_RATE}.')
        root.add_argument('-s', '--tick-scale',
                          type=arg_context_value_type,
                          dest='tick_scale',
                          default=DEFAULT_TICK_SCALE,
                          help=f'Tick scale. Default is {DEFAULT_TICK_SCALE}.')
    root.add_argument('-p', '--rpc-port',
                      type=arg_port_number_type,
                      default=CONTROLLER_RPC_PORT,
                      dest='rpc_port',
                      help='TCP port number for RPC server to bind to. '
                           f'Default is port {CONTROLLER_RPC_PORT}.')
    
    if partial:
        known_args = root.parse_known_args()[0]
        cla = vars(known_args)
    else:
        cla = vars(root.parse_args())
    
    return CommonCommandLineArguments(
        log_levels_notation=cla['log_levels'],
        rpc_port=cla['rpc_port'],
        log_path=fix_path(cla.get('log_path')),
        pid_path=fix_path(cla.get('pid_path')),
        tick_rate=cla.get('tick_rate'),
        tick_scale=cla.get('tick_scale')
    ), root
