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
from abc import ABC, abstractmethod
from enum import IntEnum
from itertools import cycle
from typing import Dict, List, Optional, Iterable, Set
from dataclasses import dataclass

from src.events import Listener
from src.interfaces import IController


class IdentifiableBase:
    
    @property
    def id(self) -> int:
        return self._id
    
    def __init__(self, id_: int):
        self._id = id_
    
    def __hash__(self) -> int:
        return self._id
    
    def __eq__(self, other) -> bool:
        if other is None:
            return False
        return self._id == other.id
    
    def __lt__(self, other) -> bool:
        return self._id < other.id
    
    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'
    
    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


@dataclass(frozen=True)
class FrozenIdentifiableBase:
    id: int
    
    def __hash__(self) -> int:
        return self.id
    
    def __eq__(self, other):
        return self.id == other.id
    
    def __lt__(self, other):
        return self.id < other.id
    
    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'
    
    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class Pollable(Listener, ABC):
    
    def __init__(self):
        self.addListener('controller.tick', self.onTick)
        self.addListener('controller.half_second', self.onHalfSecond)
        self.addListener('controller.second', self.onSecond)
    
    @abstractmethod
    def onTick(self):
        pass
    
    @abstractmethod
    def onHalfSecond(self):
        pass
    
    @abstractmethod
    def onSecond(self):
        pass
    

class FlashMode(IntEnum):
    RED = 1
    YELLOW = 2


class TrafficType(IntEnum):
    VEHICLE = 1
    PEDESTRIAN = 2


class OperationMode(IntEnum):
    DARK = 0
    CET = 1  # Control entrance transition
    CXT = 2  # Control exit transition
    LS_FLASH = 3
    NORMAL = 4


class LoadSwitch(IdentifiableBase):
    
    def __init__(self, id_: int):
        super().__init__(id_)
        self.a = False
        self.b = False
        self.c = False


class PhaseState(IntEnum):
    STOP = 0
    CAUTION = 6
    EXTEND = 8
    GO = 10
    PCLR = 12
    WALK = 14
    MAX_GO = 32


PHASE_REST_STATES = (PhaseState.STOP, PhaseState.GO, PhaseState.WALK)

PHASE_TIMED_STATES = (PhaseState.CAUTION,
                      PhaseState.EXTEND,
                      PhaseState.GO,
                      PhaseState.PCLR,
                      PhaseState.WALK,
                      PhaseState.MAX_GO)

PHASE_GO_STATES = (PhaseState.EXTEND,
                   PhaseState.GO,
                   PhaseState.PCLR,
                   PhaseState.WALK)

PHASE_PARTNER_START_STATES = (PhaseState.EXTEND,
                              PhaseState.GO,
                              PhaseState.WALK)


class Phase(IdentifiableBase):
    FYA_LOCAL = -1
    FYA_PED = -2
    
    @property
    def ped_enabled(self) -> bool:
        return self._pls is not None
    
    @property
    def ped_service(self) -> bool:
        return not self._ped_inhibit and self.ped_enabled
    
    @property
    def extend_enabled(self):
        return self._timing[PhaseState.EXTEND] > 0 and not self._extend_inhibit
    
    @property
    def extend_active(self):
        return self._state == PhaseState.EXTEND
    
    @property
    def resting(self):
        return self._resting
    
    @property
    def flash_mode(self) -> FlashMode:
        return self._flash_mode
    
    @property
    def active(self) -> bool:
        return self._state.value > 2
    
    @property
    def state(self) -> PhaseState:
        return self._state
    
    @property
    def time_upper(self):
        return self._duration
    
    @property
    def time_lower(self):
        return self._counter
    
    @property
    def veh_ls(self) -> LoadSwitch:
        return self._vls
    
    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls
    
    @property
    def interval_total(self):
        return self._interval_total
    
    def _validate_timing(self):
        if self.active:
            raise RuntimeError('Cannot changing timing map while active')
        if self._timing is None:
            raise TypeError('Timing map cannot be None')
        keys = self._timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES):
            raise RuntimeError('Timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('STOP cannot be in timing map')
    
    def __init__(self,
                 id_: int,
                 controller: IController,
                 timing: Dict[PhaseState, float],
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 flash_mode: FlashMode = FlashMode.RED,
                 ped_clear_enable: bool = True):
        super().__init__(id_)
        self._controller = controller
        self._timing = timing
        self._vls = veh_ls
        self._pls = ped_ls
        self._flash_mode = flash_mode
        self._state: PhaseState = PhaseState.STOP
        
        self._duration: float = 0.0
        self._counter: float = 0.0
        self._interval_total: float = 0.0
        
        self._ped_inhibit: bool = True
        self._ped_cycle: bool = False
        self._resting: bool = False
        self._extend_inhibit = False
        self.ped_clear_enable: bool = ped_clear_enable
        
        self._validate_timing()
    
    def getNextState(self, ped_service: bool) -> PhaseState:
        if self._state == PhaseState.STOP:
            if ped_service:
                return PhaseState.WALK
            else:
                return PhaseState.GO
        elif self._state == PhaseState.CAUTION:
            return PhaseState.STOP
        elif self._state == PhaseState.EXTEND:
            return PhaseState.CAUTION
        elif self._state == PhaseState.GO:
            if self.extend_enabled:
                return PhaseState.EXTEND
            else:
                return PhaseState.CAUTION
        elif self._state == PhaseState.PCLR:
            return PhaseState.GO
        elif self._state == PhaseState.WALK:
            if self.ped_clear_enable:
                return PhaseState.PCLR
            else:
                return PhaseState.GO
        else:
            raise NotImplementedError()
    
    def update(self, force_state: Optional[PhaseState] = None):
        if force_state is not None:
            next_state = force_state
        else:
            next_state = self.getNextState(self.ped_service)
        tv = self._timing.get(next_state, 0.0)
        
        if tv > self._controller.time_increment:
            tv -= self._controller.time_increment
        
        self._duration = tv
        self._counter = tv
        
        if next_state == PhaseState.STOP:
            self._ped_cycle = False
            self._extend_inhibit = False
        elif next_state == PhaseState.GO:
            if self._ped_cycle:
                go_time = self._timing[PhaseState.GO]
                walk_time = self._timing[PhaseState.WALK]
                self._counter = go_time - walk_time
                if self.ped_clear_enable:
                    self._counter -= self._timing[PhaseState.PCLR]
                if self._counter < 0:
                    self._counter = 0.0
        else:
            if next_state == PhaseState.WALK:
                self._ped_cycle = True
        self._state = next_state
        self._interval_total = 0.0
    
    def changeTiming(self, revised: Dict[PhaseState, float]):
        self._timing = revised
        self._validate_timing()
    
    def reduce(self):
        if self.extend_active:
            self._counter = 0.0
        else:
            raise RuntimeError('Cannot reduce, not extending')

    async def wait(self):
        self.update()
        while self.state != PhaseState.STOP:
            await asyncio.sleep(self._controller.time_increment)

    def tick(self):
        self.updateLoadSwitches()
        
        self._resting = False
        if self._state in PHASE_GO_STATES:
            if self._interval_total > self._timing[PhaseState.MAX_GO]:
                if self._controller.hasConflictingDemand(self):
                    # todo: make this condition configurable per phase
                    self.update()
    
        if self.extend_active:
            if self._counter >= self._timing[PhaseState.EXTEND]:
                if self._controller.hasConflictingDemand(self):
                    self.update()
                else:
                    self._resting = True
            else:
                self._counter += self._controller.time_increment
        else:
            if self._state != PhaseState.STOP:
                if self._counter > 0:
                    self._counter -= self._controller.time_increment
                    if self._counter < 0:
                        self._counter = 0
                else:
                    if self._state == PhaseState.WALK:
                        if self._controller.hasConflictingDemand(self):
                            if self._controller.flasher:
                                self.update()
                        else:
                            self._resting = True
                            self._extend_inhibit = True
                    else:
                        if self._state == PhaseState.GO or self._state == PhaseState.EXTEND:
                            if self._controller.hasConflictingDemand(self):
                                self.update()
                            else:
                                self._resting = True
                        else:
                            self.update()
            else:
                self._resting = True
    
        self._interval_total += self._controller.time_increment

    def updateLoadSwitches(self):
        pa = False
        pb = False
        pc = False
    
        if self._state == PhaseState.STOP:
            self._vls.a = True
            self._vls.b = False
            self._vls.c = False
            pa = True
            pc = False
        elif self._state == PhaseState.CAUTION:
            self._vls.a = False
            self._vls.b = True
            self._vls.c = False
            pa = True
            pc = False
        elif self._state == PhaseState.GO or self._state == PhaseState.EXTEND:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = True
            pc = False
        elif self._state == PhaseState.PCLR:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = self._controller.flasher
            pc = False
        elif self._state == PhaseState.WALK:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = False
            pc = True
    
        if self._pls is not None:
            self._pls.a = pa
            self._pls.b = pb
            self._pls.c = pc
    
    def __repr__(self):
        return f'<{self.getTag()} {self.state.name} {self.time_upper: 05.1f}' \
               f' {self.time_lower: 05.1f}>'


@dataclass(frozen=True)
class FrozenPhaseSetup:
    vehicle_ls: int
    ped_ls: int
    flash_mode: FlashMode
    fya_setting: int
    
    
class PhasePattern(IntEnum):
    ANY = 0
    COLUMN = 1
    DIAGONAL = 2
    SINGLE = 3
    

class Ring(IdentifiableBase):

    @property
    def phases(self):
        return self._phases
    
    def __init__(self, id_: int, controller: IController, phases: Iterable[Phase]):
        super().__init__(id_)
        self._controller = controller
        self._phases = sorted(phases)
        self._cycler = cycle(self._phases)
        self._skips: Set[Phase] = set()
    
    def getPhaseIndex(self, phase: Phase) -> Optional[int]:
        try:
            return self._phases.index(phase)
        except ValueError:
            return None
    
    def skip(self, phase: Phase) -> bool:
        try:
            self._skips.add(phase)
            return True
        except ValueError:
            return False

    async def next(self) -> Phase:
        phase_pool = self._controller.getInstantPhasePool()
        selection = next(self._cycler)
        
        if selection not in phase_pool:
            await self._controller.barrier.wait()
            await asyncio.sleep(1000)
        
        while selection in self._skips:
            selection = next(self._cycler)
        
        return selection

    async def run(self):
        while True:
            active_phase = await self.next()
            await active_phase.wait()


def get_deltas(items):
    deltas = []
    for i, item in enumerate(items):
        if i:
            prev = items[i - 1]
            deltas.append(item - prev)
    return deltas


def get_barrier_range(positions, position):
    right_index = positions.index(position)
    if right_index == 0:
        return range(0, position + 1)
    else:
        deltas = get_deltas(positions)
        left = position - deltas[right_index - 1] + 1
        return range(left, position + 1)


class Barrier:
    
    @property
    def positions(self):
        return self._positions
    
    @property
    def active(self):
        return self._active
    
    @property
    def active_range(self):
        return get_barrier_range(self._positions, self._active)
    
    def __init__(self,
                 controller: IController,
                 positions: Iterable[int],
                 ring_count: int):
        self._controller = controller
        self._ring_count = ring_count
        self._waiting_count: int = 0
        self._positions: List[int] = sorted(positions)
        self._cycler = cycle(self._positions)
        self._active: int = next(self._cycler)  # active position value, NOT INDEX!
    
    def range_of(self, pos: int) -> range:
        return get_barrier_range(self._positions, pos)
    
    def index(self, pos: int) -> int:
        return self._positions.index(pos)
    
    def next(self):
        self._active = next(self._cycler)
        
    async def wait(self):
        self._waiting_count += 1
        if self._waiting_count >= self._ring_count:
            self.next()
            self._waiting_count = 0
        else:
            await asyncio.sleep(self._controller.time_increment)
    

class Call(IdentifiableBase):
    
    @property
    def target(self) -> Phase:
        return self._target
    
    @property
    def ped_service(self):
        return self._ped_service
    
    @property
    def age(self) -> float:
        return self._age
    
    def __init__(self, id_: int, increment: float, target: Phase, ped_service=False):
        super().__init__(id_)
        self._target = target
        self._age: float = 0.0
        self._increment = increment
        self._ped_service = ped_service
        self.duplicates: int = 0
    
    def tick(self):
        self._age += self._increment
    
    def __lt__(self, other):
        if isinstance(other, Call):
            return self._age < other.age
        return False
    
    def __repr__(self):
        return f'<Call #{self._id:02d} A{self._age:0>5.2f}>'


class InputAction(IntEnum):
    NOTHING = 0
    CALL = 1
    DETECT = 2
    PREEMPTION = 3
    TIME_FREEZE = 4
    
    PED_CLEAR_INHIBIT = 5
    FYA_INHIBIT = 6
    CALL_INHIBIT = 7
    REDUCE_INHIBIT = 8
    
    MODE_DARK = 9
    MODE_NORMAL = 10
    MODE_LS_FLASH = 11


class InputActivation(IntEnum):
    LOW = 1
    HIGH = 2
    RISING = 3
    FALLING = 4


@dataclass
class Input:
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
