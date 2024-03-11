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
from atsc import constants
from enum import IntEnum
from typing import Dict, List, Optional
from atsc.logic import Timer, Flasher, EdgeTrigger
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
    
    def get_tag(self):
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
    
    def get_tag(self):
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
    RCLR = 4
    CAUTION = 6
    EXTEND = 8
    GO = 10
    PCLR = 12
    WALK = 14
    MAX_GO = 32
    MIN_SERVICE = 64
    
    def __repr__(self):
        return self.name


PHASE_RIGID_STATES = (PhaseState.RCLR, PhaseState.CAUTION, PhaseState.PCLR)

PHASE_SERVICE_STATES = (PhaseState.RCLR,
                        PhaseState.CAUTION,
                        PhaseState.EXTEND,
                        PhaseState.GO,
                        PhaseState.PCLR,
                        PhaseState.WALK)

PHASE_TIMES_STATES = (PhaseState.RCLR,
                      PhaseState.CAUTION,
                      PhaseState.EXTEND,
                      PhaseState.GO,
                      PhaseState.PCLR,
                      PhaseState.WALK)

PHASE_TIMED_STATES_ALL = (PhaseState.MIN_SERVICE,
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

PHASE_SYNC_STATES = (PhaseState.GO,
                     PhaseState.PCLR,
                     PhaseState.WALK)

PHASE_SUPPLEMENT_STATES = (PhaseState.GO, PhaseState.WALK, PhaseState.PCLR)

PHASE_PARTNER_INHIBIT_STATES = (PhaseState.CAUTION, PhaseState.EXTEND)

PHASE_RECYCLE_STATES = (PhaseState.WALK, PhaseState.GO, PhaseState.EXTEND)


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
    def resting(self):
        return self._resting
    
    @property
    def state(self) -> PhaseState:
        return self._state
    
    @property
    def previous_states(self):
        return self._previous_states
    
    @property
    def setpoint(self) -> float:
        return self._timer.trigger
    
    @setpoint.setter
    def setpoint(self, value):
        self._timer.trigger = value if value > 0.0 else 0.0
    
    @property
    def interval_elapsed(self):
        return float(self._timer.elapsed)
    
    @property
    def service_elapsed(self):
        return float(self._service_timer.elapsed)
    
    @property
    def minimum_service(self):
        return max(self.timing[PhaseState.MIN_SERVICE],
                   self.timing[PhaseState.CAUTION] + self.timing[PhaseState.RCLR] + 1)
    
    @property
    def ped_service(self):
        return self._ped_service
    
    @property
    def go_override(self):
        return self._go_override
    
    @go_override.setter
    def go_override(self, value):
        if self.go_override is not None:
            if self.go_override < 0:
                raise ValueError('go override must be positive')
            self._go_override = min(value, self.timing[PhaseState.MAX_GO])
        else:
            self._go_override = None
    
    @property
    def veh_ls(self) -> LoadSwitch:
        return self._vls
    
    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls
    
    @property
    def primary(self):
        return self.ped_ls is not None
    
    def _validate_timing(self):
        if self.active:
            raise RuntimeError('Cannot changing timing map while active')
        if self.timing is None:
            raise TypeError('Timing map cannot be None')
        keys = self.timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES_ALL):
            raise RuntimeError('Timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('STOP cannot be in timing map')
    
    def __init__(self,
                 id_: int,
                 timing: Dict[PhaseState, float],
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 flash_mode: FlashMode = FlashMode.RED):
        super().__init__(id_)
        self.flasher = Flasher()
        self.stats = Counter({
            'detections'     : 0,
            'vehicle_service': 0,
            'ped_service'    : 0
        })
        self.timing = timing
        self.extend_inhibit = False
        
        self._ped_service = False
        self._go_override: Optional[float] = None
        self._resting = False
        self._flash_mode = flash_mode
        self._state: PhaseState = PhaseState.STOP
        self._previous_states: List[PhaseState] = []
        self._timer = Timer(0, step=constants.TIME_INCREMENT)
        self._service_timer = Timer(0, step=constants.TIME_INCREMENT)
        self._vls = veh_ls
        self._pls = ped_ls
        self._validate_timing()
    
    def get_recycle_state(self, ped_service: bool) -> PhaseState:
        if self._state in PHASE_RECYCLE_STATES:
            if ped_service:
                return PhaseState.WALK
            else:
                return PhaseState.GO
        else:
            raise NotImplementedError()
    
    def get_next_state(self, ped_service: bool, expedite: bool) -> PhaseState:
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
            if self.extend_enabled and not expedite:
                return PhaseState.EXTEND
            else:
                return PhaseState.CAUTION
        elif self._state == PhaseState.PCLR:
            if expedite:
                return PhaseState.CAUTION
            else:
                return PhaseState.GO
        elif self._state == PhaseState.WALK:
            return PhaseState.PCLR
        else:
            raise NotImplementedError()
    
    def get_setpoint(self, state: PhaseState) -> float:
        if state == PhaseState.GO:
            setpoint = self.go_override or self.timing[PhaseState.GO]
            setpoint -= self.timing[PhaseState.CAUTION]
            
            extension = self.timing[PhaseState.EXTEND]
            if extension:
                setpoint -= extension / 2
            
            if self.ped_ls is not None and self.ped_service:
                setpoint -= self.timing[PhaseState.WALK]
                setpoint -= self.timing[PhaseState.PCLR]
        else:
            setpoint = self.timing.get(state, 0.0)
        
        return round(setpoint, 1)
    
    def estimate_remaining(self) -> Optional[float]:
        if self.state == PhaseState.STOP:
            return None
        
        setpoints = 0.0
        for state in PHASE_SERVICE_STATES:
            if self.state >= state.value:
                setpoints += self.get_setpoint(state)
            else:
                break
        
        # I don't know why it's SOMETIMES 1 off...
        estimate = round(setpoints - self.interval_elapsed) - 1.0
        return estimate
    
    def gap_reset(self):
        if self.extend_active:
            self._timer.reset()
    
    def activate(self, ped_service: bool):
        state = None
        
        if self.active:
            if self.state in PHASE_RIGID_STATES:
                raise RuntimeError('Cannot activate active phase during rigidly-timed interval')
            
            state = self.get_recycle_state(ped_service)
        
        changed = self.change(state=state, ped_service=ped_service)
        assert changed
        
        self._service_timer.reset()
    
    def update_field(self):
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
            pa = self.flasher.bit
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
    
    def change(self,
               state: Optional[PhaseState] = None,
               ped_service: bool = False,
               expedite: bool = False) -> bool:
        next_state = state if state is not None else self.get_next_state(ped_service,
                                                                         expedite)
        if next_state != self._state:
            self._ped_service = ped_service
            self._resting = False
            self._timer.reset()
            
            if next_state == PhaseState.STOP:
                if float(self._service_timer.elapsed) < self.minimum_service:
                    raise ValueError('less than minimum service time served')
                
                self.extend_inhibit = False
                self.go_override = None
            
            if next_state == PhaseState.GO:
                self.stats['vehicle_service'] += 1
            else:
                if next_state == PhaseState.WALK:
                    self.stats['ped_service'] += 1
            
            setpoint = self.get_setpoint(next_state)
            if next_state in PHASE_TIMED_STATES_ALL:
                assert setpoint >= 0.0
            
            self._previous_states.insert(0, self.state)
            
            if len(self._previous_states) > len(PHASE_TIMES_STATES) - 1:
                self._previous_states.pop()
            
            self._state = next_state
            self.setpoint = setpoint
            return True
        else:
            return False
    
    def tick(self, rest_inhibit: bool, supress_maximum: bool) -> bool:
        self.flasher.poll(self._state == PhaseState.PCLR)
        self.update_field()
        
        changed = False
        
        if self._timer.poll(True):
            if self.active:
                if (self._state in PHASE_RIGID_STATES) or rest_inhibit:
                    if self._state == PhaseState.WALK:
                        walk_time = self.timing[PhaseState.WALK]
                        self.extend_inhibit = self.interval_elapsed - walk_time > self.default_extend
                    changed = self.change()
                else:
                    self._resting = True
        else:
            if self.extend_active:
                self.setpoint -= constants.TIME_INCREMENT
        
        if self._state in PHASE_GO_STATES:
            if self.interval_elapsed > self.timing[PhaseState.MAX_GO]:
                if not supress_maximum or rest_inhibit:
                    changed = self.change(expedite=True)
                else:
                    self._resting = True
        
        if self.extend_active and not self.extend_enabled:
            self.change()
        
        self._service_timer.poll(self._state in PHASE_TIMES_STATES)
        
        return changed
    
    def __repr__(self):
        return (f'<{self.get_tag()} {self.state.name} '
                f'{round(self.interval_elapsed, 1)} of {round(self.setpoint, 1)}>')


class Ring(IdentifiableBase):
    
    def __init__(self, id_: int, phases: List[int]):
        super().__init__(id_)
        self.phases: List[int] = phases


class Barrier(IdentifiableBase):
    
    def __init__(self, id_: int, phases: List[int]):
        super().__init__(id_)
        self.phases: List[int] = phases


class Call:
    
    @property
    def phase_tags_list(self):
        return csl([phase.get_tag() for phase in self.phases])
    
    @property
    def sorting_weight(self):
        return max([p.interval_elapsed for p in self.phases if not p.active] or [self.age])
    
    def __init__(self, phases: List[Phase], ped_service: bool = False):
        self.phases = phases
        self.ped_service = ped_service
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
