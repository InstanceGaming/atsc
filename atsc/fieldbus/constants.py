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
from enum import IntEnum


HDLC_FLAG = 0x7E
HDLC_ESCAPE = 0x7D
HDLC_ESCAPE_MASK = 0x20
HDLC_MAX_FRAME_LENGTH = 0x80

SERIAL_BUS_CRC_POLY = 0x11021
SERIAL_BUS_CRC_INIT = 0xFFFF
SERIAL_BUS_CRC_REVERSE = True
SERIAL_BUS_CRC_XOR_OUT = 0
SERIAL_BUS_BYTE_ORDER = 'big'


class DeviceAddress(IntEnum):
    UNKNOWN = 0x00
    CONTROLLER = 0xFF
    TFIB1 = 0x08


class FrameType(IntEnum):
    UNKNOWN = 0
    AWK = 1
    NAK = 2
    IGN = 3
    BEACON = 4
    OUTPUTS = 16
    INPUTS = 32


class HDLCError(IntEnum):
    UNKNOWN = 1
    FLAG = 2
    EMPTY = 3
    NO_CRC = 4
    BAD_CRC = 5
    TOO_SHORT = 6
    TOO_LONG = 7
    NO_DATA = 8
