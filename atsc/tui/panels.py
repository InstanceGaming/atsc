#  Copyright 2024 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import math
from typing import Iterable, Dict
from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Label, Static, LoadingIndicator
from atsc.tui.widgets import SignalWidget, FieldOutputWidget
from textual.containers import Grid, Horizontal, Vertical
from atsc.tui.components import ControllerTopbar


class HomePanel(Static):
    
    def compose(self) -> ComposeResult:
        yield Label('Home')


class ConnectingPanel(Static):
    
    def compose(self) -> ComposeResult:
        yield LoadingIndicator()


class ControllerPanel(Static):
    
    def __init__(self,
                 id: str,
                 started_at: datetime,
                 field_outputs: Dict[int, FieldOutputWidget],
                 signals: Iterable[SignalWidget]):
        super().__init__(id=id)
        self.started_at = started_at
        self.field_outputs = field_outputs
        self.column_count = math.ceil(len(self.field_outputs) / 3)
        self.signals = signals
    
    def compose(self) -> ComposeResult:
        yield ControllerTopbar(self.started_at)
        
        try:
            with Horizontal():
                fo_iterator = iter(self.field_outputs.values())
                for i in range(self.column_count):
                    with Vertical(classes='column'):
                        yield next(fo_iterator)
                        yield next(fo_iterator)
                        yield next(fo_iterator)
        except StopIteration:
            pass
        
        yield Grid(*self.signals, id='signal-grid')
