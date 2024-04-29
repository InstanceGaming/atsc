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
from typing import List, Optional, Iterable
from atsc.logic import Timer, Flasher, EdgeTrigger
from jacob.text import csl
from collections import Counter
from jacob.enumerations import text_to_enum


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


class PhaseInterval(IntEnum):
    STOP = 0
    SCLR = 4
    CAUTION = 6
    GAP = 8
    GO = 10
    PCLR = 12
    WALK = 14


PHASE_FIXED_INTERVALS = (PhaseInterval.SCLR, PhaseInterval.CAUTION, PhaseInterval.PCLR)

PHASE_TIMED_INTERVALS = (PhaseInterval.SCLR,
                         PhaseInterval.CAUTION,
                         PhaseInterval.GAP,
                         PhaseInterval.GO,
                         PhaseInterval.PCLR,
                         PhaseInterval.WALK)

PHASE_GO_INTERVALS = (PhaseInterval.GAP,
                      PhaseInterval.GO,
                      PhaseInterval.PCLR,
                      PhaseInterval.WALK)


class PhaseTiming:
    
    @property
    def service_clear(self):
        return self._service_clear
    
    @property
    def service_min(self):
        return self._service_min
    
    @property
    def service_max(self):
        return self._service_max
    
    @property
    def caution(self):
        return self._caution
    
    @property
    def gap(self):
        return self._gap
    
    @property
    def gap_reduce(self):
        return self._gap_reduce
    
    @property
    def gap_min(self):
        return self._gap_min
    
    @property
    def gap_max(self):
        return self._gap_max
    
    @property
    def walk_min(self):
        return self._walk_min
    
    @property
    def walk_max(self):
        return self._walk_max
    
    @property
    def ped_clear(self):
        return self._ped_clear
    
    @property
    def service_rest(self) -> float:
        return not self.service_max
    
    @property
    def gap_rest(self) -> float:
        return not self.gap_max
    
    @property
    def walk_rest(self) -> float:
        return not self.walk_max
    
    @property
    def ped_service(self) -> float:
        if self.walk_min:
            if self.walk_rest:
                return self.walk_min + self.ped_clear
            else:
                return self.walk_max + self.ped_clear
        else:
            return 0.0
        
    @property
    def fixed_interval_total(self):
        return self.service_clear + self.caution + self.ped_clear
        
    @property
    def service_limit(self) -> float:
        if self.service_rest:
            return 0.0
        
        return self.service_max - self.fixed_interval_total
    
    def __init__(self,
                 service_clear: float = 0.0,
                 service_min: float = 1.0,
                 service_max: float = 0.0,
                 caution: float = 0.0,
                 gap: float = 0.0,
                 gap_reduce: float = constants.TIME_BASE,
                 gap_min: float = 0.0,
                 gap_max: float = 0.0,
                 walk_min: float = 0.0,
                 walk_max: float = 0.0,
                 ped_clear: float = 0.0):
        """
        Collection of timing values needed for a Phase with validation logic.
        All timing values must be positive or zero.
        
        :param service_clear: Clearance interval immediately after stop (0.0+)
        :param service_min: Minimum movement time overall (1.0+)
        :param service_max: Maximum movement time overall (0 to disable)
        :param caution: Fixed caution interval time (0 to skip)
        :param gap: Time between vehicles (0 to skip)
        :param gap_reduce: Amount to subtract from gap setpoint every tick (0.0+)
        :param gap_min: Lowest gap time (0 to ignore)
        :param gap_max: Maximum gap interval (0 to disable)
        :param walk_min: Minimum walk time for ped service (0 to disable ped service always)
        :param walk_max: Enforce fixed walk interval (0 to disable, 1.0+)
        :param ped_clear: Ped clearance interval (ignored when walk_min 0, 1.0+)
        """
        self._service_clear = service_clear
        self._service_min = service_min
        self._service_max = service_max
        self._caution = caution
        self._gap = gap
        self._gap_reduce = gap_reduce
        self._gap_min = gap_min
        self._gap_max = gap_max
        self._walk_min = walk_min
        self._walk_max = walk_max
        self._ped_clear = ped_clear
        
        if any([v < 0.0 for v in (
            service_clear,
            service_min,
            service_max,
            caution,
            gap,
            gap_reduce,
            gap_min,
            gap_max,
            walk_min,
            walk_max,
            ped_clear
        )]):
            raise ValueError('phase timing value cannot be negative')
        
        if self.service_min < 1.0:
            raise ValueError('service_min must be at least 1.0')
        
        if 0.0 < self.service_max < self.service_min:
            raise ValueError('service_max less than or equal to service_min')
        
        if 0.0 < self.caution < 1.0:
            raise ValueError('caution must be at least 1.0')
        
        if 0.0 < gap_max < gap_min:
            raise ValueError('gap_max less than gap_min')
        
        if 0.0 < gap_reduce > gap:
            raise ValueError('gap_reduce must be less than or equal to gap')
        
        if gap > gap_max:
            raise ValueError('gap must be less than or equal to gap_max')
        
        if 0.0 < gap < gap_min:
            raise ValueError('gap must be at least gap_min')
        
        if 0.0 < walk_min < 1.0:
            raise ValueError('walk_min must be at least 1.0')
        
        if 0.0 < walk_max < walk_min:
            raise ValueError('walk_max must be less than or equal to walk_min')

        if walk_min and ped_clear < 1.0:
            raise ValueError('ped_clear must be at least 1.0 (walk_min > 0.0)')
        
        if self._service_max and self.service_limit < 1.0:
            raise ValueError('service_limit less than 1.0')
        
    def for_interval(self, interval: PhaseInterval) -> float:
        match interval:
            case PhaseInterval.SCLR:
                return self.service_clear
            case PhaseInterval.CAUTION:
                return self.caution
            case PhaseInterval.GAP:
                return self.gap
            case PhaseInterval.GO:
                return self.service_min
            case PhaseInterval.PCLR:
                return self.ped_clear
            case PhaseInterval.WALK:
                return self.walk_min
        raise NotImplementedError()


class Phase(IdentifiableBase):
    
    @property
    def timing(self):
        return self._timing
    
    @property
    def flash_mode(self) -> FlashMode:
        return self._flash_mode
    
    @property
    def active(self) -> bool:
        return self._interval != PhaseInterval.STOP
    
    @property
    def interval(self) -> PhaseInterval:
        return self._interval
    
    @property
    def previous_intervals(self):
        return self._previous_intervals
    
    @property
    def interval_setpoint(self) -> float:
        return self._interval_timer.trigger
    
    @interval_setpoint.setter
    def interval_setpoint(self, value):
        self._interval_timer.trigger = value if value > 0.0 else 0.0
    
    @property
    def interval_elapsed(self):
        return self._interval_timer.elapsed
    
    @property
    def service_setpoint(self) -> float:
        return self._interval_timer.trigger
    
    @service_setpoint.setter
    def service_setpoint(self, value):
        self._service_timer.trigger = value if value > 0.0 else 0.0
    
    @property
    def service_elapsed(self):
        return self._service_timer.elapsed
    
    @property
    def ped_service(self):
        return self._interval == PhaseInterval.WALK or PhaseInterval.WALK in self._previous_intervals
    
    @ped_service.setter
    def ped_service(self, value):
        self._ped_service_request = value
    
    @property
    def service_override(self):
        return self._service_override
    
    @service_override.setter
    def service_override(self, value):
        if value < 0.0:
            raise ValueError('go override must be positive or zero')
        
        self._service_override = min(value, self._timing.service_max)
    
    @property
    def veh_ls(self) -> LoadSwitch:
        return self._vls
    
    @property
    def ped_ls(self) -> Optional[LoadSwitch]:
        return self._pls
    
    def __init__(self,
                 id_: int,
                 timing: PhaseTiming,
                 veh_ls: LoadSwitch,
                 ped_ls: Optional[LoadSwitch],
                 flash_mode: FlashMode = FlashMode.RED):
        super().__init__(id_)
        self._timing = timing
        self._flasher = Flasher()
        self._flash_mode = flash_mode
        self._ped_service_request = False
        
        # override the default plan service time
        self._service_override: float = 0.0
        self._interval: PhaseInterval = PhaseInterval.STOP
        # window of PhaseInterval's, the width of len(PhaseIntervals) - 1
        self._previous_intervals: List[PhaseInterval] = []
        
        # stores service timer elapsed at start of gap interval
        # used in calculating overall gap time elapsed
        self._gap_marker: Optional[float] = None
        
        self._interval_timer = Timer()
        self._service_timer = Timer()
        self._vls = veh_ls
        self._pls = ped_ls
        self.stats = Counter({
            'detections'     : 0,
            'vehicle_service': 0,
            'ped_service'    : 0
        })
        
        self.rest_inhibit = False
    
    def get_recycle_interval(self, ped_service: bool) -> PhaseInterval:
        if self.interval in (PhaseInterval.WALK, PhaseInterval.GO, PhaseInterval.GAP):
            if ped_service:
                return PhaseInterval.WALK
            else:
                return PhaseInterval.GO
        else:
            raise NotImplementedError()
    
    def get_next_interval(self, ped_service: bool, expedite: bool) -> PhaseInterval:
        if self.interval == PhaseInterval.STOP:
            if self.ped_ls is not None and ped_service and not expedite:
                return PhaseInterval.WALK
            else:
                return PhaseInterval.GO
        elif self.interval == PhaseInterval.SCLR:
            return PhaseInterval.STOP
        elif self.interval == PhaseInterval.CAUTION:
            return PhaseInterval.SCLR
        elif self.interval == PhaseInterval.GAP:
            return PhaseInterval.CAUTION
        elif self.interval == PhaseInterval.GO:
            if self.timing.gap and not expedite:
                return PhaseInterval.GAP
            else:
                return PhaseInterval.CAUTION
        elif self.interval == PhaseInterval.PCLR:
            if expedite:
                return PhaseInterval.CAUTION
            else:
                return PhaseInterval.GO
        elif self.interval == PhaseInterval.WALK:
            if expedite or not self.timing.ped_clear:
                return PhaseInterval.CAUTION
            else:
                return PhaseInterval.PCLR
        else:
            raise NotImplementedError()
    
    def get_setpoint(self, interval: PhaseInterval) -> float:
        default = self.timing.for_interval(interval)
        
        if interval == PhaseInterval.GO:
            rv = max(default - self._service_timer.elapsed, 0.0)
        else:
            rv = default
        
        return round(rv, 1)
    
    def estimate_remaining(self) -> Optional[float]:
        if self.interval == PhaseInterval.STOP:
            return None
        
        setpoints = constants.TIME_BASE
        for interval in PHASE_TIMED_INTERVALS:
            if self.interval.value >= interval.value:
                setpoints += self.get_setpoint(interval)
            else:
                break
        
        return round(setpoints - self.interval_elapsed, 1)
    
    def gap_reset(self):
        if self.interval == PhaseInterval.GAP:
            self._interval_timer.reset()
    
    def activate(self):
        interval = None
        
        if self.active:
            if self.interval in PHASE_FIXED_INTERVALS:
                raise RuntimeError('Cannot activate active phase during rigidly-timed interval')
            
            interval = self.get_recycle_interval(self.ped_service)
        
        changed = self.change(interval=interval)
        assert changed
    
    def update_field(self):
        pa = False
        pb = False
        pc = False
        
        match self.interval:
            case PhaseInterval.STOP | PhaseInterval.SCLR:
                self._vls.a = True
                self._vls.b = False
                self._vls.c = False
                pa = True
                pc = False
            case PhaseInterval.CAUTION:
                self._vls.a = False
                self._vls.b = True
                self._vls.c = False
                pa = True
                pc = False
            case PhaseInterval.GO | PhaseInterval.GAP:
                self._vls.a = False
                self._vls.b = False
                self._vls.c = True
                pa = True
                pc = False
            case PhaseInterval.PCLR:
                self._vls.a = False
                self._vls.b = False
                self._vls.c = True
                pa = self._flasher.bit
                pc = False
            case PhaseInterval.WALK:
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
               interval: Optional[PhaseInterval] = None,
               expedite: bool = False) -> bool:
        # cannot do or shorthand as STOP is cast to zero
        if interval is None:
            next_interval = self.get_next_interval(self._ped_service_request, expedite)
        else:
            next_interval = interval
        
        if next_interval != self._interval:
            self._interval_timer.reset()
            
            match next_interval:
                case PhaseInterval.STOP:
                    self._ped_service_request = False
                    self.service_override = 0.0
                case PhaseInterval.GO | PhaseInterval.WALK:
                    self._service_timer.reset()
                    self.service_setpoint = self.timing.service_max
                    if next_interval == PhaseInterval.WALK:
                        self.stats['ped_service'] += 1
                    self.stats['vehicle_service'] += 1
                case PhaseInterval.GAP:
                    self._gap_marker = self.service_elapsed
            
            if next_interval in PHASE_TIMED_INTERVALS:
                self.interval_setpoint = self.get_setpoint(next_interval)
            else:
                self.interval_setpoint = 0.0
            
            self._previous_intervals.insert(0, self.interval)
            if len(self._previous_intervals) > len(PHASE_TIMED_INTERVALS) - 1:
                self._previous_intervals.pop()
            
            self._interval = next_interval
            return True
        else:
            return False
    
    def tick(self) -> bool:
        self._flasher.poll(self._interval == PhaseInterval.PCLR)
        self.update_field()
        
        changed = False
        interval_limit = self._interval_timer.poll(True)
        service_limit = self._service_timer.poll(self.active)
        if self.active:
            match self.interval:
                case PhaseInterval.GAP:
                    if self.timing.gap:
                        if self.interval_setpoint >= (self.timing.gap_min + constants.TIME_BASE):
                            self.interval_setpoint -= self.timing.gap_reduce
                        gap_elapsed = self.service_elapsed - self._gap_marker
                        if self.timing.gap_max and gap_elapsed > self.timing.gap_max:
                            if self.rest_inhibit:
                                changed = self.change()
                    else:
                        changed = self.change()
                case PhaseInterval.WALK:
                    if self._timing.walk_max:
                        if self.interval_elapsed > self._timing.walk_max:
                            if self.rest_inhibit:
                                changed = self.change()
            
            if interval_limit:
                if self._service_timer.elapsed > self._timing.service_min:
                    if self.rest_inhibit or self._interval in PHASE_FIXED_INTERVALS:
                        changed = self.change()
                        
            if service_limit and not self._timing.service_rest:
                service_max = max(self._timing.fixed_interval_total, self._timing.service_limit)
                if self._service_timer.elapsed > service_max:
                    if self._interval not in PHASE_FIXED_INTERVALS:
                        changed = self.change(expedite=True)
        
        return changed
    
    def __repr__(self):
        return (f'<{self.get_tag()} {self.interval.name} '
                f'{round(self.interval_elapsed, 1)} of {round(self.interval_setpoint, 1)}>')


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
    
    def __init__(self, phases: Iterable[Phase], ped_service: bool = False):
        self.phases = sorted(phases)
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
    IGNORE = 10
    TIME_FREEZE = 11
    TECH_FLASH = 12
    RECALL = 20
    CALL_INHIBIT = 30
    EXTEND_INHIBIT = 31
    PED_CLEAR_INHIBIT = 32
    PREEMPTION = 40
    DARK = 50
    RANDOM_RECALL_INHIBIT = 51
    
    
class RecallType(IntEnum):
    MAINTAIN = 10
    LATCH = 20


class Input(IdentifiableBase):
    
    @property
    def high_elapsed(self):
        return self._high_timer.elapsed
    
    @property
    def low_elapsed(self):
        return self._low_timer.elapsed
    
    @property
    def recall_type(self):
        return self._recall_type
    
    @property
    def targets(self):
        return self._targets
    
    def __init__(self,
                 id_: int,
                 action: InputAction,
                 **kwargs):
        super().__init__(id_)
        self.action = action
        self.signal = False
        
        self._kwargs = kwargs
        self._recall_type = text_to_enum(RecallType, kwargs.get('recall-type'))
        self._targets = kwargs.get('targets')
        
        self._high_timer = Timer()
        self._low_timer = Timer()
        self._rising_edge = EdgeTrigger(True)
        self._falling_edge = EdgeTrigger(False)
    
    def poll(self):
        self._high_timer.poll(self.signal)
        self._low_timer.poll(not self.signal)
        rising = 1 if self._rising_edge.poll(self.signal) else 0
        falling = -1 if self._falling_edge.poll(self.signal) else 0
        
        return rising + falling
    
    def __repr__(self):
        elapsed = round(self.high_elapsed if self.signal else self.low_elapsed, 1)
        return f'<Input {self.id} {self.action.name} {self.signal} {elapsed}>'
