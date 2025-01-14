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
from typing import Optional

import loguru
import asyncio
import threading

from jacob.logging import attach_standard_logger

from atsc.common import cli
from grpclib.server import Server
from atsc.common.utils import setup_logger, get_platform_loop_module
from atsc.controller.core import Controller
from atsc.common.constants import ExitCode
from atsc.controller.constants import POLL_RATE
from atsc.fieldbus.constants import BUS_BAUD_RATE
from atsc.fieldbus.main import arg_baud_type, arg_field_output_count_type


logger = loguru.logger


async def rpc_server(host: str,
                     port: int,
                     controller: Controller,
                     cancel_event: threading.Event):
    logger.debug('starting RPC server...')
    
    server = Server([controller])
    try:
        await server.start(host=host, port=port)
        
        if host:
            logger.info('RPC server listening on {} port {}', host, port)
        else:
            logger.info('RPC server listening on port {} (all interfaces)', port)
        
        while not cancel_event.is_set():
            await asyncio.sleep(POLL_RATE)
    except (OSError, TimeoutError, ConnectionError) as e:
        logger.error('RPC server failed to start: {}', str(e))
    finally:
        logger.debug('closing RPC server')
        try:
            server.close()
            await server.wait_closed()
            logger.debug('RPC server closed')
        except RuntimeError:
            # server may not be started (i.e. failed to bind)
            pass


def _rpc_server_shim(host: str,
                     port: int,
                     controller: Controller,
                     cancel_event: threading.Event):
    loop = asyncio.new_event_loop()
    loop.run_until_complete(rpc_server(host, port, controller, cancel_event))


async def run_async(cla,
                    init_demand: bool,
                    time_freeze: bool,
                    presence_simulation: bool,
                    simulation_seed: int,
                    serial_port: Optional[str] = None,
                    baud_rate: Optional[int] = None,
                    truncate_field_outputs: Optional[int] = None):
    controller = Controller(asyncio.get_event_loop(),
                            pid_file=cla.pid_path,
                            init_demand=init_demand,
                            time_freeze=time_freeze,
                            presence_simulation=presence_simulation,
                            simulation_seed=simulation_seed,
                            serial_port=serial_port,
                            baud_rate=baud_rate,
                            truncate_field_outputs=truncate_field_outputs)
    rpc_cancel_event = threading.Event()
    rpc_thread = threading.Thread(target=_rpc_server_shim,
                                  args=(cla.rpc_address,
                                        cla.rpc_port,
                                        controller,
                                        rpc_cancel_event))
    rpc_thread.start()
    result = await controller.run()
    rpc_cancel_event.set()
    
    logger.debug('waiting on RPC server thread')
    rpc_thread.join()
    logger.debug('RPC server thread joined')
    
    return result


def run():
    cla, root_ap = cli.parse_common_cla('ATSC control server.',
                                        True,
                                        partial=True)
    
    root_ap.add_argument('--presence-simulation',
                         action='store_true',
                         dest='presence_simulation')
    root_ap.add_argument('--simulation-seed',
                         type=int,
                         dest='simulation_seed')
    root_ap.add_argument('--init-demand',
                         action='store_true',
                         dest='init_demand')
    root_ap.add_argument('--time-freeze',
                         action='store_true',
                         dest='time_freeze')
    root_ap.add_argument('-b', '--baud',
                         type=arg_baud_type,
                         default=BUS_BAUD_RATE,
                         dest='baud_rate')
    root_ap.add_argument('-s', '--serial-port',
                         type=str,
                         dest='serial_port')
    root_ap.add_argument('--truncate-field-outputs',
                         type=arg_field_output_count_type,
                         dest='truncate_field_outputs')
    
    extra_cla = vars(root_ap.parse_args())
    presence_simulation = extra_cla['presence_simulation']
    simulation_seed = extra_cla['simulation_seed']
    init_demand = extra_cla['init_demand']
    time_freeze = extra_cla['time_freeze']
    serial_port = extra_cla['serial_port']
    baud_rate = extra_cla['baud_rate']
    truncate_field_outputs = extra_cla['truncate_field_outputs']
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    attach_standard_logger(loguru.logger, 'asyncio')
    
    with logger.catch():
        loop_impl = get_platform_loop_module()
        with (asyncio.Runner(loop_factory=loop_impl.new_event_loop) as runner):
            runner.get_loop().set_debug(cla.asyncio_debug)
            return runner.run(run_async(cla,
                                        presence_simulation,
                                        simulation_seed,
                                        init_demand,
                                        time_freeze,
                                        serial_port=serial_port,
                                        baud_rate=baud_rate,
                                        truncate_field_outputs=truncate_field_outputs))


if __name__ == '__main__':
    exit(run())