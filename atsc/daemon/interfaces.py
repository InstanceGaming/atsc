from abc import ABC, abstractmethod
from typing import Optional, Iterable

from atsc.core.fundemental import Nameable, Tickable
from atsc.core.models import ControlMode
from atsc.core.parallel import ThreadedTickable
from atsc.daemon.models import (RoadwayCollection,
                                ApproachCollection,
                                PhaseCollection,
                                InputCollection,
                                OutputCollection)


class IController(ThreadedTickable, Nameable, ABC):
    
    @property
    @abstractmethod
    def free(self) -> bool:
        pass

    @property
    @abstractmethod
    def idle(self) -> bool:
        pass

    @property
    @abstractmethod
    def saturated(self) -> bool:
        pass

    @property
    @abstractmethod
    def transferred(self) -> bool:
        pass

    @property
    @abstractmethod
    def avg_demand(self) -> float:
        pass

    @property
    @abstractmethod
    def peek_demand(self) -> float:
        pass

    @property
    @abstractmethod
    def runtime(self) -> int:
        pass

    @property
    @abstractmethod
    def control_time(self) -> int:
        pass

    @property
    @abstractmethod
    def transfer_count(self) -> int:
        pass

    @property
    @abstractmethod
    def inputs(self) -> InputCollection:
        pass

    @property
    @abstractmethod
    def outputs(self) -> OutputCollection:
        pass

    @property
    @abstractmethod
    def phases(self) -> PhaseCollection:
        pass
    
    @property
    @abstractmethod
    def approaches(self) -> ApproachCollection:
        pass

    @property
    @abstractmethod
    def roadways(self) -> RoadwayCollection:
        pass

    @property
    @abstractmethod
    def sequencer(self) -> 'ISequencer':
        pass

    @property
    @abstractmethod
    def previous_mode(self) -> Optional[ControlMode]:
        pass

    @property
    @abstractmethod
    def current_mode(self) -> ControlMode:
        pass

    @property
    @abstractmethod
    def next_mode(self) -> Optional[ControlMode]:
        pass


class ISequencer(Tickable, ABC):
    
    @property
    @abstractmethod
    def mode(self) -> ControlMode:
        pass

    @property
    @abstractmethod
    def next_modes(self) -> Iterable[ControlMode]:
        pass
    
    @property
    @abstractmethod
    def transitioning(self) -> bool:
        pass

    @abstractmethod
    def enter(self, prev: Optional[ControlMode]):
        pass

    @abstractmethod
    def leave(self, nxt: Optional[ControlMode]):
        pass
