import asyncio
from loguru import logger
from typing import Set, Dict, List, Iterable, Optional
from asyncio import Event
from itertools import cycle
from dataclasses import dataclass
from atsc.common.primitives import Timer, Context, Updatable, Identifiable, Flasher
from atsc.controller.constants import (RingState,
                                       CallSource,
                                       FieldState,
                                       InputAction,
                                       SignalState,
                                       InputActivation)


class FieldOutput(Identifiable, Updatable):
    
    @property
    def state(self):
        return self._state
    
    def __init__(self, id_: int, fpm: float = 60.0):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._state = FieldState.OFF
        self._scalar = False
        self._flasher = Flasher()
        self.fpm: float = fpm
    
    def set(self, state: FieldState):
        if state != FieldState.INHERIT:
            match state:
                case FieldState.OFF:
                    self._scalar = False
                case FieldState.ON | FieldState.FLASHING:
                    self._scalar = True
                case _:
                    raise NotImplementedError()
            
            self._state = state
    
    def __bool__(self):
        return self._scalar
    
    def __int__(self):
        return 1 if self._scalar else 0
    
    def __repr__(self):
        return f'<FieldOutput #{self.id} {self.state.name}'
    
    def update(self, context: Context):
        if self.state == FieldState.FLASHING:
            if self._flasher.poll(context, self.fpm):
                self._scalar = not self._scalar


@dataclass()
class IntervalTiming:
    minimum: float
    maximum: Optional[float] = None
    rest: bool = False
    reduce: bool = False
    
    
@dataclass()
class IntervalConfig:
    flashing: bool = False


class Signal(Identifiable, Updatable):
    
    @property
    def active(self):
        return not self.safe.is_set()
    
    @property
    def service_enable(self):
        return self.active or self.demand.is_set()
    
    @property
    def field_outputs(self):
        rv = set()
        for field_output in self._mapping.values():
            rv.add(field_output)
        return sorted(rv)
    
    @property
    def field_mapping(self):
        return self._mapping
    
    def __init__(self,
                 id_: int,
                 timings: Dict[SignalState, IntervalTiming],
                 configs: Dict[SignalState, IntervalConfig],
                 mapping: Dict[SignalState, FieldOutput],
                 recall: bool = False,
                 recycle: bool = False):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._timings = timings
        self._configs = configs
        self._mapping = mapping
        self._recall = recall
        self._recycle = recycle
        
        self.timer = Timer()
        
        self.demand = Event()
        self.conflicting_demand = Event()
        self.safe = Event()
        
        self.children.extend(self.field_outputs)
        
        self._state = SignalState.STOP
        self.change(specific=SignalState.STOP)
    
    def get_next_state(self) -> SignalState:
        match self._state:
            case SignalState.STOP:
                return SignalState.GO
            case SignalState.CAUTION:
                return SignalState.STOP
            case SignalState.REDUCE | SignalState.FYA:
                return SignalState.CAUTION
            case SignalState.GO:
                if SignalState.REDUCE in self._timings:
                    return SignalState.REDUCE
                else:
                    return SignalState.CAUTION
            case SignalState.LS_FLASH:
                return SignalState.STOP
    
    def update(self, context: Context):
        config = self._timings[self._state]
        
        if self._state == SignalState.STOP:
            timing = self.demand.is_set() and self._recycle
        else:
            timing = True
        
        if timing and self.timer.poll(context, config.minimum):
            conflicting_demand = config.rest and self.conflicting_demand.is_set()
            rigid_interval = not config.rest
            lacking_demand = not self.demand.is_set()
            
            if conflicting_demand or rigid_interval or lacking_demand:
                if config.maximum:
                    trigger = config.maximum
                    
                    if config.reduce:
                        trigger -= self.timer.value
                    
                    if self.timer.poll(context, trigger):
                        self.change()
                else:
                    self.change()
        
        super().update(context)
    
    def change(self, specific: Optional[SignalState] = None):
        self.timer.reset()
        
        if specific is not None:
            next_state = specific
        else:
            next_state = self.get_next_state()
        
        previous_field_output = self._mapping[self._state]
        previous_field_output.set(FieldState.OFF)
        
        self._state = next_state
        field_output = self._mapping[self._state]
        interval_config = self._configs[self._state]
        
        if interval_config.flashing > 0.0:
            field_output.set(FieldState.FLASHING)
        else:
            field_output.set(FieldState.ON)
        
        if self._state == SignalState.STOP:
            if self._recall:
                self.recall()
            else:
                self.demand.clear()
            self.conflicting_demand.clear()
            self.safe.set()
        else:
            self.safe.clear()
    
    def recall(self):
        self.demand.set()
    
    async def wait(self):
        if not self.service_enable:
            raise RuntimeError(f'nothing to service for {self.get_tag()}')
        
        logger.debug('{} activated', self.get_tag())
        
        self.change()
        await self.safe.wait()


class Phase(Identifiable, Updatable):
    
    @property
    def service_enable(self):
        return any([s.service_enable for s in self.signals])
    
    @property
    def active(self):
        return self._active
    
    @property
    def field_outputs(self):
        rv = set()
        for signal in self.signals:
            for field_output in signal.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 signals: Iterable[Signal]):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._active = False
        
        self.signals = sorted(signals)
        self.children.extend(self.signals)
        
    def recall(self):
        for signal in self.signals:
            signal.recall()
    
    async def wait(self):
        if not self.service_enable:
            raise RuntimeError(f'nothing to service for {self.get_tag()}')
        
        if not self.active:
            self._active = True
            logger.debug('{} activated', self.get_tag())
            await asyncio.gather(*[s.wait() for s in self.signals if s.service_enable])
            self._active = False
        else:
            raise RuntimeError(f'attempt to reactivate phase {self.get_tag()}')


class Ring(Identifiable, Updatable):
    
    @property
    def service_enable(self):
        return any([p.service_enable for p in self.phases])
    
    @property
    def state(self):
        return self._state
    
    @property
    def field_outputs(self):
        rv = set()
        for phase in self.phases:
            for field_output in phase.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 phases: Iterable[Phase],
                 clearance_time: float):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._state = RingState.INACTIVE
        
        self.clearance_time = clearance_time
        self.phases = sorted(phases)
        self.timer = Timer()
        self.cleared = Event()
        self.children.extend(self.phases)
    
    def update(self, context: Context):
        if self._state == RingState.CLEARING:
            if self.timer.poll(context, self.clearance_time):
                self.timer.reset()
                self.cleared.set()
        
        super().update(context)
    
    async def serve(self, window: List[Phase]):
        if not self.service_enable:
            raise RuntimeError(f'nothing to service for {self.get_tag()}')
        
        if self.service_enable:
            self._state = RingState.SELECTING
            while len(window):
                candidate = window.pop(0)
                if candidate.service_enable:
                    logger.debug('{} active', self.get_tag())
                    self._state = RingState.ACTIVE
                    self.cleared.clear()
                    await candidate.wait()
                    self._state = RingState.CLEARING
                    await self.cleared.wait()
        
        self._state = RingState.INACTIVE
        
    def recall_all(self):
        for phase in self.phases:
            phase.recall()


class Barrier(Identifiable):
    
    def __init__(self, id_: int, phases: Iterable[Phase]):
        super().__init__(id_)
        self.phases = phases
    
    def intersection(self, ring: Ring) -> Set[Phase]:
        return set(self.phases).intersection(ring.phases)
    
    def recall_all(self):
        for phase in self.phases:
            phase.recall()


class RingCycler(Updatable):
    
    @property
    def rings(self):
        return self._rings
    
    @property
    def barriers(self):
        return self._barriers
    
    @property
    def barrier(self):
        return self._barrier
    
    @property
    def phases(self) -> List[Phase]:
        phases = []
        
        for ring in self.rings:
            phases.extend(ring.phases)
        
        return phases
    
    @property
    def signals(self) -> List[Signal]:
        signals = []
        
        for phase in self.phases:
            signals.extend(phase.signals)
        
        return signals
    
    @property
    def field_outputs(self):
        rv = set()
        for ring in self.rings:
            for field_output in ring.field_outputs:
                rv.add(field_output)
        return sorted(rv)
    
    def __init__(self, rings: Iterable[Ring], barriers: Iterable[Barrier]):
        super().__init__()
        self._rings = sorted(rings)
        self._barriers = sorted(barriers)
        self._cycler = cycle(self._barriers)
        self._barrier: Optional[Barrier] = None
        self._first_barrier: Optional[Barrier] = None
        self._cycle_count: int = 0
        self.children.extend(self._rings)
    
    async def run(self):
        while True:
            # todo: cycle counting, count phases ran per cycle.
            # if zero phases were served, the controller is in idle,
            # meaning preferred phases can be recycled.
            
            self._barrier = next(self._cycler)
            
            if self._first_barrier is None:
                self._first_barrier = self.barrier
            else:
                if self.barrier == self._first_barrier:
                    self._cycle_count += 1
                    logger.debug('cycle #{}', self._cycle_count)
            
            logger.debug('{} active', self.barrier.get_tag())
            
            routines = []
            for ring in self.rings:
                window = [p for p in self.barrier.intersection(ring) if p.service_enable]
                if len(window):
                    routines.append(ring.serve(window))
            
            if len(routines):
                await asyncio.gather(*routines)


class Call(Identifiable):
    
    @property
    def target(self) -> Phase:
        return self._target
    
    @property
    def source(self):
        return self._source
    
    @property
    def age(self) -> float:
        return self._age
    
    def __init__(self,
                 id_: int,
                 controller,
                 target: Phase,
                 source: CallSource):
        super().__init__(id_)
        self._controller = controller
        self._target = target
        self._source = source
        self._age: float = 0.0
        self._served = asyncio.Condition()
    
    def tick(self):
        self._age += self._controller.time_increment
    
    async def run(self):
        async with self._served:
            await self._served.wait_for(lambda _: self.target.active)
            self._controller.removeCall(self)
    
    def __lt__(self, other):
        if isinstance(other, Call):
            if abs(self._age - other.age) < self._controller.time_increment:
                return self.id < other.id
            return self._age < other.age
        return False
    
    def __repr__(self):
        return f'<Call #{self._id:02d} {self._target.get_tag()} A{self._age:0>5.2f}>'


@dataclass
class Input(Identifiable):
    trigger: InputActivation
    action: InputAction
    targets: List[Phase]
    
    state: bool = False
    last_state: bool = False
    changed: bool = False
    
    def activated(self) -> bool:
        if self.trigger == InputActivation.LOW:
            if not self.state and not self.last_state:
                return True
        elif self.trigger == InputActivation.HIGH:
            if self.state and self.last_state:
                return True
        elif self.trigger == InputActivation.RISING:
            if self.state and not self.last_state:
                return True
        elif self.trigger == InputActivation.FALLING:
            if not self.state and self.last_state:
                return True
        return False
    
    def __repr__(self):
        return f'<Input {self.trigger.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}' \
               f'{" CHANGED" if self.changed else ""}>'
