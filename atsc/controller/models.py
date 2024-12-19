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
import blinker
from loguru import logger
from typing import Set, Dict, List, Optional
from asyncio import InvalidStateError
from itertools import chain
from collections import defaultdict
from dataclasses import dataclass
from atsc.rpc.phase import Phase as rpc_Phase
from atsc.controller import utils
from atsc.rpc.signal import Signal as rpc_Signal
from atsc.common.constants import FLOAT_PRECISION_TIME, EdgeType
from atsc.rpc.field_output import FieldOutput as rpc_FieldOutput
from jacob.datetime.timing import millis
from atsc.controller.structs import IntervalConfig, IntervalTiming
from atsc.controller.constants import (
    POLL_RATE,
    FYA_MINIMUM_TIME,
    FYA_MINIMUM_PEDESTRIAN_STOP_TIME,
    ExtendMode,
    RecallMode,
    SignalType,
    InputAction,
    SignalState,
    ServiceReason,
    InputActivation,
    PhaseCyclerMode,
    TrafficMovement,
    FieldOutputState,
    ServiceModifiers,
    ServiceConditions
)
from jacob.datetime.formatting import format_ms
from atsc.controller.primitives import (
    AsyncTimer,
    EdgeTrigger,
    Identifiable,
    AsyncStopwatch
)


class FieldOutput(Identifiable):
    
    @property
    def state(self):
        return self._state
    
    @property
    def fpm(self):
        return self._fpm
    
    @property
    def flash_delay(self):
        return (60.0 / self._fpm) / 2.0
    
    def __init__(self, id_: int, fpm: float = 60.0):
        Identifiable.__init__(self, id_)
        self.state_changed = blinker.Signal()
        self.bit_changed = blinker.Signal()
        
        self._state = FieldOutputState.OFF
        self._bit = False
        self._fpm = fpm
        self._flash_timer = AsyncTimer(
            f'FieldOutputFlasher{self.id}',
            goal=self.flash_delay,
            goal_handler=self._on_flash_timer_reached_goal,
            repeat=True
        )
        self._marker = None
    
    def _change_bit(self, v: bool):
        if v != self._bit:
            self._bit = v
            self.bit_changed.send(self)
    
    def set(self, state: FieldOutputState):
        if state != FieldOutputState.INHERIT:
            before = self.state
            if state != before:
                match state:
                    case FieldOutputState.OFF:
                        self._flash_timer.cancel()
                        self._change_bit(False)
                        self._marker = None
                    case FieldOutputState.ON:
                        if self._flash_timer.running:
                            self._flash_timer.cancel()
                        self._change_bit(True)
                        self._marker = None
                    case FieldOutputState.FLASHING:
                        self._change_bit(True)
                        self._flash_timer.start()
                
                self._state = state
                self.state_changed.send(self)
    
    def __bool__(self):
        return self._bit
    
    def __int__(self):
        return 1 if self._bit else 0
    
    def __repr__(self):
        return f'<FieldOutput #{self.id} {self.state.name} {self._bit}'
    
    def _on_flash_timer_reached_goal(self, _):
        self._change_bit(not self._bit)
        
        if self._marker:
            delta = millis() - self._marker
            logger.verbose('flasher toggle took {}', format_ms(delta))
        
        self._marker = millis()
    
    def rpc_model(self):
        return rpc_FieldOutput(self.id,
                               state=self.state,
                               value=self._bit,
                               fpm=self.fpm)


class Signal(Identifiable):
    global_field_output_mapping: Dict[FieldOutput, 'Signal'] = {}
    
    @dataclass(slots=True, frozen=True)
    class ServiceStatus:
        service: bool
        reason: ServiceReason
        lagging_signal: Optional['Signal'] = None
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional['Signal']:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def type(self):
        return self._type
    
    @property
    def movement(self):
        return self._movement
    
    @property
    def active(self):
        return self._active
    
    @property
    def stop_minimum_clear(self):
        stop_timing = self.timings[SignalState.STOP]
        return not stop_timing.minimum or self.interval_timer.elapsed > stop_timing.minimum
    
    @property
    def revert_clear(self):
        if self.state == SignalState.STOP:
            return self.interval_timer.elapsed > self._revert_time
        return False
    
    @property
    def revert_time(self):
        return self._revert_time
    
    @property
    def safe(self):
        return not self.active and self.state == SignalState.STOP and self.stop_minimum_clear
    
    @property
    def state(self):
        return self._state
    
    @property
    def has_go_state(self):
        return SignalState.GO in self.mapping.keys()
    
    @property
    def field_mapping(self):
        return self.mapping
    
    @property
    def fya_active(self):
        return self.state == SignalState.FYA
    
    @property
    def fya_force_service_delay(self):
        return self._fya_force_service_delay
    
    @property
    def fya_ped_service_delay(self):
        return self._fya_ped_service_delay
    
    @property
    def fya_force_service(self):
        return self._fya_force_service
    
    @fya_force_service.setter
    def fya_force_service(self, value):
        if value != self._fya_force_service:
            logger.debug('{} fya_force_service = {}', self.get_tag(), value)
            self._fya_force_service = value
    
    @property
    def fya_enabled(self):
        return self._fya_enabled
    
    @fya_enabled.setter
    def fya_enabled(self, value):
        edge_type = self.fya_enabled_edge.poll(value)
        if edge_type is not None:
            logger.debug('{} fya_enabled = {}', self.get_tag(), value)
            self._fya_enabled = value
            self.fya_enabled_changed.send(self, edge_type=edge_type)
    
    @property
    def fya_concurrent_phase(self):
        return self._fya_concurrent_phase
    
    @fya_concurrent_phase.setter
    def fya_concurrent_phase(self, value):
        previous_phase = self._fya_concurrent_phase
        if previous_phase is None or value != previous_phase:
            logger.debug('{} fya_concurrent_phase = {}',
                         self.get_tag(),
                         value.get_tag() if isinstance(value, Phase) else value)
            self._fya_concurrent_phase = value
            self.fya_concurrent_phase_changed.send(self,
                                                   previous_phase=previous_phase,
                                                   new_phase=value)
    
    @property
    def fya_guard_phase(self):
        return self._fya_guard_phase
    
    @fya_guard_phase.setter
    def fya_guard_phase(self, value):
        previous_phase = self._fya_guard_phase
        if previous_phase is None or value != previous_phase:
            logger.debug('{} fya_guard_phase = {}',
                         self.get_tag(),
                         value.get_tag() if isinstance(value, Phase) else value)
            self._fya_guard_phase = value
    
    @property
    def fya_extension(self):
        return self._fya_extension
    
    @fya_extension.setter
    def fya_extension(self, value):
        if value != self._fya_extension:
            logger.verbose('{} fya_extension = {}', self.get_tag(), value)
            self._fya_extension = bool(value)
    
    @property
    def remote_fya_signal(self):
        return self._remote_fya_signal
    
    @remote_fya_signal.setter
    def remote_fya_signal(self, value):
        previous_signal = self._remote_fya_signal
        if previous_signal is None or value != previous_signal:
            logger.debug('{} remote_fya_signal = {}',
                         self.get_tag(),
                         value.get_tag() if isinstance(value, Signal) else value)
            self._remote_fya_signal = value
    
    @property
    def fya_available(self):
        return self.fya_enabled and self.fya_concurrent_phase is not None
    
    @property
    def demand(self):
        return self._demand
    
    @demand.setter
    def demand(self, value):
        edge_type = self.demand_edge.poll(value)
        if edge_type is not None:
            logger.verbose('{} demand = {}', self.get_tag(), value)
            self._demand = bool(value)
            self.demand_changed.send(self, edge_type=edge_type)
    
    @property
    def latch(self):
        return self._latch or self._latch_once
    
    @latch.setter
    def latch(self, value):
        if value != self._latch:
            logger.verbose('{} latch = {}', self.get_tag(), value)
            self._latch = bool(value)
    
    @property
    def latch_once(self):
        return self._latch_once
    
    @latch_once.setter
    def latch_once(self, value):
        if value != self._latch_once:
            logger.verbose('{} latch_once = {}', self.get_tag(), value)
            self._latch_once = bool(value)
    
    @property
    def presence(self):
        return self._presence and not self.presence_lockout
    
    @presence.setter
    def presence(self, value):
        edge_type = self.presence_edge.poll(value)
        if edge_type is not None:
            logger.verbose('{} presence = {}', self.get_tag(), value)
            self._presence = bool(value)
            self.presence_changed.send(self, edge_type=edge_type)
    
    @property
    def presence_lockout_delay(self):
        return self._presence_lockout_delay
    
    @property
    def presence_lockout(self):
        return self._presence_lockout
    
    @presence_lockout.setter
    def presence_lockout(self, value):
        if value != self._presence_lockout:
            logger.verbose('{} presence_lockout = {}', self.get_tag(), value)
            self._presence_lockout = bool(value)
    
    @property
    def conflicting_demand(self):
        return self._conflicting_demand
    
    @conflicting_demand.setter
    def conflicting_demand(self, value):
        if value != self._conflicting_demand:
            logger.verbose('{} conflicting_demand = {}', self.get_tag(), value)
        self._conflicting_demand = bool(value)
    
    @property
    def resting(self):
        config = self.configs.get(self.state)
        resting = False if not config else config.rest
        
        match self.state:
            case SignalState.STOP:
                resting = resting and not self.active
            case _:
                resting = resting and not self.conflicting_demand
                
                if self.leading_signals:
                    resting = resting or any([ls.active for ls in self.leading_signals])
        
        return resting
    
    @property
    def extend_mode(self):
        return self._extend_mode
    
    @extend_mode.setter
    def extend_mode(self, value):
        if value != self._extend_mode:
            logger.verbose('{} extend_mode = {}', self.get_tag(), value)
            self._extend_mode = value
    
    @property
    def extend_sync_signals(self):
        return self._extend_sync_signals
    
    @property
    def recall_mode(self):
        return self._recall_mode
    
    @recall_mode.setter
    def recall_mode(self, value):
        assert isinstance(value, RecallMode)
        if value != self._recall_mode:
            logger.verbose('{} recall_mode = {}', self.get_tag(), value.name)
        self._recall_mode = value
    
    @property
    def recall_state(self):
        return self._recall_state
    
    @property
    def service_conditions(self):
        return self._service_conditions
    
    @service_conditions.setter
    def service_conditions(self, value):
        assert isinstance(value, ServiceConditions)
        if value != self._service_conditions:
            logger.verbose('{} service_conditions = {}', self.get_tag(), value.name)
        self._service_conditions = value
    
    @property
    def service_modifiers(self):
        return self._service_modifiers
    
    @service_modifiers.setter
    def service_modifiers(self, value):
        assert isinstance(value, ServiceModifiers)
        if value != self._service_modifiers:
            logger.verbose('{} service_modifiers = {}', self.get_tag(), value.name)
        self._service_modifiers = value
    
    @property
    def service_timeout(self):
        return self._service_timeout
    
    @service_timeout.setter
    def service_timeout(self, value):
        if value != self._service_timeout:
            logger.verbose('{} service_timeout = {}', self.get_tag(), value)
        self._service_timeout = bool(value)
    
    @property
    def recycle(self):
        return self._recycle
    
    @recycle.setter
    def recycle(self, value):
        if value != self._recycle:
            logger.verbose('{} recycle = {}', self.get_tag(), value)
        self._recycle = bool(value)
    
    @property
    def service_maximum(self):
        go_timing = self.timings.get(SignalState.GO)
        
        if go_timing and go_timing.maximum and go_timing.maximum > 1.0:
            return round(go_timing.maximum, FLOAT_PRECISION_TIME)
        else:
            return None
    
    @property
    def field_outputs(self):
        rv = set()
        for field_output in self.mapping.values():
            rv.add(field_output)
        return sorted(rv)
    
    @property
    def runtime_maximum(self):
        duration = 0.0
        
        if self.service_maximum:
            duration += self.service_maximum
        else:
            go_time = self.timings[SignalState.GO]
            
            if go_time:
                if go_time.maximum:
                    duration += go_time.maximum
                else:
                    if go_time.minimum:
                        duration += go_time.minimum
                    
                    if self._can_extend():
                        extend_time = self.timings.get(SignalState.EXTEND)
                        if extend_time and extend_time.minimum:
                            duration += extend_time.minimum
        
        if self.fya_extension:
            duration += FYA_MINIMUM_TIME
        
        caution_time = self.timings[SignalState.CAUTION]
        
        if caution_time and caution_time.minimum:
            duration += caution_time.minimum
        
        stop_time = self.timings[SignalState.STOP]
        
        if stop_time and stop_time.minimum:
            duration += stop_time.minimum
        
        return round(duration, FLOAT_PRECISION_TIME)
    
    def runtime_remaining(self, cutoff_state: Optional[SignalState] = None):
        remaining = 0.0
        
        if not self.safe:
            if self.fya_active:
                caution_time = self.timings[SignalState.CAUTION]
                if caution_time and caution_time.minimum:
                    remaining += caution_time.minimum
                
                stop_time = self.timings[SignalState.STOP]
                if stop_time and stop_time.minimum:
                    remaining += stop_time.minimum
            else:
                for state in reversed(SignalState):
                    if cutoff_state is not None and state <= cutoff_state:
                        continue
                    
                    if state < self.state:
                        if state == SignalState.EXTEND and not self._can_extend():
                            continue
                        
                        interval_time = self.timings.get(state)
                        if interval_time and interval_time.minimum:
                            remaining += interval_time.minimum
                
                if self.state > SignalState.CAUTION and self.fya_extension:
                    remaining += FYA_MINIMUM_TIME
                
                if not self.resting and self.interval_timer.remaining:
                    remaining -= self.interval_timer.remaining
        
        return max(0.0, round(remaining, FLOAT_PRECISION_TIME))
    
    def __init__(self,
                 id_: int,
                 timings: Dict[SignalState, IntervalTiming],
                 configs: Dict[SignalState, IntervalConfig],
                 mapping: Dict[SignalState, FieldOutput],
                 recall: RecallMode = RecallMode.OFF,
                 recycle: bool = False,
                 demand: bool = False,
                 latch: bool = False,
                 type: SignalType = SignalType.GENERIC,
                 movement: TrafficMovement = TrafficMovement.THRU,
                 extend_mode: ExtendMode = ExtendMode.OFF,
                 service_conditions: ServiceConditions = ServiceConditions.DEMAND,
                 service_modifiers: ServiceModifiers = ServiceModifiers.UNSET,
                 initial_state: SignalState = SignalState.STOP,
                 revert_time: float = 0.0,
                 presence_lockout_delay: Optional[float] = None,
                 fya_enabled: bool = False,
                 fya_concurrent_phase: Optional['Phase'] = None,
                 fya_guard_phase: Optional['Phase'] = None,
                 fya_force_service_delay: Optional[float] = None,
                 fya_ped_service_delay: Optional[float] = None):
        Identifiable.__init__(self, id_)
        self._active = False
        self._type = type
        self._movement = movement
        self._state = SignalState.STOP
        self._conflicting_demand = False
        self._extend_mode = extend_mode
        self._extend_sync_signals = []
        self._recall_mode = recall
        self._recall_state = RecallMode.OFF
        self._recycle = recycle
        self._demand = demand
        self._latch = latch
        self._latch_once = False
        self._presence = False
        self._presence_lockout_delay = presence_lockout_delay
        self._presence_lockout = False
        self._service_conditions = service_conditions
        self._service_modifiers = service_modifiers
        self._service_timeout = False
        self._revert_time = revert_time
        self._fya_task = None
        self._fya_force_service = False
        self._fya_force_service_delay = fya_force_service_delay
        self._fya_ped_service_delay = fya_ped_service_delay
        self._fya_enabled = fya_enabled
        self._fya_concurrent_phase = fya_concurrent_phase
        self._fya_guard_phase = fya_guard_phase
        self._fya_extension = False
        self._remote_fya_signal: Optional['Signal'] = None
        
        self.timings = timings
        self.configs: Dict[SignalState, IntervalConfig] = defaultdict(IntervalConfig)
        for state, v in configs.items():
            self.configs[state] = v
        
        self.mapping = mapping
        for fo in mapping.values():
            self.global_field_output_mapping.update({fo: self})
        
        self.leading_signals: List['Signal'] = []
        
        self.state_changed = blinker.Signal()
        self.interval_timer = AsyncTimer(f'SignalInterval{self.id}', )
        self.service_timer = AsyncTimer(f'SignalService{self.id}',
                                        goal_handler=self.on_service_timeout,
                                        paused=True)
        
        self.demand_stopwatch = AsyncStopwatch()
        self.demand_edge = EdgeTrigger()
        self.demand_changed = blinker.Signal()
        self.demand_changed.connect(self.on_demand_changed, sender=self)
        self.fya_demand_timer = AsyncTimer(f'SignalFYADemand{self.id}',
                                           goal=self.fya_ped_service_delay,
                                           goal_handler=self.on_demand_timeout)
        
        self.presence_stopwatch = AsyncStopwatch()
        self.presence_timer = AsyncTimer(f'SignalPresence{self.id}',
                                         goal=self.presence_lockout_delay,
                                         goal_handler=self.on_presence_timeout)
        self.presence_edge = EdgeTrigger()
        self.presence_changed = blinker.Signal()
        self.presence_changed.connect(self.on_presence_changed, sender=self)
        self.fya_presence_timer = AsyncTimer(f'SignalFYAPresence{self.id}',
                                             goal=self.fya_force_service_delay,
                                             goal_handler=self.on_fya_force_service)
                
        self.fya_enabled_edge = EdgeTrigger()
        self.fya_enabled_changed = blinker.Signal()
        self.fya_enabled_changed.connect(self.on_fya_enabled_changed, sender=self)
        self.fya_concurrent_phase_changed = blinker.Signal()
        self.fya_concurrent_phase_changed.connect(self.on_fya_concurrent_phase_changed,
                                                  sender=self)
        self.fya_extension_timer = AsyncTimer(f'SignalFYAExtension{self.id}',
                                              goal=FYA_MINIMUM_TIME)
        
        self.extend_reset = blinker.Signal()
        self.extend_reset.connect(self.on_extend_reset)
        
        self.initial_state = initial_state
        self._change_state(self.initial_state, force=True)
    
    def add_extend_sync_signal(self, signal: 'Signal'):
        assert signal.id != self.id
        assert signal not in self.extend_sync_signals
        
        signal.extend_reset.connect(self.on_sync_signal_extend_reset)
        self.extend_sync_signals.append(signal)
    
    def recall(self):
        match self.recall_mode:
            case RecallMode.OFF:
                self._recall_state = RecallMode.OFF
            case RecallMode.MINIMUM:
                self._recall_state = RecallMode.MINIMUM
                self.demand = True
                logger.debug('{} minimum recall', self.get_tag())
            case RecallMode.MINIMUM:
                self._recall_state = RecallMode.MINIMUM
                self.demand = True
                logger.debug('{} maximum recall', self.get_tag())
            case _:
                raise NotImplementedError()
    
    def get_interval_time_remaining(self, state: Optional[SignalState] = None):
        if state is None:
            state = self.state
        
        interval_timing = self.timings.get(state)
        if interval_timing:
            interval_time = 0.0
            
            if interval_timing:
                minimum_time = interval_timing.minimum or 0.0
                maximum_time = interval_timing.maximum or 0.0
                
                if state != SignalState.GO:
                    interval_time = max(minimum_time, maximum_time)
                else:
                    interval_time = minimum_time
            
            if state == self.state:
                interval_time -= self.interval_timer.elapsed
            
            return max(0.0, interval_time)
        else:
            return None
    
    def get_service_status(self,
                           phase_group: Optional[List['Signal']] = None,
                           barrier_group: Optional[List['Signal']] = None) -> ServiceStatus:
        requires_demand = self.service_conditions & ServiceConditions.DEMAND
        demand = self.demand or not requires_demand
        
        if demand:
            if self.remote_fya_signal is not None:
                if not self.remote_fya_signal.safe or self.remote_fya_signal.fya_active:
                    return self.ServiceStatus(False, ServiceReason.REMOTE_FYA)
            
            if self.fya_available:
                if self.fya_force_service:
                    return self.ServiceStatus(True, ServiceReason.FYA_FORCE_SERVICE)
                elif ((not barrier_group or len(barrier_group) % 2 == 0) and
                    all([s.fya_available for s in phase_group]) and
                    all([s.fya_available for s in barrier_group])):
                    return self.ServiceStatus(True, ServiceReason.ALL_FYA)
                else:
                    return self.ServiceStatus(False, ServiceReason.FYA)
        
        if not self.safe:
            return self.ServiceStatus(False, ServiceReason.NOT_SAFE)
                
        if phase_group:
            with_vehicle = self.service_conditions & ServiceConditions.WITH_VEHICLE
            with_any = self.service_conditions & ServiceConditions.WITH_ANY
            
            for signal in phase_group:
                if signal == self:
                    continue
                
                check_signal = with_any
                condition = ServiceReason.WITH_ANY
                
                if with_vehicle and signal.type == SignalType.VEHICLE:
                    if signal.recycle == self.recycle or not signal.conflicting_demand:
                        condition = ServiceReason.WITH_VEHICLE
                        check_signal = True
                
                if check_signal:
                    signal_status = signal.get_service_status(phase_group=phase_group,
                                                              barrier_group=barrier_group)
                    if signal.active or signal_status.service:
                        return self.ServiceStatus(True,
                                                  condition,
                                                  lagging_signal=signal)
        
        return self.ServiceStatus(demand, ServiceReason.DEMAND)
    
    def _can_extend(self):
        if self.conflicting_demand and self.service_timeout:
            return False
        
        if SignalState.EXTEND not in self.timings:
            return False
        
        if self.extend_mode != ExtendMode.OFF:
            extend_time = self.timings.get(SignalState.EXTEND)
            if extend_time is not None and extend_time.minimum:
                proceed = True
                
                if self.extend_mode == ExtendMode.MINIMUM_SKIP:
                    proceed = self.presence_stopwatch.elapsed < extend_time.minimum
                
                if proceed:
                    go_time = self.timings.get(SignalState.GO)
                    if go_time is not None and go_time.maximum:
                        proceed = self.service_timer.elapsed < go_time.maximum
                
                if proceed:
                    if self.recall_state != RecallMode.MAXIMUM:
                        return True
        return False
    
    def _change_state(self,
                      new_state: SignalState,
                      force: bool = False):
        previous_state = self._state
        if new_state != previous_state or force:
            previous_field_output = self.mapping[self._state]
            previous_field_output.set(FieldOutputState.OFF)
            
            self._state = new_state
            
            field_output = self.mapping[self._state]
            interval_config = self.configs.get(self._state)
            
            if interval_config and interval_config.flashing:
                field_output.set(FieldOutputState.FLASHING)
            else:
                field_output.set(FieldOutputState.ON)
            
            logger.debug('{} state = {}', self.get_tag(), new_state.name)
            self.state_changed.send(self, previous_state=previous_state, new_state=new_state)
    
    async def _wait_rest(self):
        while self.resting:
            await asyncio.sleep(POLL_RATE)
    
    async def _caution_interval(self):
        caution_timing = self.timings.get(SignalState.CAUTION)
        if caution_timing:
            caution_time = caution_timing.minimum
            
            if caution_time:
                self.service_timer.pause()
                
                if self.service_timer.running:
                    self.service_timer.cancel()
                
                self._change_state(SignalState.CAUTION)
                self.interval_timer.set(caution_time)
                marker = millis()
                await self.interval_timer.wait()
                delta = millis() - marker
                logger.debug('{} caution interval took {}',
                             self.get_tag(),
                             format_ms(delta))
    
    async def _stop_interval(self):
        self.service_timer.pause()
        
        if self.service_timer.running:
            self.service_timer.cancel()
        
        self._change_state(SignalState.STOP)
        stop_timing = self.timings.get(SignalState.STOP)
        if stop_timing:
            stop_minimum = stop_timing.minimum
            if stop_minimum:
                self.interval_timer.set(stop_minimum)
                marker = millis()
                await self.interval_timer.wait()
                delta = millis() - marker
                logger.debug('{} stop interval took {}',
                             self.get_tag(),
                             format_ms(delta))
        
        self.presence_lockout = False
        self.demand = self.presence
        
        self.recall()
    
    async def fya(self):
        assert self.state == SignalState.STOP
        self.fya_concurrent_phase.state_changed.connect(self.on_fya_concurrent_phase_state_changed)
        self._change_state(SignalState.FYA)
        if not self.latch:
            self.demand = False
    
    async def _go_extend(self):
        go_timing = self.timings.get(SignalState.GO)
        
        if not go_timing:
            return
        
        self.service_timeout = False
        self.demand = False
        self.fya_force_service = False
        
        go_minimum = go_timing.minimum
        if go_minimum:
            self._change_state(SignalState.GO)
            
            go_maximum = go_timing.maximum
            if go_maximum:
                self.service_timer.set(go_maximum)
                self.service_timer.start()
            
            self.interval_timer.set(go_minimum)
            
            marker = millis()
            await self.interval_timer.wait()
            delta = millis() - marker
            logger.debug('{} go interval took {}',
                         self.get_tag(),
                         format_ms(delta))
            
            await self._wait_rest()
        
        if self._can_extend():
            extend_minimum = self.timings[SignalState.EXTEND].minimum
            self._change_state(SignalState.EXTEND)
            self.interval_timer.set(extend_minimum)
            
            await self.interval_timer.wait()
            await self._wait_rest()
        
        if self.fya_extension:
            await self.fya_extension_timer.wait()
    
    async def serve(self, group: Optional[List['Signal']] = None):
        if not self.safe and not self.fya_force_service:
            raise RuntimeError(f'{self.get_tag()} not safe to serve')
        
        if not self.has_go_state:
            raise RuntimeError(f'{self.get_tag()} does not have go state to serve')

        go_timing = self.timings.get(SignalState.GO)
        if go_timing:
            lagging_signals = []
            if self.service_modifiers & ServiceModifiers.BEFORE_VEHICLE:
                for signal in group:
                    if (signal.type == SignalType.VEHICLE and
                        not signal.movement & TrafficMovement.PROTECTED_TURN):
                        signal.leading_signals.append(self)
                        lagging_signals.append(signal)
            
            self._active = True
            
            await self._go_extend()
            while not self.conflicting_demand:
                await self._go_extend()
            
            await self._caution_interval()
            await self._stop_interval()
        
            for lagging_signal in lagging_signals:
                lagging_signal.leading_signals.remove(self)
            
            self._active = False
            self.latch_once = False
            self.fya_extension = False
    
    def on_service_timeout(self, _):
        self.service_timeout = True
        
        if self.state in (SignalState.GO, SignalState.EXTEND):
            if self.interval_timer.running:
                self.interval_timer.cancel()
    
    def on_demand_changed(self, _, edge_type: EdgeType):
        self.demand_stopwatch.reset()
        
        match edge_type:
            case EdgeType.RISING:
                self.fya_demand_timer.start()
            case EdgeType.FALLING:
                self.fya_demand_timer.cancel()
    
    def on_demand_timeout(self, _):
        if self.demand:
            if self.remote_fya_signal is not None:
                if self.remote_fya_signal.fya_active:
                    logger.debug('{} terminating {} (remote)',
                                 self.get_tag(),
                                 self.remote_fya_signal.get_tag())
                    self.remote_fya_signal.terminate_fya()
    
    def on_sync_signal_extend_reset(self, signal: 'Signal'):
        assert signal.id != self.id
        self.on_extend_reset(self)
    
    def on_extend_reset(self, _):
        if self.state == SignalState.EXTEND:
            self.interval_timer.reset()
            #self.interval_timer.pause()
    
    def on_presence_changed(self, _, edge_type: EdgeType):
        self.presence_stopwatch.reset()
        
        match edge_type:
            case EdgeType.RISING:
                self.presence_timer.start()
                
                if self.state == SignalState.EXTEND:
                    self.extend_reset.send(self)
                elif self.fya_active:
                    self.fya_presence_timer.start()
                elif self.state in (SignalState.CAUTION, SignalState.STOP):
                    self.demand = True
            case EdgeType.FALLING:
                self.presence_timer.cancel()
                #self.interval_timer.resume()
                
                if self.fya_active:
                    self.fya_presence_timer.cancel()
                if not self.latch and self.recall_state == RecallMode.OFF:
                    self.demand = False
    
    def on_presence_timeout(self, _):
        if self.presence:
            if self.state != SignalState.STOP:
                self.presence_lockout = True
    
    async def _wait_for_fya_termination(self):
        assert self.fya_active
        await self._caution_interval()
        await self._stop_interval()
    
    def terminate_fya(self):
        if self.fya_active:
            self._fya_task = asyncio.create_task(self._wait_for_fya_termination())
        else:
            logger.debug('FYA termination skipped as signal state is {}', self.state.name)
    
    def on_fya_concurrent_phase_state_changed(self,
                                              _,
                                              signal: 'Signal',
                                              previous_state: Optional['SignalState'] = None,
                                              new_state: Optional['SignalState'] = None):
        if self.fya_active:
            if new_state not in (SignalState.GO, SignalState.EXTEND):
                if self.fya_force_service:
                    return
                
                logger.debug('{} terminating {} (concurrent)',
                             signal.get_tag(),
                             self.get_tag())
                self.terminate_fya()
            else:
                if not self.has_go_state and not self.latch:
                    self.demand = False
    
    def on_fya_enabled_changed(self, _, edge_type: EdgeType):
        if edge_type == EdgeType.FALLING:
            logger.debug('{} terminated (FYA disabled)', self.get_tag())
            self.terminate_fya()
    
    def on_fya_force_service(self, _):
        if not self.fya_force_service:
            if self.fya_available and self.fya_active:
                if self.has_go_state and self.fya_guard_phase is not None:
                    if self.fya_guard_phase.state in (SignalState.GO, SignalState.EXTEND) and self.fya_guard_phase.resting:
                        if self.presence:
                            self.fya_guard_phase.state_changed.connect(self.on_fya_guard_phase_state_changed)
                            self.fya_force_service = True
                            self.demand = True
                    else:
                        logger.debug('{} cannot force FYA service as guard phase '
                                     '{} is not resting or in a disallowed state',
                                     self.get_tag(),
                                     self.fya_guard_phase.get_tag())
                else:
                    logger.debug('{} cannot force FYA service as does not have a '
                                 'guard phase or go state',
                                 self.get_tag())
            else:
                logger.debug('{} cannot force FYA service as FYA is not available or active',
                             self.get_tag())
        else:
            logger.debug('{} already forcing FYA service', self.get_tag())
    
    def on_fya_guard_phase_state_changed(self,
                                         _,
                                         signal: 'Signal',
                                         previous_state: Optional['SignalState'] = None,
                                         new_state: Optional['SignalState'] = None):
        if self.fya_force_service:
            if new_state not in (SignalState.GO, SignalState.EXTEND):
                logger.debug('{} terminating {} (guard)',
                             signal.get_tag(),
                             self.get_tag())
                self.terminate_fya()
    
    def on_fya_concurrent_phase_changed(self,
                                        _,
                                        previous_phase: Optional['Phase'] = None,
                                        new_phase: Optional['Phase'] = None):
        if previous_phase:
            for ped_signal in previous_phase.pedestrian_signals:
                ped_signal.remote_fya_signal = None
        
        for ped_signal in new_phase.pedestrian_signals:
            ped_signal.remote_fya_signal = self
    
    def __repr__(self):
        return (f'<Signal #{self.id} {self.state.name} '
                f'service_time={self.service_timer.elapsed:03.2f} '
                f'active={self.active} '
                f'demand={self.demand} '
                f'presence={self.presence} '
                f'presence_time={self.presence_stopwatch.elapsed:03.2f} '
                f'resting={self.resting} '
                f'recall={self.recall_mode.name} '
                f'recycle={self.recycle}>')
    
    def rpc_model(self):
        return rpc_Signal(self.id,
                          active=self.active,
                          resting=self.resting,
                          presence=self.presence,
                          presence_lockout=self.presence_lockout,
                          demand=self.demand,
                          interval_time=self.interval_timer.elapsed,
                          service_time=self.service_timer.elapsed,
                          presence_time=self.presence_stopwatch.elapsed,
                          demand_time=self.demand_stopwatch.elapsed,
                          runtime_remaining=self.runtime_remaining(),
                          runtime_maximum=self.runtime_maximum,
                          service_maximum=self.service_maximum,
                          state=self.state)


class Phase(Identifiable):
    global_field_output_mapping: Dict[FieldOutput, 'Phase'] = {}
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional['Signal']:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def active_signals(self):
        return [s for s in self.signals if s.active]
    
    @property
    def inactive_signals(self):
        return [s for s in self.signals if not s.active]
    
    @property
    def waiting_signals(self):
        return [s for s in self.signals if s.demand]
    
    @property
    def fya_signals(self):
        return [s for s in self.signals if s.fya_available]
    
    @property
    def vehicle_signals(self):
        return [s for s in self.signals if s.type == SignalType.VEHICLE]
    
    @property
    def pedestrian_signals(self):
        return [s for s in self.signals if s.type == SignalType.PEDESTRIAN]
    
    @property
    def state(self):
        return SignalState(max([s.state for s in self.signals]))
    
    @property
    def has_go_state(self):
        return all([s.has_go_state for s in self.signals])
    
    @property
    def demand(self):
        return any([s.demand for s in self.signals])
    
    @demand.setter
    def demand(self, value):
        for signal in self.signals:
            signal.demand = bool(value)
    
    @property
    def latch(self):
        return any([s.latch for s in self.signals])
    
    @latch.setter
    def latch(self, value):
        for signal in self.signals:
            signal.latch = value
    
    @property
    def latch_once(self):
        return any([s.latch_once for s in self.signals])
    
    @latch_once.setter
    def latch_once(self, value):
        for signal in self.signals:
            signal.latch_once = value
    
    @property
    def conflicting_demand(self):
        return any([s.conflicting_demand for s in self.signals])
    
    @conflicting_demand.setter
    def conflicting_demand(self, value):
        for signal in self.signals:
            signal.conflicting_demand = value
    
    @property
    def resting(self):
        return all([s.resting for s in self.signals])
    
    @property
    def presence(self):
        return any([s.presence for s in self.signals])
    
    @presence.setter
    def presence(self, value):
        for signal in self.signals:
            signal.presence = bool(value)
    
    @property
    def interval_time(self):
        return max([s.interval_timer.elapsed for s in self.signals])
    
    @property
    def service_time(self):
        return max([s.service_timer.elapsed for s in self.signals])
    
    @property
    def runtime_maximum(self):
        return max([s.runtime_maximum for s in self.signals])
    
    def runtime_remaining(self, cutoff_state: Optional[SignalState] = None):
        return max([s.runtime_remaining(cutoff_state=cutoff_state) for s in self.signals])
    
    @property
    def fya_active(self):
        return any([s.fya_active for s in self.signals])
    
    @property
    def fya_available(self):
        return any([s.fya_available for s in self.signals])
    
    @property
    def fya_extension(self):
        return all([s.fya_extension for s in self.signals])
    
    @property
    def field_outputs(self):
        rv = set()
        for signal in self.signals:
            for field_output in signal.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 signals: List[Signal],
                 default_signals: Optional[List[Signal]] = None,
                 default_phases: Optional[List['Phase']] = None,
                 recycle: bool = True):
        Identifiable.__init__(self, id_)
        
        self.recycle = recycle
        self.state_changed = blinker.Signal()
        self.signals = signals
        self.default_signals = default_signals or []
        self.default_phases = default_phases or []
        
        for signal in signals:
            for fo in signal.field_outputs:
                self.global_field_output_mapping.update({fo: self})
            signal.state_changed.connect(self._signal_state_changed)
    
    def _signal_state_changed(self, signal: Signal, previous_state: SignalState, new_state: SignalState):
        self.state_changed.send(self, signal=signal, previous_state=previous_state, new_state=new_state)
    
    def get_serviceable_signals(self, barrier_group: Optional[List['Signal']] = None):
        for signal in self.signals:
            status = signal.get_service_status(phase_group=self.signals,
                                               barrier_group=barrier_group)
            if status.service:
                yield signal
    
    def get_interval_time_remaining(self, state: Optional[SignalState] = None):
        return max([s.get_interval_time_remaining(state=state) for s in self.signals])
    
    def recall(self):
        for signal in self.signals:
            signal.recall()
    
    def __repr__(self):
        return f'<Phase #{self.id} active={len(self.active_signals)} demand={self.demand}>'
    
    def rpc_model(self):
        return rpc_Phase(self.id,
                         presence=self.presence,
                         demand=self.demand,
                         resting=self.resting,
                         field_output_ids=[fo.id for fo in self.field_outputs],
                         signal_ids=[s.id for s in self.signals],
                         interval_time=self.interval_time,
                         service_time=self.service_time,
                         state=self.state)


class Ring(Identifiable):
    
    @property
    def active_phase(self) -> Optional[Phase]:
        for phase in self.phases:
            if phase.active_signals:
                return phase
        return None
    
    @property
    def active_phases(self):
        return [p for p in self.phases if p.active_signals]
    
    @property
    def waiting_phases(self):
        return [p for p in self.phases if p.demand and not p.active_signals]
    
    @property
    def signals(self):
        return list(chain(*[p.signals for p in self.phases]))
    
    @property
    def demand(self):
        return any([p.demand for p in self.phases])
    
    @demand.setter
    def demand(self, value):
        for phase in self.phases:
            phase.demand = value
    
    @property
    def field_outputs(self):
        rv = set()
        for phase in self.phases:
            for field_output in phase.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 phases: List[Phase]):
        super().__init__(id_)
        self.phases = phases
    
    def intersection(self, barrier: 'Barrier') -> Set[Phase]:
        return set(self.phases).intersection(barrier.phases)
    
    def __repr__(self):
        active = self.active_phase.get_tag() if self.active_phase else None
        return f'<Ring #{self.id} active={active} waiting={len(self.waiting_phases)}>'


class Barrier(Identifiable):
    
    @property
    def active_phases(self):
        return [p for p in self.phases if p.active_signals]
    
    @property
    def waiting_phases(self):
        return [p for p in self.phases if p.demand and not p.active_signals]
    
    @property
    def fya_phases(self):
        return [p for p in self.phases if p.fya_available]
    
    @property
    def signals(self):
        return list(chain(*[p.signals for p in self.phases]))
    
    @property
    def demand(self):
        return any([p.demand for p in self.phases])
    
    @demand.setter
    def demand(self, value):
        for phase in self.phases:
            phase.demand = value
            
    @property
    def conflicting_demand(self):
        return self._conflicting_demand
    
    @conflicting_demand.setter
    def conflicting_demand(self, value):
        if value != self._conflicting_demand:
            logger.verbose('{} conflicting_demand = {}', self.get_tag(), value)
        self._conflicting_demand = value
    
    
    def __init__(self, id_: int, phases: List[Phase]):
        super().__init__(id_)
        self._conflicting_demand: bool = False

        self.phases = phases
        self.service_history: List[Signal] = []
    
    def __repr__(self):
        return (f'<Barrier #{self.id} '
                f'active={len(self.active_phases)} '
                f'waiting={len(self.waiting_phases)} '
                f'conflicting_demand={self.conflicting_demand} '
                f'service_history={self.service_history}>')


class IntersectionService:
    
    @property
    def phases(self) -> List[Phase]:
        return list(chain(*[r.phases for r in self.rings]))
    
    @property
    def active_phases(self) -> List[Phase]:
        return [p for p in self.phases if p.active_signals]
    
    @property
    def waiting_phases(self) -> List[Phase]:
        return [p for p in self.phases if p.demand and not p.active_signals]
    
    @property
    def active_barrier(self):
        if len(self.barrier_history):
            return self.barrier_history[-1]
        else:
            return None
    
    @property
    def inactive_barriers(self):
        active_barrier = self.active_barrier
        if active_barrier is None:
            return self.barriers
        else:
            return [b for b in self.barriers if b != active_barrier]
    
    @property
    def waiting_barriers(self):
        return [b.waiting_phases for b in self.inactive_barriers]
    
    @property
    def signals(self) -> List[Signal]:
        return list(chain(*[p.signals for p in self.phases]))
    
    @property
    def field_outputs(self):
        rv = set()
        for ring in self.rings:
            for field_output in ring.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    @property
    def mode(self):
        return self._mode
    
    @property
    def cycle_count(self):
        return self._cycle_count
    
    @property
    def fya_enabled(self):
        return self._fya_enabled
    
    @fya_enabled.setter
    def fya_enabled(self, value):
        if value != self._fya_enabled:
            logger.verbose('fya_enabled = {}', value)
            self._fya_enabled = value
    
    def __init__(self,
                 rings: List[Ring],
                 barriers: List[Barrier],
                 mode: PhaseCyclerMode,
                 fya_enabled: bool = False):
        super().__init__()
        self.rings = rings
        self.barriers = barriers
        
        self.barrier_history: List[Barrier] = []
        
        self._mode = PhaseCyclerMode.PAUSE
        self._cycle_count: int = 0
        self._signal_tasks: List[asyncio.Task] = []
        self._fya_enabled = fya_enabled
        self._max_revert_time = max([s.revert_time for s in self.signals])
        self._stopped_with_demand_stopwatch = AsyncStopwatch()
        
        # sequential mode only
        self._phase_sequence = utils.cycle(self.phases)
        
        # concurrent mode only
        self._barrier_sequence = utils.cycle(self.barriers)
        
        for barrier in self.barriers:
            barrier.ring_count = len(self.rings)
        
        self.set_mode(mode)
    
    def get_ring_by_phase(self, phase: Phase) -> Optional[Ring]:
        for ring in self.rings:
            if phase in ring.phases:
                return ring
        return None
    
    def get_barrier_by_phase(self, phase: Phase) -> Optional[Barrier]:
        for barrier in self.barriers:
            if phase in barrier.phases:
                return barrier
        return None
    
    def get_phase_by_signal(self, signal: Signal) -> Optional[Phase]:
        for phase in self.phases:
            if signal in phase.signals:
                return phase
        return None
    
    def set_mode(self, mode: PhaseCyclerMode):
        if mode == self.mode:
            return False
        
        match self.mode:
            case PhaseCyclerMode.SEQUENTIAL:
                self.barrier_history.clear()
                
                if self.active_phases:
                    last_phase = self.active_phases[-1]
                    phase_index = self.phases.index(last_phase)
                    next_index = phase_index + 1 if phase_index < (len(self.phases) - 1) else 0
                else:
                    next_index = 0
                
                self._phase_sequence = utils.cycle(self.phases, initial=next_index)
            case PhaseCyclerMode.CONCURRENT:
                barrier_index = 0
                last_barrier = None
                
                if self.active_barrier is not None:
                    barrier_index = self.barriers.index(self.active_barrier) + 1
                elif self.active_phases:
                    for barrier in self.barriers:
                        if self.active_phases[-1] in barrier.phases:
                            last_barrier = barrier
                            break
                    
                    if last_barrier:
                        barrier_index = self.barriers.index(last_barrier)
                
                self._barrier_sequence = utils.cycle(self.barriers, initial=barrier_index)
                
                if last_barrier is not None:
                    self.barrier_history.append(last_barrier)
                else:
                    self.barrier_history.append(self.barriers[0])
        
        self._mode = mode
        logger.info('cycle_mode = {}', mode.name)
        return True
    
    def select_phases(self):
        assert self.active_barrier
        
        selected: Dict[Phase, List[Signal]] = {}
        
        for ring in self.rings:
            if ring.active_phase:
                continue
            
            phase_intersection = ring.intersection(self.active_barrier)
            for phase in phase_intersection:
                if phase.demand and phase.has_go_state:
                    selected.update({phase: []})
                    break
        
        if len(selected):
            fya_phases = [p for p in selected.keys() if p.fya_available]
            if self.waiting_barriers and not all(fya_phases):
                for skip_phase in fya_phases:
                    logger.verbose('selection disqualified {} (lagging FYA '
                                   'service with waiting phases in other barrier)',
                                   skip_phase.get_tag())
                    del selected[skip_phase]
        
            empty_phases = []
            
            for phase in selected.keys():
                barrier_group = list(chain(*[p.signals for p in selected.keys()]))
                
                for signal in phase.get_serviceable_signals(barrier_group=barrier_group):
                    if self.active_barrier is not None:
                        if self.active_barrier.conflicting_demand:
                            if signal in self.active_barrier.service_history:
                                continue
                    selected[phase].append(signal)
                
                if not len(selected[phase]):
                    empty_phases.append(phase)
            
            for empty_phase in empty_phases:
                logger.verbose('selection disqualified {} (empty)', empty_phase.get_tag())
                del selected[empty_phase]
        
        return selected
    
    def change_barrier(self, b: Barrier):
        self.barrier_history.append(b)
        logger.debug('{} active', b.get_tag())
        
        if len(self.barrier_history) > len(self.barriers):
            self.barrier_history.pop(0)
            return True
        else:
            return False
    
    async def _try_idle(self):
        if not self.waiting_phases:
            logger.debug('idle')
            marker = millis()
            while not self.waiting_phases:
                await asyncio.sleep(POLL_RATE)
            delta = millis() - marker
            logger.debug('idled for {}', format_ms(delta))
            return True
        else:
            return False
    
    async def _try_pause(self):
        if self.mode == PhaseCyclerMode.PAUSE:
            logger.debug('paused')
            marker = millis()
            while self.mode == PhaseCyclerMode.PAUSE:
                await asyncio.sleep(POLL_RATE)
            delta = millis() - marker
            logger.debug('paused for {}', format_ms(delta))
            return True
        else:
            return False
    
    def serve_signals(self, signals: List[Signal] = None):
        for signal in signals:
            if self.active_barrier is not None:
                assert signal in self.active_barrier.signals
                self.active_barrier.service_history.append(signal)
            self._signal_tasks.append(
                asyncio.create_task(signal.serve(group=signals))
            )
    
    async def _wait_for_signals(self):
        if len(self._signal_tasks):
            done, pending = await asyncio.wait(self._signal_tasks,
                                               return_when=asyncio.FIRST_COMPLETED)
            while pending:
                for task in pending:
                    try:
                        raise task.exception()
                    except (TypeError, InvalidStateError):
                        pass
                
                await asyncio.sleep(POLL_RATE)
                done, pending = await asyncio.wait(self._signal_tasks,
                                                   return_when=asyncio.FIRST_COMPLETED)
                
            for task in done:
                try:
                    raise task.exception()
                except (TypeError, InvalidStateError):
                    pass
            
            while not all(s.safe for s in self.signals):
                await asyncio.sleep(POLL_RATE)
            
            self._signal_tasks.clear()
    
    async def _wait_for_all_safe(self):
        while any([not s.safe for s in self.signals]):
            await asyncio.sleep(POLL_RATE)
    
    async def poll(self):
        try:
            while True:
                for barrier in self.barriers:
                    barrier.conflicting_demand = False
                    for other_barrier in self.barriers:
                        if other_barrier.id == barrier.id:
                            continue
                        if other_barrier.waiting_phases:
                            barrier.conflicting_demand = True
                            break
                
                for phase in self.phases:
                    barrier = self.get_barrier_by_phase(phase)
                    
                    for signal in phase.signals:
                        signal.fya_enabled = self.fya_enabled
                        
                        if signal.active:
                            if self.active_barrier:
                                if signal not in self.active_barrier.signals:
                                    raise Conflict(f'{signal.get_tag()} not in {self.active_barrier.get_tag()}')
                        else:
                            if signal.fya_available:
                                if not signal.fya_active:
                                    if signal.safe and signal.revert_clear:
                                        if signal.fya_concurrent_phase.state in (SignalState.GO, SignalState.EXTEND):
                                            if not signal.fya_concurrent_phase.fya_extension:
                                                service_remaining = signal.fya_concurrent_phase.runtime_remaining(
                                                    cutoff_state=SignalState.CAUTION
                                                )
                                                if service_remaining < FYA_MINIMUM_TIME:
                                                    for vehicle_signal in signal.fya_concurrent_phase.vehicle_signals:
                                                        vehicle_signal.fya_extension = True
                                            
                                            service_remaining = signal.fya_concurrent_phase.runtime_remaining(
                                                cutoff_state=SignalState.CAUTION
                                            )
                                            if service_remaining >= FYA_MINIMUM_TIME:
                                                for ps in signal.fya_concurrent_phase.pedestrian_signals:
                                                    if ps.active:
                                                        break
                                                    
                                                    if ps.interval_timer.elapsed < FYA_MINIMUM_PEDESTRIAN_STOP_TIME:
                                                        break
                                                else:
                                                    await signal.fya()
                                    
                                    for vehicle_signal in signal.fya_concurrent_phase.vehicle_signals:
                                        if not signal.has_go_state:
                                            vehicle_signal.presence = vehicle_signal.presence or signal.presence
                                        
                                        if self.active_barrier and self.active_barrier != barrier:
                                            if signal.demand:
                                                if barrier and all([fp.demand for fp in barrier.fya_phases]):
                                                    for fya_phase in barrier.fya_phases:
                                                        fya_phase.latch_once = True
                                                    break
                                                else:
                                                    vehicle_signal.demand = True
                                                    signal.demand = False
                    
                    if phase.demand:
                        for signal in phase.default_signals:
                            if not signal.active:
                                signal.demand = True
                        
                        if barrier:
                            for barrier_phase in barrier.phases:
                                if barrier_phase == phase:
                                    continue
                                if barrier_phase.demand:
                                    break
                            else:
                                for other_phase in phase.default_phases:
                                    if (not other_phase.demand and
                                        not other_phase.active_signals):
                                        if other_phase.default_signals:
                                            for default_signal in other_phase.default_signals:
                                                default_signal.demand = True
                                        else:
                                            other_phase.demand = True
                    
                    ring = self.get_ring_by_phase(phase)
                    
                    for waiting_phase in self.waiting_phases:
                        if self.active_barrier:
                            if waiting_phase not in self.active_barrier.phases:
                                phase.conflicting_demand = True
                                break
                            if waiting_phase in ring.phases and waiting_phase.fya_active:
                                phase.conflicting_demand = True
                                break
                        if ring and waiting_phase in ring.phases:
                            phase.conflicting_demand = True
                            break
                        for ped_signal in waiting_phase.pedestrian_signals:
                            if ped_signal.remote_fya_signal is not None:
                                ped_signal.conflicting_demand = True
                                break
                    else:
                        phase.conflicting_demand = False
                        
                        signals = []
                        if self.active_barrier is not None and len(phase.inactive_signals):
                            if all([s.resting and not s.leading_signals for s in phase.active_signals]):
                                for signal in phase.inactive_signals:
                                    if not signal.fya_available:
                                        status = signal.get_service_status(phase_group=phase.active_signals)
                                        if status.service:
                                            signals.append(signal)
                        self.serve_signals(signals)
                    
                    # selected = self.select_phases()
                    # if selected:
                    #     signals = list(chain(*selected.values()))
                    #     self.serve_signals(signals)
                
                for ring in self.rings:
                    if len(ring.active_phases) > 1:
                        raise Conflict(f'{ring.get_tag()} has multiple phases active')
                
                stopped_resting_signals = 0
                signals_with_demand = 0
                for signal in self.signals:
                    if signal.state == SignalState.STOP and signal.resting:
                        stopped_resting_signals += 1
                    if signal.demand:
                        signals_with_demand += 1
                
                if self.cycle_count >= 1:
                    if stopped_resting_signals == len(self.signals) and signals_with_demand:
                        if self._stopped_with_demand_stopwatch.elapsed > self._max_revert_time:
                            self._stopped_with_demand_stopwatch.reset()
                            raise RuntimeError('phase service deadlock')
                    else:
                        self._stopped_with_demand_stopwatch.reset()
                
                await asyncio.sleep(POLL_RATE)
        except asyncio.CancelledError:
            pass
    
    async def service(self):
        logger.debug('max revert time is {}', self._max_revert_time)
        self.change_barrier(next(self._barrier_sequence))
        
        try:
            while True:
                await self._try_pause()
                
                for phase in self.phases:
                    phase.recall()
                
                await self._try_idle()
                await self._wait_for_all_safe()
                
                match self.mode:
                    case PhaseCyclerMode.SEQUENTIAL:
                        for _ in range(len(self.phases)):
                            phase = next(self._phase_sequence)
                            if phase in self.waiting_phases:
                                selected = self.select_phases()
                                assert len(selected.keys()) == 1
                                signals = list(chain(*selected.values()))
                                self.serve_signals(signals)
                                await self._wait_for_signals()
                    case PhaseCyclerMode.CONCURRENT:
                        while True:
                            selected = self.select_phases()
                            
                            if selected:
                                signals = list(chain(*selected.values()))
                                self.serve_signals(signals)
                                await self._wait_for_signals()
                            else:
                                if self.change_barrier(next(self._barrier_sequence)):
                                    break
                            
                            if self.active_barrier is None:
                                break
                
                for barrier in self.barriers:
                    barrier.service_history.clear()
                
                self._cycle_count += 1
                logger.debug('cycle #{}', self._cycle_count)
        except asyncio.CancelledError:
            pass


class Input(Identifiable):
    
    @property
    def state(self):
        return self._state
    
    @property
    def last_state(self):
        return self._last_state
    
    @property
    def changed(self):
        return self._changed
    
    def __init__(self,
                 id_: int,
                 activation: InputActivation,
                 action: InputAction,
                 targets: List[Phase]):
        super().__init__(id_)
        
        self.activation = activation
        self.action = action
        self.targets = targets
        
        self._state: bool = False
        self._last_state: bool = False
        self._changed: bool = False
    
    def activated(self) -> bool:
        match self.activation:
            case InputActivation.LOW:
                if not self.state and not self.last_state:
                    return True
            case InputActivation.HIGH:
                if self.state and self.last_state:
                    return True
            case InputActivation.RISING:
                if self.state and not self.last_state:
                    return True
            case InputActivation.FALLING:
                if not self.state and self.last_state:
                    return True
        return False
    
    def __repr__(self):
        return f'<Input {self.activation.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}' \
               f'{" CHANGED" if self.changed else ""}>'


class Conflict(Exception):
    pass
