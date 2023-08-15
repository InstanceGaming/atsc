import asyncio
from abc import ABC, abstractmethod
from asyncio import Event
from typing import Set, TypeVar, Optional, Union, Type, SupportsFloat
from atsc.utils import millis


class StopwatchEvent(Event):

    @property
    def elapsed(self):
        return millis() - self._marker

    def __init__(self):
        Event.__init__(self)
        self._marker = 0

    def set(self):
        Event.set(self)
        self._marker = millis()

    def clear(self) -> None:
        Event.clear(self)
        self._marker = millis()


class Runnable(ABC):
    
    @abstractmethod
    async def run(self):
        pass


class Identifiable:
    _global_identifiers: Set[int] = set()
    
    @property
    def id(self) -> int:
        return self._id
    
    def __init__(self, id_: int):
        if id_ in self._global_identifiers:
            raise ValueError('attempt to redefine reserved ID')
        self._id = id_
    
    def __hash__(self) -> int:
        return self._id
    
    def __eq__(self, other) -> bool:
        if other is None:
            return False
        return self._id == other.id
    
    def __lt__(self, other) -> bool:
        if isinstance(other, Referencable):
            return self._id < other.id
        else:
            raise TypeError()
    
    def getTag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'
    
    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class Referencable(Identifiable):
    _global_refs = {}

    def __init__(self, id_: int):
        super().__init__(id_)
        self._global_refs.update({id_: self})


R_T = TypeVar('R_T', bound=Referencable)


def ref(r: Optional[Union[int, Referencable]], cls: Type[R_T]) -> Optional[R_T]:
    if r is None:
        return None
    if isinstance(r, Referencable):
        return r
    elif isinstance(r, int):
        for k, v in Referencable._global_refs.items():
            if k == r:
                if not isinstance(v, cls):
                    raise TypeError(f'type of {r} was not {cls.__name__}')
                return v
        raise LookupError(f'failed to find reference {r} (type {cls.__name__})')
    else:
        raise TypeError()
