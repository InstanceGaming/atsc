import enum
import random
from typing import List
from atsc.common.primitives import Timer, Identifiable
from atsc.common.structs import Context
from atsc.controller.models import Signal


class ApproachState(enum.Enum):
    IDLE = enum.auto()
    PRESENCE = enum.auto()
    GAP = enum.auto()


class ApproachSimulator(Identifiable):
    
    @property
    def elapsed(self):
        return self.timer.value
    
    def __init__(self,
                 id_: int,
                 rng: random.Random,
                 signal: Signal,
                 enabled: bool = True,
                 permissive: bool = False):
        super().__init__(id_)
        self.rng = rng
        self.signal = signal
        self.enabled = enabled
        self.permissive = permissive
        self.state = ApproachState.IDLE
        self.trigger = self.rng.randrange(1, 60)
        self.timer = Timer()
    
    def tick(self, context: Context):
        match self.state:
            case ApproachState.PRESENCE:
                if not self.signal.active:
                    if not self.permissive or self.permissive and round(self.rng.random()):
                        self.timer.reset()
        
        if self.timer.poll(context, self.trigger):
            self.timer.reset()
            match self.state:
                case ApproachState.PRESENCE:
                    self.state = ApproachState.GAP
                    self.trigger = self.rng.randrange(1, 4)
                case ApproachState.GAP:
                    self.trigger /= 2
                    
                    if self.trigger > (context.delay * 2):
                        self.state = ApproachState.PRESENCE
                        self.trigger = self.rng.randrange(1, 6)
                    else:
                        self.state = ApproachState.IDLE
                        self.trigger = self.rng.randrange(1, 60)
                case ApproachState.IDLE:
                    self.state = ApproachState.PRESENCE
                    self.trigger = self.rng.randrange(3, 6)
        
        self.signal.presence = self.state == ApproachState.PRESENCE
    
    def __repr__(self):
        return f'<ApproachSimulator {self.state.name} {self.elapsed:.1f} of {self.trigger:.1f}>'


class IntersectionSimulator:
    
    def __init__(self, signals: List[Signal], seed=None):
        self.rng = random.Random(seed)
        self.signals = signals
        self.approaches = []
        
        for i in range(len(signals)):
            signal = signals[i]
            permissive = signal.id % 2 == 0
            self.approaches.append(ApproachSimulator(i + 7001,
                                                     self.rng,
                                                     signal,
                                                     permissive=permissive))
    
    def tick(self, context: Context):
        for approach in self.approaches:
            approach.tick(context)
