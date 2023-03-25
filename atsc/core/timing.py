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
from time import perf_counter_ns
from typing import Callable


def millis() -> int:
    return perf_counter_ns() // 1000000


def seconds() -> int:
    return millis() // 1000


def minutes() -> int:
    return seconds() // 60


def hours() -> int:
    return minutes() // 60


def days() -> int:
    return hours() // 24


_TIMING_STANDALONE_FUNCS = [
    millis,
    seconds,
    minutes,
    hours,
    days
]


class SystemTimer:

    @property
    def marker(self):
        return self._marker

    def __init__(self,
                 reference,
                 trigger_init: int):
        if reference not in _TIMING_STANDALONE_FUNCS:
            raise ValueError('timer reference can only be one of the '
                             'functions defined in timing.py')

        self._ref: Callable = reference
        self._marker: int = self._ref()
        self.trigger = trigger_init

    def __lt__(self, other):
        assert isinstance(other, SystemTimer)
        return self._marker < other.marker

    def delta(self) -> int:
        return self._ref() - self._marker

    def poll(self) -> bool:
        return self.delta() > self.trigger

    def reset(self):
        self._marker = self._ref()
