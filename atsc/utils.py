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
import re
import platform
from enum import Enum
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Type, Tuple, Union, Optional, Iterable, List
from bitarray import bitarray
from datetime import datetime


def fix_path(raw: Optional[str]) -> Optional[Path]:
    if raw:
        norm = os.path.normpath(raw.strip())
        expanded = os.path.expandvars(os.path.expanduser(norm))
        return Path(expanded)
    return None


def fix_paths(paths: Iterable[Optional[str]]) -> List[Optional[Path]]:
    rv = []
    for path in paths:
        rv.append(fix_path(path))
    return rv


def uniform_key_name(raw_name: str) -> str:
    name = raw_name.lower().strip()
    name = re.sub(r'^(\d)+', '', name)
    name = re.sub(r'([^a-z\d_])+', '_', name)
    return name


def bits_from_bytearray(ib: bytearray) -> bitarray:
    bit = bitarray()
    bit.frombytes(bytes(ib))
    return bit


def format_ms(ms):
    if ms < 1000:
        if isinstance(ms, float):
            return f'{ms:01.2f}ms'
        return f'{ms}ms'
    elif 1000 <= ms < 60000:
        secs = ms / 1000
        return f'{secs:01.2f}s'
    elif 3600000 > ms >= 60000:
        mins = ms / 60000
        return f'{mins:01.2f}m'
    elif 86400000 > ms >= 3600000:
        hrs = ms / 3600000
        return f'{hrs:01.2f}h'
    elif ms >= 86400000:
        dys = ms / 86400000
        return f'{dys:01.2f}d'


def format_us(us):
    if us < 1000:
        if isinstance(us, float):
            return f'{us:01.2f}us'
        return f'{us}us'
    else:
        return format_ms(us / 1000)


def pretty_timedelta(td, prefix=None, format_spec=None):
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


def pretty_bin_literal(ba: Union[bytearray, bytes]) -> str:
    if isinstance(ba, bytes):
        ba = bytearray(ba)
    return ' '.join([format(b, '08b') for b in ba])


def pretty_byte_size(size: int, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(size) < 1024.0:
            return "%3d%s%s" % (size, unit, suffix)
        size /= 1024.0
    return "%.1f%s%s" % (size, 'Yi', suffix)


def compact_datetime(dt: datetime, tz=None) -> str:
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


def deltas(items):
    d = []
    for i, item in enumerate(items):
        if i:
            prev = items[i - 1]
            d.append(item - prev)
    return d


def stride_range(strides, index):
    stride = strides[index]
    if index == 0:
        return range(0, stride + 1)
    else:
        d = deltas(strides)
        left = stride - d[index - 1] + 1
        return range(left, stride + 1)


def dhms(seconds) -> Tuple[int, int, int, int]:
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


def short_enum_name(e: Enum):
    if e is not None:
        return e.name[0:3]
    return ''


def default_enum(et: Type[Enum], value: Any) -> dict:
    rv = {}
    for i in [e.value for e in et]:
        rv.update({i: value})
    return rv


def field_representation(a, b, c):
    first = 'R' if a else '-'
    second = 'Y' if b else '-'
    third = 'G' if c else '-'
    return f'{first}{second}{third}'


def conditional_text(msg, paren=False, prefix=' ', postfix='', cond=False):
    if msg is not None or cond:
        if paren:
            return f'{prefix}({msg}){postfix}'
        return f'{prefix}{msg}{postfix}'
    return ''


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


_TIMING_FUNCS = [micros, millis, seconds, minutes, hours, days]


def text_to_enum(et: Type[Enum], v, to_length=None, dash_underscore=True):
    """
    Attempt to return the matching enum next_state based off of
    the text tag of a next_state.

    :param et: enum type
    :param v: string representation of an enum next_state
    :param to_length: only match to this many chars
    :param dash_underscore: make dash equal to underscore character
    :return: enum next_state of type e or None if was None
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


def format_fields(a, b, c, colored=False):
    r = '<r>R</r>' if colored else 'R'
    y = '<y>Y</y>' if colored else 'Y'
    g = '<g>G</g>' if colored else 'G'
    off = '<d>-</d>' if colored else '-'
    first = r if a else off
    second = y if b else off
    third = g if c else off
    return first + second + third
