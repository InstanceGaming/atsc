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
from typing import Dict, List, Optional, Iterable, Tuple
from dataclasses import dataclass

from loguru import logger

from atsc.constants import *
from atsc.eventbus import BusEvent
from atsc.parameters import DelayProvider
from atsc.primitives import Referencable, Runnable, ref
from atsc.utils import format_us, micros


class Clock(Referencable, Runnable, DelayProvider):
    onTick = BusEvent('clock.tick')
    
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
            self.onTick.invoke(self)
            logger.trace('{} took {} to process {} subscribers',
                         self.getTag(),
                         format_us(micros() - marker),
                         self.onTick.subscribed)
            marker = micros()
            await asyncio.sleep(self.delay)
            logger.trace('{} slept for {}',
                         self.getTag(),
                         format_us(micros() - marker))


class Ticking(Referencable):
    
    def __init__(self, id_: int):
        Referencable.__init__(self, id_)
        BusEvent.match('clock.tick').subscribe(self.onClockTick)
    
    def onClockTick(self, clock: Clock):
        match clock.id:
            case StandardObjects.TIME_TICK:
                self.onTimeTick(clock)
            case StandardObjects.INPUTS_TICK:
                self.onInputsTick(clock)
            case StandardObjects.BUS_TICK:
                self.onBusTick(clock)
            case StandardObjects.NETWORK_TICK:
                self.onNetworkTick(clock)
            case StandardObjects.FLASH_TICK:
                self.onFlashTick(clock)
    
    def onTimeTick(self, clock: Clock):
        pass
    
    def onInputsTick(self, clock: Clock):
        pass
    
    def onBusTick(self, clock: Clock):
        pass
    
    def onNetworkTick(self, clock: Clock):
        pass
    
    def onFlashTick(self, clock: Clock):
        pass


class Flasher(Ticking):
    onToggle = BusEvent('flasher.toggle')
    
    @property
    def a(self):
        return self._a
    
    @property
    def b(self):
        return self._b
    
    def __init__(self,
                 id_: int,
                 invert: bool = False):
        Ticking.__init__(self, id_)
        
        self._a = not invert
        self._b = invert
    
    def onFlashTick(self, clock: Clock):
        self._a = not self._a
        self._b = not self._b
        self.onToggle.invoke(self)


class FieldOutput(Referencable):
    onChange = BusEvent('field_output.on_change')
    
    @property
    def state(self):
        return self._state
    
    @state.setter
    def state(self, next_state: FieldState):
        if next_state != FieldState.INHERIT:
            qb = self._q
            if next_state & FieldState.ON:
                if next_state & FieldState.FLASHING:
                    self._q = False
                else:
                    self._q = True
            elif next_state == FieldState.OFF:
                self._q = False
            
            self._state = next_state
            if self._q != self._lq:
                self._lq = qb
                self.onChange.invoke(self)
    
    @property
    def q(self):
        return self._q
    
    def __init__(self,
                 id_: int,
                 flash_polarity: FlashPolarity):
        super().__init__(id_)
        BusEvent.match('flasher.toggle').subscribe(self.onFlasherToggle)
        self._flash_polarity = flash_polarity
        self._state = FieldState.OFF
        self._q = False
        self._lq = True
    
    def onFlasherToggle(self, flasher: Flasher):
        if self.state & FieldState.FLASHING:
            self._lq = self._q
            if self._flash_polarity == FlashPolarity.A:
                self._q = flasher.a
            elif self._flash_polarity == FlashPolarity.B:
                self._q = flasher.b
            else:
                raise NotImplementedError()
    
    def on(self):
        self.state = FieldState.ON
    
    def flashing(self):
        self.state = FieldState.FLASHING
    
    def off(self):
        self.state = FieldState.OFF


FieldTriad = namedtuple('FieldTriad', ('a', 'b', 'c'))
FieldMapping = Dict[SignalState, FieldTriad]


class LoadSwitch(Referencable):
    
    @property
    def mapping(self):
        return self._mapping
    
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
    
    def update(self, signal_state: SignalState):
        field_states = self._mapping.get(signal_state)
        if field_states is not None:
            self.a.state = field_states.a
            self.b.state = field_states.b
            self.c.state = field_states.c
    
    @staticmethod
    def make_simple(ls_id: int,
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
    nominal: TimeMap
    maximum: TimeMap


DEFAULT_SIGNAL_STATE = SignalState.OFF


class Signal(Ticking):
    
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
    def previous_states(self):
        return self._previous_states
    
    @property
    def minimum(self):
        return self.timing.minimum[self.state]
    
    @property
    def maximum(self):
        return self.timing.maximum[self.state]
    
    @property
    def remaining(self):
        return self._remaining
    
    @property
    def elapsed(self):
        return self._elapsed
    
    def __init__(self,
                 id_: int,
                 timing: TimingPlan,
                 primary: LoadSwitch,
                 secondary: Optional[LoadSwitch] = None,
                 initial_state: SignalState = SignalState.STOP):
        super().__init__(id_)
        
        self._primary = primary
        primary.update(initial_state)
        
        self._secondary = secondary
        self._state = initial_state
        self._previous_states: List[SignalState] = []
        self._setpoint: float = 0.0
        self._remaining: float = 0.0
        self._elapsed: float = 0.0
        self._ready = asyncio.Event()
        self.timing = timing
        self.demand = False
    
    def getNextState(self) -> SignalState:
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
    
    def change(self):
        self._previous_states.insert(0, self._state)
        
        if len(self._previous_states) > len(SignalState):
            self._previous_states.pop(-1)
        
        self._state = self.getNextState()
        self._primary.update(self._state)
        
        self._setpoint: float = self.timing.nominal[self.state]
        self._remaining: float = self._setpoint
        self._elapsed: float = 0
        
        if self.state == SignalState.STOP:
            self.demand = False
            self._ready.set()
        else:
            if self._ready.is_set():
                self._ready.clear()
    
    def onTimeTick(self, clock: Clock):
        if self._remaining > clock.delay:
            self._remaining -= clock.delay
    
        self._elapsed += clock.delay
    
        over_maximum = self.elapsed > self.maximum
        if self.remaining < clock.delay or over_maximum:
            if self.state == SignalState.CAUTION or self.demand or over_maximum:
                self.change()
    
    async def wait(self):
        await self._ready.wait()


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
                 signals: List[Signal],
                 enabled: bool = True,
                 skip: bool = False):
        super().__init__(id_)
        
        self._active = False
        self._signals = signals
        self.enabled = enabled
        self.skip = skip
    
    async def wait(self):
        if self.ready:
            self._active = True
            await asyncio.gather(*[s.wait() for s in self._signals])
            self._active = False


class Ring(Referencable):
    
    @property
    def phases(self):
        return self._phases
    
    def __init__(self,
                 id_: int,
                 phases: Iterable[int]):
        super().__init__(id_)
        self._phases = sorted([ref(pid, Phase) for pid in phases])
        self._cycler = cycle(self._phases)
    
    def available(self, within: Iterable[Phase] = None) -> List[Phase]:
        results = []
        
        for phase in self._phases:
            if phase.ready:
                if within is None or phase in within:
                    results.append(phase)
        
        return results
    
    def select(self) -> Phase:
        while True:
            phase = next(self._cycler)
            
            if phase.ready:
                break
        
        return phase


class Barrier(Referencable):
    
    @property
    def phases(self):
        return self._phases
    
    def __init__(self,
                 id_: int,
                 phases: Iterable[int]):
        super().__init__(id_)
        self._phases = sorted([ref(pid, Phase) for pid in phases])


class BarrierManager(Runnable):
    
    def __init__(self,
                 barriers: List[Barrier],
                 rings: List[Ring]):
        self._barriers = barriers
        self._rings = rings
    
    async def run(self):
        while True:
            group = []
            for ring in self._rings:
                selected = ring.select()
                group.append(selected)
            await asyncio.gather(*[phase.wait() for phase in group])
            await asyncio.sleep(1)


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
        return f'<Call #{self._id:02d} {self._target.getTag()} A{self._age:0>5.2f}>'


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
