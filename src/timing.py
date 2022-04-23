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
from typing import Optional


def micros() -> int:
    return perf_counter_ns() // 1000


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
    micros,
    millis,
    seconds,
    minutes,
    hours,
    days
]


class HardwareTimer:

    @property
    def marker(self) -> int:
        return self._marker

    @property
    def trigger(self) -> Optional[int]:
        return self._trigger

    @trigger.setter
    def trigger(self, v):
        if v < 0:
            raise ValueError('Trigger must be a positive integer')

        self._trigger = v

    @property
    def polling(self) -> bool:
        if self._trigger is not None:
            return self._trigger > 0
        return False

    @property
    def pause(self) -> bool:
        return self._pause

    @pause.setter
    def pause(self, v: bool):
        if not v:
            self._marker = self._ref()

        self._pause = v

    def __init__(self,
                 reference,
                 trigger: Optional[int] = None,
                 pause: bool = False):
        if reference not in _TIMING_STANDALONE_FUNCS:
            raise ValueError('Timer reference can only be one of the '
                             'functions defined in timing.py')
        self._ref = reference
        self._marker: int = self._ref()

        self._trigger: Optional[int] = trigger
        self._pause = pause

        self._last_remaining = 0
        self._last_delta = 0

    def __lt__(self, other):
        if other is not None:
            return self.marker < other.marker
        return False

    def getMarkerGoal(self) -> int:
        if self._trigger is not None:
            return self._marker + self._trigger
        return 0

    def getDelta(self) -> int:
        if self.pause:
            return self._last_delta
        else:
            rv = (self._ref() - self._marker) or 0
            self._last_delta = rv
            return rv

    def getRemaining(self) -> int:
        if self.pause:
            return self._last_remaining
        else:
            if self._trigger is None:
                return 0
            else:
                rv = self._trigger - self.getDelta()
                self._last_remaining = rv
                return rv

    def poll(self) -> bool:
        if self._trigger is not None:
            return self.getDelta() >= self._trigger

    def reset(self):
        self._marker = self._ref()


class MillisecondTimer(HardwareTimer):

    def __init__(self,
                 trigger: Optional[int] = None,
                 pause: bool = False):
        super(MillisecondTimer, self).__init__(millis,
                                               trigger=trigger,
                                               pause=pause)

    def getSeconds(self) -> int:
        return self.getDelta() // 1000

    def getMinutes(self) -> int:
        return self.getSeconds() // 60

    def getHours(self) -> int:
        return self.getMinutes() // 60

    def getDays(self) -> int:
        return self.getHours() // 24


class SecondTimer(HardwareTimer):

    def __init__(self,
                 trigger: Optional[int] = None,
                 pause: bool = False):
        super(SecondTimer, self).__init__(seconds,
                                          trigger=trigger,
                                          pause=pause)

    def getMinutes(self) -> int:
        return self.getDelta() // 60

    def getHours(self) -> int:
        return self.getMinutes() // 60

    def getDays(self) -> int:
        return self.getHours() // 24


class MinuteTimer(HardwareTimer):

    def __init__(self,
                 trigger: Optional[int] = None,
                 pause: bool = False):
        super(MinuteTimer, self).__init__(minutes,
                                          trigger=trigger,
                                          pause=pause)

    def getHours(self) -> int:
        return self.getDelta() // 60

    def getDays(self) -> int:
        return self.getHours() // 24
