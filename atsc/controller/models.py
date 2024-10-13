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
from collections import defaultdict

from loguru import logger
from typing import Set, Dict, List, Self, Optional
from asyncio import Event
from itertools import chain
from dataclasses import dataclass
from atsc.rpc.phase import Phase as rpc_Phase
from atsc.controller import utils
from atsc.rpc.signal import Signal as rpc_Signal
from atsc.common.constants import FLOAT_PRECISION_TIME
from atsc.rpc.field_output import FieldOutput as rpc_FieldOutput
from jacob.datetime.timing import millis
from atsc.common.primitives import (
    Timer,
    Context,
    Flasher,
    Tickable,
    EdgeTrigger,
    Identifiable
)
from atsc.controller.structs import IntervalConfig, IntervalTiming
from atsc.controller.constants import (
    RecallMode,
    SignalType,
    InputAction,
    SignalState,
    InputActivation,
    PhaseCyclerMode,
    FieldOutputState,
    ServiceModifiers,
    ServiceConditions, TrafficMovement, CYCLER_SERVICE_POLL_RATE
)
from jacob.datetime.formatting import format_ms


class FieldOutput(Identifiable, Tickable):
    
    @property
    def state(self):
        return self._state
    
    @property
    def flasher(self):
        return self._flasher
    
    def __init__(self, id_: int, fpm: float = 60.0):
        Identifiable.__init__(self, id_)
        Tickable.__init__(self)
        self._state = FieldOutputState.OFF
        self._bit = False
        self._flasher = Flasher(fpm)
    
    def set(self, state: FieldOutputState):
        if state != FieldOutputState.INHERIT:
            match state:
                case FieldOutputState.OFF:
                    self._bit = False
                case FieldOutputState.FLASHING:
                    self._flasher.reset()
                case FieldOutputState.ON:
                    self._bit = True
            
            self._state = state
    
    def __bool__(self):
        return self._bit
    
    def __int__(self):
        return 1 if self._bit else 0
    
    def __repr__(self):
        return f'<FieldOutput #{self.id} {self.state.name}'
    
    def tick(self, context: Context):
        if self.state == FieldOutputState.FLASHING:
            self._flasher.poll(context)
            self._bit = bool(self._flasher)
    
    def rpc_model(self):
        return rpc_FieldOutput(self.id,
                               state=self.state,
                               value=self._bit,
                               fpm=self.flasher.fpm)


class Signal(Identifiable, Tickable):
    global_field_output_mapping: Dict[FieldOutput, Self] = {}
    
    @dataclass(slots=True, frozen=True)
    class ServiceStatus:
        service: bool
        condition: ServiceConditions
        lagging_signal: Optional['Signal'] = None
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional[Self]:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def type(self):
        return self._type
    
    @property
    def movement(self):
        return self._movement
    
    @property
    def active(self):
        return not self.inactive_event.is_set()
    
    @property
    def initial_state(self):
        return self._initial_state
    
    @property
    def state(self):
        return self._state
    
    @property
    def field_mapping(self):
        return self._mapping
    
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
        return self._presence
    
    @presence.setter
    def presence(self, value):
        if value != self._presence:
            logger.verbose('{} presence = {}', self.get_tag(), value)
            self._presence = bool(value)
    
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
        config = self._configs.get(self.state)
        rest_allowed_for_interval = False if not config else config.rest
        
        match self.state:
            case SignalState.STOP:
                resting = rest_allowed_for_interval and not self.active
            case _:
                resting = rest_allowed_for_interval and not self.conflicting_demand
        
        return resting
    
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
        go_timing = self._timings.get(SignalState.GO)
        
        if go_timing and go_timing.maximum and go_timing.maximum >= 1.0:
            return go_timing.maximum
        else:
            return None
    
    @property
    def field_outputs(self):
        rv = set()
        for field_output in self._mapping.values():
            rv.add(field_output)
        return sorted(rv)
    
    @property
    def runtime_maximum(self):
        duration = 0.0
        
        if self.service_maximum:
            duration += self.service_maximum
        else:
            go_time = self._timings[SignalState.GO]
            
            if go_time:
                if go_time.maximum:
                    duration += go_time.maximum
                else:
                    if go_time.minimum:
                        duration += go_time.minimum
                    extend_time = self._timings[SignalState.EXTEND]
                    if extend_time and extend_time.minimum:
                        duration += extend_time.minimum
        
        caution_time = self._timings[SignalState.CAUTION]
        
        if caution_time and caution_time.minimum:
            duration += caution_time.minimum
        
        stop_time = self._timings[SignalState.STOP]
        
        if stop_time and stop_time.minimum:
            duration += stop_time.minimum
        
        return duration
    
    @property
    def runtime_remaining(self):
        remaining = 0.0
        
        for state in reversed(SignalState):
            interval_timing = self._timings.get(state)
            interval_time = 0.0
            
            if interval_timing:
                minimum_time = interval_timing.minimum or 0.0
                maximum_time = interval_timing.maximum or 0.0
                
                if state != SignalState.GO:
                    interval_time = max(minimum_time, maximum_time)
                else:
                    interval_time = minimum_time
            
            remaining += interval_time
            
            if state == self.state:
                remaining -= self.interval_timer.value
        
        return remaining
    
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
                 initial_state: SignalState = SignalState.STOP,
                 service_conditions: ServiceConditions = ServiceConditions.WITH_DEMAND,
                 service_modifiers: ServiceModifiers = ServiceModifiers.UNSET):
        Identifiable.__init__(self, id_)
        Tickable.__init__(self)
        self._timings = timings
        self._configs = defaultdict(IntervalConfig)
        
        for k, v in configs.items():
            self._configs[k] = v
        
        self._mapping = mapping
        self._type = type
        self._movement = movement
        
        for fo in mapping.values():
            self.global_field_output_mapping.update({fo: self})
        
        self._state = SignalState.STOP
        self._initial_state = initial_state
        
        self._conflicting_demand = False
        self._recall_mode = recall
        self._recall_state = RecallMode.OFF
        self._recycle = recycle
        self._demand = demand
        self._latch = latch
        self._presence = False
        self._presence_falling = EdgeTrigger(False)
        self._service_conditions = service_conditions
        self._service_modifiers = service_modifiers
        
        self.leading_signals: List['Signal'] = []
        
        self.service_timer = Timer()
        self.interval_timer = Timer()
        self.inactive_event = Event()
        
        if initial_state == SignalState.STOP:
            self.inactive_event.set()
        
        self.tickables.extend(self.field_outputs)
        self.change(state=initial_state)
        self.recall()
    
    def get_next_state(self) -> SignalState:
        match self.state:
            case SignalState.STOP:
                # todo: go to FYA if conditions are met
                return SignalState.GO
            case SignalState.CAUTION:
                return SignalState.STOP
            case SignalState.FYA:
                # todo: go to green if next up
                return SignalState.CAUTION
            case SignalState.EXTEND:
                return SignalState.CAUTION
            case SignalState.GO:
                service_max = self.service_timer.value > self.service_maximum if self.service_maximum else False
                timing_max = self._timings[SignalState.GO].maximum
                interval_max = self.interval_timer.value > timing_max if timing_max else False
                if (SignalState.EXTEND in self._timings
                    and self.recall_state != RecallMode.MAXIMUM
                    and not service_max
                    and not interval_max):
                    return SignalState.EXTEND
                else:
                    return SignalState.CAUTION
            case SignalState.LS_FLASH:
                return self._initial_state
            case _:
                raise NotImplementedError()
    
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
    
    def _terminate(self):
        if self.active:
            self.inactive_event.set()
            self.recall()
            self.leading_signals.clear()
    
    def tick(self, context: Context):
        timing = self._timings[self.state]
        config = self._configs[self.state]
        minmax_inhibit = any([ls.active for ls in self.leading_signals])
        
        if self.interval_timer.poll(context, timing.minimum):
            match self.state:
                case SignalState.STOP:
                    self._terminate()
                case SignalState.CAUTION:
                    self.change()
                case SignalState.EXTEND:
                    if not minmax_inhibit:
                        if self.conflicting_demand or not config.rest:
                            self.change()
                case SignalState.GO:
                    if not minmax_inhibit and self.recall_state != RecallMode.MAXIMUM:
                        if self.conflicting_demand or not config.rest:
                            self.change()
                case _:
                    raise NotImplementedError()
        
        if not timing.minimum:
            if self.state == SignalState.STOP:
                self._terminate()
        
        match self.state:
            case SignalState.STOP | SignalState.CAUTION:
                if not self.latch and self._presence_falling.poll(self.presence):
                    if self.recall_state == RecallMode.OFF:
                        self.demand = False
                else:
                    self.demand = self.demand or self.presence
            case SignalState.GO | SignalState.EXTEND:
                if self.recall_state == RecallMode.OFF:
                    self.demand = False
                
                if self.state == SignalState.EXTEND and self.presence:
                    self.interval_timer.value = 0.0
                
                if self.service_timer.poll(context, self.service_maximum):
                    if not minmax_inhibit:
                        if self.conflicting_demand or not config.rest:
                            self.change(state=SignalState.CAUTION)
        
        if not minmax_inhibit and timing.maximum:
            if self.conflicting_demand or not config.rest:
                if self.interval_timer.value > (timing.maximum - context.delay):
                    self.change()
        
        super().tick(context)
    
    def change(self, state: Optional[SignalState] = None):
        if state is not None:
            next_state = state
        else:
            next_state = self.get_next_state()
        
        previous_field_output = self._mapping[self._state]
        previous_field_output.set(FieldOutputState.OFF)
        
        self._state = next_state
        
        logger.debug('{} state = {}', self.get_tag(), next_state.name)
        
        field_output = self._mapping[self._state]
        interval_config = self._configs.get(self._state)
        
        if interval_config and interval_config.flashing:
            field_output.set(FieldOutputState.FLASHING)
        else:
            field_output.set(FieldOutputState.ON)
        
        if self.state != SignalState.STOP:
            self.inactive_event.clear()
        
        if self.state in (SignalState.GO, SignalState.FYA):
            self.service_timer.value = 0.0
        
        self.interval_timer.value = 0.0
    
    def get_service_status(self,
                           group: Optional[List['Signal']] = None) -> ServiceStatus:
        with_demand = self.service_conditions & ServiceConditions.WITH_DEMAND
        service = not self.active and not with_demand or self.demand
        
        if group:
            with_pedestrian = self.service_conditions & ServiceConditions.WITH_PEDESTRIAN
            with_vehicle = self.service_conditions & ServiceConditions.WITH_VEHICLE
            with_any = self.service_conditions & ServiceConditions.WITH_ANY
            
            for signal in group:
                if signal == self:
                    continue
                
                check_signal = with_any
                condition = ServiceConditions.WITH_ANY
                
                if with_pedestrian and signal.type == SignalType.PEDESTRIAN:
                    condition = ServiceConditions.WITH_PEDESTRIAN
                    check_signal = True
                elif with_vehicle and signal.type == SignalType.VEHICLE:
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
            stop_time = self._timings[SignalState.STOP]
            if stop_time:
                revert_time = stop_time.revert
                if revert_time and self.interval_timer.value < revert_time:
                    service = False
        
        return self.ServiceStatus(service, ServiceConditions.WITH_DEMAND)
    
    async def serve(self, group: Optional[List['Signal']] = None):
        assert not self.active
        
        lagging_signals = []
        if self.service_modifiers & ServiceModifiers.BEFORE_VEHICLE:
            if group:
                for signal in group:
                    if (signal.type & SignalType.VEHICLE and not
                    signal.movement & TrafficMovement.PROTECTED_TURN):
                        if not signal.active:
                            signal.recall()
                        
                        signal.leading_signals.append(self)
                        lagging_signals.append(signal)
        
        self.change()
        await self.inactive_event.wait()
        
        for signal in lagging_signals:
            signal.leading_signals.remove(self)
    
    def __repr__(self):
        return (f'<Signal #{self.id} {self.state.name} '
                f'interval_time={self.interval_timer.value:.1f} '
                f'service_time={self.service_timer.value:.1f} '
                f'demand={self.demand} presence={self.presence} '
                f'resting={self.resting} recall={self.recall_mode.name} '
                f'recycle={self.recycle}>')
    
    def rpc_model(self):
        return rpc_Signal(self.id,
                          active=self.active,
                          resting=self.resting,
                          presence=self.presence,
                          demand=self.demand,
                          interval_time=round(self.interval_timer.value, FLOAT_PRECISION_TIME),
                          service_time=round(self.service_timer.value, FLOAT_PRECISION_TIME),
                          state=self.state)


class Phase(Identifiable, Tickable):
    global_field_output_mapping: Dict[FieldOutput, Self] = {}
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional[Self]:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def active_signals(self):
        return [s for s in self.signals if s.active]
    
    @property
    def inactive_signals(self):
        return [s for s in self.signals if not s.active]
    
    @property
    def state(self):
        return SignalState(max([s.state for s in self.signals]))
    
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
        return max([s.interval_timer.value for s in self.signals])
    
    @property
    def service_time(self):
        return max([s.service_timer.value for s in self.signals])
    
    @property
    def runtime_maximum(self):
        return max([s.runtime_maximum for s in self.signals])
    
    @property
    def runtime_remaining(self):
        return max([s.runtime_remaining for s in self.signals])
    
    @property
    def field_outputs(self):
        rv = set()
        for signal in self.signals:
            for field_output in signal.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 signals: List[Signal]):
        Identifiable.__init__(self, id_)
        Tickable.__init__(self)
        
        self.signals = signals
        
        for signal in signals:
            for fo in signal.field_outputs:
                self.global_field_output_mapping.update({fo: self})
        
        self.tickables.extend(self.signals)
    
    def get_serviceable_signals(self):
        serviceable = []
        for signal in self.signals:
            status = signal.get_service_status(self.signals)
            if status.service:
                serviceable.append(signal)
        return serviceable
    
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
    def waiting_phases(self):
        return [p for p in self.phases if p.demand and not p.active_signals]
    
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


class PhaseCycler(Tickable):
    
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
        if len(self.cycle_barriers):
            return self.cycle_barriers[-1]
        else:
            return None
    
    @property
    def signals(self):
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
    
    def __init__(self,
                 rings: List[Ring],
                 barriers: List[Barrier],
                 mode: PhaseCyclerMode):
        super().__init__()
        self.rings = rings
        self.barriers = barriers
        self.cycle_barriers: List[Barrier] = []
        self.cycle_serviced: List[Phase] = []
        self.cycle_recycled: List[Phase] = []
        
        self._mode = PhaseCyclerMode.PAUSE
        self._cycle_count: int = 0
        self._signal_tasks: List[asyncio.Task] = []
        
        # sequential mode only
        self._phase_sequence = utils.cycle(self.phases)
        
        # concurrent mode only
        self._barrier_sequence = utils.cycle(self.barriers)
        
        for barrier in self.barriers:
            barrier.ring_count = len(self.rings)
        
        self.tickables.extend(self.phases)
        self.set_mode(mode)
    
    def get_ring_by_phase(self, phase: Phase) -> Optional[Ring]:
        for ring in self.rings:
            if phase in ring.phases:
                return ring
        return None
    
    def tick(self, context: Context):
        for phase in self.phases:
            ring = self.get_ring_by_phase(phase)
            
            for other_phase in self.waiting_phases:
                if self.active_barrier:
                    if other_phase not in self.active_barrier.phases:
                        phase.conflicting_demand = True
                        break
                if ring and other_phase in ring.phases:
                    phase.conflicting_demand = True
                    break
            else:
                phase.conflicting_demand = False
                
                if all([s.resting and not s.leading_signals for s in phase.active_signals]):
                    for signal in phase.inactive_signals:
                        status = signal.get_service_status(group=phase.active_signals)
                        if status.service:
                            self._signal_tasks.append(asyncio.create_task(signal.serve(group=phase.active_signals)))
        
        if self.active_barrier:
            if 0 < len(self.active_phases) < len(self.rings):
                if set(self.active_phases + self.waiting_phases).issubset(self.active_barrier.phases):
                    active_resting = any([p.resting for p in self.active_phases])
                    active_remaining = max([p.runtime_remaining for p in self.active_phases])
                    
                    for phase in self.waiting_phases:
                        if phase in self.cycle_serviced:
                            if not phase.demand:
                                continue
                            
                            if self.recycle_phase(phase):
                                if active_resting:
                                    logger.debug('removed {} from cycled phases list',
                                                 phase.get_tag())
                                if phase.runtime_maximum <= active_remaining:
                                    logger.debug('removed {} from cycled phases list ({}s <= {}s)',
                                                 phase.get_tag(),
                                                 phase.runtime_maximum,
                                                 active_remaining)
        
        super().tick(context)
    
    def set_mode(self, mode: PhaseCyclerMode):
        if mode == self.mode:
            return False
        
        match self.mode:
            case PhaseCyclerMode.SEQUENTIAL:
                self.cycle_serviced.clear()
                self.cycle_recycled.clear()
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
        logger.info('cycle mode = {}', mode.name)
        return True
    
    def serve_single(self, phase: Phase) -> List[Signal]:
        self.cycle_serviced.append(phase)
        return phase.get_serviceable_signals()
    
    def serve_multiple(self, phases: List[Phase]) -> List[Signal]:
        signal_group = []
        
        for phase in phases:
            self.cycle_serviced.append(phase)
            signals = phase.get_serviceable_signals()
            signal_group.extend(signals)
        
        return signal_group
    
    def recycle_phase(self, phase: Phase) -> bool:
        if phase in self.cycle_serviced and phase not in self.cycle_recycled:
            self.cycle_recycled.append(phase)
            self.cycle_serviced.remove(phase)
            return True
        else:
            return False
    
    def select_phases(self):
        assert self.active_barrier
        
        selected_phases = []
        
        for ring in self.rings:
            if ring.active_phase:
                continue
            
            common_phases = ring.intersection(self.active_barrier)
            new_phases = sorted(common_phases - set(self.cycle_serviced))
            
            for phase in new_phases:
                if phase.demand:
                    selected_phases.append(phase)
                    break
        
        return selected_phases
    
    def try_change_barrier(self, b: Barrier):
        if len(self.cycle_barriers) == len(self.barriers):
            del self.cycle_barriers[0]
            last_barrier = self.cycle_barriers[-1]
        else:
            last_barrier = None
        
        self.cycle_barriers.append(b)
        
        if last_barrier is not None:
            logger.debug('crossed to {} from {}',
                         b.get_tag(),
                         last_barrier.get_tag())
        else:
            logger.debug('{} active', b.get_tag())
        
        return last_barrier is not None
    
    async def try_idle(self):
        if not self.waiting_phases:
            logger.debug('idle')
            marker = millis()
            while not self.waiting_phases:
                await asyncio.sleep(CYCLER_SERVICE_POLL_RATE)
            delta = millis() - marker
            logger.debug('idled for {}', format_ms(delta))
            return True
        else:
            return False
    
    async def try_pause(self):
        if self.mode == PhaseCyclerMode.PAUSE:
            logger.debug('paused')
            marker = millis()
            while self.mode == PhaseCyclerMode.PAUSE:
                await asyncio.sleep(CYCLER_SERVICE_POLL_RATE)
            delta = millis() - marker
            logger.debug('paused for {}', format_ms(delta))
            return True
        else:
            return False
    
    async def run(self):
        self.try_change_barrier(next(self._barrier_sequence))
        
        while True:
            await self.try_pause()
            await self.try_idle()
            
            match self.mode:
                case PhaseCyclerMode.SEQUENTIAL:
                    for _ in range(len(self.phases)):
                        phase = next(self._phase_sequence)
                        if phase not in self.cycle_serviced and phase in self.waiting_phases:
                            signals = self.serve_single(phase)
                            
                            while not signals:
                                await asyncio.sleep(CYCLER_SERVICE_POLL_RATE)
                                signals = self.serve_single(phase)
                            
                            for signal in signals:
                                self._signal_tasks.append(asyncio.create_task(signal.serve(group=signals)))
                            
                            await asyncio.wait(self._signal_tasks)
                    
                    self._signal_tasks.clear()
                case PhaseCyclerMode.CONCURRENT:
                    while True:
                        selected_phases = self.select_phases()
                        
                        if selected_phases:
                            signals = self.serve_multiple(selected_phases)
                            
                            while not signals:
                                await asyncio.sleep(CYCLER_SERVICE_POLL_RATE)
                                signals = self.serve_multiple(selected_phases)
                            
                            for signal in signals:
                                self._signal_tasks.append(asyncio.create_task(signal.serve(group=signals)))
                            
                            await asyncio.wait(self._signal_tasks)
                        else:
                            if self.try_change_barrier(next(self._barrier_sequence)):
                                break
                        
                        self._signal_tasks.clear()
                        
                        if self.active_barrier is None:
                            break
            
            self.cycle_serviced.clear()
            self.cycle_recycled.clear()
            self._cycle_count += 1
            logger.debug('cycle #{}', self._cycle_count)


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
