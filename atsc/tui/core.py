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
import asyncio
import shutil
from typing import Optional, List
from asyncio import AbstractEventLoop, get_event_loop

from grpc import RpcError
from loguru import logger

from atsc.rpc import controller
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT
from atsc.rpc.phase import Phase as rpc_Phase


def move_cursor(row: int, col: int = 0):
    print(f'\033[{row};{col}H', end='')


# Helper function to clear the current terminal line
def clear_line():
    print('\033[K', end='')


class TUI(AsyncDaemon):
    
    def __init__(self,
                 context: Context,
                 controller_rpc: controller.ControllerStub,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout=shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self._controller = controller_rpc
        
        self._console_letters = ('R', 'Y', 'G', 'D', 'W')
        self._console_size = shutil.get_terminal_size()
        self._console_rows = 0
        self._console_lines: List[List[str]] = []
        self._phases: List[rpc_Phase] = []
        self._extra_rows = 3
        
        # self.routines.append(self.update())
    
    async def _poll_phases(self):
        request = controller.ControllerPhasesRequest()
        response = await self._controller.get_phases(request)
        self._phases = response.phases
    
    async def before_run(self):
        await self._poll_phases()
        
        self._console_rows = max([len(p.field_outputs) - 1 for p in self._phases]) + self._extra_rows
        
        for i in range(self._console_rows + 1):
            self._console_lines.append(['.'] * min(len(self._phases), self._console_size.columns))
            
        # await super().before_run()
    
    async def update(self):
        for pi, phase in enumerate(self._phases):
            for fi, fo in enumerate(phase.field_outputs):
                try:
                    letter = self._console_letters[fi]
                except IndexError:
                    letter = 'X'
                
                self._console_lines[fi][pi] = letter if fo.value else '.'
            self._console_lines[-3][pi] = f'{phase.interval_time:.0f}' if phase.interval_time < 9 else '.'
            self._console_lines[-2][pi] = 'D' if phase.demand else '.'
            self._console_lines[-1][pi] = 'P' if phase.presence else '.'
        
        for li, line in enumerate(reversed(self._console_lines)):
            move_cursor(self._console_size.lines - li)
            line_text = ''.join(line)
            clear_line()
            print(line_text, end='')
        
        move_cursor(self._console_size.lines - (self._console_rows + 1))
        
        await self._poll_phases()

    async def run(self) -> int:
        try:
            await self.before_run()
        except RpcError as e:
            logger.exception(e)
            return 1
        
        self.running.set()
        while self.running.is_set():
            try:
                await self.update()
            except RpcError as e:
                logger.exception(e)
            await asyncio.sleep(self.context.delay)
        return 0
    
    def shutdown(self):
        self.running.clear()
