from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional

from atsc.common.serializing import Deserializable


class Nameable(Deserializable):

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    def __init__(self, name: Optional[str] = None):
        self._name = name

    @staticmethod
    def deserialize(data, **kwargs):
        if isinstance(data, dict):
            name = data.get('name')
            return Nameable(name)
        else:
            raise TypeError()


class Identifiable(Deserializable):

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

    @staticmethod
    def deserialize(data, **kwargs):
        if isinstance(data, dict):
            id_ = data['id']
            return Identifiable(id_)
        else:
            raise TypeError()

    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class IdentifiedCollection(Identifiable, list):

    def __init__(self, id_: int, initial=None):
        super().__init__(id_)
        if isinstance(initial, Iterable):
            self.extend(initial)
        else:
            raise TypeError()

    @staticmethod
    def deserialize(data, **kwargs):
        if isinstance(data, dict):
            id_ = data['id']
            items = data['items']
            return IdentifiedCollection(id_, initial=items)
        else:
            raise TypeError()


class Tickable(ABC):

    @property
    def tick_delay(self):
        return self._tick_delay

    def __init__(self, tick_delay: float):
        self._tick_delay = tick_delay

    @abstractmethod
    def tick(self, *args, **kwargs) -> Any:
        pass
