from abc import ABC, abstractmethod


class DelayProvider(ABC):
    
    @property
    @abstractmethod
    def delay(self) -> float:
        pass
