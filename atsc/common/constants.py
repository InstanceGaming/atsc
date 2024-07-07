from enum import IntEnum

from jacob.logging import CustomLevel


CUSTOM_LOG_LEVELS = {
    CustomLevel(10, 'bus_tx'),
    CustomLevel(11, 'bus_rx'),
    CustomLevel(12, 'bus'),
    CustomLevel(20, 'net'),
    CustomLevel(25, 'fields'),
    CustomLevel(35, 'verbose'),
    CustomLevel(40, 'debug'),
    CustomLevel(50, 'info'),
    CustomLevel(90, 'warning'),
    CustomLevel(100, 'error'),
    CustomLevel(200, 'critical')
}


class ExitCode(IntEnum):
    DIRECT_CALL_REQUIRED = 1
    LOG_LEVEL_PARSE_FAIL = 2
    LOG_FILE_STRUCTURE_FAIL = 3
    LOG_FACILITY_FAIL = 4
    PID_CREATE_FAIL = 5
    PID_EXISTS = 6
    PID_REMOVE_FAIL = 7
