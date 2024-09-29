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
import loguru
import asyncio
from atsc.common import cli
from atsc.tui.core import TUI
from grpclib.client import Channel
from atsc.common.utils import setup_logger
from atsc.common.structs import Context
from atsc.rpc.controller import ControllerStub
from atsc.common.constants import ExitCode


logger = loguru.logger


def run():
    cla, root_ap = cli.parse_common_cla('ATSC TUI.',
                                        True,
                                        partial=True)
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    context = Context(cla.tick_rate, cla.tick_scale)
    
    channel = Channel(host='127.0.0.1', port=cla.rpc_port)
    controller = ControllerStub(channel)
    tui = TUI(context, controller, pid_file=cla.pid_path)
    
    try:
        asyncio.get_event_loop().run_until_complete(tui.run())
    except Exception as e:
        logger.exception(e)
    
    channel.close()


if __name__ == '__main__':
    exit(run())
else:
    print('This file must be ran directly.')
    exit(1)
