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
import asyncio
from io import TextIOWrapper
from abc import ABC
from loguru import logger
from typing import List, Optional, Coroutine
from pathlib import Path
from datetime import datetime
from atsc.common import utils
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT, ExitCode
from jacob.datetime.timing import seconds
from jacob.datetime.formatting import format_ms, format_dhms, compact_datetime


class AsyncDaemon(ABC):
    
    @property
    def started_at_monotonic_delta(self):
        return seconds() - self.started_at_monotonic
    
    def __init__(self,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()):
        super().__init__()
        self.loop = loop
        self.pid_file = pid_file
        
        self.started_at_epoch = round(time.time())
        self.started_at_monotonic = seconds()
        
        self.tasks: List[asyncio.Task] = []
        
        self.running = asyncio.Event()
        self.shutdown_task = None
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_begin = utils.StopwatchEvent()
        self.shutdown_complete = asyncio.Event()
        
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
                self.shutdown()
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
            assert isinstance(self.pid_file, TextIOWrapper)
            
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
    
    def add_task(self, coro: Coroutine, name: Optional[str] = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task
    
    async def before_run(self):
        self.started_at_epoch = round(time.time())
        self.started_at_monotonic = seconds()
        self.running.set()
        
        return ExitCode.OK
    
    async def run(self) -> int:
        pid_lock_result = await self.lock_pid()
        
        if pid_lock_result is not ExitCode.OK:
            return pid_lock_result
        
        try:
            result = await self.before_run()
            
            if result != ExitCode.OK:
                return result
            
            if len(self.tasks) and self.running.is_set():
                try:
                    await asyncio.gather(*self.tasks)
                except Exception:
                    self.shutdown()
                    raise
                except asyncio.CancelledError:
                    pass
            
            result = await self.after_run()
            
            if result != ExitCode.OK:
                return result
        finally:
            pid_unlock_result = await self.unlock_pid()
            
            if pid_unlock_result is not ExitCode.OK:
                return pid_unlock_result
        
        return ExitCode.OK
    
    async def after_run(self):
        monotonic_delta = seconds() - self.started_at_monotonic
        ed, eh, em, es = format_dhms(monotonic_delta)
        started_at_dt = datetime.fromtimestamp(self.started_at_epoch)
        formatted_timestamp = compact_datetime(started_at_dt)
        logger.info('runtime of {} days, {} hours, {} minutes and {} seconds '
                    '(since {})',
                    ed, eh, em, es, formatted_timestamp)
        
        return ExitCode.OK
    
    async def _shutdown_wait(self):
        while True:
            incomplete = [t for t in self.tasks if not t.done()]
            if incomplete:
                logger.debug('waiting for {} tasks to return', len(incomplete))
                logger.verbose('pending tasks: {}', ', '.join([t.get_name() for t in incomplete]))
                await asyncio.sleep(1.0)
            else:
                break
        
        self.shutdown_complete.set()
        logger.info('shutdown complete ({})',
                    format_ms(self.shutdown_begin.elapsed))
    
    def shutdown(self):
        if not self.shutdown_begin.is_set():
            logger.info('shutdown begin')
            
            self.shutdown_begin.set()
            self.running.clear()
            
            logger.debug('canceling {} tasks', len(self.tasks))
            for task in self.tasks:
                task.cancel()
            
            self.shutdown_task = asyncio.create_task(self._shutdown_wait())
        else:
            logger.warning('shutdown already pending')
