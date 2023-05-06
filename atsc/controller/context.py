from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    tick_delay: float
    tps: int
