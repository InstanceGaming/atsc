from typing import Iterable, Optional
from asyncio import AbstractEventLoop, get_event_loop
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.controller.models import Ring, Barrier, RingCycler


class SimpleController(AsyncDaemon):
    
    def __init__(self,
                 context: Context,
                 rings: Iterable[Ring],
                 barriers: Iterable[Barrier],
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self.cycler = RingCycler(rings, barriers)
        self.routines.append(self.cycler.run())
