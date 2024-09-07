from dataclasses import dataclass
from typing import Optional


@dataclass()
class IntervalTiming:
    minimum: float
    maximum: Optional[float] = None


@dataclass()
class IntervalConfig:
    rest: bool = False
    reduce: bool = False
    flashing: bool = False
