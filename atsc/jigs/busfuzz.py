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
from atsc import fieldbus
from typing import Optional
from asyncio import AbstractEventLoop, get_event_loop
from jacob.logging import setup_logger
from jacob.filesystem import fix_path
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.fieldbus.frames import InputStateFrame
from atsc.common.constants import CUSTOM_LOG_LEVELS, ExitCode
from atsc.fieldbus.constants import DeviceAddress


logger = loguru.logger


class BusFuzzer(AsyncDaemon):
    
    def __init__(self,
                 context: Context,
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self.rng = random.Random()
        self.max_delay = 10
        
        self.fieldbus = fieldbus.FieldBus(context, 'COM5', 115200, loop=loop)
        
        self.routines.extend((
            self.fieldbus.receive(),
            self.fieldbus.transmit(),
            self.fuzz(),
            self.frame_handler()
        ))
    
    async def frame_handler(self):
        while True:
            async with self.fieldbus.frames_unread:
                await self.fieldbus.frames_unread.wait()
                for frame in self.fieldbus.process_frames():
                    logger.bus('handled frame type {}', frame.type)
    
    async def fuzz(self):
        try:
            while True:
                bytefield = bytearray(5)
                for i in range(5):
                    if round(self.rng.random()):
                        bytefield[i] = self.rng.getrandbits(8)
                
                frame = InputStateFrame(DeviceAddress.CONTROLLER, bytefield)
                self.fieldbus.enqueue_frame(frame)
                
                delay = self.rng.randrange(0, self.max_delay)
                await asyncio.sleep(delay)
        except KeyboardInterrupt:
            pass
    
    def shutdown(self):
        self.fieldbus.close()
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


def run():
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


if __name__ == '__main__':
    run()
