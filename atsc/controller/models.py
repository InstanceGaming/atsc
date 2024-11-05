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
        condition: ServiceConditions
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
    def fya_force_service_delay(self):
        return self._fya_force_service_delay
    
    @property
    def fya_force_service(self):
        return self._fya_force_service
    
    @fya_force_service.setter
    def fya_force_service(self, value):
        if value != self._fya_force_service:
            logger.debug('{} fya_force_service = {}', self.get_tag(), value)
            self._fya_force_service = value
    
    @property
    def fya_available(self):
        return self.fya_enabled and self.fya_concurrent_phase is not None
    
    @property
    def demand(self):
        return self._demand
    
    @demand.setter
    def demand(self, value):
        if value != self._demand:
            logger.verbose('{} demand = {}', self.get_tag(), value)
            self._demand = bool(value)
    
    @property
    def latch(self):
        return self._latch
    
    @latch.setter
    def latch(self, value):
        if value != self._latch:
            logger.verbose('{} latch = {}', self.get_tag(), value)
            self._latch = bool(value)
    
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
            return go_timing.maximum
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
                    
                    extend_time = self.timings.get(SignalState.EXTEND)
                    if extend_time and extend_time.minimum:
                        duration += extend_time.minimum
        
        caution_time = self.timings[SignalState.CAUTION]
        
        if caution_time and caution_time.minimum:
            duration += caution_time.minimum
        
        stop_time = self.timings[SignalState.STOP]
        
        if stop_time and stop_time.minimum:
            duration += stop_time.minimum
        
        return duration
    
    @property
    def runtime_remaining(self):
        remaining = 0.0
        
        for state in reversed(SignalState):
            interval_time = self.get_interval_time_remaining(state=state)
            if interval_time:
                remaining += interval_time
        
        return round(remaining, FLOAT_PRECISION_TIME)
    
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
                 service_conditions: ServiceConditions = ServiceConditions.WITH_DEMAND,
                 service_modifiers: ServiceModifiers = ServiceModifiers.UNSET,
                 initial_state: SignalState = SignalState.STOP,
                 fya_enabled: bool = False,
                 fya_concurrent_phase: Optional['Phase'] = None,
                 fya_guard_phase: Optional['Phase'] = None,
                 fya_force_service_delay: Optional[float] = None,
                 revert_time: float = 0.0,
                 presence_lockout_delay: Optional[float] = None):
        Identifiable.__init__(self, id_)
        self._active = False
        self._type = type
        self._movement = movement
        self._state = SignalState.STOP
        self._conflicting_demand = False
        self._extend_mode = extend_mode
        self._recall_mode = recall
        self._recall_state = RecallMode.OFF
        self._recycle = recycle
        self._demand = demand
        self._latch = latch
        self._presence = False
        self._presence_lockout_delay = presence_lockout_delay
        self._presence_lockout = False
        self._service_conditions = service_conditions
        self._service_modifiers = service_modifiers
        self._revert_time = revert_time
        self._fya_task = None
        self._fya_force_service_delay = fya_force_service_delay
        
        self.timings = timings
        self.configs: Dict[SignalState, IntervalConfig] = defaultdict(IntervalConfig)
        for state, v in configs.items():
            self.configs[state] = v
        
        self.mapping = mapping
        for fo in mapping.values():
            self.global_field_output_mapping.update({fo: self})
        
        self.fya_enabled = fya_enabled
        self.fya_concurrent_phase = fya_concurrent_phase
        self.fya_guard_phase = fya_guard_phase
        self._fya_force_service = False
        
        self.leading_signals: List['Signal'] = []
        
        self.state_changed = blinker.Signal()
        self.interval_timer = AsyncTimer()
        self.service_timer = AsyncTimer(goal_handler=self.on_service_timeout,
                                        paused=True)
        self.presence_stopwatch = AsyncStopwatch()
        self.presence_timer = AsyncTimer(goal=self._presence_lockout_delay,
                                         goal_handler=self.on_presence_timeout)
        self.presence_edge = EdgeTrigger()
        self.presence_changed = blinker.Signal()
        self.presence_changed.connect(self.on_presence_changed)
        self.fya_presence_timer = AsyncTimer(goal=self.fya_force_service_delay,
                                             goal_handler=self.on_fya_force_service,
                                             repeat=True)
        
        self.initial_state = initial_state
        self._change_state(self.initial_state, force=True)
    
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
            
            return interval_time
        else:
            return None
    
    def get_service_status(self,
                           group: Optional[List['Signal']] = None) -> ServiceStatus:
        with_demand = self.service_conditions & ServiceConditions.WITH_DEMAND
        service = self.safe and not with_demand or self.demand
        
        if group:
            with_vehicle = self.service_conditions & ServiceConditions.WITH_VEHICLE
            with_any = self.service_conditions & ServiceConditions.WITH_ANY
            
            for signal in group:
                if signal == self:
                    continue
                
                check_signal = with_any
                condition = ServiceConditions.WITH_ANY
                
                if with_vehicle and signal.type == SignalType.VEHICLE:
                    if signal.recycle == self.recycle or not signal.conflicting_demand:
                        condition = ServiceConditions.WITH_VEHICLE
                        check_signal = True
                
                if check_signal:
                    signal_status = signal.get_service_status()
                    if signal.active or signal_status.service:
                        service = True
                        return self.ServiceStatus(service,
                                                  condition,
                                                  lagging_signal=signal)
        
        if service:
            if not self.fya_available or not self.fya_force_service:
                if not self.revert_clear:
                    service = False
        
        return self.ServiceStatus(service, ServiceConditions.WITH_DEMAND)
    
    def _can_extend(self):
        if self.extend_mode != ExtendMode.OFF:
            extend_time = self.timings.get(SignalState.EXTEND, 0.0)
            if extend_time and extend_time.minimum:
                proceed = False
                
                if self.extend_mode == ExtendMode.MINIMUM_SKIP:
                    proceed = self.presence_stopwatch.elapsed < extend_time.minimum
                
                if proceed:
                    go_time = self.timings.get(SignalState.GO, 0.0)
                    if go_time and go_time.maximum:
                        proceed = self.service_timer.elapsed < go_time.maximum
                
                if self.presence:
                    proceed = True
                
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
                self.service_timer.cancel()
                
                self._change_state(SignalState.CAUTION)
                self.interval_timer.set(caution_time)
                marker = millis()
                await self.interval_timer.wait()
                delta = millis() - marker
                logger.debug('caution interval took {}', format_ms(delta))
    
    async def _stop_interval(self):
        self.service_timer.pause()
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
                logger.debug('stop interval took {}', format_ms(delta))
        
        self.presence_lockout = False
        
        if self.presence:
            self.demand = True
        
        self.recall()
    
    async def fya(self):
        assert self.state == SignalState.STOP
        self.fya_concurrent_phase.state_changed.connect(self._on_fya_concurrent_phase_state_changed)
        self._change_state(SignalState.FYA)
        self.demand = False
        if self.presence:
            self.fya_presence_timer.start()
    
    def _on_fya_concurrent_phase_state_changed(self,
                                               _,
                                               signal: Optional['Signal'] = None,
                                               previous_state: Optional['SignalState'] = None,
                                               new_state: Optional['SignalState'] = None):
        if self.state == SignalState.FYA:
            if new_state not in (SignalState.GO, SignalState.EXTEND):
                if self.fya_force_service:
                    return
                
                self._fya_task = asyncio.create_task(self._fya_terminate())
            else:
                if not self.has_go_state:
                    self.demand = False
                
                self.fya_force_service = False
    
    async def _fya_terminate(self):
        if self.state == SignalState.FYA:
            await self._caution_interval()
            await self._stop_interval()
    
    async def serve(self, group: Optional[List['Signal']] = None):
        assert not self.active and self.has_go_state
        
        lagging_signals = []
        if self.service_modifiers & ServiceModifiers.BEFORE_VEHICLE:
            if group:
                for signal in group:
                    if (signal.type & SignalType.VEHICLE and not
                    signal.movement & TrafficMovement.PROTECTED_TURN):
                        signal.leading_signals.append(self)
                        lagging_signals.append(signal)
        
        self._active = True
        self.demand = False
        self.fya_force_service = False
        
        go_timing = self.timings.get(SignalState.GO)
        if go_timing:
            go_minimum = go_timing.minimum
            go_maximum = go_timing.maximum
            
            if go_maximum:
                self.service_timer.set(go_maximum)
                self.service_timer.resume()
                self.service_timer.start()
            
            if go_minimum:
                self._change_state(SignalState.GO)
                self.interval_timer.set(go_minimum)
                marker = millis()
                await self.interval_timer.wait()
                delta = millis() - marker
                logger.debug('go interval took {}', format_ms(delta))
            
            await self._wait_rest()
            
            if self._can_extend():
                extend_time = self.timings[SignalState.EXTEND].minimum
                
                if extend_time:
                    self._change_state(SignalState.EXTEND)
                    self.interval_timer.set(extend_time)
                    await self.interval_timer.wait()
            
            await self._wait_rest()
            await self._caution_interval()
        
        await self._stop_interval()
        
        for lagging_signal in lagging_signals:
            lagging_signal.leading_signals.remove(self)
        
        self._active = False
    
    def on_service_timeout(self, _):
        if not self.resting:
            if self.state in (SignalState.GO, SignalState.EXTEND):
                self.interval_timer.cancel()
            else:
                raise RuntimeError(f'service timer timeout while state is {self.state.name}')
    
    def on_presence_changed(self, _, edge_type: EdgeType):
        self.presence_stopwatch.reset()
        
        match edge_type:
            case EdgeType.RISING:
                self.presence_timer.start()
                
                if self.state == SignalState.EXTEND:
                    self.interval_timer.reset()
                elif self.state == SignalState.FYA:
                    self.fya_presence_timer.start()
                elif self.state in (SignalState.CAUTION, SignalState.STOP):
                    self.demand = True
            case EdgeType.FALLING:
                self.presence_timer.cancel()
                
                if self.state == SignalState.FYA:
                    self.fya_presence_timer.cancel()
                if not self.latch and self.recall_state == RecallMode.OFF:
                    self.demand = False
    
    def on_presence_timeout(self, _):
        if self.state != SignalState.STOP:
            self.presence_lockout = True
    
    def on_fya_force_service(self, _):
        if self.state == SignalState.FYA and self.has_go_state:
            if self.fya_guard_phase is not None:
                if not self.fya_force_service:
                    if (self.fya_guard_phase.state in (SignalState.GO, SignalState.EXTEND) and
                        self.fya_guard_phase.resting):
                        if self.presence:
                            self.fya_guard_phase.state_changed.connect(self._on_fya_guard_phase_state_changed)
                            self.fya_force_service = True
                            self.demand = True
    
    def _on_fya_guard_phase_state_changed(self,
                                          _,
                                          signal: Optional['Signal'] = None,
                                          previous_state: Optional['SignalState'] = None,
                                          new_state: Optional['SignalState'] = None):
        if self.fya_force_service:
            if new_state not in (SignalState.GO, SignalState.EXTEND):
                self._fya_task = asyncio.create_task(self._fya_terminate())
    
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
                          interval_time=round(self.interval_timer.elapsed, FLOAT_PRECISION_TIME),
                          service_time=round(self.service_timer.elapsed, FLOAT_PRECISION_TIME),
                          presence_time=round(self.presence_stopwatch.elapsed, FLOAT_PRECISION_TIME),
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
    
    @property
    def runtime_remaining(self):
        return max([s.runtime_remaining for s in self.signals])
    
    @property
    def fya_active(self):
        return any([s.state == SignalState.FYA for s in self.signals])
    
    @property
    def fya_available(self):
        return any([s.fya_available for s in self.signals])
    
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
    
    def get_serviceable_signals(self):
        serviceable = []
        for signal in self.signals:
            status = signal.get_service_status(self.signals)
            if status.service:
                serviceable.append(signal)
        return serviceable
    
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
                         interval_time=round(self.interval_time, FLOAT_PRECISION_TIME),
                         service_time=round(self.service_time, FLOAT_PRECISION_TIME),
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
    def signals(self):
        return list(chain(*[p.signals for p in self.phases]))
    
    @property
    def demand(self):
        return any([p.demand for p in self.phases])
    
    @demand.setter
    def demand(self, value):
        for phase in self.phases:
            phase.demand = value
    
    def __init__(self, id_: int, phases: List[Phase]):
        super().__init__(id_)
        self.phases = phases
    
    def __repr__(self):
        return f'<Barrier #{self.id} active={len(self.active_phases)} waiting={len(self.waiting_phases)}>'


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
    def phases_serviced(self):
        serviced = []
        
        for signal in self.signals_serviced:
            phase = self.get_phase_by_signal(signal)
            if phase not in serviced:
                serviced.append(phase)
        
        return serviced
    
    @property
    def phases_recycled(self):
        recycled = []
        
        for signal in self.signals_recycled:
            phase = self.get_phase_by_signal(signal)
            if phase not in recycled:
                recycled.append(phase)
        
        return recycled
    
    @property
    def active_barrier(self):
        if len(self.cycle_barriers):
            return self.cycle_barriers[-1]
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
        
        self.signals_serviced: List[Signal] = []
        self.signals_recycled: List[Signal] = []
        
        self.cycle_barriers: List[Barrier] = [self.barriers[0]]
        
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
                self.signals_serviced.clear()
                self.signals_recycled.clear()
                self.cycle_barriers.clear()
                
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
                    self.cycle_barriers.append(last_barrier)
                else:
                    self.cycle_barriers.append(self.barriers[0])
        
        self._mode = mode
        logger.info('cycle_mode = {}', mode.name)
        return True
    
    def select_signals(self, *phases) -> List[Signal]:
        signal_group = []
        
        phases: List[Phase]
        for phase in phases:
            signals = phase.get_serviceable_signals()
            
            for signal in signals:
                self.signals_serviced.append(signal)
                signal_group.append(signal)
        
        return signal_group
    
    def recycle_phase(self, phase: Phase) -> bool:
        if phase in self.phases_serviced and phase not in self.phases_recycled:
            if phase.recycle or any([s.demand and s.fya_force_service for s in phase.signals]):
                if self.active_barrier:
                    if any([b.waiting_phases for b in self.inactive_barriers]):
                        return False
                
                for signal in phase.signals:
                    if signal in self.signals_serviced:
                        self.signals_serviced.remove(signal)
                    if signal in self.signals_recycled:
                        self.signals_recycled.remove(signal)
                return True
        return False
    
    def select_phases(self):
        assert self.active_barrier
        
        selected_phases = []
        for ring in self.rings:
            if ring.active_phase:
                continue
            
            common_phases = ring.intersection(self.active_barrier)
            new_phases = sorted(common_phases - set(self.phases_serviced))
            
            for phase in new_phases:
                if phase.demand and phase.has_go_state:
                    selected_phases.append(phase)
                    break
        
        return selected_phases
    
    def try_change_barrier(self, b: Barrier):
        if self.cycle_barriers:
            if len(self.cycle_barriers) == len(self.barriers):
                del self.cycle_barriers[0]
            
            last_barrier = self.cycle_barriers[-1]
            self.cycle_barriers.append(b)
            
            logger.debug('crossed to {} from {}',
                         b.get_tag(),
                         last_barrier.get_tag())
            return True
        else:
            logger.debug('{} active', b.get_tag())
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
    
    async def _wait_for_signals(self):
        if len(self._signal_tasks):
            done, pending = await asyncio.wait(self._signal_tasks,
                                               return_when=asyncio.FIRST_COMPLETED)
            while pending:
                await asyncio.sleep(POLL_RATE)
                done, pending = await asyncio.wait(self._signal_tasks,
                                                   return_when=asyncio.FIRST_COMPLETED)
            
            self._signal_tasks.clear()
            
            while not all(s.safe for s in self.signals):
                await asyncio.sleep(POLL_RATE)
    
    async def _wait_for_all_revert_clear(self):
        while all([s.active or not s.revert_clear for s in self.signals]):
            await asyncio.sleep(POLL_RATE)
    
    async def poll(self):
        try:
            while True:
                for signal in self.signals:
                    if signal.active:
                        if self.active_barrier:
                            if signal not in self.active_barrier.signals:
                                raise Conflict(f'{signal.get_tag()} not in {self.active_barrier.get_tag()}')
                    else:
                        if signal.fya_concurrent_phase is not None:
                            signal.fya_enabled = self.fya_enabled
                            if signal.fya_enabled and signal.state != SignalState.FYA and signal.revert_clear:
                                if signal.fya_concurrent_phase.state in (SignalState.GO, SignalState.EXTEND):
                                    for ps in signal.fya_concurrent_phase.signals:
                                        if ps.type == SignalType.PEDESTRIAN:
                                            if ps.active:
                                                break
                                            
                                            if ps.interval_timer.elapsed < FYA_MINIMUM_PEDESTRIAN_STOP_TIME:
                                                break
                                    else:
                                        if signal.state == SignalState.STOP:
                                            interval_remaining = signal.fya_concurrent_phase.get_interval_time_remaining()
                                            if interval_remaining > FYA_MINIMUM_TIME:
                                                await signal.fya()
                
                for phase in self.phases:
                    if phase.fya_available and not phase.has_go_state:
                        for signal in phase.fya_signals:
                            other_signal: Signal
                            for other_signal in signal.fya_concurrent_phase.signals:
                                if other_signal.type == SignalType.VEHICLE:
                                    other_signal.demand = other_signal.demand or phase.demand
                                    other_signal.presence = other_signal.presence or phase.presence
                    
                    if phase.fya_active:
                        continue
                    
                    if phase.demand:
                        for signal in phase.default_signals:
                            if not signal.demand and not signal.active:
                                signal.demand = True
                        
                        barrier = self.get_barrier_by_phase(phase)
                        
                        if barrier:
                            for barrier_phase in barrier.phases:
                                if barrier_phase == phase:
                                    continue
                                if barrier_phase.demand:
                                    break
                            else:
                                for other_phase in phase.default_phases:
                                    if (not other_phase.demand and
                                        not other_phase.active_signals and
                                        other_phase not in self.phases_serviced):
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
                    else:
                        phase.conflicting_demand = False
                        
                        if self.active_barrier is not None and len(phase.inactive_signals):
                            if all([s.resting and not s.leading_signals for s in phase.active_signals]):
                                for signal in phase.inactive_signals:
                                    if not signal.fya_available:
                                        status = signal.get_service_status(group=phase.active_signals)
                                        if status.service:
                                            self._signal_tasks.append(asyncio.create_task(signal.serve(group=phase.active_signals)))
                
                if self.active_barrier and 0 < len(self.active_phases) < len(self.rings):
                    if set(self.active_phases + self.waiting_phases).issubset(self.active_barrier.phases):
                        active_resting = any([p.resting for p in self.active_phases])
                        active_remaining = max([p.runtime_remaining for p in self.active_phases])
                        
                        for phase in self.waiting_phases:
                            if phase in self.phases_serviced:
                                if not phase.demand:
                                    continue
                                
                                if self.recycle_phase(phase):
                                    if active_resting:
                                        logger.debug('removed {} from cycled phases list',
                                                     phase.get_tag())
                                    if phase.runtime_maximum < active_remaining:
                                        logger.debug('removed {} from cycled phases list ({}s < {}s)',
                                                     phase.get_tag(),
                                                     phase.runtime_maximum,
                                                     active_remaining)
                    
                    selected_phases = self.select_phases()
                    if selected_phases:
                        signals = self.select_signals(*selected_phases)
                        
                        if signals:
                            for signal in signals:
                                self._signal_tasks.append(
                                    asyncio.create_task(signal.serve(group=signals))
                                )
                
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
                            if __debug__:
                                breakpoint()
                            else:
                                raise RuntimeError('phase service deadlock')
                    else:
                        self._stopped_with_demand_stopwatch.reset()
                
                await asyncio.sleep(POLL_RATE)
        except asyncio.CancelledError:
            pass
    
    async def service(self):
        logger.debug('max revert time is {}', self._max_revert_time)
        self.try_change_barrier(next(self._barrier_sequence))
        
        try:
            while True:
                await self._try_pause()
                
                for phase in self.phases:
                    phase.recall()
                
                await self._try_idle()
                await self._wait_for_all_revert_clear()
                
                match self.mode:
                    case PhaseCyclerMode.SEQUENTIAL:
                        for _ in range(len(self.phases)):
                            phase = next(self._phase_sequence)
                            if phase not in self.phases_serviced and phase in self.waiting_phases:
                                signals = self.select_signals(phase)
                                
                                for signal in signals:
                                    self._signal_tasks.append(asyncio.create_task(signal.serve(group=signals)))
                                
                                await self._wait_for_signals()
                        self._signal_tasks.clear()
                    case PhaseCyclerMode.CONCURRENT:
                        while True:
                            selected_phases = self.select_phases()
                            if selected_phases:
                                signals = self.select_signals(*selected_phases)
                                for signal in signals:
                                    self._signal_tasks.append(
                                        asyncio.create_task(signal.serve(group=signals))
                                    )
                                await self._wait_for_signals()
                            else:
                                if self.try_change_barrier(next(self._barrier_sequence)):
                                    break
                                else:
                                    breakpoint()
                            
                            if self.active_barrier is None:
                                break
                
                self.signals_serviced.clear()
                self.signals_recycled.clear()
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
