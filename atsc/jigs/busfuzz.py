import asyncio
import random
from asyncio import AbstractEventLoop, get_event_loop
from typing import Optional

from loguru import logger

from atsc import fieldbus
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.fieldbus.frames import InputStateFrame
from atsc.fieldbus.constants import DeviceAddress


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
        
        self.fieldbus = fieldbus.SerialBus(context, 'COM5', 115200, loop=loop)
        
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
