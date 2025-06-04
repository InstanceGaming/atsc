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
from atsc import logic, constants
from enum import IntEnum
from loguru import logger
from typing import Dict, List, Optional

from atsc.constants import TIME_INCREMENT
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
    FYA = 11
    PCLR = 12
    WALK = 14
    MAX_GO = 32
    FYA_DELAY = 33


PHASE_STOP_STATES = (PhaseState.STOP, PhaseState.MIN_STOP, PhaseState.RCLR)

PHASE_RIGID_STATES = (PhaseState.CAUTION, PhaseState.PCLR)

PHASE_TIMED_STATES = (PhaseState.MIN_STOP,
                      PhaseState.RCLR,
                      PhaseState.CAUTION,
                      PhaseState.EXTEND,
                      PhaseState.GO,
                      PhaseState.FYA,
                      PhaseState.PCLR,
                      PhaseState.WALK,
                      PhaseState.MAX_GO,
                      PhaseState.FYA_DELAY)

PHASE_GO_STATES = (PhaseState.EXTEND,
                   PhaseState.GO,
                   PhaseState.PCLR,
                   PhaseState.WALK)

PHASE_FYA_GO_STATES = (PhaseState.EXTEND,
                       PhaseState.GO)

PHASE_PED_STATES = (PhaseState.PCLR,
                    PhaseState.WALK)

PHASE_DURATION_ESTIMATION_STATES = (PhaseState.RCLR,
                                    PhaseState.CAUTION,
                                    PhaseState.EXTEND,
                                    PhaseState.GO,
                                    PhaseState.PCLR,
                                    PhaseState.WALK)

PHASE_REMAINING_ESTIMATION_STATES = (PhaseState.RCLR,
                                     PhaseState.CAUTION,
                                     PhaseState.EXTEND,
                                     PhaseState.GO,
                                     PhaseState.FYA,
                                     PhaseState.PCLR,
                                     PhaseState.WALK)


class Phase(IdentifiableBase):
    
    @property
    def veh_ls(self) -> LoadSwitch:
        return self._vls
    
    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls
    
    @property
    def service_remaining_minimum(self):
        return self._service_remaining_minimum
    
    @property
    def secondary(self):
        return self.ped_ls is None
    
    @property
    def ped_service(self):
        return self._ped_service
    
    @property
    def extend_enabled(self):
        return self.timing[PhaseState.EXTEND] > 0.0 and not self.extend_inhibit
    
    @property
    def extension_time(self):
        return self.timing[PhaseState.EXTEND]
    
    @property
    def half_extension_time(self):
        return self.extension_time / 2.0
    
    @property
    def extend_active(self):
        return self.state == PhaseState.EXTEND
    
    @property
    def flash_mode(self) -> FlashMode:
        return self._flash_mode
    
    @property
    def active(self) -> bool:
        return self.state != PhaseState.STOP
    
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
    
    def _validate_timing(self):
        if self.timing is None:
            raise TypeError('Timing map cannot be None')
        keys = self.timing.keys()
        if len(keys) != len(PHASE_TIMED_STATES):
            raise RuntimeError('Timing map mismatched size')
        elif PhaseState.STOP in keys:
            raise KeyError('STOP cannot be in timing map')
    
    def __init__(self,
                 id_: int,
                 flasher: logic.Flasher,
                 timing: Dict[PhaseState, float],
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 recall: bool,
                 walk_rest: bool,
                 flash_mode: FlashMode = FlashMode.RED,
                 fya_phase: Optional['Phase'] = None):
        super().__init__(id_)
        self._ped_service: bool = False
        self._fya_service: bool = False
        self.extend_inhibit = False
        self.recall = recall
        self.conflicting_demand = False
        self.fya_enabled = False
        self.walk_rest = walk_rest
        self.stats = Counter({
            'detections'     : 0,
            'vehicle_service': 0,
            'ped_service'    : 0
        })
        self._flasher = flasher
        self.timing = timing
        self._state: PhaseState = PhaseState.STOP
        self._validate_timing()
        self._flash_mode = flash_mode
        self._timer: logic.Timer = logic.Timer(0, step=constants.TIME_INCREMENT)
        self._detection_timer: logic.Timer = logic.Timer(0, step=constants.TIME_INCREMENT)
        self._service_remaining_minimum = 0.0
        self._vls = veh_ls
        self._pls = ped_ls
        self.fya_phase = fya_phase
        self.setpoint = round(self.timing.get(PhaseState.MIN_STOP, 0.0), 1)
    
    def getGoTime(self, ped_service: bool):
        if self.secondary:
            pclr = 0.0
            walk = 0.0
        else:
            pclr = self.timing.get(PhaseState.PCLR, 0.0)
            walk = self.timing.get(PhaseState.WALK, 0.0)
        
        go = self.timing.get(PhaseState.GO, 0.0)
        if ped_service:
            go = max(0.0, go - (pclr + walk))
        return go
    
    def getServiceDurationMinimum(self, ped_service: bool):
        estimation = 0.0
        for state in PHASE_DURATION_ESTIMATION_STATES:
            if not ped_service and state in PHASE_PED_STATES:
                continue
            
            if state == PhaseState.GO:
                time = self.getGoTime(ped_service)
            else:
                time = self.timing.get(state, 0.0)
            
            if state == PhaseState.EXTEND:
                time /= 2
            
            if state == PhaseState.WALK:
                time += self._flasher.delay
            
            estimation += time
        return estimation
    
    def getServiceRemainingMinimum(self):
        estimation = 0.0
        for state in PHASE_REMAINING_ESTIMATION_STATES:
            if state > self.state:
                break
            
            if ((state == PhaseState.FYA and self.fya_phase is None) or
                (state in PHASE_FYA_GO_STATES and self._fya_service) or
                (state in PHASE_PED_STATES and (self.secondary or not self.ped_service)) or
                (state == PhaseState.EXTEND and self.extend_inhibit)):
                continue
            
            if state == PhaseState.GO:
                time = self.getGoTime(self.ped_service)
            else:
                time = self.timing.get(state, 0.0)
            
            if state == PhaseState.EXTEND:
                time /= 2
            
            if state == PhaseState.WALK:
                time += max(0.0, self._flasher.delay - self._flasher.elapsed)
            
            if state == self.state:
                if self._timer.elapsed < self.setpoint:
                    time = self.setpoint - self._timer.elapsed
                else:
                    time = 0.0
            
            estimation += time
        return round(estimation, 1)
    
    def getNextState(self, ped_service: bool, activation: bool = False) -> PhaseState:
        if self.state == PhaseState.STOP:
            if not self.secondary and ped_service:
                next_state = PhaseState.WALK
            else:
                next_state = PhaseState.GO
        elif self.state == PhaseState.RCLR:
            next_state = PhaseState.STOP
        elif self.state == PhaseState.CAUTION:
            next_state = PhaseState.RCLR
        elif self.state == PhaseState.EXTEND:
            next_state = PhaseState.CAUTION
        elif self.state == PhaseState.GO:
            if self.extend_inhibit:
                next_state = PhaseState.CAUTION
            else:
                next_state = PhaseState.EXTEND
        elif self.state == PhaseState.FYA:
            if activation and not ped_service:
                next_state = PhaseState.GO
            else:
                next_state = PhaseState.CAUTION
        elif self.state == PhaseState.PCLR:
            next_state = PhaseState.GO
        elif self.state == PhaseState.WALK:
            next_state = PhaseState.PCLR
        else:
            raise NotImplementedError()
        
        if next_state == PhaseState.GO:
            go_time = self.getGoTime(ped_service)
            if go_time < TIME_INCREMENT:
                next_state = PhaseState.EXTEND
        
        if next_state == PhaseState.EXTEND:
            if not self.extend_enabled:
                next_state = PhaseState.CAUTION
        
        return next_state
    
    def detect(self):
        self._detection_timer.reset()
        
        if self.extend_active:
            self._timer.reset()
    
    def activate(self, ped_service: bool = False):
        if self.active:
            raise RuntimeError('Cannot activate active phase')
        
        changed = self.change(activation=True, ped_service=ped_service)
        assert changed
    
    def update_field(self):
        pa = False
        pc = False
        fya = False
        
        if self.state in PHASE_STOP_STATES:
            self._vls.a = True
            self._vls.b = False
            self._vls.c = False
            pa = True
            pc = False
        elif self.state == PhaseState.CAUTION:
            self._vls.a = False
            self._vls.b = True
            self._vls.c = False
            pa = True
            pc = False
        elif self.state in PHASE_FYA_GO_STATES:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = True
            pc = False
        elif self.state == PhaseState.FYA:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = False
            fya = self._flasher.bit
        elif self.state == PhaseState.PCLR:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = self._flasher.bit
            pc = False
        elif self.state == PhaseState.WALK:
            self._vls.a = False
            self._vls.b = False
            self._vls.c = True
            pa = False
            pc = True
        
        if self.fya_phase is not None:
            self.fya_phase.ped_ls.b = fya
        
        if self._pls is not None:
            self._pls.a = pa
            self._pls.c = pc
    
    def change(self,
               force_state: Optional[PhaseState] = None,
               activation: bool = False,
               ped_service: bool = False) -> bool:
        if force_state is not None:
            if force_state == PhaseState.FYA:
                assert self.fya_phase is not None
            next_state = force_state
        else:
            next_state = self.getNextState(ped_service, activation=activation)
        
        if next_state != self.state:
            if self.state == PhaseState.WALK and not self._flasher.bit:
                return False
            
            self._timer.reset()
            
            if next_state == PhaseState.STOP:
                self.setpoint = round(self.timing.get(PhaseState.MIN_STOP, 0.0), 1)
                self._ped_service = False
                self._fya_service = False
                self.extend_inhibit = False
            elif next_state in PHASE_TIMED_STATES:
                if next_state == PhaseState.GO:
                    setpoint = self.getGoTime(self.ped_service)
                    self._detection_timer.reset()
                    self.stats['vehicle_service'] += 1
                else:
                    setpoint = self.timing.get(next_state, 0.0)
                    
                    if next_state == PhaseState.WALK:
                        self._ped_service = True
                        self.stats['ped_service'] += 1
                    elif next_state == PhaseState.FYA:
                        self._fya_service = True
                
                self.setpoint = round(setpoint, 1)
            
            self._state = next_state
            return True
        else:
            return False
    
    def tick(self) -> bool:
        self.update_field()
        changed = False
        
        self._detection_timer.poll(True)
        
        if self._timer.poll(True):
            if self.active and self.state in PHASE_TIMED_STATES:
                if (self.state in PHASE_RIGID_STATES or
                    (self.state == PhaseState.WALK and not self.walk_rest)):
                    changed = self.change()
                elif self.state != PhaseState.FYA and self.conflicting_demand:
                    if self.state == PhaseState.WALK:
                        walk_time = self.timing[PhaseState.WALK]
                        self.extend_inhibit = self.elapsed - walk_time > self.half_extension_time
                        if self.extend_inhibit:
                            logger.debug('{} extend inhibited', self.getTag())
                    
                    changed = self.change()
        else:
            if self.extend_active:
                self.setpoint -= constants.TIME_INCREMENT
        
        if self.state in PHASE_GO_STATES:
            if self._detection_timer.elapsed > self.extension_time:
                self.extend_inhibit = True
            
            if self.elapsed > self.timing[PhaseState.MAX_GO]:
                if self.conflicting_demand:
                    changed = self.change()
        
        if self.state == PhaseState.FYA:
            if (
                self._timer.elapsed > self.timing[PhaseState.FYA] and
                (self.fya_phase.state <= PhaseState.CAUTION or not self.fya_enabled)
            ):
                changed = self.change()
        elif (
            self.fya_enabled and
            self.fya_phase is not None and
            self.state == PhaseState.STOP and
            self._timer.elapsed > self.timing[PhaseState.FYA_DELAY]
        ):
            if (
                self.fya_phase.state in PHASE_FYA_GO_STATES and
                self.fya_phase.elapsed > self.timing[PhaseState.FYA_DELAY]
            ):
                changed = self.change(force_state=PhaseState.FYA)
        
        self._service_remaining_minimum = self.getServiceRemainingMinimum()
        
        return changed
    
    def __repr__(self):
        return (f'<{self.getTag()} {self.state.name} '
                f'{round(self.elapsed, 1)} of {round(self.setpoint, 1)}>')


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
        return csl([str(phase.id) for phase in self.phases], separator=',')
    
    def __init__(self, phases: List[Phase], ped_service: bool = False):
        self.phases = phases.copy()
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
