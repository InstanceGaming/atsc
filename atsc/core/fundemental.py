from abc import ABC, abstractmethod
from typing import Any, Iterable


class Identifiable:

    @property
    def id(self) -> int:
        return self._id

    def __init__(self, id_: int):
        self._id = id_

    def __hash__(self) -> int:
        return self._id

    def __eq__(self, other) -> bool:
        if other is None:
            return False
        return self._id == other.id

    def __lt__(self, other) -> bool:
        return self._id < other.id

    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'

    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class IdentifiedCollection(Identifiable, list):

    def __init__(self, id_: int, initial=None):
        super().__init__(id_)
        if isinstance(initial, Iterable):
            self.extend(initial)


class Tickable(ABC):

    @property
    def tick_size(self):
        return self._tick_size

    def __init__(self, tick_size: float):
        self._tick_size = tick_size

    @abstractmethod
    def tick(self, *args, **kwargs) -> Any:
        pass
