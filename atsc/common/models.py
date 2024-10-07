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
import os
import time
import signal
from abc import ABC
from loguru import logger
from typing import List, TextIO, Optional, Coroutine
from asyncio import (
    Task,
    Event,
    AbstractEventLoop,
    sleep,
    wait_for,
    create_task,
    get_event_loop
)
from pathlib import Path
from datetime import datetime
from atsc.common.structs import Context
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT, ExitCode
from jacob.datetime.timing import seconds
from atsc.common.primitives import Tickable, StopwatchEvent
from jacob.datetime.formatting import format_ms, format_dhms, compact_datetime


class AsyncDaemon(Tickable, ABC):
    
    @property
    def started_at_monotonic_delta(self):
        return seconds() - self.started_at_monotonic
    
    def __init__(self,
                 context: Context,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        super().__init__()
        self.loop = loop
        self.pid_file = pid_file
        self.shutdown_timeout = shutdown_timeout
        self.context = context
        self.started_at_epoch: Optional[int] = None
        self.started_at_monotonic: Optional[int] = None
        self.ticking = True
        
        self.routines: List[Coroutine] = []
        self.tasks: List[Task] = []
        self.running = StopwatchEvent()
        self.request_shutdown = StopwatchEvent()
        self.shutdown_clean = Event()
        
        for sig in signal.valid_signals():
            try:
                signal.signal(sig, lambda s, f: self.loop.create_task(self.signal_handler(s, f)))
            except OSError as e:
                # certain signals are still not valid depending on OS
                logger.debug('failed to attach signal handler {}: {}', sig.name, str(e))
    
    async def signal_handler(self, sig, _):
        match sig:
            case signal.SIGTERM | signal.SIGINT:
                logger.info('signal {} received', sig)
                await self.on_terminate()
            case unhandled_signal:
                logger.warning('unhandled signal {} received', unhandled_signal)
    
    async def lock_pid(self):
        pid = os.getpid()
        if self.pid_file is None:
            logger.info('process #{} (file disabled)', pid)
        else:
            assert isinstance(self.pid_file, os.PathLike)
            abs_path = Path(self.pid_file).absolute()
            
            try:
                file = open(abs_path, 'x')
                file.write(str(pid))
                file.flush()
                logger.info('process #{} ({})', pid, abs_path)
                self.pid_file = file
            except FileExistsError:
                logger.error('process already running ({})', abs_path)
                return ExitCode.PID_EXISTS
            except OSError as e:
                logger.error('could not create process lock at {}: {}', abs_path, str(e))
                return ExitCode.PID_CREATE_FAIL
        return ExitCode.OK
    
    async def unlock_pid(self):
        if self.pid_file is not None:
            assert isinstance(self.pid_file, TextIO)
            
            pid_path = os.path.realpath(self.pid_file.name)
            if not self.pid_file.closed:
                self.pid_file.close()
            
            try:
                os.remove(pid_path)
            except OSError as e:
                logger.error('could not remove PID file at {}: {}', pid_path, str(e))
                return ExitCode.PID_REMOVE_FAIL
            
            logger.info('removed PID file at {}', pid_path)
        return ExitCode.OK
    
    async def before_run(self):
        self.started_at_epoch = round(time.time())
        self.started_at_monotonic = seconds()
        self.running.set()
        
        for routine in self.routines:
            self.tasks.append(self.loop.create_task(routine))
    
    async def run(self) -> int:
        pid_lock_result = await self.lock_pid()
        
        if pid_lock_result is not ExitCode.OK:
            return pid_lock_result
        
        try:
            await self.before_run()
            while self.running.is_set():
                if self.request_shutdown.is_set():
                    break
                
                if self.ticking:
                    self.tick(self.context)
                await sleep(self.context.delay)
            await self.after_run()
        finally:
            pid_unlock_result = await self.unlock_pid()
            
            if pid_unlock_result is not ExitCode.OK:
                return pid_unlock_result
        
        self.shutdown_clean.set()
        return ExitCode.OK
    
    async def after_run(self):
        logger.debug('canceling {} tasks', len(self.tasks))
        
        for task in self.tasks:
            task.cancel()
        
        monotonic_delta = seconds() - self.started_at_monotonic
        ed, eh, em, es = format_dhms(monotonic_delta)
        started_at_dt = datetime.fromtimestamp(self.started_at_epoch)
        formatted_timestamp = compact_datetime(started_at_dt)
        logger.info('runtime of {} days, {} hours, {} minutes and {} seconds '
                    '(since {})',
                    ed, eh, em, es, formatted_timestamp)
        
        self.running.clear()
    
    async def on_terminate(self):
        self.shutdown()
    
    async def _shutdown_wait(self):
        try:
            await wait_for(self.shutdown_clean.wait(),
                           timeout=self.shutdown_timeout)
            logger.info('shutdown took {}',
                        format_ms(self.request_shutdown.elapsed))
        except TimeoutError:
            delta = self.request_shutdown.elapsed - (self.shutdown_timeout / 1000)
            logger.error('exceeded shutdown timeout by {}', format_ms(delta))
        
    def shutdown(self):
        if not self.request_shutdown.is_set():
            logger.info('shutdown requested')
            self.request_shutdown.set()
            
            create_task(self._shutdown_wait())
        else:
            logger.warning('shutdown already pending')
