import asyncio
from loguru import logger
from typing import Set, Dict, List, Optional, Iterable, Self
from asyncio import Event, Task
from itertools import chain
from atsc.common.primitives import Timer, Context, Tickable, Identifiable, Flasher
from atsc.controller import utils
from atsc.controller.constants import (CallSource,
                                       FieldState,
                                       InputAction,
                                       SignalState,
                                       InputActivation, PhaseCyclerMode)
from atsc.controller.structs import IntervalTiming, IntervalConfig


class FieldOutput(Identifiable, Tickable):
    
    @property
    def state(self):
        return self._state
    
    def __init__(self, id_: int, fpm: float = 60.0):
        Identifiable.__init__(self, id_)
        Tickable.__init__(self)
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
            
            self._state = state
    
    def __bool__(self):
        return self._scalar
    
    def __int__(self):
        return 1 if self._scalar else 0
    
    def __repr__(self):
        return f'<FieldOutput #{self.id} {self.state.name}'
    
    def tick(self, context: Context):
        if self.state == FieldState.FLASHING:
            if self._flasher.poll(context, self.fpm):
                self._scalar = not self._scalar


class Signal(Identifiable, Tickable):
    global_field_output_mapping: Dict[FieldOutput, Self] = {}
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional[Self]:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def active(self):
        return not self.inactive.is_set()
    
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
        self._demand = value
        
    @property
    def free(self):
        return self._free
    
    @free.setter
    def free(self, value):
        if value != self._free:
            logger.verbose('{} free = {}', self.get_tag(), value)
        self._free = value
        
    @property
    def recall(self):
        return self._recall
    
    @recall.setter
    def recall(self, value):
        if value != self._recall:
            logger.verbose('{} recall = {}', self.get_tag(), value)
        self._recall = value
        
    @property
    def recycle(self):
        return self._recycle
    
    @recycle.setter
    def recycle(self, value):
        if value != self._recycle:
            logger.verbose('{} recycle = {}', self.get_tag(), value)
        self._recycle = value
    
    @property
    def field_outputs(self):
        rv = set()
        for field_output in self._mapping.values():
            rv.add(field_output)
        return sorted(rv)
    
    def __init__(self,
                 id_: int,
                 timings: Dict[SignalState, IntervalTiming],
                 configs: Dict[SignalState, IntervalConfig],
                 mapping: Dict[SignalState, FieldOutput],
                 recall: bool = False,
                 recycle: bool = False,
                 rest: bool = False,
                 demand: bool = False,
                 initial_state: SignalState = SignalState.STOP):
        Identifiable.__init__(self, id_)
        Tickable.__init__(self)
        self._timings = timings
        self._configs = configs
        self._mapping = mapping
        
        for fo in mapping.values():
            self.global_field_output_mapping.update({fo: self})
        
        self._state = SignalState.STOP
        self._initial_state = initial_state
        self._free = rest
        self._recall = recall
        self._recycle = recycle
        self._demand = demand
        
        self.timer = Timer()
        self.inactive = Event()
        
        if initial_state == SignalState.STOP:
            self.inactive.set()
        
        self.tickables.extend(self.field_outputs)
        self.change(force_state=initial_state)
    
    def get_next_state(self) -> SignalState:
        match self._state:
            case SignalState.STOP:
                # todo: go to FYA if conditions are met
                return SignalState.GO
            case SignalState.CAUTION:
                return SignalState.STOP
            case SignalState.FYA:
                # todo: go to green if next up
                return SignalState.CAUTION
            case SignalState.GO:
                return SignalState.CAUTION
            case SignalState.LS_FLASH:
                return self._initial_state
    
    def tick(self, context: Context):
        timing = self._timings[self._state]
        config = self._configs[self._state]
        
        if self.timer.poll(context, timing.minimum):
            if self._state == SignalState.STOP:
                if self.active:
                    if self.recall and not self.demand:
                        self.demand = True
                        logger.debug('{} recalled', self.get_tag())
                    self.inactive.set()
            else:
                if not config.rest or not self.free:
                    if timing.maximum:
                        trigger = timing.maximum
                        
                        if config.reduce:
                            trigger -= self.timer.value
                        
                        if self.timer.poll(context, trigger):
                            self.change()
                    else:
                        self.change()
        
        super().tick(context)
    
    def change(self, force_state: Optional[SignalState] = None):
        self.timer.reset()
        
        if force_state is not None:
            next_state = force_state
        else:
            next_state = self.get_next_state()
        
        previous_field_output = self._mapping[self._state]
        previous_field_output.set(FieldState.OFF)
        
        self._state = next_state
        field_output = self._mapping[self._state]
        interval_config = self._configs[self._state]
        
        if interval_config.flashing:
            field_output.set(FieldState.FLASHING)
        else:
            field_output.set(FieldState.ON)
        
        if self._state != SignalState.STOP:
            self.inactive.clear()
    
    async def serve(self):
        if self.demand:
            logger.debug('{} activated', self.get_tag())
            self.change()
            await self.inactive.wait()
            logger.debug('{} deactivated', self.get_tag())


class Phase(Identifiable, Tickable):
    global_field_output_mapping: Dict[FieldOutput, Self] = {}
    
    @classmethod
    def by_field_output(cls, fo: FieldOutput) -> Optional[Self]:
        return cls.global_field_output_mapping.get(fo)
    
    @property
    def active_signals(self):
        return [s for s in self.signals if s.active]
    
    @property
    def demand(self):
        return any([s.demand for s in self.signals])
    
    @demand.setter
    def demand(self, value):
        for signal in self.signals:
            signal.demand = value
    
    @property
    def free(self):
        return any([s.free for s in self.signals])
    
    @free.setter
    def free(self, value):
        for signal in self.signals:
            signal.free = value
    
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
        self._active = False
        self.signals = signals
        
        for signal in signals:
            for fo in signal.field_outputs:
                self.global_field_output_mapping.update({fo: self})
        
        self.tickables.extend(self.signals)
    
    async def serve(self):
        if self.active_signals:
            raise RuntimeError(f'phase {self.get_tag()} already active')
        
        if self.demand:
            self._active = True
            logger.debug('{} activated', self.get_tag())
            
            signals = self.signals
            tasks = [asyncio.create_task(s.serve()) for s in signals]
            
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            while pending:
                for i, task in enumerate(tasks):
                    signal = signals[i]
                    if signal.free and signal.recycle and not signal.active:
                        logger.debug('{} recycling', signal.get_tag())
                        tasks[i] = asyncio.create_task(signal.serve())
                
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            self._active = False
            logger.debug('{} deactivated', self.get_tag())


class Ring(Identifiable):
    
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
    
    @property
    def free(self):
        return any([p.free for p in self.phases])
    
    @free.setter
    def free(self, value):
        for phase in self.phases:
            phase.free = value
    
    def __init__(self, id_: int, phases: List[Phase]):
        super().__init__(id_)
        self.phases = phases


class PhaseCycler(Tickable):
    
    @property
    def phases(self):
        return list(chain(*[r.phases for r in self.rings]))
    
    @property
    def active_phases(self):
        return [p for p in self.phases if p.active_signals]
    
    @property
    def waiting_phases(self):
        return [p for p in self.phases if p.demand and not p.active_signals]
    
    @property
    def last_phase(self):
        if len(self.cycle_phases):
            return self.cycle_phases[-1]
        else:
            return None
    
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
    
    def __init__(self,
                 rings: List[Ring],
                 barriers: List[Barrier],
                 mode: PhaseCyclerMode):
        super().__init__()
        self.rings = rings
        self.barriers = barriers
        self.cycle_barriers: List[Barrier] = []
        self.cycle_phases: List[Phase] = []
        
        self._mode = PhaseCyclerMode.PAUSE
        self._cycle_count: int = 0
        
        # sequential mode only
        self._phase_sequence = utils.cycle(self.phases)
        
        # concurrent mode only
        self._barrier_sequence = utils.cycle(self.barriers)
        
        for barrier in self.barriers:
            barrier.ring_count = len(self.rings)
        
        self.tickables.extend(self.phases)
        self.set_mode(mode)
    
    def tick(self, context: Context):
        free = not self.waiting_phases
        for phase in self.active_phases:
            phase.free = free
        
        super().tick(context)
    
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
    
    def set_mode(self, mode: PhaseCyclerMode):
        if mode == self.mode:
            return
        
        match self.mode:
            case PhaseCyclerMode.SEQUENTIAL:
                phase_index = self.phases.index(self.last_phase) if self.last_phase else 0
                self._phase_sequence = utils.cycle(self.phases, initial=phase_index)
            case PhaseCyclerMode.CONCURRENT:
                barrier_index = 0
                if self.active_barrier is not None:
                    barrier_index = self.barriers.index(self.active_barrier) + 1
                elif self.last_phase is not None:
                    phase_barriers = get_phase_barriers(self.barriers, self.last_phase)
                    if phase_barriers:
                        phase_barrier = phase_barriers[0]
                        barrier_index = self.barriers.index(phase_barrier)
                        self.last_phase.skip_once = True
                
                self._barrier_sequence = utils.cycle(self.barriers, initial=barrier_index)
        
        self._mode = mode
    
    def serve_phase(self, phase: Phase) -> Task:
        self.cycle_phases.append(phase)
        return asyncio.create_task(phase.serve())
    
    def select_phases(self):
        assert self.active_barrier
        
        selected_phases = []
        
        for ring in self.rings:
            if ring.active_phases:
                continue
            
            intersection_phases = sorted(ring.intersection(self.active_barrier))
            for phase in intersection_phases:
                if phase not in self.cycle_phases and phase in self.waiting_phases:
                    selected_phases.append(phase)
                    break
                    
        return selected_phases
    
    async def run(self):
        self.try_change_barrier(next(self._barrier_sequence))
        
        while True:
            match self.mode:
                case PhaseCyclerMode.PAUSE:
                    await asyncio.sleep(0.0)
                    continue
                case PhaseCyclerMode.SEQUENTIAL:
                    while not self.waiting_phases:
                        await asyncio.sleep(0.0)
                    
                    for _ in range(len(self.phases)):
                        phase = next(self._phase_sequence)
                        if phase not in self.cycle_phases and phase in self.waiting_phases:
                            await self.serve_phase(phase)
                case PhaseCyclerMode.CONCURRENT:
                    while True:
                        selected_phases = self.select_phases()
                        if selected_phases:
                            phase_tasks = [self.serve_phase(p) for p in selected_phases]
                            done, pending = await asyncio.wait(phase_tasks, return_when=asyncio.FIRST_COMPLETED)
                            
                            if len(done) != len(phase_tasks):
                                while pending:
                                    selected_phases = self.select_phases()
                                    if selected_phases:
                                        phase_tasks.extend([self.serve_phase(p) for p in selected_phases])
                                    else:
                                        await asyncio.sleep(0.0)
                                    
                                    done, pending = await asyncio.wait(phase_tasks,
                                                                       return_when=asyncio.FIRST_COMPLETED)
                        else:
                            if self.try_change_barrier(next(self._barrier_sequence)):
                                break
                
            self._cycle_count += 1
            self.cycle_phases.clear()
            logger.debug('cycle #{}', self._cycle_count)
            
            if self._cycle_count:
                self.set_mode(PhaseCyclerMode.CONCURRENT)


def get_phase_barriers(barriers: Iterable[Barrier], phase: Phase) -> List[Barrier]:
    rv = []
    for barrier in barriers:
        if phase in barrier.phases:
            rv.append(barrier)
    return rv


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
            await self._served.wait_for(lambda _: self.target.active_signals)
            self._controller.removeCall(self)
    
    def __lt__(self, other):
        if isinstance(other, Call):
            if abs(self._age - other.age) < self._controller.time_increment:
                return self.id < other.id
            return self._age < other.age
        return False
    
    def __repr__(self):
        return f'<Call #{self._id:02d} {self._target.get_tag()} A{self._age:0>5.2f}>'


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
