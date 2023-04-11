from enum import IntEnum


VERSION = '2.1.0'
START_BANNER = f'Actuated Traffic Signal Controller v{VERSION} by Jacob Jewett'
FLOAT_ROUND_PLACES = 2
SECONDS_WEEK = 604800
SECONDS_DAY = 86400
SECONDS_HOUR = 3600
SECONDS_MINUTE = 60


class ExitCode(IntEnum):
    OK                                      = 0x0000000
    LOGGER_INVALID                          = 0x1000001
    LOGGER_FILE_CREATION_FAILED             = 0x1000002
    CONFIG_NOT_FOUND                        = 0x1000010
    CONFIG_OPEN_FAILED                      = 0x1000011
    CONFIG_INVALID_SCHEMA                   = 0x1000012
    CONFIG_INVALID_DATA                     = 0x1000013
    CONFIG_MERGE_FAILED                     = 0x1000014
    CONFIG_VERSION_UNKNOWN                  = 0x1000016
    SCHEMA_ERROR                            = 0x1000017
    BUS_START_FAILED                        = 0x3000001
    BUS_START_TIMEOUT                       = 0x3000002
    BUS_CRITICAL_RETRY_EXHAUSTED            = 0x3000003
    UNEXPECTED_SHUTDOWN                     = 0x3FFFFFF
    UNKNOWN                                 = 0xFFFFFFF
