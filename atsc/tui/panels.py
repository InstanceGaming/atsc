from typing import List

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
    
    @property
    def field_output_count(self):
        return len(self.field_output_ids)
    
    @property
    def signal_count(self):
        return len(self.signal_ids)
    
    @property
    def phase_count(self):
        return len(self.phase_ids)
    
    def __init__(self,
                 id: str,
                 field_output_ids: List[int],
                 signal_ids: List[int],
                 phase_ids: List[int]):
        super().__init__(id=id, expand=True)
        self.field_output_ids = field_output_ids
        self.signal_ids = signal_ids
        self.phase_ids = phase_ids
        
        self.signals = []
        
        for id in self.signal_ids:
            self.signals.append(Signal(id))
    
    def compose(self) -> ComposeResult:
        yield ControllerRuntime()
        yield Grid(*self.signals, id='signal-grid')
