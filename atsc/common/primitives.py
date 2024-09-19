#  Copyright 2024 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
from typing import Dict, List, Self, Type, Union, TypeVar, Optional
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
    global_objects_mapping: Dict[int, Self] = {}
    
    @property
    def id(self) -> int:
        return self._id
    
    def __init__(self, id_: int):
        if id_ in self.global_objects_mapping.keys():
            raise ValueError(f'attempt to redefine reserved identifier {id_}')
        else:
            self._id = id_
            self.global_objects_mapping.update({id_: self})
    
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


R_T = TypeVar('R_T', bound=Identifiable)


def ref(r: Optional[Union[int, Identifiable]],
        cls: Type[R_T]) -> Optional[R_T]:
    if r is None:
        return None
    if isinstance(r, Identifiable):
        return r
    elif isinstance(r, int):
        for k, v in Identifiable.global_objects_mapping.items():
            if k == r:
                if type(v) != cls:
                    raise TypeError(f'type of {r} was not {cls.__name__}')
                return v
        raise LookupError(f'failed to find reference {r} (type {cls.__name__})')
    else:
        raise TypeError()


class Tickable:
    
    def __init__(self):
        self.tickables: List[Tickable] = []
    
    def tick(self, context: Context):
        for tickable in self.tickables:
            tickable.tick(context)


class Timer:
    
    @property
    def value(self):
        return self._value
    
    def __init__(self):
        self._value = 0.0
    
    def poll(self, context: Context, trigger: float) -> bool:
        rv = self._value >= trigger
        self._value += context.delay
        return rv
    
    def reset(self):
        self._value = 0.0

    def __repr__(self):
        return f'<Timer {self._value:01.1f}>'


class Flasher:
    
    def __init__(self):
        self._timer = Timer()
    
    def poll(self, context: Context, fpm: float):
        fps = 60.0 / fpm
        delay = fps / 2
        t = self._timer.poll(context, delay)
        if t:
            self._timer.reset()
        return t
