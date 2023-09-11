import signal
import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, TextIO, Union, Set, List
from atsc.models import Flasher, Clock, BarrierManager, Ring, Barrier
from atsc import parameters, eventbus
from atsc.primitives import StopwatchEvent, Runnable, Referencable
from atsc.constants import *
from atsc.utils import format_ms, seconds, dhms, compact_datetime


class AsyncProgram(Runnable, ABC):
    
    def __init__(self,
                 logger,
                 loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()):
        self.loop = loop
        self.logger = logger
        
        for sig in signal.valid_signals():
            signal.signal(sig, lambda s, f: self.loop.create_task(self.signal_handler(s, f)))
    
    async def start(self):
        await self.loop.run_until_complete(self.run())
    
    async def signal_handler(self, sig, _):
        match sig:
            case signal.SIGTERM | signal.SIGINT:
                self.logger.info('signal {} received', sig)
                await self.on_terminate()
            case unhandled_signal:
                self.logger.warning('unhandled signal {} received', unhandled_signal)
    
    async def on_terminate(self):
        pass
    
    @abstractmethod
    async def run(self):
        pass
    
    def die(self):
        self.loop.stop()



class Daemon(AsyncProgram, Referencable):
    
    def __init__(self,
                 logger,
                 rings: List[Ring],
                 barriers: List[Barrier],
                 pid_path: Optional[os.PathLike] = None,
                 time_rate: float = 1.0,
                 flashes_per_minute: float = 60.0,
                 shutdown_timeout: float = 10,
                 loop: AbstractEventLoop = asyncio.get_event_loop()):
        Referencable.__init__(self, StandardObjects.CONTROLLER)
        AsyncProgram.__init__(self, logger, loop=loop)
        eventbus.listeners[StandardObjects.FLASH_TICK].add(
            self.print_field_states
        )
        self._runnables: Set[Runnable] = set()

        self.pid_file: Optional[Union[os.PathLike, TextIO]] = pid_path
        
        self.shutdown_timeout = shutdown_timeout
        self.request_shutdown = StopwatchEvent()
        self.shutdown_clean = StopwatchEvent()
        
        self.add_runnable(Clock(StandardObjects.TIME_TICK,
                                parameters.TimeRate(time_rate)))
        self.add_runnable(Clock(StandardObjects.INPUTS_TICK,
                                parameters.InputsRate(20.0)))
        self.add_runnable(Clock(StandardObjects.BUS_TICK,
                                parameters.BusRate(20.0)))
        self.add_runnable(Clock(StandardObjects.NETWORK_TICK,
                                parameters.NetworkRate(20.0)))
        self.add_runnable(Clock(StandardObjects.FLASH_TICK,
                                parameters.FlashRate(flashes_per_minute)))
        self.flasher = Flasher(StandardObjects.FLASHER1)
        
        self.add_runnable(BarrierManager(
            barriers,
            rings
        ))
    
    def print_field_states(self, flasher: Flasher):
        self.logger.field('{}')
    
    def add_runnable(self, r):
        self._runnables.add(r)
    
    async def lock_pid(self):
        pid = os.getpid()
        if self.pid_file is None:
            self.logger.info('PID {} (file disabled)', pid)
        else:
            assert isinstance(self.pid_file, os.PathLike)
            abs_path = Path(self.pid_file).absolute()
            
            try:
                file = open(abs_path, 'x')
                file.write(str(pid))
                file.flush()
                self.logger.info('PID {} ({})', pid, abs_path)
                self.pid_file = file
            except FileExistsError:
                self.logger.error('already running ({})', abs_path)
                exit(ExitCode.PID_EXISTS)
            except OSError as e:
                self.logger.error('could not create PID file at {}: {}', abs_path, str(e))
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
    
    def start(self):
        self.loop.run_until_complete(self.run())
    
    async def run(self):
        await self.lock_pid()
        try:
            start_dt = datetime.now()
            runtime_marker = seconds()
            
            self.logger.info('control started at {}', compact_datetime(start_dt))
            
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(r.run()) for r in self._runnables]

                while True:
                    if self.request_shutdown.is_set():
                        for task in tasks:
                            task.cancel()
                        break
                    await asyncio.sleep(SHUTDOWN_POLL_RATE)
                
                self.shutdown_clean.set()
                runtime = seconds() - runtime_marker
                self.logger.info('runtime {} days {} hours {:02d}:{:02d}', *dhms(runtime))
                self.logger.info('control was started at {}', compact_datetime(start_dt))
        finally:
            await self.unlock_pid()
    
    async def on_terminate(self):
        await self.shutdown()
    
    async def shutdown(self):
        self.logger.info('shutdown requested')
        self.request_shutdown.set()
        try:
            await asyncio.wait_for(self.shutdown_clean.wait(),
                                   timeout=self.shutdown_timeout)
            self.logger.info('shutdown took {}', format_ms(self.request_shutdown.elapsed))
        except TimeoutError:
            diff = format_ms(self.request_shutdown.elapsed - (self.shutdown_timeout / 1000))
            self.logger.error('exceeded shutdown timeout by {}', diff)
            self.die()


class CommandLine(AsyncProgram):
    
    def __init__(self,
                 logger,
                 cla: Dict[str, Any],
                 loop: AbstractEventLoop = asyncio.get_event_loop()):
        super().__init__(logger, loop=loop)
        self.cla = cla
    
    async def run(self):
        pass
