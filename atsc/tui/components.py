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
import asyncio
from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Label, Static
from atsc.tui.widgets import (
    ControllerCycleMode,
    ControllerCycleCount,
    ControllerTimeFreeze,
    ControllerDatetimeReadout,
    ControllerDurationReadout
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
