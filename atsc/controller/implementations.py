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
import shutil
from atsc import fieldbus
from typing import List, Optional
from asyncio import AbstractEventLoop, get_event_loop
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.fieldbus.frames import OutputStateFrame
from atsc.common.primitives import ref, refs
from atsc.controller.models import (Ring,
                                    Phase,
                                    Signal,
                                    Barrier,
                                    FieldOutput,
                                    PhaseCycler,
                                    IntervalConfig,
                                    IntervalTiming)
from atsc.fieldbus.constants import DeviceAddress, FrameType
from atsc.controller.constants import SignalState, PhaseCyclerMode
from atsc.jigs.implementations import IntersectionSimulator


# Helper function to move cursor to a specific terminal position
def move_cursor(row: int, col: int = 0):
    print(f'\033[{row};{col}H', end='')


# Helper function to clear the current terminal line
def clear_line():
    print('\033[K', end='')


class ConsoleManager:
    
    def __init__(self, phases: List[Phase], enable=True):
        self.enable = enable
        self._console_letters = ('R', 'Y', 'G', 'D', 'W')
        self._console_size = shutil.get_terminal_size()
        self._console_rows = max([len(p.field_outputs) - 1 for p in phases])
        self._console_lines: List[List[str]] = []
        self._phases = phases
        
        for i in range(self._console_rows + 1):
            self._console_lines.append(['.'] * min(len(self._phases), self._console_size.columns))
    
    def update(self):
        if self.enable:
            for pi, phase in enumerate(self._phases):
                for fi, fo in enumerate(phase.field_outputs):
                    try:
                        letter = self._console_letters[fi]
                    except IndexError:
                        letter = 'X'
                    
                    self._console_lines[fi][pi] = letter if fo else '.'
            
            for li, line in enumerate(reversed(self._console_lines)):
                move_cursor(self._console_size.lines - li)
                line_text = ''.join(line)
                clear_line()
                print(line_text, end='')
            
            move_cursor(self._console_size.lines - (self._console_rows + 2))


class Controller(AsyncDaemon):
    
    @property
    def phases(self) -> List[Phase]:
        return self._phases
    
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
        self.fieldbus = fieldbus.SerialBus(context, 'COM4', 115200, loop=loop)
        
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
        self.field_outputs = [FieldOutput(100 + i) for i in range(1, 97)]
        self.signals = [
            Signal(
                501,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 101),
                    SignalState.STOP        : ref(FieldOutput, 101),
                    SignalState.CAUTION     : ref(FieldOutput, 102),
                    SignalState.GO          : ref(FieldOutput, 103)
                }
            ),
            Signal(
                502,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 104),
                    SignalState.STOP        : ref(FieldOutput, 104),
                    SignalState.CAUTION     : ref(FieldOutput, 105),
                    SignalState.GO          : ref(FieldOutput, 106)
                }, recall=True
            ),
            Signal(
                503,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 107),
                    SignalState.STOP        : ref(FieldOutput, 107),
                    SignalState.CAUTION     : ref(FieldOutput, 108),
                    SignalState.GO          : ref(FieldOutput, 109)
                }
            ),
            Signal(
                504,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 110),
                    SignalState.STOP        : ref(FieldOutput, 110),
                    SignalState.CAUTION     : ref(FieldOutput, 111),
                    SignalState.GO          : ref(FieldOutput, 112)
                }
            ),
            Signal(
                505,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 113),
                    SignalState.STOP        : ref(FieldOutput, 113),
                    SignalState.CAUTION     : ref(FieldOutput, 114),
                    SignalState.GO          : ref(FieldOutput, 115)
                }
            ),
            Signal(
                506,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 116),
                    SignalState.STOP        : ref(FieldOutput, 116),
                    SignalState.CAUTION     : ref(FieldOutput, 117),
                    SignalState.GO          : ref(FieldOutput, 118)
                }, recall=True
            ),
            Signal(
                507,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 119),
                    SignalState.STOP        : ref(FieldOutput, 119),
                    SignalState.CAUTION     : ref(FieldOutput, 120),
                    SignalState.GO          : ref(FieldOutput, 121)
                }
            ),
            Signal(
                508,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                {
                    SignalState.LS_FLASH    : ref(FieldOutput, 122),
                    SignalState.STOP        : ref(FieldOutput, 122),
                    SignalState.CAUTION     : ref(FieldOutput, 123),
                    SignalState.GO          : ref(FieldOutput, 124)
                }
            ),
            Signal(
                509,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(FieldOutput, 125),
                    SignalState.CAUTION     : ref(FieldOutput, 125),
                    SignalState.GO          : ref(FieldOutput, 127)
                }, recycle=True
            ),
            Signal(
                510,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(FieldOutput, 128),
                    SignalState.CAUTION     : ref(FieldOutput, 128),
                    SignalState.GO          : ref(FieldOutput, 130)
                }
            ),
            Signal(
                511,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(FieldOutput, 131),
                    SignalState.CAUTION     : ref(FieldOutput, 131),
                    SignalState.GO          : ref(FieldOutput, 133)
                }, recycle=True
            ),
            Signal(
                512,
                self.interval_timing_ped,
                self.interval_config_ped,
                {
                    SignalState.STOP        : ref(FieldOutput, 134),
                    SignalState.CAUTION     : ref(FieldOutput, 134),
                    SignalState.GO          : ref(FieldOutput, 136)
                }
            )
        ]
        self._phases = [
            Phase(601, refs(Signal, 501)),
            Phase(602, refs(Signal, 502, 509)),
            Phase(603, refs(Signal, 503)),
            Phase(604, refs(Signal, 504, 510)),
            Phase(605, refs(Signal, 505)),
            Phase(606, refs(Signal, 506, 511)),
            Phase(607, refs(Signal, 507)),
            Phase(608, refs(Signal, 508, 512))
        ]
        self.rings = [
            Ring(701, refs(Phase, 601, 602, 603, 604)),
            Ring(702, refs(Phase, 605, 606, 607, 608))
        ]
        self.barriers = [
            Barrier(801, refs(Phase, 601, 602, 605, 606)),
            Barrier(802, refs(Phase, 603, 604, 607, 608))
        ]
        self.cycler = PhaseCycler(self.rings,
                                  self.barriers,
                                  PhaseCyclerMode.CONCURRENT)
        
        # for ring in self.rings:
        #     ring.demand = True
        
        self.tickables.append(self.cycler)
        self.routines.extend((
            self.cycler.run(),
            self.fieldbus.receive(),
            self.fieldbus.transmit(),
            self.fieldbus_frame_handler()
        ))
        
        self._simulator = IntersectionSimulator(self.signals)
    
    async def fieldbus_frame_handler(self):
        while True:
            async with self.fieldbus.frames_unread:
                await self.fieldbus.frames_unread.wait()
            
            for frame in self.fieldbus.process_frames():
                if frame.address != DeviceAddress.CONTROLLER:
                    continue
                
                match frame.type:
                    case FrameType.INPUTS:
                        # bitfield = bitarray(buffer=frame.payload)
                        # for bit, signal in zip(bitfield, self.signals):
                        #     signal.presence = bit
                        pass
    
    def tick(self, context: Context):
        super().tick(context)
        self._simulator.tick(context)
        
        f = OutputStateFrame(DeviceAddress.TFIB1, self.field_outputs, True)
        self.fieldbus.enqueue_frame(f)

    def shutdown(self):
        self.fieldbus.close()
        super().shutdown()
