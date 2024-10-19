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
import asyncio
from atsc import __version__ as atsc_version
from loguru import logger
from typing import Optional
from asyncio import AbstractEventLoop, get_event_loop
from atsc.rpc import controller
from atsc.rpc import controller as rpc_controller
from atsc.rpc.signal import SignalMetadata as rpc_SignalMetadata
from atsc.common.models import AsyncDaemon
from atsc.common.structs import Context
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT
from atsc.rpc.field_output import FieldOutputMetadata as rpc_FieldOutputMetadata
from atsc.common.primitives import ref, refs
from atsc.controller.models import (
    Ring,
    Phase,
    Signal,
    Barrier,
    FieldOutput,
    IntervalConfig,
    IntervalTiming,
    IntersectionService
)
from atsc.controller.constants import (
    ExtendMode,
    RecallMode,
    SignalType,
    SignalState,
    PhaseCyclerMode,
    TrafficMovement,
    ServiceModifiers
)
from atsc.controller.simulation import IntersectionSimulator


def vehicle_signal_field_mapping(stop_field_id: int, fya_output: Optional[int] = None):
    rv = {
        SignalState.LS_FLASH: ref(FieldOutput, stop_field_id),
        SignalState.STOP    : ref(FieldOutput, stop_field_id),
        SignalState.CAUTION : ref(FieldOutput, stop_field_id + 1),
        SignalState.EXTEND  : ref(FieldOutput, stop_field_id + 2),
        SignalState.GO      : ref(FieldOutput, stop_field_id + 2)
    }
    if fya_output:
        rv.update({
            SignalState.FYA : ref(FieldOutput, fya_output)
        })
    return rv


def ped_signal_field_mapping(dont_walk_field_id: int):
    return {
        SignalState.STOP   : ref(FieldOutput, dont_walk_field_id),
        SignalState.CAUTION: ref(FieldOutput, dont_walk_field_id),
        SignalState.GO     : ref(FieldOutput, dont_walk_field_id + 2)
    }


class Controller(AsyncDaemon, controller.ControllerBase):
    
    @property
    def time_freeze(self):
        return not self.context.timing
    
    @time_freeze.setter
    def time_freeze(self, value):
        if value == self.context.timing:
            logger.info('time freeze = {}', not value)
            self.context.timing = not value
    
    @property
    def presence_simulation(self):
        return self._presence_simulation
    
    @presence_simulation.setter
    def presence_simulation(self, value):
        if value != self._presence_simulation:
            logger.info('presence simulation = {}', value)
            self._presence_simulation = value
    
    def __init__(self,
                 context: Context,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop(),
                 presence_simulation: bool = False,
                 simulation_seed: Optional[int] = None,
                 init_demand: bool = False):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout=shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self._presence_simulation = False
        
        self.interval_timing_vehicle1 = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.EXTEND  : IntervalTiming(5.0),
            SignalState.GO      : IntervalTiming(10.0, 55.0)
        }
        self.interval_timing_vehicle2 = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.EXTEND  : IntervalTiming(2.5),
            SignalState.GO      : IntervalTiming(5.0, 20.0)
        }
        self.interval_timing_vehicle_fya = {
            SignalState.LS_FLASH: IntervalTiming(16.0),
            SignalState.STOP    : IntervalTiming(1.0, revert=2.0),
            SignalState.CAUTION : IntervalTiming(4.0),
            SignalState.EXTEND  : IntervalTiming(2.5),
            SignalState.GO      : IntervalTiming(5.0, 15.0)
        }
        self.interval_timing_ped1 = {
            SignalState.STOP   : IntervalTiming(0.0),
            SignalState.CAUTION: IntervalTiming(14.0),
            SignalState.GO     : IntervalTiming(5.0, 5.0)
        }
        self.interval_timing_ped2 = {
            SignalState.STOP   : IntervalTiming(0.0),
            SignalState.CAUTION: IntervalTiming(10.0),
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
            SignalState.CAUTION : IntervalConfig(flashing=True)
        }
        self.field_outputs = [FieldOutput(100 + i) for i in range(1, 97)]
        self.signals = [
            Signal(
                501,
                self.interval_timing_vehicle_fya,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(101, fya_output=126),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PROTECTED_TURN,
                extend_mode=ExtendMode.MINIMUM_SKIP,
                fya_enabled=True,
                fya_service_delay=30.0
            ),
            Signal(
                502,
                self.interval_timing_vehicle1,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(104),
                recall=RecallMode.MINIMUM,
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PERMISSIVE_TURN,
                extend_mode=ExtendMode.MAXIMUM_SKIP
            ),
            Signal(
                503,
                self.interval_timing_vehicle_fya,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(107, fya_output=129),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PROTECTED_TURN,
                extend_mode=ExtendMode.MINIMUM_SKIP,
                fya_enabled=True,
                fya_service_delay=30.0
            ),
            Signal(
                504,
                self.interval_timing_vehicle2,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(110),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PERMISSIVE_TURN,
                extend_mode=ExtendMode.MAXIMUM_SKIP
            ),
            Signal(
                505,
                self.interval_timing_vehicle_fya,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(113, fya_output=132),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PROTECTED_TURN,
                extend_mode=ExtendMode.MINIMUM_SKIP,
                fya_enabled=True,
                fya_service_delay=30.0
            ),
            Signal(
                506,
                self.interval_timing_vehicle1,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(116),
                recall=RecallMode.MINIMUM,
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PERMISSIVE_TURN,
                extend_mode=ExtendMode.MAXIMUM_SKIP
            ),
            Signal(
                507,
                self.interval_timing_vehicle_fya,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(119, fya_output=135),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PROTECTED_TURN,
                extend_mode=ExtendMode.MINIMUM_SKIP,
                fya_enabled=True,
                fya_service_delay=30.0
            ),
            Signal(
                508,
                self.interval_timing_vehicle2,
                self.interval_config_vehicle,
                vehicle_signal_field_mapping(122),
                type=SignalType.VEHICLE,
                movement=TrafficMovement.PERMISSIVE_TURN,
                extend_mode=ExtendMode.MAXIMUM_SKIP
            ),
            Signal(
                509,
                self.interval_timing_ped1,
                self.interval_config_ped,
                ped_signal_field_mapping(125),
                recycle=True,
                latch=True,
                type=SignalType.PEDESTRIAN,
                service_modifiers=ServiceModifiers.BEFORE_VEHICLE
            ),
            Signal(
                510,
                self.interval_timing_ped2,
                self.interval_config_ped,
                ped_signal_field_mapping(128),
                latch=True,
                type=SignalType.PEDESTRIAN,
                service_modifiers=ServiceModifiers.BEFORE_VEHICLE
            ),
            Signal(
                511,
                self.interval_timing_ped1,
                self.interval_config_ped,
                ped_signal_field_mapping(131),
                recycle=True,
                latch=True,
                type=SignalType.PEDESTRIAN,
                service_modifiers=ServiceModifiers.BEFORE_VEHICLE
            ),
            Signal(
                512,
                self.interval_timing_ped2,
                self.interval_config_ped,
                ped_signal_field_mapping(134),
                latch=True,
                type=SignalType.PEDESTRIAN,
                service_modifiers=ServiceModifiers.BEFORE_VEHICLE
            )
        ]
        self.phases = [
            Phase(601, refs(Signal, 501)),
            Phase(602, refs(Signal, 502, 509), default_signals=refs(Signal, 502)),
            Phase(603, refs(Signal, 503)),
            Phase(604, refs(Signal, 504, 510), default_signals=refs(Signal, 504)),
            Phase(605, refs(Signal, 505)),
            Phase(606, refs(Signal, 506, 511), default_signals=refs(Signal, 506)),
            Phase(607, refs(Signal, 507)),
            Phase(608, refs(Signal, 508, 512), default_signals=refs(Signal, 508))
        ]
        ref(Phase, 608).default_phases.append(ref(Phase, 604))
        ref(Phase, 604).default_phases.append(ref(Phase, 608))
        ref(Signal, 501).fya_phase = ref(Phase, 602)
        ref(Signal, 505).fya_phase = ref(Phase, 606)
        ref(Signal, 503).fya_phase = ref(Phase, 604)
        ref(Signal, 507).fya_phase = ref(Phase, 608)
        self.rings = [
            Ring(701, refs(Phase, 601, 602, 603, 604)),
            Ring(702, refs(Phase, 605, 606, 607, 608))
        ]
        self.barriers = [
            Barrier(801, refs(Phase, 601, 602, 605, 606)),
            Barrier(802, refs(Phase, 603, 604, 607, 608))
        ]
        self.cycler = IntersectionService(self.rings,
                                          self.barriers,
                                          PhaseCyclerMode.CONCURRENT,
                                          fya_enabled=True)
        
        self.tickables.append(self.cycler)
        self.routines.extend((
            self.test_rpc_calls(),
            self.cycler.run()
        ))
        self.presence_simulation = presence_simulation
        self.simulator = IntersectionSimulator(self.signals,
                                               seed=simulation_seed)
        
        if init_demand:
            for phase in self.phases:
                phase.demand = True
    
    async def test_rpc_calls(self):
        await self.get_metadata(rpc_controller.ControllerMetadataRequest())
        await self.get_runtime_info(rpc_controller.ControllerRuntimeInfoRequest())
        await self.get_field_outputs(rpc_controller.ControllerFieldOutputsRequest())
        await self.get_signals(rpc_controller.ControllerSignalsRequest())
        await self.get_phases(rpc_controller.ControllerPhasesRequest())
        
    def tick(self, context: Context):
        super().tick(context)
        
        if self.presence_simulation:
            self.simulator.tick(context)
    
    def shutdown(self):
        super().shutdown()
    
    async def test_connection(
        self,
        request: controller.ControllerTestConnectionRequest
    ):
        return controller.ControllerTestConnectionReply()
    
    async def get_metadata(
        self,
        request: controller.ControllerMetadataRequest
    ):
        field_output_metadata = []
        for field_output in self.field_outputs:
            field_output_metadata.append(rpc_FieldOutputMetadata(field_output.id))

        signal_metadata = []
        for signal in self.signals:
            signal_metadata.append(rpc_SignalMetadata(
                id=signal.id,
                field_output_ids=[fo.id for fo in signal.field_outputs],
                type=signal.type,
                movement=signal.movement,
                initial_state=signal.initial_state
            ))
        
        return controller.ControllerMetadataReply(
            version=atsc_version,
            started_at_epoch=self.started_at_epoch,
            supports_time_freeze=True,
            supports_time_scaling=True,
            supports_coordination=False,
            supports_scheduling=False,
            supports_dimming=False,
            field_outputs=field_output_metadata,
            signals=signal_metadata
        )
    
    def _get_runtime_info(self):
        rv = controller.ControllerRuntimeInfoReply(
            run_seconds=self.started_at_monotonic_delta,
            control_seconds=self.started_at_monotonic_delta,
            time_freeze=self.time_freeze,
            time_scale=self.context.scale,
            coordinating=False,
            on_schedule=False,
            dimming=False,
            active_phases=[p.id for p in self.cycler.active_phases],
            waiting_phases=[p.id for p in self.cycler.waiting_phases],
            cycle_mode=self.cycler.mode,
            cycle_count=self.cycler.cycle_count
        )
        return rv
    
    async def get_runtime_info(
        self,
        request: controller.ControllerRuntimeInfoRequest
    ):
        return self._get_runtime_info()
    
    async def set_time_freeze(self, request: controller.ControllerTimeFreezeRequest):
        before = self.time_freeze
        self.time_freeze = request.time_freeze
        changed = self.time_freeze != before
        return controller.ControllerChangeVariableResult(True, changed)
    
    async def set_cycle_mode(self, request: controller.ControllerCycleModeRequest):
        changed = False
        try:
            before = self.cycler.mode
            success = self.cycler.set_mode(request.cycle_mode)
            changed = self.cycler.mode != before
        except Exception as e:
            logger.exception('[RPC] set_cycle_mode() raised exception', e)
            success = False
        return controller.ControllerChangeVariableResult(success, changed)
    
    async def set_presence_simulation(
        self,
        request: controller.ControllerPresenceSimulationRequest
    ):
        before = self.presence_simulation
        self.presence_simulation = request.enabled
        changed = self.presence_simulation != before
        return controller.ControllerChangeVariableResult(True, changed)
    
    async def set_fya_enabled(
        self,
        request: controller.ControllerFyaEnabledRequest
    ):
        before = self.cycler.fya_enabled
        self.cycler.fya_enabled = request.enabled
        changed = self.cycler.fya_enabled != before
        return controller.ControllerChangeVariableResult(True, changed)
    
    async def get_field_output(
        self,
        request: controller.ControllerIdentifiableObjectRequest
    ):
        result = None
        for field_output in self.field_outputs:
            if field_output.id == request.id:
                result = field_output.rpc_model()
        return controller.ControllerFieldOutputReply(result)
    
    def _get_field_outputs(self):
        for field_output in self.field_outputs:
            yield field_output.rpc_model()
    
    async def get_field_outputs(
        self,
        request: controller.ControllerFieldOutputsRequest
    ):
        field_outputs = list(self._get_field_outputs())
        return controller.ControllerFieldOutputsReply(field_outputs)
    
    async def get_signal(
        self,
        request: controller.ControllerIdentifiableObjectRequest
    ):
        result = None
        for signal in self.signals:
            if signal.id == request.id:
                result = signal.rpc_model()
        return controller.ControllerSignalsReply(result)
    
    def _get_signals(self):
        for signal in self.signals:
            yield signal.rpc_model()
    
    async def get_signals(
        self,
        request: controller.ControllerSignalsRequest
    ):
        signals = list(self._get_signals())
        return controller.ControllerSignalsReply(signals)
    
    async def set_signal_demand(
        self,
        request: controller.ControllerSignalDemandRequest
    ):
        success = False
        changed = False
        for signal in self.signals:
            if signal.id == request.id:
                before = signal.demand
                signal.demand = request.demand
                changed = signal.demand != before
                success = True
                break
        return controller.ControllerChangeVariableResult(success, changed)
    
    async def set_signal_presence(
        self,
        request: controller.ControllerSignalPresenceRequest
    ):
        success = False
        changed = False
        for signal in self.signals:
            if signal.id == request.id:
                before = signal.presence
                signal.presence = request.presence
                changed = signal.presence != before
                success = True
                break
        return controller.ControllerChangeVariableResult(success, changed)
    
    async def get_phase(
        self,
        request: controller.ControllerIdentifiableObjectRequest
    ):
        result = None
        for phase in self.phases:
            if phase.id == request.id:
                result = phase.rpc_model()
        return controller.ControllerPhaseReply(result)
    
    async def get_phases(
        self,
        request: controller.ControllerPhasesRequest
    ):
        rpc_phases = []
        
        for phase in self.phases:
            rpc_phases.append(phase.rpc_model())
        
        return controller.ControllerPhasesReply(rpc_phases)

    async def set_phase_demand(
        self,
        request: controller.ControllerPhaseDemandRequest
    ):
        success = False
        changed = False
        for phase in self.phases:
            if phase.id == request.id:
                before = phase.demand
                phase.demand = request.demand
                changed = phase.demand != before
                success = True
                break
        return controller.ControllerChangeVariableResult(success, changed)

    async def get_state_stream(
        self,
        request: controller.ControllerGetStateStreamRequest
    ):
        while self.running.is_set():
            runtime_info = self._get_runtime_info() if request.runtime_info else None
            
            if request.field_outputs:
                field_outputs = list(self._get_field_outputs())
            else:
                field_outputs = None
            
            if request.signals:
                signals = list(self._get_signals())
            else:
                signals = None
            
            yield controller.ControllerGetStateStreamResponse(
                runtime_info=runtime_info,
                field_outputs=field_outputs,
                signals=signals
            )
            await asyncio.sleep(self.context.delay)
