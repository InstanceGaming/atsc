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
from atsc import logic
from enum import IntEnum
from loguru import logger
from typing import Dict, List, Optional
from atsc.logic import EdgeTrigger
from jacob.text import csl
from collections import Counter
from dataclasses import dataclass


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


class FlashMode(IntEnum):
    RED = 1
    YELLOW = 2


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
    MIN_STOP = 2
    RCLR = 4
    CAUTION = 6
    EXTEND = 8
    GO = 10
    PCLR = 12
    WALK = 14
    MAX_GO = 32


PHASE_RIGID_STATES = (PhaseState.CAUTION, PhaseState.PCLR)

PHASE_TIMED_STATES = (PhaseState.MIN_STOP,
                      PhaseState.RCLR,
                      PhaseState.CAUTION,
                      PhaseState.EXTEND,
                      PhaseState.GO,
                      PhaseState.PCLR,
                      PhaseState.WALK,
                      PhaseState.MAX_GO)

PHASE_GO_STATES = (PhaseState.EXTEND,
                   PhaseState.GO,
                   PhaseState.PCLR,
                   PhaseState.WALK)


class Phase(IdentifiableBase):
    
    @property
    def extend_enabled(self):
        return self.timing[PhaseState.EXTEND] > 0.0 and not self.extend_inhibit
    
    @property
    def default_extend(self):
        return self.timing[PhaseState.EXTEND] / 2.0
    
    @property
    def extend_active(self):
        return self._state == PhaseState.EXTEND
    
    @property
    def flash_mode(self) -> FlashMode:
        return self._flash_mode
    
    @property
    def active(self) -> bool:
        return self._state != PhaseState.STOP
    
    @property
    def state(self) -> PhaseState:
        return self._state
    
    @property
    def setpoint(self) -> float:
        return self._timer.trigger
    
    @setpoint.setter
    def setpoint(self, value):
        self._timer.trigger = value if value > 0.0 else 0.0
    
    @property
    def elapsed(self) -> float:
        return float(self._timer.elapsed)
    
    @property
    def veh_ls(self) -> LoadSwitch:
        return self._vls
    
    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls
    
    @property
    def secondary(self):
        return self.ped_ls is None
    
    def _validate_timing(self):
        if self.active:
            raise RuntimeError('Cannot changing timing map while active')
        if self.timing is None:
            raise TypeError('Timing map cannot be None')
        keys = self.timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES):
            raise RuntimeError('Timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('STOP cannot be in timing map')
    
    def __init__(self,
                 id_: int,
                 time_increment: float,
                 timing: Dict[PhaseState, float],
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 flash_mode: FlashMode = FlashMode.RED):
        super().__init__(id_)
        self.ped_service: bool = True
        self.extend_inhibit = False
        self.stats = Counter({
            'detections': 0,
            'vehicle_service': 0,
            'ped_service': 0
        })
        self.timing = timing
        self.flasher = True
        self.flash_timer = logic.Timer(0.5, step=time_increment)
        self._increment = time_increment
        self._flash_mode = flash_mode
        self._state: PhaseState = PhaseState.STOP
        self._timer: logic.Timer = logic.Timer(0, step=time_increment)
        self._vls = veh_ls
        self._pls = ped_ls
        self._validate_timing()
    
    def getNextState(self, ped_service: bool) -> PhaseState:
        if self._state == PhaseState.STOP:
            if self.ped_ls is not None and ped_service:
                return PhaseState.WALK
            else:
                return PhaseState.GO
        elif self._state == PhaseState.RCLR:
            return PhaseState.STOP
        elif self._state == PhaseState.CAUTION:
            return PhaseState.RCLR
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
            return PhaseState.PCLR
        else:
            raise NotImplementedError()

    def gap_reset(self):
        if self.extend_active:
            self._timer.reset()
    
    def activate(self):
        if self.active:
            raise RuntimeError('Cannot activate active phase')
        
        changed = self.change()
        assert changed
        
    def update_field(self, flasher: bool):
        pa = False
        pb = False
        pc = False
        
        if self._state == PhaseState.STOP or self._state == PhaseState.RCLR:
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
            pa = flasher
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
    
    def change(self, force_state: Optional[PhaseState] = None) -> bool:
        next_state = force_state if force_state is not None else self.getNextState(self.ped_service)
        
        if next_state != self._state:
            self._timer.reset()
            
            if next_state == PhaseState.STOP:
                self.extend_inhibit = False
            
            if next_state == PhaseState.GO:
                setpoint = self.timing[PhaseState.GO]
                setpoint -= self.timing[PhaseState.CAUTION]
                
                if self.ped_ls is not None and self.ped_service:
                    walk_time = self.timing[PhaseState.WALK]
                    pclr_time = self.timing[PhaseState.PCLR]
                    setpoint -= (walk_time + pclr_time)
                
                self.stats['vehicle_service'] += 1
            else:
                setpoint = self.timing.get(next_state, 0.0)
                
                if next_state == PhaseState.WALK:
                    self.stats['ped_service'] += 1
            
            if next_state in PHASE_TIMED_STATES:
                assert setpoint >= 1.0
            self._state = next_state
            self.setpoint = round(setpoint, 1)
            return True
        else:
            return False
    
    def tick(self, rest_inhibit: bool) -> bool:
        if self.flash_timer.poll(self._state == PhaseState.PCLR):
            self.flash_timer.reset()
            self.flasher = not self.flasher
        
        self.update_field(self.flasher)
        changed = False
        
        if self._timer.poll(True):
            if self.active:
                if (self._state in PHASE_RIGID_STATES) or rest_inhibit:
                    walking = self._state == PhaseState.WALK
                    if walking:
                        walk_time = self.timing[PhaseState.WALK]
                        self.extend_inhibit = self.elapsed - walk_time > self.default_extend
                        
                        if self.extend_inhibit:
                            logger.debug('{} extend inhibited', self.getTag())
                    changed = self.change()
        else:
            if self.extend_active:
                self.setpoint -= self._increment
                
        if self._state in PHASE_GO_STATES:
            if self.elapsed > self.timing[PhaseState.MAX_GO]:
                if rest_inhibit:
                    changed = self.change()
        
        return changed
    
    def __repr__(self):
        return (f'<{self.getTag()} {self.state.name} '
                f'{round(self.elapsed, 1)} of {round(self.setpoint, 1)}>')


class Call:
    
    @property
    def phase_tags_list(self):
        return csl([phase.getTag() for phase in self.phases])
    
    def __init__(self, phases: List[Phase]):
        self.phases = phases
        self.age = 0.0
    
    def __contains__(self, item):
        if isinstance(item, Phase):
            return item in self.phases
        else:
            raise NotImplementedError()
    
    def __eq__(self, other):
        if isinstance(other, Call):
            if set(self.phases).intersection(other.phases):
                return True
            else:
                return False
        else:
            return NotImplementedError()
    
    def __repr__(self):
        return f'<Call {self.phase_tags_list} {self.age}>'


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
    OFF = 0
    LOW = 1
    HIGH = 2
    RISING = 3
    FALLING = 4


class Input:
    
    def __init__(self,
                 trigger: InputActivation,
                 action: InputAction,
                 targets: List[Phase],
                 state: bool = False):
        self.trigger = trigger
        self.action = action
        self.targets = targets
        self.state = state
        self.rising = EdgeTrigger(True)
        self.falling = EdgeTrigger(False)
    
    def activated(self) -> bool:
        if self.trigger.RISING:
            return self.rising.poll(self.state)
        elif self.trigger.FALLING:
            return self.falling.poll(self.state)
        else:
            if self.trigger.HIGH:
                return self.state
            elif self.trigger.LOW:
                return not self.state
        return False
    
    def __repr__(self):
        return f'<Input {self.trigger.name} {self.action.name} ' \
               f'{"ACTIVE" if self.state else "INACTIVE"}'
