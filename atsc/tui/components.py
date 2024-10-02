import asyncio
from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Label, Static
from atsc.tui.widgets import (
    ControllerCycleMode,
    ControllerTimeFreeze,
    ControllerDatetimeReadout,
    ControllerDurationReadout, ControllerCycleCount
)


class Banner(Static):
    
    def __init__(self,
                 title: str,
                 description: str | None = None,
                 classes: str | None = None,
                 timeout: float = 0.0):
        super().__init__(classes=f'banner {classes or ""}', expand=True)
        self.title = title
        self.description = description
        self.timeout = timeout
        
        if timeout > 0.0:
            self.run_worker(self.remove_in(timeout))
    
    async def remove_in(self, timeout: float):
        await asyncio.sleep(timeout)
        self.call_later(self.remove())
    
    def compose(self) -> ComposeResult:
        yield Label(self.title, classes='title')
        if self.description:
            yield Label(self.description)


class ControllerTopbar(Static):
    
    def __init__(self, started_at: datetime):
        super().__init__()
        self.started_at = started_at
    
    def compose(self) -> ComposeResult:
        yield ControllerCycleCount()
        yield ControllerTimeFreeze()
        yield ControllerCycleMode()
        yield ControllerDatetimeReadout(self.started_at)
        yield ControllerDurationReadout()
