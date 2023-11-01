import asyncio
from loguru import logger
from typing import Set, Dict, List, Iterable, Optional
from asyncio import Lock, Event
from itertools import cycle
from dataclasses import dataclass
from atsc.common.primitives import Timer, Context, Updatable, Identifiable
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
    
    def __init__(self, id_: int, invert: bool = False):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._lock = Lock()
        self._state = FieldState.OFF
        self._scalar = not invert
        self.flash_timer = Timer()
    
    async def write(self, state: FieldState):
        if state != FieldState.INHERIT:
            async with self._lock:
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
    
    async def update(self, context: Context):
        if self.state == FieldState.FLASHING:
            if self.flash_timer.poll(context, 0.5):
                async with self._lock:
                    self._scalar = not self._scalar


@dataclass()
class IntervalConfig:
    field: FieldOutput
    minimum: float
    maximum: Optional[float] = None
    reduce: bool = False
    flashing: bool = False
    restable: bool = True
    collect: bool = False


class Signal(Identifiable, Updatable):
    
    @property
    def fields(self):
        return self._fields
    
    def __init__(self,
                 id_: int,
                 intervals: Dict[SignalState, IntervalConfig]):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._state = SignalState.STOP
        self._intervals = intervals
        self._fields = list(set([c.field for c in intervals.values()]))
        
        self.demand = True
        self.timer = Timer()
        self.conflicting_demand = Event()
        self.safe = Event()
        
        self.children.extend(self._fields)
    
    def get_next_state(self) -> SignalState:
        match self._state:
            case SignalState.STOP:
                return SignalState.GO
            case SignalState.CAUTION:
                return SignalState.STOP
            case SignalState.REDUCE | SignalState.FYA:
                return SignalState.CAUTION
            case SignalState.GO:
                if SignalState.REDUCE in self._intervals:
                    return SignalState.REDUCE
                else:
                    return SignalState.CAUTION
            case SignalState.LS_FLASH:
                return SignalState.STOP
    
    async def update(self, context: Context):
        config = self._intervals[self._state]
        
        if self.timer.poll(context, config.minimum):
            conflicting_demand = config.restable and self.conflicting_demand.is_set()
            rigid_interval = not config.restable
            lacking_demand = not self.demand
            
            if conflicting_demand or rigid_interval or lacking_demand:
                if config.maximum:
                    trigger = config.maximum
                    
                    if config.reduce:
                        trigger -= self.timer.value
                    
                    if self.timer.poll(context, trigger):
                        await self.change()
                else:
                    await self.change()
        
        await super().update(context)
        
    async def change(self, specific: Optional[SignalState] = None):
        next_state = specific or self.get_next_state()
        self._state = next_state
        
        config = self._intervals[self._state]
        for field in self._fields:
            if field == config.field:
                if config.flashing:
                    await field.write(FieldState.FLASHING)
                else:
                    await field.write(FieldState.ON)
            else:
                await field.write(FieldState.OFF)
        
        if self._state == SignalState.STOP:
            self.safe.set()
    
    def actuation(self):
        if self._intervals[self._state].collect:
            self.demand = True
        else:
            self.timer.reset()
    
    async def wait(self):
        if self.demand:
            await self.change()
            await self.safe.wait()
        else:
            await asyncio.sleep(0.0)


class Phase(Identifiable, Updatable):
    
    @property
    def active(self):
        return self._active
    
    @property
    def fields(self):
        rv = []
        for signal in self.signals:
          rv.extend(signal.fields)
        return rv
    
    def __init__(self,
                 id_: int,
                 signals: Iterable[Signal]):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._active = False
        
        self.signals = sorted(signals)
        self.children.extend(self.signals)
    
    async def wait(self):
        if not self.active:
            self._active = True
            logger.debug('{} activated', self.get_tag())
            
            await asyncio.gather(*[s.wait() for s in self.signals])
            
            self._active = False
            logger.debug('{} deactivated', self.get_tag())
        else:
            raise RuntimeError(f'attempt to reactivate phase {self.get_tag()}')


class Ring(Identifiable, Updatable):
    
    @property
    def state(self):
        return self._state
    
    @property
    def fields(self):
        rv = []
        for phase in self.phases:
            rv.extend(phase.fields)
        return rv
    
    def __init__(self,
                 id_: int,
                 phases: Iterable[Phase],
                 clearance_time: float,
                 enabled: bool = True):
        Identifiable.__init__(self, id_)
        Updatable.__init__(self)
        self._state = RingState.INACTIVE
        
        self.clearance_time = clearance_time
        self.phases = sorted(phases)
        self.enabled = enabled
        self.timer = Timer()
        self.cleared = Event()
        self.children.extend(self.phases)
    
    async def update(self, context: Context):
        if self._state == RingState.CLEARING:
            if self.timer.poll(context, self.clearance_time):
                self.cleared.set()
        
        await super().update(context)
    
    async def serve(self, window: List[Phase] = None):
        window = window or self.phases
        assert len(set(window).difference(self.phases)) == 0
        
        if self.enabled:
            logger.debug('{} activated', self.get_tag())
            
            self._state = RingState.SELECTING
            
            while len(window):
                candidate = window.pop(0)
                
                self._state = RingState.ACTIVE
                self.cleared.clear()
                await candidate.wait()
                self._state = RingState.CLEARING
                await self.cleared.wait()
            
            logger.debug('{} deactivated', self.get_tag())
        
        self._state = RingState.INACTIVE


class Barrier(Identifiable):
    
    def __init__(self, id_: int, phases: Iterable[Phase]):
        super().__init__(id_)
        self.phases = phases
    
    def intersection(self, ring: Ring) -> Set[Phase]:
        return set(self.phases).intersection(ring.phases)


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
    def fields(self):
        rv = []
        for ring in self._rings:
            rv.extend(ring.fields)
        return rv
    
    def __init__(self, rings: Iterable[Ring], barriers: Iterable[Barrier]):
        super().__init__()
        self._rings = sorted(rings)
        self._barriers = sorted(barriers)
        self._cycler = cycle(self._barriers)
        self._barrier: Optional[Barrier] = None
        self.children.extend(self._rings)
    
    async def run(self):
        while True:
            # todo: cycle counting, count phases ran per cycle.
            # if zero phases were served, the controller is in idle,
            # meaning preferred phases can be recycled.
            
            self._barrier = next(self._cycler)
            logger.debug('{} is active barrier', self._barrier.get_tag())
            
            routines = []
            for ring in self._rings:
                window = sorted(self._barrier.intersection(ring))
                routines.append(ring.serve(window))
            
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
