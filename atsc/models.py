#  Copyright 2022 Jacob Jewett
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
from collections import namedtuple
from itertools import cycle
from typing import Dict, List, Optional, Iterable, Tuple, Union, Set
from dataclasses import dataclass
from loguru import logger
from atsc.constants import *
from atsc import eventbus
from atsc.parameters import DelayProvider
from atsc.primitives import Referencable, Runnable, ref
from atsc.utils import format_us, micros, field_representation


class Clock(Referencable, Runnable, DelayProvider):
    
    @property
    def delay(self):
        return self._dp.delay
    
    def __init__(self,
                 id_: int,
                 dp: DelayProvider):
        Referencable.__init__(self, id_)
        Runnable.__init__(self)
        DelayProvider.__init__(self)
        self._dp = dp
    
    async def run(self):
        while True:
            marker = micros()
            eventbus.invoke(StandardObjects.E_CLOCK, self)
            logger.clocks('{} took {}',
                          self.get_tag(),
                          format_us(micros() - marker))
            marker = micros()
            await asyncio.sleep(self.delay)
            logger.clocks('{} slept for {}',
                          self.get_tag(),
                          format_us(micros() - marker))


class Ticking:
    
    def __init__(self):
        eventbus.listeners[StandardObjects.E_CLOCK].add(self.on_clock)
    
    def on_clock(self, clock: Clock):
        match clock.id:
            case StandardObjects.TIME_TICK:
                self.on_time_tick(clock)
            case StandardObjects.INPUTS_TICK:
                self.on_inputs_tick(clock)
            case StandardObjects.BUS_TICK:
                self.on_bus_tick(clock)
            case StandardObjects.NETWORK_TICK:
                self.on_network_tick(clock)
            case StandardObjects.FLASH_TICK:
                self.on_flash_tick(clock)
    
    def on_time_tick(self, clock: Clock):
        pass
    
    def on_inputs_tick(self, clock: Clock):
        pass
    
    def on_bus_tick(self, clock: Clock):
        pass
    
    def on_network_tick(self, clock: Clock):
        pass
    
    def on_flash_tick(self, clock: Clock):
        pass


class Flasher(Referencable, Ticking):
    
    @property
    def a(self):
        return self._a
    
    @property
    def b(self):
        return self._b
    
    def __init__(self,
                 id_: int,
                 invert: bool = False):
        Referencable.__init__(self, id_)
        Ticking.__init__(self)
        
        self._a = not invert
        self._b = invert
    
    def on_flash_tick(self, clock: Clock):
        self._a = not self._a
        self._b = not self._b
        eventbus.invoke(StandardObjects.E_FLASHER, self)


class FieldOutput(Referencable, Ticking):
    
    @property
    def state(self):
        return self._state
    
    @property
    def q(self):
        return self._q
    
    def __init__(self,
                 id_: int,
                 flash_polarity: FlashPolarity):
        Referencable.__init__(self, id_)
        Ticking.__init__(self)
        eventbus.listeners[StandardObjects.E_FLASHER].add(self.on_flasher)
        self._flash_polarity = flash_polarity
        self._rising = asyncio.Event()
        self._state = FieldState.OFF
        self._q = False
        self._lq = True
        
        self._change_event()
    
    def __bool__(self):
        return self.q
    
    def _change_event(self):
        if self._q != self._lq:
            eventbus.invoke(StandardObjects.E_FIELD_OUTPUT_Q_CHANGED, self)
            if self._q:
                self._rising.set()
    
    def on_flasher(self, flasher: Flasher):
        if self.state & FieldState.FLASHING:
            self._lq = self._q
            match self._flash_polarity:
                case FlashPolarity.A:
                    self._q = flasher.a
                case FlashPolarity.B:
                    self._q = flasher.b
            self._change_event()
    
    async def update(self, next_state: FieldState):
        if next_state != FieldState.INHERIT:
            self._lq = self._q
            
            if next_state & FieldState.ON:
                if next_state & FieldState.FLASHING:
                    self._q = False
                else:
                    self._q = True
            elif next_state == FieldState.OFF:
                self._q = False
            
            # if next_state == FieldState.FLASHING:
            #     if not self._q:
            #         self._rising.clear()
            #         await self._rising.wait()
            
            self._state = next_state
            
            eventbus.invoke(StandardObjects.E_FIELD_OUTPUT_STATE_CHANGED, self)
            self._change_event()


FieldTriad = namedtuple('FieldTriad', ('a', 'b', 'c'))
FieldMapping = Dict[SignalState, FieldTriad]


class LoadSwitch(Referencable):
    
    @property
    def mapping(self):
        return self._mapping
    
    @property
    def field_outputs(self):
        return [self.a, self.b, self.c]
    
    def __init__(self,
                 id_: int,
                 mapping: FieldMapping,
                 a: FieldOutput,
                 b: FieldOutput,
                 c: FieldOutput):
        super().__init__(id_)
        self._mapping = mapping
        self.a = a
        self.b = b
        self.c = c
    
    async def update(self, signal_state: SignalState):
        field_states = self._mapping.get(signal_state)
        if field_states is not None:
            await asyncio.gather(
                self.a.update(field_states.a),
                self.b.update(field_states.b),
                self.c.update(field_states.c)
            )
    
    def __repr__(self):
        field_rep = field_representation(self.a, self.b, self.c)
        return f'<LoadSwitch #{self.id} {field_rep}>'
    
    @staticmethod
    def make_generic(ls_id: int,
                     field_ids: Tuple[int, int, int],
                     flags: LSFlag,
                     flash_polarity: FlashPolarity = FlashPolarity.A):
        if flags == LSFlag.DISABLED:
            mapping = {
                SignalState.OFF: (FieldState.ON, FieldState.OFF, FieldState.OFF)
            }
        else:
            mapping = {
                SignalState.OFF: (FieldState.OFF, FieldState.OFF, FieldState.OFF)
            }
        
        if flags & LSFlag.YEL_FLASH:
            mapping.update({
                SignalState.LS_FLASH: (FieldState.OFF, FieldState.FLASHING, FieldState.OFF)
            })
        else:
            mapping.update({
                SignalState.LS_FLASH: (FieldState.FLASHING, FieldState.OFF, FieldState.OFF)
            })
        
        if flags & LSFlag.STANDARD:
            mapping.update({
                SignalState.STOP   : FieldTriad(FieldState.ON, FieldState.OFF, FieldState.OFF),
                SignalState.CAUTION: FieldTriad(FieldState.OFF, FieldState.ON, FieldState.OFF),
                SignalState.GO     : FieldTriad(FieldState.OFF, FieldState.OFF, FieldState.ON)
            })
            
            if flags & LSFlag.FYA:
                if flags & LSFlag.FYA_OUT_C:
                    mapping.update({
                        SignalState.FYA: FieldTriad(FieldState.OFF, FieldState.OFF, FieldState.FLASHING)
                    })
                elif flags & LSFlag.FYA_OUT_B:
                    mapping.update({
                        SignalState.FYA: FieldTriad(FieldState.OFF, FieldState.FLASHING, FieldState.OFF)
                    })
                else:
                    mapping.update({
                        SignalState.FYA: FieldTriad(FieldState.OFF, FieldState.OFF, FieldState.OFF)
                    })
        
        if flags & LSFlag.PED:
            mapping.update({
                SignalState.STOP: FieldTriad(FieldState.ON, FieldState.INHERIT, FieldState.OFF),
                SignalState.GO  : FieldTriad(FieldState.OFF, FieldState.INHERIT, FieldState.ON),
            })
            
            if flags & LSFlag.PED_CLEAR:
                mapping.update({
                    SignalState.CAUTION: FieldTriad(FieldState.FLASHING, FieldState.INHERIT, FieldState.OFF)
                })
            else:
                mapping.update({
                    SignalState.CAUTION: FieldTriad(FieldState.ON, FieldState.INHERIT, FieldState.OFF)
                })
            
            if flags & LSFlag.FYA_OUT_B:
                mapping.update({
                    SignalState.FYA: FieldTriad(FieldState.INHERIT, FieldState.FLASHING, FieldState.INHERIT)
                })
        
        a = FieldOutput(field_ids[0], flash_polarity)
        b = FieldOutput(field_ids[1], flash_polarity)
        c = FieldOutput(field_ids[2], flash_polarity)
        return LoadSwitch(ls_id, mapping, a, b, c)


TimeMap = Dict[SignalState, float]


@dataclass(frozen=True)
class TimingPlan:
    minimum: TimeMap
    maximum: Optional[TimeMap] = None
    
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
        
        return TimingPlan(self.minimum | other_min,
                          self.maximum | other_max)


DEFAULT_SIGNAL_STATE = SignalState.OFF


class Signal(Runnable, Referencable, Ticking):
    
    @property
    def ready(self):
        return self._ready.is_set()
    
    @property
    def idle(self):
        return not self.remaining and not self.demand
    
    @property
    def state(self):
        return self._state
    
    @property
    def pending_update(self):
        return self._queue_update.is_set()
    
    @property
    def previous_states(self):
        return self._previous_states
    
    @property
    def minimum(self):
        return self.timing.minimum.get(self.state)
    
    @property
    def maximum(self):
        if self.timing.maximum is not None:
            return self.timing.maximum.get(self.state)
        return None
    
    @property
    def remaining(self):
        return max(self._setpoint - self._elapsed, 0)
    
    @property
    def elapsed(self):
        return self._elapsed
    
    @property
    def primary(self):
        return self._primary
    
    @property
    def secondary(self):
        return self._secondary
    
    @property
    def load_switches(self):
        switches = [self.primary]
        
        if self.secondary is not None:
            switches.append(self.secondary)
        
        return switches
    
    def __init__(self,
                 id_: int,
                 timing: TimingPlan,
                 primary: LoadSwitch,
                 secondary: Optional[LoadSwitch] = None,
                 initial_state: SignalState = SignalState.STOP):
        Runnable.__init__(self)
        Referencable.__init__(self, id_)
        Ticking.__init__(self)
        
        self._primary = primary
        self._secondary = secondary
        self._state = initial_state
        self._previous_states: List[SignalState] = []
        self._setpoint: float = 0.0
        self._elapsed: float = 0.0
        self._ready = asyncio.Event()
        self._ready.set()
        self._queue_update = asyncio.Event()
        self.timing = timing
        self.demand = False
    
    def get_next_state(self) -> SignalState:
        match self._state:
            case SignalState.OFF:
                return SignalState.STOP
            case SignalState.STOP:
                return SignalState.GO
            case SignalState.CAUTION:
                return SignalState.STOP
            case SignalState.GO | SignalState.FYA:
                return SignalState.CAUTION
            case SignalState.LS_FLASH:
                ls_flash_mapping = self._primary.mapping[SignalState.LS_FLASH]
                if ls_flash_mapping.a == FieldState.FLASHING:
                    return SignalState.STOP
                else:
                    return SignalState.CAUTION
            case _:
                raise NotImplementedError()
    
    async def update(self):
        self._queue_update.clear()
        
        self._previous_states.insert(0, self._state)
        if len(self._previous_states) > len(SignalState):
            self._previous_states.pop(-1)

        self._state = self.get_next_state()

        if self.state != SignalState.STOP:
            self._ready.clear()
        
        self._setpoint: float = self.minimum
        self._elapsed: float = 0
        
        await self._primary.update(self._state)
        
        logger.debug('{} changed to {} for {:.02f}s',
                     self.get_tag(),
                     self.state.name,
                     self._setpoint)
    
    def on_time_tick(self, clock: Clock):
        was_idle = self.idle
        self._elapsed += clock.delay
        
        timed_out = self.remaining < clock.delay
        exceeded_min = self.elapsed >= self.minimum
        
        exceeded_limit = False
        if self.maximum is not None and self.maximum >= clock.delay:
            exceeded_limit = self.elapsed > self.maximum
        else:
            if self.state != SignalState.STOP and exceeded_min:
                exceeded_limit = True
        
        if not self.pending_update:
            if not self.ready:
                if not self.idle:
                    logger.timing('{} {:03.02f}', self.get_tag(), self.remaining)
                elif self.idle and not was_idle:
                    logger.timing('{} idle', self.get_tag())
                    eventbus.invoke(StandardObjects.E_SIGNAL_IDLE_START, self)
            
            rigid_interval = self.state == SignalState.CAUTION
            if timed_out and (rigid_interval or exceeded_limit or self.demand):
                reasons = []
                if rigid_interval:
                    reasons.append('rigid')
                if exceeded_min:
                    reasons.append('minimum')
                if self.demand:
                    reasons.append('demand')
                if exceeded_limit:
                    reasons.append('maximum')
                
                logger.timing('{} {}', self.get_tag(), ', '.join(reasons))
                self._queue_update.set()

    async def wait(self):
        if not self.ready:
            raise RuntimeError(f'tried to await unready signal {self.get_tag()}')
        logger.debug('{} activated', self.get_tag())
        await self.update()
        await self._ready.wait()
        logger.debug('{} deactivated', self.get_tag())
    
    async def run(self):
        await self._primary.update(SignalState.STOP)
        while True:
            await self._queue_update.wait()
            await self.update()
            
            if self.state == SignalState.STOP:
                self.demand = False
                self._ready.set()


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


class PhaseContainer:
    
    @property
    def phases(self):
        return self._phases
    
    @phases.setter
    def phases(self, phases):
        instances = []
        for v in phases:
            if isinstance(v, int):
                instances.append(ref(v, Phase))
            elif isinstance(v, Phase):
                instances.append(v)
            else:
                raise TypeError()
        self._phases = sorted(instances)
    
    def __init__(self,
                 phases: Optional[Iterable[Union[int, Phase]]] = None):
        self._phases = []
        
        if phases:
            self.phases = phases


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
    
    def on_time_tick(self, clock: Clock):
        if self._state == RingState.RED_CLEARANCE:
            if self._remaining > clock.delay:
                self._remaining -= clock.delay
                logger.timing('{} {:03.02f}', self.get_tag(), self._remaining)
            else:
                logger.timing('{} 0.00 (notified)', self.get_tag())
                self._cleared.set()
    
    async def serve(self, segment: List[Phase] = None):
        segment = segment or self.phases
        assert len(set(segment).difference(self.phases)) == 0
        
        if self.enabled:
            logger.debug('{} activated', self.get_tag())
            
            self._state = RingState.SELECTING
            
            while len(segment):
                candidate = segment.pop(0)
                
                if candidate.ready:
                    selected = candidate
                    
                    self._state = RingState.ACTIVE
                    await selected.wait()
                    
                    if self._setpoint > 0:
                        logger.debug('{} {:03.02f} red clearance',
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
                segment = sorted(self._active.intersection(ring))
                routines.append(ring.serve(segment))
            
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
