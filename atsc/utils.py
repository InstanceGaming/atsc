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
import os
import sys
import platform
from enum import Enum
from loguru import logger
from typing import Type, Tuple, Union, Callable
from datetime import datetime
from functools import partialmethod


def register_logging_levels():
    logger.level('SORT', no=1, color='<d>')
    logger.__class__.sort = partialmethod(logger.__class__.log, 'SORT')
    logger.level('BUS', no=2, color='<d>')
    logger.__class__.bus = partialmethod(logger.__class__.log, 'BUS')
    logger.level('NET', no=3, color='<d>')
    logger.__class__.net = partialmethod(logger.__class__.log, 'NET')
    logger.level('VERB', no=7, color='<c>')
    logger.__class__.verb = partialmethod(logger.__class__.log, 'VERB')


def default_logger(level,
                   color=True,
                   dev=True,
                   timestamp=True):
    fmt = '[{thread: 8}] <level>{level: >8}</level>: {message}'

    if timestamp:
        fmt = '[{time:ddd MMM DD hh:mm:ss.SS A}]' + fmt

    if dev:
        fmt += ' <d>[<i>{file}:{line}</i>]</d>'

    logger.remove()
    logger.add(sys.stdout, colorize=color, level=level, format=fmt)
    return logger.opt(ansi=color)


def format_ms_elapsed(before, now):
    return format_ms(now - before)


def format_ms(milliseconds):
    if milliseconds is not None:
        if milliseconds <= 1000:
            if isinstance(milliseconds, float):
                return f'{milliseconds:04.2f}ms'
            return f'{milliseconds:04d}ms'
        elif 1000 < milliseconds <= 60000:
            seconds = milliseconds / 1000
            return f'{seconds:02.2f}s'
        elif milliseconds > 60000:
            minutes = milliseconds / 60000
            return f'{minutes:02.2f}min'
    return None


def format_td(td, prefix=None, format_spec=None):
    prefix = prefix if not None else ''
    format_spec = format_spec if format_spec is not None else '02.2f'

    if td is not None:
        seconds = td.total_seconds()
        if seconds < 60:
            return prefix + format(seconds, format_spec) + ' seconds'
        elif 60 <= seconds < 3600:
            return prefix + format(seconds / 60, format_spec) + ' minutes'
        elif 3600 <= seconds < 86400:
            return prefix + format(seconds / 3600, format_spec) + ' hours'
        elif 86400 <= seconds:
            return prefix + format(seconds / 86400, format_spec) + ' days'
    return None


def format_bin_literal(ba: Union[bytearray, bytes]) -> str:
    if isinstance(ba, bytes):
        ba = bytearray(ba)
    return ' '.join([format(b, '08b') for b in ba])


def format_byte_size(size: int, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(size) < 1024.0:
            return "%3d%s%s" % (size, unit, suffix)
        size /= 1024.0
    return "%.1f%s%s" % (size, 'Yi', suffix)


def compact_dt(dt: datetime, tz=None) -> str:
    if platform.system() == 'Windows':
        no_pad_char = '#'
    else:
        no_pad_char = '-'

    now = datetime.now(tz)
    time_part = dt.time()
    date_part = dt.date()

    if time_part.minute == 0:
        time_fmt = f'%{no_pad_char}I%p'
    else:
        time_fmt = f'%{no_pad_char}I:%M%p'

    time_text = time_part.strftime(time_fmt).lower()
    date_text = ''
    year_text = ''

    if date_part is not None:
        if date_part != now.date():
            date_text = date_part.strftime(f'%b %{no_pad_char}d')

            yearpart = date_part.year
            if yearpart != now.year:
                year_text = f', {yearpart} '
            else:
                date_text += ' '

    return f'{date_text}{year_text}{time_text}'


def interface_address(filter_if_name: str):
    from netifaces import AF_INET, ifaddresses

    interface = ifaddresses(filter_if_name)
    protocol = interface[AF_INET]
    return protocol[0]['addr']


def format_dhms(seconds) -> Tuple[int, int, int, int]:
    seconds_to_minute = 60
    seconds_to_hour = 60 * seconds_to_minute
    seconds_to_day = 24 * seconds_to_hour

    days = seconds // seconds_to_day
    seconds %= seconds_to_day

    hours = seconds // seconds_to_hour
    seconds %= seconds_to_hour

    minutes = seconds // seconds_to_minute
    seconds %= seconds_to_minute

    seconds = seconds

    return days, hours, minutes, seconds


def ellipsize_enum(e: Enum):
    if e is not None:
        return e.name[0:3]
    return ''


def format_fields(a, b, c, colored=False):
    r = '<r>R</r>' if colored else 'R'
    y = '<y>Y</y>' if colored else 'Y'
    g = '<g>G</g>' if colored else 'G'
    off = '<d>-</d>' if colored else '-'
    first = r if a else off
    second = y if b else off
    third = g if c else off
    return first + second + third


def conditional_text(msg, paren=False, prefix=' ', postfix='', cond=False):
    if msg is not None or cond:
        if paren:
            return f'{prefix}({msg}){postfix}'
        return f'{prefix}{msg}{postfix}'
    return ''


def text_to_enum(et: Type[Enum],
                 v,
                 to_length=None,
                 dash_underscore=True):
    """
    Attempt to return the matching enum value based off of
    the text name of a value.

    :param et: enum type
    :param v: string representation of an enum value
    :param to_length: only match to this many chars
    :param dash_underscore: make dash equal to underscore character
    :return: enum value of type e or None if was None
    :raises ValueError: if text could not be mapped to type
    """
    if v is None:
        return None

    v = v.strip().lower()

    if dash_underscore:
        v = v.replace('-', '_')

    for e in et:
        name = e.name.lower()
        if isinstance(to_length, int):
            if v[0:to_length] == name[0:to_length]:
                return v
        else:
            if v == name:
                return e
    raise ValueError(f'Could not match "{v}" to {str(et)}')


def cmp_key_args(cmp_func: Callable, *args, **kwargs):
    """Convert a cmp= function into a key= function and pass args"""

    class Comparator:
        __hash__ = None
        __slots__ = ['obj']

        def __init__(self, obj):
            self.obj = obj

        def __lt__(self, other):
            return cmp_func(self.obj, other.obj, *args, **kwargs) < 0

        def __gt__(self, other):
            return cmp_func(self.obj, other.obj, *args, **kwargs) > 0

        def __eq__(self, other):
            return cmp_func(self.obj, other.obj, *args, **kwargs) == 0

        def __le__(self, other):
            return cmp_func(self.obj, other.obj, *args, **kwargs) <= 0

        def __ge__(self, other):
            return cmp_func(self.obj, other.obj, *args, **kwargs) >= 0

    return Comparator


def get_config_schema_path() -> str:
    entry_script_dir = os.path.abspath(os.path.dirname(__file__))
    config_schema_path = os.path.join(entry_script_dir,
                                      'schemas',
                                      'configuration.json')
    return config_schema_path
