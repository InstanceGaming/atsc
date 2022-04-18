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
from core import Phase, IntervalType, OperationMode
from utils import condText
from typing import Dict, List, Tuple, Optional, FrozenSet
from natsort import natsorted
from datetime import datetime
from timespan import (Timespan,
                      day_of_year,
                      datetime_month,
                      datetime_weekday,
                      sort_overlap_duration)
from functools import lru_cache
from dataclasses import dataclass
from ringbarrier import Ring, Barrier


@dataclass(frozen=True)
class PhaseTimesheet:
    minimums: Dict[IntervalType, int]  # seconds
    maximums: Dict[IntervalType, int]  # seconds
    targets: Dict[IntervalType, int]  # seconds

    def getRange(self, it: IntervalType) -> range:
        return range(self.minimums[it], self.maximums[it])

    def getValues(self, it: IntervalType) -> Tuple[int, int, int]:
        return self.minimums[it], self.targets[it], self.maximums[it]

    def getTargetOrMin(self, it: IntervalType) -> int:
        target = self.targets[it]
        return target if target > 0 else self.minimums[it]

    def getMinMax(self, it: IntervalType) -> Tuple[int, int]:
        return self.minimums[it], self.maximums[it]

    def getRangeText(self, it: IntervalType) -> str:
        text = ''
        min_value = self.minimums[it]
        target = self.targets[it]
        max_value = self.maximums[it]

        if min_value != 0:
            text += f'{min_value}>'

        text += target if target != 0 else '-'

        if max_value != 0:
            text += f'<{max_value}'

        return text

    def getAllIntervalsRangeText(self) -> str:
        segments = []

        for it in IntervalType:
            segments.append(f'{it.name}={self.getRangeText(it)}')

        return ' '.join(segments)

    def __repr__(self):
        return f'<PhaseTimesheet {self.getAllIntervalsRangeText()}>'


@dataclass
class Schedule:
    enabled: bool
    name: str
    activation_blocks: FrozenSet[Timespan]
    mode: OperationMode
    free: bool
    phases: FrozenSet[Phase]
    rings: List[Ring]
    barriers: List[Barrier]
    timesheets: Dict[Phase, PhaseTimesheet]
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

    def __repr__(self):
        return f'<Schedule "{self.name}" {"ENABLED" if self.enabled else ""} ' \
               f'{self.getActivationBlocksText()} ' \
               f'{self.mode.name} {"FREE" if self.free else "TIMED"}' \
               f'{len(self.phases)} phases ' \
               f'{len(self.rings)} rings {len(self.barriers)} barriers ' \
               f'{len(self.timesheets)} timesheets>'


class ScheduleManager:
    LOG = logging.getLogger('atsc.scheduling')

    @property
    def active(self) -> Schedule:
        return self._active

    @property
    def timespan(self) -> Optional[Timespan]:
        return self._timespan

    @property
    def timesheets(self) -> Dict[Phase, PhaseTimesheet]:
        return self._active.timesheets

    @property
    def mode(self) -> OperationMode:
        return self._active.mode

    @property
    def free(self) -> bool:
        return self._active.free

    @property
    def rings(self) -> List[Ring]:
        return self._active.rings

    @property
    def barriers(self) -> List[Barrier]:
        return self._active.barriers

    @property
    def phases(self) -> FrozenSet[Phase]:
        return self._active.phases

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
        return natsorted(self._schedules, key=lambda s: s.name)

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
            ts_text = condText(f'and changed block to {ts.getDurationText()}',
                               paren=True)

        self.LOG.info(f'Changed schedule to "{s.name}"{ts_text}')
