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
import random
import asyncio
import argparse
from typing import Optional
from atsc.fieldbus import FieldBus
from jacob.logging import setup_logger
from jacob.filesystem import fix_path
from atsc.common.utils import asyncio_loop_patch
from atsc.fieldbus.frames import InputStateFrame
from atsc.fieldbus.models import DecodedBusFrame
from atsc.common.constants import CUSTOM_LOG_LEVELS, ExitCode
from atsc.fieldbus.constants import DeviceAddress


logger = loguru.logger


class BusFuzzer(FieldBus):
    
    def __init__(self,
                 serial_port: str,
                 baud: int,
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None):
        super().__init__(serial_port,
                         baud,
                         shutdown_timeout,
                         pid_file=pid_file)
        self.rng = random.Random()
        self.max_delay = 10
        
        self.add_task(self.fuzz())
        self.received_frame.connect(self.frame_handler, sender=self)
    
    async def fuzz(self):
        try:
            while True:
                bytefield = bytearray(5)
                for i in range(5):
                    if round(self.rng.random()):
                        bytefield[i] = self.rng.getrandbits(8)
                
                frame = InputStateFrame(DeviceAddress.CONTROLLER, bytefield)
                await self.transmit_now(frame)
                
                delay = self.rng.randrange(0, self.max_delay)
                await asyncio.sleep(delay)
        except KeyboardInterrupt:
            pass
    
    def frame_handler(self, _, decoded_frame: DecodedBusFrame):
        logger.bus('handled frame type {}', decoded_frame.type)
        
    def shutdown(self):
        super().shutdown()


def get_cli_args():
    root = argparse.ArgumentParser(description='Actuated traffic signal controller bus fuzzer.')
    root.add_argument('-L', '--levels',
                      type=str,
                      dest='log_levels',
                      default='debug,warning;stderr=error',
                      help='Define logging levels.')
    root.add_argument('-l', '--log',
                      type=str,
                      dest='log_file',
                      default=None,
                      help='Define log file path.')
    
    return vars(root.parse_args())


async def run():
    cla = get_cli_args()
    
    log_file = fix_path(cla.get('log_file'))
    levels_notation = cla['log_levels']
    try:
        loguru.logger = setup_logger(levels_notation,
                                     custom_levels=CUSTOM_LOG_LEVELS,
                                     log_file=log_file)
    except ValueError as e:
        print(f'Malformed logging level specification "{levels_notation}":', e)
        return ExitCode.LOG_LEVEL_PARSE_FAIL
    
    field_bus = BusFuzzer('COM5', 115200)
    result = await field_bus.run()
    return result


asyncio_loop_patch()
exit(asyncio.get_event_loop().run_until_complete(run()))
