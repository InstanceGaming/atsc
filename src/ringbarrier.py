#  Copyright 2022 Jacob Jewett
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

from core import FrozenIdentifiableBase, IdentifiableBase
from typing import List
from dataclasses import dataclass


@dataclass(frozen=True)
class Ring(FrozenIdentifiableBase):
    phases: List[int]


class Barrier(IdentifiableBase):
    
    @property
    def phases(self):
        return self._phases

    def __init__(self, id_: int, phases: List[int]):
        super().__init__(id_)
        self._phases = phases
        self.cycle_count = 0
