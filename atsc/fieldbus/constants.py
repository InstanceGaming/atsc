from enum import IntEnum


HDLC_FLAG = 0x7E
HDLC_ESCAPE = 0x7D
HDLC_ESCAPE_MASK = 0x20

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
