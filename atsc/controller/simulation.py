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
import os
import enum
import random
import asyncio
import blinker
from loguru import logger
from typing import List
from atsc.controller.models import Signal
from atsc.controller.constants import POLL_RATE, SignalType, SignalState
from atsc.controller.primitives import AsyncTimer, Identifiable


def random_range_biased(start: int,
                        end: int,
                        bias: float,
                        rng: random.Random | None = None) -> int:
    """
    Generates a random number biased toward the higher or lower end of the range,
    using a normalized bias between 0.0 and 1.0.
    """
    assert 0.0 < bias < 1.0
    
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
    presence_simulation_enabled = blinker.signal('atsc.controller.presence_simulation.enabled')
    presence_simulation_disabled = blinker.signal('atsc.controller.presence_simulation.disabled')
    
    @property
    def elapsed(self):
        return self.timer.elapsed
    
    @property
    def is_thru(self):
        return not self.signal.id % 2
    
    @property
    def is_arterial(self):
        return self.signal.id in (501, 502, 505, 506, 509, 511)
    
    def __init__(self,
                 id_: int,
                 rng: random.Random,
                 signal: Signal):
        super().__init__(id_)
        self.presence_simulation_enabled.connect(self._on_enable)
        self.presence_simulation_disabled.connect(self._on_disable)
        self._enabled = False
        
        self.rng = rng
        self.signal = signal
        self.state = ApproachState.IDLE
        self.timer = AsyncTimer()
        self.cycle_count = 0
    
    def random_range_biased(self, start: int, end: int, bias: float):
        return random_range_biased(start, end, bias, rng=self.rng)
    
    def get_idle_time(self, first: bool = False):
        min_idle = 0 if first else 1
        match self.signal.type:
            case SignalType.VEHICLE:
                if self.is_arterial:
                    bias = 0.1 if self.is_thru else 0.9
                    return self.random_range_biased(min_idle, 60, bias)
                else:
                    bias = 0.5 if self.is_thru else 0.9
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
                elif self.signal.state == SignalState.FYA:
                    return self.random_range_biased(1, 150, 0.1)
                else:
                    if after_idle:
                        return self.random_range_biased(2, 15, 0.1)
                    else:
                        return self.random_range_biased(1, 5, 0.1)
            case SignalType.PEDESTRIAN:
                return 0.2
            case _:
                raise NotImplementedError()
    
    def get_gap_time(self):
        return self.random_range_biased(1, 5, 0.5)
    
    async def run(self):
        try:
            while True:
                if self._enabled:
                    self.state = ApproachState.IDLE
                    self.timer.set(self.get_idle_time(self.cycle_count == 0))
                    await self.timer.wait()
                    
                    if self._enabled:
                        platoon = True
                        after_idle = True
                        while platoon:
                            permissive = round(self.rng.random()) if self.is_thru else False
                            self.state = ApproachState.PRESENCE
                            self.timer.set(self.get_presence_time(after_idle))
                            self.signal.presence = True
                            await self.timer.wait()
                            
                            if self.signal.type == SignalType.VEHICLE:
                                while not self.signal.active:
                                    if permissive:
                                        await asyncio.sleep(self.random_range_biased(3, 15, 0.5))
                                    else:
                                        await asyncio.sleep(POLL_RATE)
                                
                                self.signal.presence = False
                                
                                self.state = ApproachState.GAP
                                self.timer.set(self.get_gap_time())
                                await self.timer.wait()
                                
                                if not self._enabled:
                                    break
                                
                                platoon = round(self.rng.random())
                            else:
                                self.signal.presence = False
                                platoon = False
                            
                            after_idle = False
                    
                    self.cycle_count += 1
                else:
                    await asyncio.sleep(POLL_RATE)
        except asyncio.CancelledError:
            pass
    
    def _on_enable(self, _):
        self._enabled = True
        
    def _on_disable(self, _):
        self._enabled = False
    
    def __repr__(self):
        return f'<ApproachSimulator {self.state.name} {self.elapsed:.1f}>'


class IntersectionSimulator:
    
    def __init__(self, signals: List[Signal], seed=None):
        if seed is None:
            seed = int.from_bytes(os.urandom(8), byteorder='big')
        
        logger.info('simulation seed = {}', seed)
        
        self.rng = random.Random(seed)
        self.signals = signals
        self.approaches = []
        
        for i in range(len(signals)):
            signal = signals[i]
            self.approaches.append(ApproachSimulator(i + 7001, self.rng, signal))
