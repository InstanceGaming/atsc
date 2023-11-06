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

import sys
import logging
from enum import Enum
from typing import Type, Tuple, Union
from bitarray import bitarray


def configureLogger(log):
    handler = logging.StreamHandler(sys.stdout)
    
    # noinspection PyUnreachableCode
    if __debug__:
        log.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter('{levelname:>8}: {message} [{name}@{lineno}]',
                                               datefmt='%x %H:%M:%S',
                                               style='{'))
    else:
        log.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('{levelname:>8}: {message}', style='{'))
    
    log.handlers = []
    log.addHandler(handler)


def prettyBinaryLiteral(ba: Union[bytearray, bytes]) -> str:
    if isinstance(ba, bytes):
        ba = bytearray(ba)
    return ' '.join([format(b, '08b') for b in ba])


def prettyByteSize(size: int, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(size) < 1024.0:
            return "%3d%s%s" % (size, unit, suffix)
        size /= 1024.0
    return "%.1f%s%s" % (size, 'Yi', suffix)


def getIPAddress(filter_if_name: str):
    from netifaces import AF_INET, ifaddresses
    
    interface = ifaddresses(filter_if_name)
    protocol = interface[AF_INET]
    return protocol[0]['addr']


def dhmsText(seconds) -> Tuple[int, int, int, int]:
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


def textToEnum(et: Type[Enum], v, to_length=None, dash_underscore=True):
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


def formatFields(a, b, c, colored=False):
    r = '<r>R</r>' if colored else 'R'
    y = '<y>Y</y>' if colored else 'Y'
    g = '<g>G</g>' if colored else 'G'
    off = '<d>-</d>' if colored else '-'
    first = r if a else off
    second = y if b else off
    third = g if c else off
    return first + second + third
