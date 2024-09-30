from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Label, Static, LoadingIndicator
from atsc.tui.widgets import ControllerRuntime, Signal


class HomePanel(Static):
    
    def compose(self) -> ComposeResult:
        yield Label('Home')


class ConnectingPanel(Static):
    
    def compose(self) -> ComposeResult:
        yield LoadingIndicator()


class ControllerPanel(Static):
    
    def __init__(self,
                 id: str,
                 field_output_count: int,
                 phase_count: int,
                 signal_count: int):
        super().__init__(id=id, expand=True)
        self.field_output_count = field_output_count
        self.phase_count = phase_count
        self.signal_count = signal_count
        self.signals = []
        
        for i in range(1, self.signal_count + 1):
            self.signals.append(Signal(i))
    
    def compose(self) -> ComposeResult:
        yield ControllerRuntime()
        yield Grid(*self.signals, id='signal-grid')
