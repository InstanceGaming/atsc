import asyncio
from typing import Set, List
from asyncio import Event
from atsc.common.structs import Context
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
        if isinstance(other, Identifiable):
            return self._id < other.id
        else:
            raise TypeError()
    
    def get_tag(self):
        return f'{type(self).__name__[:2].upper()}{self.id:02d}'
    
    def __repr__(self):
        return f'<{type(self).__name__} #{self.id}>'


class Updatable:
    
    def __init__(self):
        self.children: List[Updatable] = []
    
    async def update(self, context: Context):
        await asyncio.gather(*[child.update(context) for child in self.children])


class Timer:
    
    @property
    def value(self):
        return self._value
    
    def __init__(self):
        self._value = 0.0
    
    def poll(self, context: Context, trigger: float) -> bool:
        if self._value >= trigger:
            self.reset()
            return True
        else:
            self._value += context.delay
            return False
    
    def reset(self):
        self._value = 0.0
