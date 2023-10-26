import asyncio
from dataclasses import dataclass
from asyncio import Event
from typing import Set, TypeVar, Optional, Union, Type, List
from jacob.datetime.timing import millis


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

    def clear(self):
        Event.clear(self)
        self._marker = millis()
        

@dataclass()
class Context:
    rate: float
    scale: float
    
    @property
    def delay(self):
        return self.scale / self.rate


class Updatable:
    
    def __init__(self):
        self.children: List[Updatable] = []

    async def update(self, context: Context):
        await asyncio.gather(*[child.update(context) for child in self.children])


class Identifiable:
    _global_identifiers: Set[int] = set()
    
    @property
    def id(self) -> int:
        return self._id
    
    def __init__(self, id_: int):
        if id_ in self._global_identifiers:
            raise ValueError(f'attempt to redefine reserved identifier {id_}')
        self._id = id_
    
    def __hash__(self) -> int:
        return self._id
    
    def __eq__(self, other) -> bool:
        if isinstance(other, Identifiable):
            return self._id == other.id
        else:
            raise TypeError()
    
    def __lt__(self, other) -> bool:
        if isinstance(other, Referencable):
            return self._id < other.id
        else:
            raise TypeError()
    
    def get_tag(self):
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
    assert isinstance(cls, type(Referencable))
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
        raise LookupError(f'failed to find reference {r} (type {cls.__name__}), is it initialized?')
    else:
        raise TypeError()
