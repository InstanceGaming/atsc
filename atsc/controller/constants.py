from enum import IntEnum, auto, Enum


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


class FlashChannel(Enum):
    RED = auto()
    YELLOW = auto()


class OperationMode(Enum):
    DARK = auto()
    CET = auto()
    CXT = auto()
    LS_FLASH = auto()
    NORMAL = auto()


class FieldState(Enum):
    OFF = auto()
    ON = auto()
    FLASHING = auto()
    INHERIT = auto()


class SignalState(IntEnum):
    STOP = 1
    CAUTION = 2
    REDUCE = 3
    GO = 4
    FYA = 5
    LS_FLASH = 6


class RingState(Enum):
    INACTIVE = auto()
    SELECTING = auto()
    ACTIVE = auto()
    RED_CLEARANCE = auto()
    BARRIER = auto()


class CallSource(Enum):
    UNKNOWN = auto()
    SYSTEM = auto()
    RECALL = auto()
    FIELDBUS = auto()
    NETWORK = auto()


class InputAction(Enum):
    NOTHING = auto()
    CALL = auto()
    DETECT = auto()
    PREEMPTION = auto()
    TIME_FREEZE = auto()
    
    PED_CLEAR_INHIBIT = auto()
    FYA_INHIBIT = auto()
    CALL_INHIBIT = auto()
    REDUCE_INHIBIT = auto()
    
    MODE_DARK = auto()
    MODE_NORMAL = auto()
    MODE_LS_FLASH = auto()


class InputActivation(Enum):
    LOW = auto()
    HIGH = auto()
    RISING = auto()
    FALLING = auto()


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
