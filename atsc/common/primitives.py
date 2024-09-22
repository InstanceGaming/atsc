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
from typing import Dict, List, Self, Type, TypeVar
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


def ref(cls: Type[R_T], o) -> R_T:
    if isinstance(o, Identifiable):
        return o
    elif isinstance(o, int):
        instance = Identifiable.global_objects_mapping.get(o)
        if instance is None:
            raise LookupError(f'failed to find reference {o} (type {cls.__name__})')
        if not isinstance(instance, cls):
            raise TypeError(f'type of {instance} was not {cls.__name__}')
        return instance
    else:
        raise TypeError()


def refs(cls: Type[R_T], *objects) -> List[R_T]:
    instances = []
    for o in objects:
        instances.append(ref(cls, o))
    return instances


class Tickable:
    
    def __init__(self):
        self.tickables: List[Tickable] = []
    
    def tick(self, context: Context):
        for tickable in self.tickables:
            tickable.tick(context)


class EdgeTrigger:

    @property
    def triggered(self):
        return self._triggered
    
    def __init__(self, polarity: bool):
        """
        Pulse when a logic signal has changed from one state to another.

        :param polarity: True for rising-edge, False for falling-edge.
        """
        super().__init__()
        self._polarity = polarity
        self._previous = polarity
        self._triggered = False
    
    def poll(self, signal: bool) -> bool:
        """
        Check the signal state against the previous.

        :param signal: Logic signal to monitor for edge changes.
        :return: True only if the edge has changed this poll.
        """
        if (self._polarity and (not self._previous and signal) or
            not self._polarity and (self._previous and not signal)):
            
            self._triggered = True
        else:
            self._triggered = False
        
        self._previous = signal
        return self._triggered


class MonitoredBit(Tickable):
    
    @property
    def rising(self):
        return self._rising.triggered
    
    @property
    def falling(self):
        return self._falling.triggered
    
    @property
    def edge(self):
        return self.rising or self.falling
    
    @property
    def bit(self):
        return self._bit
    
    @bit.setter
    def bit(self, v):
        self._bit = bool(v)
    
    def __init__(self, v):
        super().__init__()
        self._bit = bool(v)
        self._rising = EdgeTrigger(True)
        self._falling = EdgeTrigger(False)
    
    def tick(self, context: Context):
        self._rising.poll(self._bit)
        self._falling.poll(self._bit)
    
    def __eq__(self, other):
        return self._bit == bool(other)
    
    def __bool__(self):
        return self._bit


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
