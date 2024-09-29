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
from atsc import __version__ as atsc_version
from typing import Optional
from asyncio import AbstractEventLoop, get_event_loop
from atsc.rpc import controller
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT
from atsc.common.primitives import ref, refs
from atsc.controller.models import (
    Ring,
    Phase,
    Signal,
    Barrier,
    FieldOutput,
    PhaseCycler,
    IntervalConfig,
    IntervalTiming
)
from atsc.controller.constants import (
    RecallMode,
    SignalType,
    SignalState,
    PhaseCyclerMode
)
from atsc.controller.simulation import IntersectionSimulator
from atsc.rpc import controller as rpc_controller


def vehicle_signal_field_mapping(stop_field_id: int):
    return {
        SignalState.LS_FLASH: ref(FieldOutput, stop_field_id),
        SignalState.STOP    : ref(FieldOutput, stop_field_id),
        SignalState.CAUTION : ref(FieldOutput, stop_field_id + 1),
        SignalState.EXTEND  : ref(FieldOutput, stop_field_id + 2),
        SignalState.GO      : ref(FieldOutput, stop_field_id + 2)
    }


def ped_signal_field_mapping(dont_walk_field_id: int):
    return {
        SignalState.STOP   : ref(FieldOutput, dont_walk_field_id),
        SignalState.CAUTION: ref(FieldOutput, dont_walk_field_id),
        SignalState.GO     : ref(FieldOutput, dont_walk_field_id + 2)
    }


class Controller(AsyncDaemon, controller.ControllerBase):
    
    def __init__(self,
                 context: Context,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout=shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        
        self.interval_timing_vehicle = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.EXTEND  : IntervalTiming(3.0),
            SignalState.GO      : IntervalTiming(5.0, 30.0)
        }
        self.interval_timing_vehicle_turn = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.EXTEND  : IntervalTiming(2.5),
            SignalState.GO      : IntervalTiming(3.0, 15.0),
            SignalState.FYA     : IntervalTiming(4.0)
        }
        self.interval_timing_ped = {
            SignalState.STOP   : IntervalTiming(1.0),
            SignalState.CAUTION: IntervalTiming(5.0, 5.0),
            SignalState.GO     : IntervalTiming(5.0, 5.0)
        }
        self.interval_config_vehicle = {
            SignalState.LS_FLASH: IntervalConfig(flashing=True, rest=True),
            SignalState.STOP    : IntervalConfig(rest=True),
            SignalState.GO      : IntervalConfig(rest=True),
            SignalState.FYA     : IntervalConfig(flashing=True, rest=True)
        }
        self.interval_config_ped = {
            SignalState.STOP    : IntervalConfig(rest=True),
            SignalState.CAUTION : IntervalConfig(flashing=True),
            SignalState.GO      : IntervalConfig(rest=True)
        }
        self.field_outputs = [FieldOutput(100 + i) for i in range(1, 97)]
        self.signals = [
            Signal(
                501,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(101),
                type=SignalType.VEHICLE
            ),
            Signal(
                502,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(104),
                recall=RecallMode.MINIMUM,
                type=SignalType.VEHICLE
            ),
            Signal(
                503,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(107),
                type=SignalType.VEHICLE
            ),
            Signal(
                504,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(110),
                type=SignalType.VEHICLE
            ),
            Signal(
                505,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(113),
                type=SignalType.VEHICLE
            ),
            Signal(
                506,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(116),
                recall=RecallMode.MINIMUM,
                type=SignalType.VEHICLE
            ),
            Signal(
                507,
                self.interval_timing_vehicle_turn,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(119),
                type=SignalType.VEHICLE
            ),
            Signal(
                508,
                self.interval_timing_vehicle,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(122),
                type=SignalType.VEHICLE
            ),
            Signal(
                509,
                self.interval_timing_ped,
                self.interval_config_ped,
                ped_signal_field_mapping(125),
                recycle=True,
                latch=True,
                type=SignalType.PEDESTRIAN
            ),
            Signal(
                510,
                self.interval_timing_ped,
                self.interval_config_ped,
                ped_signal_field_mapping(128),
                latch=True,
                type=SignalType.PEDESTRIAN
            ),
            Signal(
                511,
                self.interval_timing_ped,
                self.interval_config_ped,
                ped_signal_field_mapping(131),
                recycle=True,
                latch=True,
                type=SignalType.PEDESTRIAN
            ),
            Signal(
                512,
                self.interval_timing_ped,
                self.interval_config_ped,
                ped_signal_field_mapping(134),
                latch=True,
                type=SignalType.PEDESTRIAN
            )
        ]
        self.phases = [
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
        
        self.tickables.append(self.cycler)
        self.routines.extend((
            self.test_rpc_calls(),
            self.cycler.run()
        ))
        self.simulator = IntersectionSimulator(self.signals)
    
    async def test_rpc_calls(self):
        await self.get_metadata(rpc_controller.ControllerMetadataRequest())
        await self.get_runtime_info(rpc_controller.ControllerRuntimeInfoRequest())
        await self.get_field_outputs(rpc_controller.ControllerFieldOutputsRequest())
        await self.get_signals(rpc_controller.ControllerSignalsRequest())
        await self.get_phases(rpc_controller.ControllerPhasesRequest())
    
    def tick(self, context: Context):
        super().tick(context)
        self.simulator.tick(context)
    
    def shutdown(self):
        super().shutdown()
    
    async def get_metadata(
        self,
        controller_metadata_request: controller.ControllerMetadataRequest
    ):
        return controller.ControllerMetadataReply(
            version=atsc_version,
            supports_time_freeze=False,
            supports_time_scaling=True,
            supports_coordination=False,
            supports_scheduling=False,
            supports_dimming=False,
            supported_field_outputs=len(self.field_outputs),
            supported_signals=len(self.signals),
            supported_phases=len(self.phases),
            supported_rings=len(self.rings),
            supported_barriers=len(self.barriers),
            supported_inputs=0
        )
    
    async def get_runtime_info(
        self,
        controller_runtime_info_request: controller.ControllerRuntimeInfoRequest
    ):
        return controller.ControllerRuntimeInfoReply(
            started_at=self.started_at,
            run_seconds=self.started_at_monotonic_delta,
            control_seconds=self.started_at_monotonic_delta,
            freeze_time=False,
            time_scale=self.context.scale,
            coordinating=False,
            on_schedule=False,
            dimming=False,
            enabled_field_outputs=len(self.field_outputs),
            enabled_signals=len(self.signals),
            enabled_phases=len(self.phases),
            enabled_rings=len(self.rings),
            enabled_barriers=len(self.barriers),
            enabled_inputs=0
        )
    
    async def get_field_outputs(
        self,
        controller_field_outputs_request: controller.ControllerFieldOutputsRequest
    ):
        rpc_field_outputs = []
        
        for field_output in self.field_outputs:
            rpc_field_outputs.append(field_output.rpc_model())
        
        return controller.ControllerFieldOutputsReply(rpc_field_outputs)
    
    async def get_signals(
        self,
        controller_signals_request: controller.ControllerSignalsRequest
    ):
        rpc_signals = []
        
        for signal in self.signals:
            rpc_signals.append(signal.rpc_model())
            
        return controller.ControllerSignalsReply(rpc_signals)
    
    async def get_phases(
        self,
        controller_phases_request: controller.ControllerPhasesRequest
    ):
        rpc_phases = []
        
        for phase in self.phases:
            rpc_phases.append(phase.rpc_model())
        
        return controller.ControllerPhasesReply(rpc_phases)
