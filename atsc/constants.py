import os
from enum import IntEnum, IntFlag


SHUTDOWN_POLL_RATE = 0.1
ABSOLUTE_MAXIMUM_RATE = 100.0
MINIMUM_INPUTS_RATE = 1.0
MAXIMUM_INPUTS_RATE = 40.0
MINIMUM_BUS_RATE = 1.0
MAXIMUM_BUS_RATE = 20.0
MINIMUM_NETWORK_RATE = 1.0
MAXIMUM_NETWORK_RATE = 40.0
MINIMUM_FLASH_RATE = 54.0
MAXIMUM_FLASH_RATE = 66.0

SERIAL_BUS_CRC_POLY = 0x11021
SERIAL_BUS_CRC_INIT = 0xFFFF
SERIAL_BUS_CRC_REVERSE = True
SERIAL_BUS_CRC_XOR_OUT = 0
SERIAL_BUS_BYTE_ORDER = 'big'


class StandardObjects(IntEnum):
    CONTROLLER = 1
    
    # virtual clocks
    TIME_TICK = 901
    INPUTS_TICK = 902
    BUS_TICK = 903
    NETWORK_TICK = 904
    FLASH_TICK = 905
    
    # virtual flashers
    FLASHER1 = 1001
    FLASHER2 = 1002

    # rings
    RING1 = 701
    RING2 = 702
    RING3 = 703
    RING4 = 704
    
    # barriers
    BARRIER1 = 801
    BARRIER2 = 802
    BARRIER3 = 803
    BARRIER4 = 804
    
    # parameters
    P_CONTROLLER_NAME = 8001
    
    P_TIME_RATE = 8100
    P_INPUTS_RATE = 8101
    P_BUS_RATE = 8102
    P_NETWORK_RATE = 8103
    P_FPM = 8104
    
    E_CLOCK = 10001
    E_FLASHER = 10002
    E_PARAMETER_CHANGED = 10003
    
    E_FIELD_OUTPUT_STATE_CHANGED = 10100
    E_FIELD_OUTPUT_TOGGLED = 10101
    E_LOAD_SWITCH_UPDATED = 10101
    E_SIGNAL_CHANGED = 10102
    E_SIGNAL_IDLE_START = 10103


class ExitCode(IntEnum):
    DIRECT_CALL_REQUIRED = 1
    LOG_LEVEL_PARSE_FAIL = 2
    LOG_FILE_STRUCTURE_FAIL = 3
    LOG_FACILITY_FAIL = 4
    PID_CREATE_FAIL = 5
    PID_EXISTS = 6
    PID_REMOVE_FAIL = 7


def get_default_pid_path():
    return os.path.join(os.getcwd(), 'atsc.pid')


class FlashChannel(IntFlag):
    RED = 1
    YELLOW = 2


class OperationMode(IntEnum):
    DARK = 0
    CET = 1  # Control entrance transition
    CXT = 2  # Control exit transition
    LS_FLASH = 3
    NORMAL = 4


class FieldState(IntFlag):
    OFF = 0
    ON = 1
    FLASHING = 2
    INHERIT = 3


class SignalState(IntEnum):
    
    @property
    def shorthand(self):
        match self:
            case SignalState.OFF:
                return 'OFF'
            case SignalState.STOP:
                return 'STP'
            case SignalState.CAUTION:
                return 'CAU'
            case SignalState.GO:
                return 'GO '
            case SignalState.FYA:
                return 'FYA'
            case SignalState.LS_FLASH:
                return 'LSF'
            case _:
                raise NotImplementedError()
    
    OFF = 0
    STOP = 1
    CAUTION = 2
    GO = 4
    FYA = 8
    LS_FLASH = 16


class LSFlag(IntEnum):
    DISABLED = 0
    STANDARD = 0b00000001
    PED = 0b00000010
    PED_CLEAR = 0b00000100
    FYA = 0b00001000
    FYA_OUT_C = 0b00010000
    FYA_OUT_B = 0b00100000
    YEL_FLASH = 0b01000000


class RingState(IntFlag):
    INACTIVE = 0x0
    SELECTING = 0x1
    ACTIVE = 0x2
    RED_CLEARANCE = 0x4
    BARRIER = 0x8


class BusState(IntFlag):
    STANDBY = 0
    INIT = 1
    ACTIVE = 2
    DEGRADED = 4
    FAILED = 8


class CallSource(IntFlag):
    UNKNOWN = 0
    INPUT = 1
    SYSTEM = 2
    RECALL = 4
    REMOTE = 8


class InputAction(IntEnum):
    NOTHING = 0
    CALL = 1
    DETECT = 2
    PREEMPTION = 3
    TIME_FREEZE = 4
    
    PED_CLEAR_INHIBIT = 5
    FYA_INHIBIT = 6
    CALL_INHIBIT = 7
    REDUCE_INHIBIT = 8
    
    MODE_DARK = 9
    MODE_NORMAL = 10
    MODE_LS_FLASH = 11


class InputActivation(IntEnum):
    LOW = 1
    HIGH = 2
    RISING = 3
    FALLING = 4
