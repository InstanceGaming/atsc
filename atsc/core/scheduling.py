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

import logging
from typing import List, Tuple, Optional, FrozenSet
from datetime import datetime

from atsc.utils import conditional_text
from timespan import (Timespan,
                      day_of_year,
                      datetime_month,
                      datetime_weekday,
                      sort_overlap_duration)
from functools import lru_cache
from dataclasses import dataclass


@dataclass
class Schedule:
    enabled: bool
    name: str
    activation_blocks: FrozenSet[Timespan]
    free: bool
    last_active: Optional[datetime] = None

    def getRankedBlocks(self,
                        current: datetime,
                        doy=True,
                        weekdays=True,
                        months=True) -> List[Timespan]:
        """
        Get activation timespans overlapping with the current datetime ordered
        by duration remaining of the overlap from most to least. Will
        unconditionally return the only block if the size of `activation_blocks`
        is one. Can return an empty list if no blocks overlap.

        Will entirely omit blocks under the following conditions:
         - If the `current` day-of-year is an exception when `doy` is True.
         - If the `current` weekday is an exception when `weekdays` is True.
         - If the `current` day-of-month is an exception when `months` is True.

        :param current: the datetime now
        :param doy: enable day-of-year check
        :param weekdays: enable weekday check
        :param months: enable day-of-month check
        :return: an ordered list of timespans
        """
        if len(self.activation_blocks) > 1:
            usable = []
            for block in self.activation_blocks:
                if doy:
                    if day_of_year(current) in block.day_exceptions:
                        continue

                if weekdays:
                    if datetime_weekday(current) not in block.weekdays:
                        continue

                if months:
                    if datetime_month(current) not in block.months:
                        continue

                if block.overlap(current):
                    usable.append(block)

            usable.sort(key=lambda b: sort_overlap_duration(b, current))
            return usable
        else:
            if len(self.activation_blocks) > 0:
                return [list(self.activation_blocks)[0]]
            return []

    def getActivationBlocksText(self) -> str:
        return ', '.join([b.getDurationText() for b in self.activation_blocks])

    def __hash__(self):
        return hash(self.name)


class ScheduleManager:
    LOG = logging.getLogger('atsc.scheduling')

    @property
    def active(self) -> Schedule:
        return self._active

    @property
    def timespan(self) -> Optional[Timespan]:
        return self._timespan

    @property
    def free(self) -> bool:
        return self._active.free

    def __init__(self,
                 schedules: FrozenSet[Schedule],
                 tz=None):
        self._tz = tz
        self._schedules = schedules
        self._active: Schedule = self.getDefaultSchedule()
        self.LOG.info(f'Default schedule is "{self._active.name}"')
        self._timespan: Optional[Timespan] = None

    @lru_cache(32)
    def getAlphabetical(self) -> List[Schedule]:
        return sorted(self._schedules, key=lambda s: s.name)

    @lru_cache(32)
    def getScheduleByName(self, name: str) -> Schedule:
        for sch in self._schedules:
            if sch.name == name:
                return sch

        raise RuntimeError(f'Failed to locate schedule "{name}"')

    def getDefaultSchedule(self) -> Schedule:
        rv = None

        for sch in self.getAlphabetical():
            if sch.enabled:
                rv = sch

        return rv

    def getNextSchedule(self) -> Tuple[Schedule, Optional[Timespan]]:
        for sch in self.getAlphabetical():
            if sch.enabled:
                blocks = sch.getRankedBlocks(datetime.now(self._tz))

                if len(blocks) > 0:
                    chosen_timespan = blocks[0]
                    self.LOG.debug(f'Next schedule is '
                                   f'"{sch.name}" with timespan '
                                   f'{chosen_timespan.getDurationText()}')
                    return sch, chosen_timespan
        return self.getDefaultSchedule(), None

    def setActive(self, s: Schedule, ts: Optional[Timespan] = None):
        s.last_active = datetime.now(self._tz)
        self._active = s
        self._timespan = ts

        ts_text = ''
        if ts is not None:
            ts_text = conditional_text(f'and changed block to '
                                       f'{ts.getDurationText()}', paren=True)

        self.LOG.info(f'Changed schedule to "{s.name}"{ts_text}')
