import asyncio
from typing import Optional
from asyncio import AbstractEventLoop, get_event_loop

from loguru import logger

from atsc.common.models import AsyncDaemon
from atsc.common.primitives import ref
from atsc.common.structs import Context
from atsc.controller.constants import SignalState, FieldState, PhaseCyclerMode
from atsc.controller.models import Ring, Barrier, PhaseCycler, IntervalTiming, Signal, Phase, FieldOutput, IntervalConfig


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
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.GO      : IntervalTiming(15.0)
        }
        self.interval_timing_vehicle_turn = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.GO      : IntervalTiming(5.0),
            SignalState.FYA     : IntervalTiming(4.0)
        }
        self.interval_timing_ped = {
            SignalState.STOP   : IntervalTiming(1.0),
            SignalState.CAUTION: IntervalTiming(5.0),
            SignalState.GO     : IntervalTiming(5.0)
        }
        self.interval_config_vehicle = {
            SignalState.LS_FLASH: IntervalConfig(flashing=True),
            SignalState.STOP    : IntervalConfig(),
            SignalState.CAUTION : IntervalConfig(),
            SignalState.GO      : IntervalConfig(rest=True),
            SignalState.FYA     : IntervalConfig(flashing=True, rest=True)
        }
        self.interval_config_ped = {
            SignalState.STOP    : IntervalConfig(),
            SignalState.CAUTION : IntervalConfig(flashing=True),
            SignalState.GO      : IntervalConfig(rest=True)
        }
        self.field_outputs = [FieldOutput(100 + i) for i in range(1, 49)]
        self.signals = [
            Signal(
                501,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(101, FieldOutput),
                    SignalState.STOP        : ref(101, FieldOutput),
                    SignalState.CAUTION     : ref(102, FieldOutput),
                    SignalState.GO          : ref(103, FieldOutput)
                }, recall=True
            ),
            Signal(
                502,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(104, FieldOutput),
                    SignalState.STOP        : ref(104, FieldOutput),
                    SignalState.CAUTION     : ref(105, FieldOutput),
                    SignalState.GO          : ref(106, FieldOutput)
                }, recall=True
            ),
            Signal(
                503,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(107, FieldOutput),
                    SignalState.STOP        : ref(107, FieldOutput),
                    SignalState.CAUTION     : ref(108, FieldOutput),
                    SignalState.GO          : ref(109, FieldOutput)
                }, recall=True
            ),
            Signal(
                504,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(110, FieldOutput),
                    SignalState.STOP        : ref(110, FieldOutput),
                    SignalState.CAUTION     : ref(111, FieldOutput),
                    SignalState.GO          : ref(112, FieldOutput)
                }, recall=True
            ),
            Signal(
                505,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(113, FieldOutput),
                    SignalState.STOP        : ref(113, FieldOutput),
                    SignalState.CAUTION     : ref(114, FieldOutput),
                    SignalState.GO          : ref(115, FieldOutput)
                }, recall=True
            ),
            Signal(
                506,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(116, FieldOutput),
                    SignalState.STOP        : ref(116, FieldOutput),
                    SignalState.CAUTION     : ref(117, FieldOutput),
                    SignalState.GO          : ref(118, FieldOutput)
                }, recall=True
            ),
            Signal(
                507,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(119, FieldOutput),
                    SignalState.STOP        : ref(119, FieldOutput),
                    SignalState.CAUTION     : ref(120, FieldOutput),
                    SignalState.GO          : ref(121, FieldOutput)
                }, recall=True
            ),
            Signal(
                508,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(122, FieldOutput),
                    SignalState.STOP        : ref(122, FieldOutput),
                    SignalState.CAUTION     : ref(123, FieldOutput),
                    SignalState.GO          : ref(124, FieldOutput)
                }, recall=True
            ),
            Signal(
                509,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(125, FieldOutput),
                    SignalState.CAUTION     : ref(125, FieldOutput),
                    SignalState.GO          : ref(127, FieldOutput)
                }, recall=True, recycle=True
            ),
            Signal(
                510,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(128, FieldOutput),
                    SignalState.CAUTION     : ref(128, FieldOutput),
                    SignalState.GO          : ref(130, FieldOutput)
                }, recall=True, recycle=True
            ),
            Signal(
                511,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(131, FieldOutput),
                    SignalState.CAUTION     : ref(131, FieldOutput),
                    SignalState.GO          : ref(133, FieldOutput)
                }, recall=True
            ),
            Signal(
                512,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(134, FieldOutput),
                    SignalState.CAUTION     : ref(134, FieldOutput),
                    SignalState.GO          : ref(136, FieldOutput)
                }, recall=True
            )
        ]
        self.phases = [
            Phase(601, [self.signals[0]]),
            Phase(602, [self.signals[1], self.signals[8]]),
            Phase(603, [self.signals[2]]),
            Phase(604, [self.signals[3], self.signals[10]]),
            Phase(605, [self.signals[4]]),
            Phase(606, [self.signals[5], self.signals[9]]),
            Phase(607, [self.signals[6]]),
            Phase(608, [self.signals[7], self.signals[11]])
        ]
        self.rings = [
            Ring(701, self.phases[0:4]),
            Ring(702, self.phases[4:8])
        ]
        self.barriers = [
            Barrier(801, self.phases[0:2] + self.phases[4:6]),
            Barrier(802, self.phases[2:4] + self.phases[6:8])
        ]
        self.cycler = PhaseCycler(self.rings,
                                  self.barriers,
                                  PhaseCyclerMode.CONCURRENT)
        
        for ring in self.rings:
            ring.demand = True
        
        self.tickables.append(self.cycler)
        self.routines.append(self.cycler.run())
        self.routines.append(self.print_fields_debug())
    
        self._previous_fields_line = ''
    
    def tick(self, context: Context):
        # overridden only for a spot to breakpoint that keeps context
        super().tick(context)
    
    async def print_fields_debug(self):
        while True:
            line = ''
            for i, field_output in enumerate(self.field_outputs, start=1):
                match field_output.state:
                    case FieldState.FLASHING:
                        symbol = 'F'
                    case FieldState.ON:
                        symbol = 'S'
                    case _:
                        symbol = '.'
                line += symbol
            
            if line != self._previous_fields_line:
                self._previous_fields_line = line
                logger.fields(line)
            else:
                await asyncio.sleep(0.1)
