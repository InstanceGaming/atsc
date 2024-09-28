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
from typing import Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass(slots=True)
class Context:
    rate: float
    scale: float
    
    @property
    def delay(self):
        return self.scale / self.rate


@dataclass(slots=True, frozen=True)
class CommonCommandLineArguments:
    log_levels_notation: str
    rpc_port: int
    log_path: Optional[Path] = None
    pid_path: Optional[Path] = None
    tick_rate: Optional[float] = None
    tick_scale: Optional[float] = None
