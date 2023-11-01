import loguru
from jacob.logging import setup_logger
from atsc.controller.implementations import SimpleController
from atsc.common.structs import Context
from atsc.controller.models import Ring, Phase, Signal, Barrier, FieldOutput, IntervalConfig
from atsc.controller.constants import LOGGING_LEVELS, SignalState


logger = setup_logger('FIELD,DEBUG;stderr=ERROR', LOGGING_LEVELS)
loguru.logger = logger


context = Context(10.0, 1.0)

fields = [FieldOutput(n) for n in range(1, 37)]


def vehicle_config(field_group):
    return {
        SignalState.STOP   : IntervalConfig(field_group[0], 1.0),
        SignalState.CAUTION: IntervalConfig(field_group[1], 3.0, 6.0, restable=False, collect=True),
        SignalState.REDUCE : IntervalConfig(field_group[2], 1.0, 3.0, reduce=True),
        SignalState.GO     : IntervalConfig(field_group[2], 10.0)
    }

def ped_config(field_group):
    return {
        SignalState.STOP   : IntervalConfig(field_group[0], 1.0),
        SignalState.CAUTION: IntervalConfig(field_group[0], 10.0, restable=False, flashing=True),
        SignalState.GO     : IntervalConfig(field_group[1], 3.0)
    }

signals = [
    Signal(1, vehicle_config(fields[0:3])),
    Signal(2, ped_config((fields[12], fields[14]))),
    Signal(3, vehicle_config(fields[3:6])),
    Signal(4, ped_config((fields[15], fields[17])))
]

phases = [
    Phase(1, signals[0:2]),
    Phase(2, signals[2:5])
]

rings = [
    Ring(1, phases, 1.0)
]
barriers = [
    Barrier(1, [phases[0]]),
    Barrier(2, [phases[1]])
]

SimpleController(context, rings, barriers).start()
