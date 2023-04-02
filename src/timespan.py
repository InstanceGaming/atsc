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

import re
from enum import IntEnum
from utils import condText, textToEnum, compactDatetime
from typing import Set, List, Tuple, Optional
from datetime import tzinfo, datetime, timedelta
from dateutil.parser import ParserError
from dateutil.parser import parse as _dt_parser


def is_midnight(dt: datetime) -> bool:
    return dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def datetime_overlap(start: datetime, current: datetime, end: datetime) -> bool:
    """Whether current datetime is in the range start through end"""
    return start <= current <= end


DAYS_IN_YEAR = 366


class Month(IntEnum):
    JAN = 0
    FEB = 1
    MAR = 2
    APR = 3
    MAY = 4
    JUN = 5
    JUL = 6
    AUG = 7
    SEP = 8
    OCT = 9
    NOV = 10
    DEC = 11


SUMMER_MONTHS = [Month.JUN, Month.JUL]

WINTER_MONTHS = [Month.NOV, Month.DEC, Month.JAN, Month.FEB]

SPRING_MONTHS = [Month.MAR, Month.APR, Month.MAY]

FALL_MONTHS = [Month.AUG, Month.SEP, Month.OCT]

HOLIDAY_MONTHS = [Month.NOV, Month.DEC]


class Weekday(IntEnum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


WEEKEND = [Weekday.SAT, Weekday.SUN]

WORKDAYS = [Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI]


def day_of_month(dt: datetime) -> int:
    return dt.timetuple()[2]


def day_of_year(dt: datetime) -> int:
    return dt.timetuple()[7]


def week_index(dt: datetime) -> int:
    return dt.timetuple()[6]


def datetime_weekday(dt: datetime) -> Weekday:
    index = week_index(dt)
    return Weekday(index)


def datetime_month(dt: datetime) -> Month:
    index = day_of_month(dt)
    return Month(index)


def is_dst(dt: datetime) -> int:
    return dt.timetuple()[8]


class Timespan:
    
    @property
    def start_stamp(self) -> int:
        return round(self._start.timestamp())
    
    @property
    def end_stamp(self) -> int:
        return round(self._end.timestamp())
    
    @property
    def stamp_range(self):
        return range(self.start_stamp, self.end_stamp)
    
    @property
    def start_midnight(self) -> bool:
        return is_midnight(self.start)
    
    @property
    def end_midnight(self):
        return is_midnight(self.end)
    
    @property
    def day_aligned(self):
        """
        If the whole timespan is evenly aligned to a day (that the start and
        end are both midnight).
        """
        return self.start_midnight and self.end_midnight
    
    @property
    def tz_aware(self):
        return self.start.tzinfo is not None and self.start.utcoffset() is not None and self.end.tzinfo is not None and self.end.utcoffset() is not None
    
    @property
    def delta(self) -> timedelta:
        return self.end - self.start
    
    @property
    def start(self):
        return self._start
    
    @start.setter
    def start(self, v: datetime):
        self._start = v
        self._validate()
    
    @property
    def end(self):
        return self._end
    
    @end.setter
    def end(self, v: datetime):
        self._end = v
        self._validate()
    
    @property
    def weekdays(self):
        return self._weekdays
    
    @property
    def months(self):
        return self._months
    
    @property
    def day_exceptions(self):
        return self._day_exceptions
    
    @property
    def reoccuring(self) -> bool:
        """
        If this instance defines weekdays or months
        """
        return len(self._weekdays) > 0 or len(self._months) > 0
    
    def __init__(self, start: datetime, end: datetime, weekdays=None, months=None, day_exceptions=None):
        self._start: datetime = start
        self._end: datetime = end
        self._weekdays: Set[Weekday] = weekdays or set()
        self._months: Set[Month] = months or set()
        self._day_exceptions: Set[int] = day_exceptions or set()
        self._validate()
    
    def overlap(self, other: datetime) -> bool:
        return datetime_overlap(self.start, other, self.end)
    
    def has_exception(self, other: datetime) -> bool:
        return day_of_year(other) in self._day_exceptions
    
    def _validate(self):
        assert isinstance(self._start, datetime)
        assert isinstance(self._end, datetime)
        
        if self._start == self._end:
            raise RuntimeError('start and end are the same')
        elif self._end < self._start:
            raise RuntimeError('end of timespan before start')
        
        tz_s = self._start.tzinfo
        tz_e = self._end.tzinfo
        
        if tz_s is not None and tz_e is not None:
            if tz_s != tz_e:
                raise RuntimeError('start and end have differing tzinfo data')
            
            if is_dst(self._start) != is_dst(self._end):
                raise RuntimeError('start and end have differing DST states')
        
        weekday_size = len(self._weekdays)
        if weekday_size > len(Weekday):
            raise RuntimeError('weekdays set cannot be larger '
                               'than Weekday enum')
        
        for weekday in self._weekdays:
            if not isinstance(weekday, Weekday):
                raise TypeError('weekdays entry must be Weekday type')
        
        months_size = len(self._months)
        if months_size > len(Month):
            raise RuntimeError('months set cannot be larger '
                               'than Month enum')
        
        for month in self._months:
            if not isinstance(month, Month):
                raise TypeError('months entry must be Month type')
        
        day_indices_size = len(self._day_exceptions)
        if day_indices_size == DAYS_IN_YEAR:
            raise RuntimeError('day exceptions set cannot encompass an '
                               'entire year')
        elif day_indices_size > DAYS_IN_YEAR:
            raise RuntimeError('day exceptions set cannot be larger '
                               'than a year')
        
        for day_index in self._day_exceptions:
            if not isinstance(day_index, int):
                raise TypeError('day exception must be an integer')
            
            if day_index == 0 or day_index > DAYS_IN_YEAR:
                raise ValueError('day exception index out-of-bounds')
    
    def __lt__(self, other):
        if self.overlap(other):
            return False
        
        if self.end < other.end:
            if self.start < other.start:
                return True
        return False
    
    def __repr__(self):
        return f'<timespan {self.getDurationText()}' \
               f'{condText(self.getWeekdaysText())}' \
               f'{condText(self.getMonthsText())}' \
               f' {len(self._day_exceptions)} exceptions>'
    
    def getWeekdaysText(self) -> str:
        return ','.join([w.name for w in self._weekdays])
    
    def getMonthsText(self) -> str:
        return ','.join([m.name for m in self._months])
    
    def getDurationText(self) -> str:
        return f'{compactDatetime(self.start)} to ' \
               f'{compactDatetime(self.end)}'


WEEKDAYS_CSV_PATTERN = re.compile(r'^(workdays|weekdays)$|'
                                  r'^((mon|tue|wed|thu|fri|sat|sun+)'
                                  r'(,*(mon|tue|wed|thu|fri|sat|sun)+)*)$', flags=re.IGNORECASE)

MONTHS_CSV_PATTERN = re.compile(r'^(holidays|summer|winter|spring|fall)$|'
                                '(^((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|'
                                'nov|dec)+)(,*(jan|feb|mar|apr|may|jun|jul|aug|'
                                'sep|oct|nov|dec)+)*$)', flags=re.IGNORECASE)


def parse_datetime_text(text: str, tz):
    rv = _dt_parser(text, dayfirst=False, yearfirst=False, ignoretz=True, fuzzy=False)
    return rv.replace(tzinfo=tz)


def parse_timespan_text(raw_calendar_value,
                        day_exceptions_list: List[int],
                        raw_start_text: str,
                        raw_end_text: str,
                        tz: tzinfo
                        ) -> Tuple[Optional[Timespan], Optional[str]]:
    weekdays = None
    months = None
    
    # parse calendar values
    if raw_calendar_value is not None:
        cleaned_calendar = ' '.join(raw_calendar_value.strip().split()).upper()
        calendar_text_parts = cleaned_calendar.split(' ')
        calendar_used_parts = set()
        
        # identify weekdays range or shorthand forms
        for part in calendar_text_parts:
            results = WEEKDAYS_CSV_PATTERN.match(part)
            if results:
                shorthand_text = results.group(1)
                weekdays_csv_text = results.group(2)
                
                if shorthand_text is not None:
                    if shorthand_text == 'WORKDAYS':
                        weekdays = set(WORKDAYS)
                    elif shorthand_text == 'WEEKEND':
                        weekdays = set(WEEKEND)
                else:
                    if weekdays_csv_text is not None:
                        weekdays_csv = weekdays_csv_text.split(',')
                        weekdays = set()
                        for csvalue in weekdays_csv:
                            weekday_enum = textToEnum(Weekday, csvalue)
                            weekdays.add(weekday_enum)
                
                calendar_used_parts.add(part)
                break
        
        # identify months range or shorthand forms
        for part in calendar_text_parts:
            results = MONTHS_CSV_PATTERN.match(part)
            if results:
                shorthand_text = results.group(1)
                months_csv_text = results.group(2)
                
                if shorthand_text is not None:
                    if shorthand_text == 'HOLIDAYS':
                        months = set(HOLIDAY_MONTHS)
                    elif shorthand_text == 'SUMMER':
                        months = set(SUMMER_MONTHS)
                    elif shorthand_text == 'FALL':
                        months = set(FALL_MONTHS)
                    elif shorthand_text == 'WINTER':
                        months = set(WINTER_MONTHS)
                    elif shorthand_text == 'SPRING':
                        months = set(SPRING_MONTHS)
                else:
                    if months_csv_text is not None:
                        months_csv = months_csv_text.split(',')
                        months = set()
                        for csvalue in months_csv:
                            month_enum = textToEnum(Month, csvalue)
                            months.add(month_enum)
                
                calendar_used_parts.add(part)
                break
        
        # remaining segments are considered an error
        remaining_parts = set(calendar_text_parts) - calendar_used_parts
        
        if len(remaining_parts) > 0:
            unrecognized = ', '.join([f'"{us}"' for us in remaining_parts])
            return None, f'{len(remaining_parts)} unused calendar ' \
                         f'tokens ({unrecognized})'
        
        if weekdays is None and months is None:
            return None, 'calendar value defined but no data was parsed'
    
    # gather day exception indices
    day_exceptions = set()
    
    for day_index in day_exceptions_list:
        if day_index == 0 or day_index > DAYS_IN_YEAR:
            return None, f'exception index {day_index} out-of-bounds'
        
        if day_exceptions_list.count(day_index) > 1:
            return None, f'redefinition of exception index {day_index}'
        
        day_exceptions.add(day_index)
    
    cleaned_start = ' '.join(raw_start_text.strip().split()).upper()
    
    try:
        start_dt = parse_datetime_text(cleaned_start, tz)
    except ParserError as e:
        return None, f'could not parse start value: {str(e)}'
    
    cleaned_end = ' '.join(raw_end_text.strip().split()).upper()
    
    try:
        end_dt = parse_datetime_text(cleaned_end, tz)
    except ParserError as e:
        return None, f'could not parse end value: {str(e)}'
    
    ts = Timespan(start_dt, end_dt, weekdays=weekdays, months=months, day_exceptions=day_exceptions)
    
    return ts, None


def sort_overlap_duration(ts: Timespan, current: datetime) -> int:
    """
    Get sorting key of remaining duration relative to the current time only
    if overlapping.
    """
    if not ts.overlap(current):
        return 0
    
    remaining = round((ts.end - current).total_seconds())
    return remaining
