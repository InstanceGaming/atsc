from abc import abstractmethod, ABC
from typing import List, Iterable


class IController(ABC):
    
    @property
    @abstractmethod
    def max_phases(self):
        pass
    
    @property
    @abstractmethod
    def max_load_switches(self):
        pass
    
    @property
    @abstractmethod
    def time_increment(self):
        pass
    
    @property
    @abstractmethod
    def barrier_manager(self):
        pass
    
    @property
    @abstractmethod
    def flasher(self) -> bool:
        pass
    
    @property
    @abstractmethod
    def phases(self) -> list:
        pass
    
    @property
    @abstractmethod
    def red_clearance(self) -> float:
        pass
    
    @abstractmethod
    def hasConflictingDemand(self, phase) -> bool:
        pass
