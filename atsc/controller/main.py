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
import threading
import loguru
import asyncio
from atsc.common import cli
from grpclib.server import Server
from atsc.common.utils import setup_logger, asyncio_loop_patch
from atsc.controller.constants import POLL_RATE
from atsc.controller.core import Controller
from atsc.common.constants import ExitCode


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
        server.close()
        await server.wait_closed()
        logger.debug('RPC server closed')


def _rpc_server_shim(host: str,
                     port: int,
                     controller: Controller,
                     cancel_event: threading.Event):
    loop = asyncio.new_event_loop()
    loop.run_until_complete(rpc_server(host, port, controller, cancel_event))


async def run():
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
                         
    extra_cla = vars(root_ap.parse_args())
    presence_simulation = extra_cla['presence_simulation']
    simulation_seed = extra_cla['simulation_seed']
    init_demand = extra_cla['init_demand']
    time_freeze = extra_cla['time_freeze']
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    controller = Controller(pid_file=cla.pid_path,
                            init_demand=init_demand,
                            time_freeze=time_freeze,
                            presence_simulation=presence_simulation,
                            simulation_seed=simulation_seed)
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


asyncio_loop_patch()
exit(asyncio.get_event_loop().run_until_complete(run()))
