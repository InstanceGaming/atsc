from asyncio import Lock, Event
from itertools import cycle
from typing import Dict, Iterable, Set, Optional, Union, List
from loguru import logger
import asyncio
from dataclasses import dataclass

from pydantic import BaseModel

from atsc.common.primitives import Identifiable, Updatable, Context
from atsc.controller.constants import FieldState, SignalState


IntervalTime = Dict[SignalState, float]


class TimingPlan(BaseModel):
    minimum: IntervalTime
    maximum: Optional[IntervalTime] = None
    
    def merge(self, *args, **kwargs) -> 'TimingPlan':
        other_min = {}
        other_max = {}
        
        arg_count = len(args)
        if arg_count == 1:
            first_arg = args[0]
            if isinstance(first_arg, TimingPlan):
                other_min = first_arg.minimum
                other_max = first_arg.maximum
            elif isinstance(first_arg, dict):
                other_min = first_arg
            else:
                raise TypeError()
        elif arg_count == 2:
            if isinstance(args[0], dict) and isinstance(args[1], dict):
                other_min = args[0]
                other_max = args[1]
            else:
                raise TypeError()
        elif arg_count == 0:
            if len(kwargs) == 0:
                raise TypeError()
            else:
                other_min = kwargs.get('minimum', {})
                other_max = kwargs.get('maximum', {})
        
        return TimingPlan(minimum=self.minimum | other_min,
                          maximum=self.maximum | other_max)


class FieldOutput(Identifiable, Updatable):
    
    @property
    def state(self):
        return self._state
    
    def __init__(self, id_: int, invert: bool):
        super().__init__(id_)
        self._lock = Lock()
        self._state = FieldState.OFF
        self._scalar = not invert
        self._elapsed = 0.0
    
    async def write(self, state: FieldState):
        if state != FieldState.INHERIT:
            async with self._lock:
                match state:
                    case FieldState.OFF:
                        self._scalar = False
                    case (FieldState.ON, FieldState.FLASHING):
                        self._scalar = True
                    case _:
                        raise NotImplementedError()
                
                self._state = state
    
    async def read(self) -> bool:
        async with self._lock:
            return self._scalar
        
    async def update(self, context: Context):
        if self.state == FieldState.FLASHING and self._elapsed > (context.scale / 2):
            async with self._lock:
                self._scalar = not self._scalar
            
            self._elapsed = 0.0
        else:
            self._elapsed += context.delay


class Signal(Identifiable, Updatable):
    
    def __init__(self,
                 id_: int,
                 outputs: Iterable[FieldOutput]):
        super().__init__(id_)
        self._state = SignalState.STOP
        self._outputs = outputs
        self._limits_map = {}
        self._field_map = {}
        
        self._setpoint: float = 0.0
        self._elapsed: float = 0.0
        self._serve_elapsed: float = 0.0
        
        self.safe = Event()
        self.conflicting_demand = Event()
        
        self.children.extend(outputs)
    
    def map_limit(self, state: SignalState, minimum: float, maximum: Optional[float] = None):
        self._limits_map.update({state: (minimum, maximum)})
        
    def map_output(self, state: SignalState, output: FieldOutput, flashing: bool):
        field_state = FieldState.FLASHING if flashing else FieldState.ON
        self._field_map.update({state: (output, field_state)})
    
    def get_next_state(self) -> SignalState:
        pass
    
    def change_state(self, specific: Optional[SignalState] = None):
        next_state = specific or self.get_next_state()
        self._state = next_state
    
    async def update(self, context: Context):
        await super().update(context)
    
    async def wait(self):
        self.change_state()
        await asyncio.wait_for(self.safe.wait(), None)


class Phase(Referencable):
    
    @property
    def ready(self):
        return self.enabled and not self.active and not self.skip
    
    @property
    def active(self):
        return self._active
    
    @property
    def signals(self):
        return self._signals
    
    def __init__(self,
                 id_: int,
                 signals: Iterable[Signal],
                 enabled: bool = True,
                 skip: bool = False):
        super().__init__(id_)
        
        self._active = False
        self._signals = sorted(signals)
        self.enabled = enabled
        self.skip = skip
    
    async def wait(self):
        if self.ready:
            self._active = True
            logger.debug('{} activated', self.get_tag())
            await asyncio.gather(*[s.wait() for s in self._signals])
            self._active = False
            logger.debug('{} deactivated', self.get_tag())
        else:
            raise RuntimeError(f'attempted to await unready phase {self.get_tag()}')


class Ring(Referencable, Ticking, PhaseContainer):
    
    @property
    def state(self):
        return self._state
    
    def __init__(self,
                 id_: int,
                 phases: Optional[Iterable[Union[int, Phase]]] = None,
                 red_clearance: float = 0,
                 enabled: bool = True):
        Referencable.__init__(self, id_)
        Ticking.__init__(self)
        PhaseContainer.__init__(self, phases)
        self._state = RingState.INACTIVE
        self._setpoint = red_clearance
        self._remaining = red_clearance
        self._cleared = asyncio.Event()
        self.enabled = enabled
    
    async def on_time_tick(self, clock: Clock):
        if self._state == RingState.RED_CLEARANCE:
            if self._remaining > clock.delay:
                self._remaining -= clock.delay
                logger.timing('{} {:03.02f}', self.get_tag(), self._remaining)
            else:
                logger.timing('{} limit', self.get_tag())
                self._cleared.set()
    
    async def serve(self, window: List[Phase] = None):
        window = window or self.phases
        assert len(set(window).difference(self.phases)) == 0
        
        if self.enabled:
            logger.debug('{} activated', self.get_tag())
            
            self._state = RingState.SELECTING
            
            while len(window):
                candidate = window.pop(0)
                
                if candidate.ready:
                    selected = candidate
                    
                    self._state = RingState.ACTIVE
                    await selected.wait()
                    
                    if self._setpoint > 0:
                        logger.debug('{} red clearance',
                                     self.get_tag(),
                                     self._setpoint)
                        
                        self._state = RingState.RED_CLEARANCE
                        self._remaining = self._setpoint
                        await self._cleared.wait()
                        self._cleared.clear()
            
            logger.debug('{} deactivated', self.get_tag())
        
        self._state = RingState.INACTIVE


class Barrier(Referencable, PhaseContainer):
    
    def __init__(self, id_: int, phases: Optional[Iterable[Union[int, Phase]]] = None):
        Referencable.__init__(self, id_)
        PhaseContainer.__init__(self, phases)
    
    def intersection(self, ring: Ring) -> Set[Phase]:
        return set(self.phases).intersection(ring.phases)


class RingCycler(Runnable):
    
    @property
    def active(self):
        return self._active
    
    @property
    def rings(self):
        return self._rings
    
    @property
    def barriers(self):
        return self._barriers
    
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
    def load_switches(self) -> List[LoadSwitch]:
        switches = []
        
        for signal in self.signals:
            switches.extend(signal.load_switches)
        
        return switches
    
    @property
    def field_outputs(self) -> List[FieldOutput]:
        field_outputs = []
        
        for switch in self.load_switches:
            field_outputs.extend(switch.field_outputs)
        
        return field_outputs
    
    def __init__(self,
                 rings: Iterable[Ring],
                 barriers: Iterable[Barrier]):
        self._rings = sorted(rings)
        self._barriers = sorted(barriers)
        self._cycler = cycle(self._barriers)
        self._active: Optional[Barrier] = None
    
    async def run(self):
        while True:
            # todo: cycle counting, count phases ran per cycle.
            # if zero phases were served, the controller is in idle,
            # meaning preferred phases can be recycled.
            
            self._active = next(self._cycler)
            logger.debug('{} is active barrier', self._active.get_tag())
            
            routines = []
            for ring in self._rings:
                window = sorted(self._active.intersection(ring))
                routines.append(ring.serve(window))
            
            await asyncio.gather(*routines)


class Call(Referencable):
    
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
class Input(Referencable):
    trigger: InputActivation
    action: InputAction
    targets: List[Phase]
    
    # update states and changed together
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
