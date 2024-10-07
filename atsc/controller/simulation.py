#  Copyright 2024 Jacob Jewett
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
import enum
import random
from typing import List
from atsc.common.structs import Context
from atsc.common.primitives import Timer, Identifiable
from atsc.controller.models import Signal
from atsc.controller.constants import SignalType, SignalState


def random_range_biased(start: int,
                        end: int,
                        bias: float,
                        rng: random.Random | None = None) -> int:
    """
    Generates a random number biased toward the higher or lower end of the range,
    using a normalized bias between 0.0 and 1.0.
    """
    assert 0.0 <= bias <= 1.0
    
    rng = rng or random.Random()
    
    random_float = rng.random()
    biased_float = random_float ** (1 - bias)
    result = start + int(biased_float * (end - start))
    
    return result


class ApproachState(enum.Enum):
    IDLE = enum.auto()
    PRESENCE = enum.auto()
    GAP = enum.auto()


class ApproachSimulator(Identifiable):
    
    @property
    def elapsed(self):
        return self.timer.value
    
    @property
    def is_left_turn(self):
        return self.signal.id % 2
    
    @property
    def is_arterial(self):
        return self.signal.id in (501, 502, 505, 506, 509, 511)
    
    def __init__(self,
                 id_: int,
                 rng: random.Random,
                 signal: Signal,
                 enabled: bool = True):
        super().__init__(id_)
        self.rng = rng
        self.signal = signal
        self.enabled = enabled
        self.turn_on_red = False
        self.state = ApproachState.IDLE
        self.trigger = self.get_idle_time(first=True)
        self.timer = Timer()
    
    def random_range_biased(self, start: int, end: int, bias: float):
        return random_range_biased(start, end, bias, rng=self.rng)
    
    def get_idle_time(self, first: bool = False):
        min_idle = 0 if first else 1
        match self.signal.type:
            case SignalType.VEHICLE:
                if self.is_arterial:
                    bias = 0.9 if self.is_left_turn else 0.1
                    return self.random_range_biased(min_idle, 60, bias)
                else:
                    bias = 0.9 if self.is_left_turn else 0.5
                    return self.random_range_biased(min_idle, 300, bias)
            case SignalType.PEDESTRIAN:
                bias = 0.5 if self.is_arterial else 0.9
                return self.random_range_biased(min_idle, 3600, bias)
            case _:
                raise NotImplementedError()
    
    def get_presence_time(self, after_idle: bool = False):
        match self.signal.type:
            case SignalType.VEHICLE:
                if self.signal.state in (SignalState.GO, SignalState.EXTEND):
                    return self.rng.randrange(1, 3)
                else:
                    if after_idle:
                        return self.random_range_biased(2, 15, 0.1)
                    else:
                        return self.random_range_biased(1, 5, 0.1)
            case SignalType.PEDESTRIAN:
                return 0.2
            case _:
                raise NotImplementedError()
    
    def change(self):
        self.timer.value = 0.0
        
        match self.state:
            case ApproachState.IDLE:
                match self.signal.type:
                    case SignalType.VEHICLE:
                        self.turn_on_red = round(self.rng.random()) if not self.is_left_turn else False
                    case _:
                        self.turn_on_red = False
                
                self.state = ApproachState.PRESENCE
                self.trigger = self.get_presence_time(after_idle=True)
            case ApproachState.PRESENCE:
                match self.signal.type:
                    case SignalType.VEHICLE:
                        self.state = ApproachState.GAP
                        self.trigger = self.random_range_biased(1, 5, 0.5)
                    case SignalType.PEDESTRIAN:
                        self.state = ApproachState.IDLE
                        self.trigger = self.get_idle_time()
                    case _:
                        raise NotImplementedError()
            case ApproachState.GAP:
                if round(self.rng.random()):
                    self.state = ApproachState.PRESENCE
                    self.trigger = self.get_presence_time()
                else:
                    self.state = ApproachState.IDLE
                    self.trigger = self.get_idle_time()
    
    def tick(self, context: Context):
        match self.signal.type:
            case SignalType.VEHICLE:
                if not self.signal.active and self.state == ApproachState.PRESENCE:
                    if self.turn_on_red:
                        self.trigger = self.random_range_biased(4, 15, 0.6)
                    else:
                        self.timer.value = 0.0
            case SignalType.PEDESTRIAN:
                if self.signal.active and self.state == ApproachState.IDLE:
                    self.timer.value = 0.0
        
        if self.timer.poll(context, self.trigger):
            self.change()
        
        self.signal.presence = self.state == ApproachState.PRESENCE
    
    def __repr__(self):
        return f'<ApproachSimulator {self.state.name} {self.elapsed:.1f} of {self.trigger:.1f}>'


class IntersectionSimulator:
    
    def __init__(self,
                 signals: List[Signal],
                 seed=None,
                 enabled=True):
        self.rng = random.Random(seed)
        self.signals = signals
        self.approaches = []
        self.enabled = enabled
        
        for i in range(len(signals)):
            signal = signals[i]
            self.approaches.append(ApproachSimulator(i + 7001,
                                                     self.rng,
                                                     signal,
                                                     enabled=enabled))
    
    def tick(self, context: Context):
        # ignore time freeze
        context = Context(context.rate, context.scale, timing=True)
        
        if self.enabled:
            for approach in self.approaches:
                approach.tick(context)
