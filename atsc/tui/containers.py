from atsc.tui.panels import HomePanel, ConnectingPanel
from textual.widgets import ContentSwitcher


class MainContentSwitcher(ContentSwitcher):
    
    def __init__(self):
        super().__init__(
            HomePanel(id='home-panel', expand=True),
            ConnectingPanel(id='connecting-panel', expand=True),
            initial='home-panel'
        )
