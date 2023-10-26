import asyncio
import os
from datetime import datetime
from typing import Optional, Union, TextIO, Set, List

from jacob.datetime.formatting import format_ms, compact_datetime, format_dhms
from jacob.datetime.timing import seconds
from atsc.common.primitives import AsyncDaemon, StopwatchEvent
from atsc.controller.constants import SHUTDOWN_POLL_RATE


class Controller(AsyncDaemon):
    
    def __init__(self,
                 logger,
                 flashers: Set[Flasher],
                 signals: List[Signal],
                 rings: List[Ring],
                 barriers: List[Barrier],
                 pid_path: Optional[os.PathLike] = None,
                 time_rate: float = 1.0,
                 flashes_per_minute: float = 60.0,
                 shutdown_timeout: float = 10,
                 loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()):
        AsyncDaemon.__init__(self, logger, loop=loop)
        eventbus.listeners[StandardObjects.E_FIELD_OUTPUT_STATE_CHANGED].append(self.on_field_output_changed)
        self._runnables: Set[Runnable] = set()
        
        self.pid_file: Optional[Union[os.PathLike, TextIO]] = pid_path
        
        self.shutdown_timeout = shutdown_timeout
        self.request_shutdown = StopwatchEvent()
        self.shutdown_clean = StopwatchEvent()
        self.flashers = flashers
        self.signals = signals
        
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
        
        self._bus = SerialBus('COM4', 115200, loop=self.loop)
        self.add_runnable(self._bus)
        
        self._synchronizer = RingCycler(rings, barriers)
        self.add_runnable(self._synchronizer)
    
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
                self.logger.info('runtime {} days {} hours {:02d}:{:02d}', *format_dhms(runtime))
                self.logger.info('control was started at {}', compact_datetime(start_dt))
        finally:
            await self.unlock_pid()
    
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
            self.stop()
