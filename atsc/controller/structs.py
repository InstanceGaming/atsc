from dataclasses import dataclass
from typing import Optional


@dataclass()
class IntervalTiming:
    minimum: float
    maximum: Optional[float] = None
    rest: bool = False
    reduce: bool = False


@dataclass()
class IntervalConfig:
    flashing: bool = False
