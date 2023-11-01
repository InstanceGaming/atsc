from dataclasses import dataclass


@dataclass()
class Context:
    rate: float
    scale: float
    
    @property
    def delay(self):
        return self.scale / self.rate
