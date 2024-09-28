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
from grpclib.client import Channel
from atsc.common.utils import setup_logger
from atsc.fieldbus.core import FieldBus
from atsc.common.structs import Context
from atsc.rpc.controller import ControllerStub
from atsc.common.constants import ExitCode
from atsc.fieldbus.constants import SERIAL_BUS_BAUD_RATE, SERIAL_BUS_BAUD_RATES


logger = loguru.logger


def arg_baud_type(v: str) -> int:
    baud = int(v)
    if baud not in SERIAL_BUS_BAUD_RATES:
        raise ValueError(f'baud rate out of rage {SERIAL_BUS_BAUD_RATES}')
    return baud


def run():
    cla, root_ap = cli.parse_common_cla('ATSC field bus server.',
                                        True,
                                        partial=True)
    
    root_ap.add_argument('-b', '--baud',
                         type=arg_baud_type,
                         default=SERIAL_BUS_BAUD_RATE,
                         dest='baud_rate')
    root_ap.add_argument(type=str, dest='serial_port')
    fieldbus_cla = vars(root_ap.parse_args())
    
    serial_port = fieldbus_cla['serial_port']
    baud_rate = fieldbus_cla['baud_rate']
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    context = Context(cla.tick_rate, cla.tick_scale)
    
    channel = Channel(host='127.0.0.1', port=cla.rpc_port)
    controller = ControllerStub(channel)
    field_bus = FieldBus(context, controller, serial_port, baud_rate, pid_file=cla.pid_path)
    asyncio.get_event_loop().run_until_complete(field_bus.run())
    channel.close()


if __name__ == '__main__':
    exit(run())
else:
    print('This file must be ran directly.')
    exit(1)
