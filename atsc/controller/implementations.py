import asyncio
from typing import Optional
from asyncio import AbstractEventLoop, get_event_loop

from loguru import logger

from atsc.common.models import AsyncDaemon
from atsc.common.primitives import ref
from atsc.common.structs import Context
from atsc.controller.constants import SignalState, FieldState
from atsc.controller.models import Ring, Barrier, RingCycler, IntervalTiming, Signal, Phase, FieldOutput, IntervalConfig


class SimpleController(AsyncDaemon):
    
    def __init__(self,
                 context: Context,
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self.interval_timing_vehicle = {
            SignalState.LS_FLASH: IntervalTiming(4.0, rest=True),
            SignalState.STOP    : IntervalTiming(1.0, rest=True),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.REDUCE  : IntervalTiming(2.0, 4.0),
            SignalState.GO      : IntervalTiming(2.0, 5.0),
            SignalState.FYA     : IntervalTiming(4.0, rest=True)
        }
        self.interval_config_vehicle = {
            SignalState.LS_FLASH: IntervalConfig(flashing=True),
            SignalState.STOP    : IntervalConfig(),
            SignalState.CAUTION : IntervalConfig(),
            SignalState.REDUCE  : IntervalConfig(),
            SignalState.GO      : IntervalConfig(),
            SignalState.FYA     : IntervalConfig(flashing=True)
        }
        self.interval_timing_ped = {
            SignalState.STOP   : IntervalTiming(1.0, rest=True),
            SignalState.CAUTION: IntervalTiming(10.0),
            SignalState.GO     : IntervalTiming(5.0)
        }
        self.interval_config_ped = {
            SignalState.STOP    : IntervalConfig(),
            SignalState.CAUTION : IntervalConfig(flashing=True),
            SignalState.GO      : IntervalConfig()
        }
        self.field_outputs = [FieldOutput(100 + i) for i in range(1, 49)]
        self.signals = [
            Signal(
                501,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(101, FieldOutput),
                    SignalState.STOP    : ref(101, FieldOutput),
                    SignalState.CAUTION : ref(102, FieldOutput),
                    SignalState.REDUCE  : ref(103, FieldOutput),
                    SignalState.GO      : ref(103, FieldOutput)
                }
            ),
            Signal(
                502,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(104, FieldOutput),
                    SignalState.STOP    : ref(104, FieldOutput),
                    SignalState.CAUTION : ref(105, FieldOutput),
                    SignalState.REDUCE  : ref(106, FieldOutput),
                    SignalState.GO      : ref(106, FieldOutput)
                }, recall=True
            ),
            Signal(
                503,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(107, FieldOutput),
                    SignalState.STOP    : ref(107, FieldOutput),
                    SignalState.CAUTION : ref(108, FieldOutput),
                    SignalState.REDUCE  : ref(109, FieldOutput),
                    SignalState.GO      : ref(109, FieldOutput)
                }
            ),
            Signal(
                504,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(110, FieldOutput),
                    SignalState.STOP    : ref(110, FieldOutput),
                    SignalState.CAUTION : ref(111, FieldOutput),
                    SignalState.REDUCE  : ref(112, FieldOutput),
                    SignalState.GO      : ref(112, FieldOutput)
                }
            ),
            Signal(
                505,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(113, FieldOutput),
                    SignalState.STOP    : ref(113, FieldOutput),
                    SignalState.CAUTION : ref(114, FieldOutput),
                    SignalState.REDUCE  : ref(115, FieldOutput),
                    SignalState.GO      : ref(115, FieldOutput)
                }
            ),
            Signal(
                506,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(116, FieldOutput),
                    SignalState.STOP    : ref(116, FieldOutput),
                    SignalState.CAUTION : ref(117, FieldOutput),
                    SignalState.REDUCE  : ref(118, FieldOutput),
                    SignalState.GO      : ref(118, FieldOutput)
                }, recall=True
            ),
            Signal(
                507,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(119, FieldOutput),
                    SignalState.STOP    : ref(119, FieldOutput),
                    SignalState.CAUTION : ref(120, FieldOutput),
                    SignalState.REDUCE  : ref(121, FieldOutput),
                    SignalState.GO      : ref(121, FieldOutput)
                }
            ),
            Signal(
                508,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH: ref(122, FieldOutput),
                    SignalState.STOP    : ref(122, FieldOutput),
                    SignalState.CAUTION : ref(123, FieldOutput),
                    SignalState.REDUCE  : ref(124, FieldOutput),
                    SignalState.GO      : ref(124, FieldOutput)
                }
            ),
            Signal(
                509,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP    : ref(125, FieldOutput),
                    SignalState.CAUTION : ref(125, FieldOutput),
                    SignalState.GO      : ref(127, FieldOutput)
                }
            ),
            Signal(
                510,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP    : ref(128, FieldOutput),
                    SignalState.CAUTION : ref(128, FieldOutput),
                    SignalState.GO      : ref(130, FieldOutput)
                }
            ),
            Signal(
                511,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP    : ref(131, FieldOutput),
                    SignalState.CAUTION : ref(131, FieldOutput),
                    SignalState.GO      : ref(133, FieldOutput)
                }
            ),
            Signal(
                512,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP    : ref(134, FieldOutput),
                    SignalState.CAUTION : ref(134, FieldOutput),
                    SignalState.GO      : ref(136, FieldOutput)
                }
            )
        ]
        self.phases = [
            Phase(601, [self.signals[0]]),
            Phase(602, [self.signals[1], self.signals[8]]),
            Phase(603, [self.signals[2]]),
            Phase(604, [self.signals[3], self.signals[9]]),
            Phase(605, [self.signals[4]]),
            Phase(606, [self.signals[5], self.signals[10]]),
            Phase(607, [self.signals[6]]),
            Phase(608, [self.signals[7], self.signals[11]])
        ]
        self.rings = [
            Ring(701, self.phases[0:4], 1.0),
            Ring(702, self.phases[4:8], 1.0)
        ]
        self.barriers = [
            Barrier(801, self.phases[0:2] + self.phases[4:6]),
            Barrier(802, self.phases[2:4] + self.phases[6:8])
        ]
        self.cycler = RingCycler(self.rings, self.barriers)
        self.children.append(self.cycler)
        self.routines.append(self.cycler.run())
        self.routines.append(self.print_fields_debug())
        
        for ring in self.rings:
            ring.recall_all()
    
        self._previous_fields_line = ''
    
    def update(self, context: Context):
        # for breakpoint with context
        super().update(context)
    
    async def print_fields_debug(self):
        while True:
            label = ''
            line = ''
            for i, field_output in enumerate(self.field_outputs, start=1):
                match field_output.state:
                    case FieldState.FLASHING:
                        symbol = 'F'
                    case FieldState.ON:
                        symbol = 'S'
                    case _:
                        symbol = '.'
                label += str(i)[-1]
                line += symbol
            
            if line != self._previous_fields_line:
                self._previous_fields_line = line
                logger.fields(label)
                logger.fields(line)
            else:
                await asyncio.sleep(0.1)
