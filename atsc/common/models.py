#  Copyright 2022 Jacob Jewett
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
import os
import signal
from abc import ABC
from asyncio import Event, AbstractEventLoop, get_event_loop, wait_for, sleep, TaskGroup, create_task
from datetime import datetime
from enum import IntFlag
from pathlib import Path
from typing import Optional, List, Coroutine, TextIO
from jacob.datetime.formatting import format_dhms, compact_datetime, format_ms
from loguru import Logger
from atsc.common.constants import ExitCode
from atsc.common.primitives import StopwatchEvent, Context, Updatable


class AsyncDaemon(Updatable, ABC):
    
    def __init__(self,
                 logger: Logger,
                 context: Context,
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        super().__init__()
        self.loop = loop
        self.logger = logger
        self.pid_file = pid_file
        self.shutdown_timeout = shutdown_timeout
        self.context = context
        self.started_at: Optional[datetime] = None
        
        self.routines: List[Coroutine] = []
        self.running = StopwatchEvent()
        self.request_shutdown = StopwatchEvent()
        self.shutdown_clean = Event()
        
        for sig in signal.valid_signals():
            signal.signal(sig, lambda s, f: self.loop.create_task(self.signal_handler(s, f)))
    
    async def signal_handler(self, sig, _):
        match sig:
            case signal.SIGTERM | signal.SIGINT:
                self.logger.info('signal {} received', sig)
                await self.on_terminate()
            case unhandled_signal:
                self.logger.warning('unhandled signal {} received', unhandled_signal)
    
    async def lock_pid(self):
        pid = os.getpid()
        if self.pid_file is None:
            self.logger.info('process #{} (file disabled)', pid)
        else:
            assert isinstance(self.pid_file, os.PathLike)
            abs_path = Path(self.pid_file).absolute()
            
            try:
                file = open(abs_path, 'x')
                file.write(str(pid))
                file.flush()
                self.logger.info('process #{} ({})', pid, abs_path)
                self.pid_file = file
            except FileExistsError:
                self.logger.error('process already running ({})', abs_path)
                exit(ExitCode.PID_EXISTS)
            except OSError as e:
                self.logger.error('could not create process lock at {}: {}', abs_path, str(e))
                exit(ExitCode.PID_CREATE_FAIL)
    
    async def unlock_pid(self):
        if self.pid_file is not None:
            assert isinstance(self.pid_file, TextIO)
            
            pid_path = os.path.realpath(self.pid_file.name)
            if not self.pid_file.closed:
                self.pid_file.close()
            
            try:
                os.remove(pid_path)
            except OSError as e:
                self.logger.error('could not remove PID file at {}: {}', pid_path, str(e))
                exit(ExitCode.PID_REMOVE_FAIL)
            
            self.logger.info('removed PID file at {}', pid_path)
    
    async def start(self):
        await self.loop.run_until_complete(self.run())
    
    async def before_run(self):
        self.started_at = datetime.now()
        self.running.set()
    
    async def run(self):
        await self.lock_pid()
        try:
            await self.before_run()
            async with TaskGroup() as task_group:
                tasks = []
                for routine in self.routines:
                    tasks.append(task_group.create_task(routine))
                
                while self.running.is_set():
                    if self.request_shutdown.is_set():
                        for task in tasks:
                            task.cancel()
                        break
                    
                    await self.update(self.context)
                    await sleep(self.context.delay)
            await self.after_run()
        finally:
            await self.unlock_pid()
    
    async def after_run(self):
        self.logger.info('ran for {} days {} hours {:02d}:{:02d} (since {})',
                         format_dhms(self.running.elapsed / 1000),
                         compact_datetime(self.started_at))
        self.running.clear()
    
    async def on_terminate(self):
        self.shutdown()
    
    async def _shutdown_wait(self):
        try:
            await wait_for(self.shutdown_clean.wait(),
                           timeout=self.shutdown_timeout)
            self.logger.info('shutdown took {}',
                             format_ms(self.request_shutdown.elapsed))
        except TimeoutError:
            delta = self.request_shutdown.elapsed - (self.shutdown_timeout / 1000)
            self.logger.error('exceeded shutdown timeout by {}', format_ms(delta))
            self.stop()
    
    def shutdown(self):
        if not self.request_shutdown.is_set():
            self.logger.info('shutdown requested')
            self.request_shutdown.set()
            
            create_task(self._shutdown_wait())
        else:
            self.logger.warning('shutdown already pending')
    
    def stop(self):
        self.logger.info('loop stopped')
        self.loop.stop()
