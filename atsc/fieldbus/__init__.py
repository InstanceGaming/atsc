import asyncio
from atsc.common.primitives import AsyncDaemon


class FieldBus(AsyncDaemon):
    
    @property
    def port(self):
        return self._port
    
    @property
    def baud_rate(self):
        return self._baud
    
    def __init__(self,
                 logger,
                 port: str,
                 baud_rate: int,
                 loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()):
        super().__init__(logger, loop)
        self._port = port
        self._baud = baud_rate
        
    def start(self):
        pass
    
    async def run(self):
        pass
