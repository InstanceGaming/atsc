import asyncio
from textual.app import ComposeResult
from textual.widgets import Static, ContentSwitcher, Label

from atsc.tui.panels import ConnectingPanel, HomePanel


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


class MainContentSwitcher(ContentSwitcher):
    
    def __init__(self):
        super().__init__(
            HomePanel(id='home-panel', expand=True),
            ConnectingPanel(id='connecting-panel', expand=True),
            initial='home-panel'
        )
