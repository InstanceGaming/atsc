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
from atsc.common.cli import arg_poll_rate_type
from atsc.common.utils import setup_logger, asyncio_loop_patch
from atsc.fieldbus.core import ControllerFieldBus
from atsc.rpc.controller import ControllerStub
from atsc.common.constants import ExitCode
from atsc.fieldbus.constants import BUS_BAUD_RATE, BUS_BAUD_RATES
from atsc.controller.constants import POLL_RATE


logger = loguru.logger


def arg_baud_type(v: str) -> int:
    baud = int(v)
    if baud not in BUS_BAUD_RATES:
        raise ValueError(f'baud rate out of rage {BUS_BAUD_RATES}')
    return baud


def arg_field_output_count_type(v: str) -> int:
    count = int(v)
    if count < 1:
        raise ValueError('one field output required')
    return count


async def run():
    cla, root_ap = cli.parse_common_cla('ATSC field bus server.',
                                        True,
                                        partial=True)
    
    root_ap.add_argument('-b', '--baud',
                         type=arg_baud_type,
                         default=BUS_BAUD_RATE,
                         dest='baud_rate')
    root_ap.add_argument('-r', '--poll-rate',
                         type=arg_poll_rate_type,
                         default=POLL_RATE,
                         dest='poll_rate')
    root_ap.add_argument('--truncate-field-outputs',
                         type=arg_field_output_count_type,
                         dest='truncate_field_outputs')
    root_ap.add_argument(type=str, dest='serial_port')
    
    extra_cla = vars(root_ap.parse_args())
    serial_port = extra_cla['serial_port']
    baud_rate = extra_cla['baud_rate']
    poll_rate = extra_cla['poll_rate']
    truncate_field_outputs = extra_cla['truncate_field_outputs']
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    channel = Channel(host=cla.rpc_address, port=cla.rpc_port)
    try:
        controller = ControllerStub(channel)
        field_bus = ControllerFieldBus(
            controller,
            poll_rate,
            serial_port,
            baud_rate,
            pid_file=cla.pid_path,
            truncate_field_outputs=truncate_field_outputs
        )
        result = await field_bus.run()
        return result
    finally:
        channel.close()


asyncio_loop_patch()
exit(asyncio.get_event_loop().run_until_complete(run()))
