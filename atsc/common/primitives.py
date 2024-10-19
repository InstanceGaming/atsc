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
from typing import Dict, List, Self, Type, TypeVar, Optional
from asyncio import Event
from atsc.common.structs import Context
from atsc.common.constants import FLOAT_PRECISION_TIME, EdgeType
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
    
    def __init__(self, polarity: Optional[bool] = None):
        """
        Pulse when a logic signal has changed from one state to another.

        :param polarity: True for rising-edge, False for falling-edge, None for either.
        """
        super().__init__()
        self._polarity = polarity
        self._previous = polarity
    
    def poll(self, signal: bool) -> Optional[EdgeType]:
        """
        Check the signal state against the previous.

        :param signal: Logic signal to monitor for edge changes.
        :return: None if no change, EdgeType if changed.
        """
        edge = None
        if (self._polarity is None or self._polarity) and (not self._previous and signal):
            edge = EdgeType.RISING
        elif (self._polarity is None or not self._polarity) and (self._previous and not signal):
            edge = EdgeType.FALLING
        
        self._previous = signal
        return edge


class Timer:
    
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value):
        assert value is None or value >= 0.0
        self._value = value or 0.0
    
    def __init__(self, value=None):
        self._value = 0.0
        self._trigger_edge = EdgeTrigger(True)
        self.value = value
    
    def poll(self, context: Context, trigger: Optional[float] = None) -> bool:
        rv = False
        
        if context.timing:
            if trigger:
                rv = self._value > trigger - context.delay
        
        if not self._trigger_edge.poll(rv):
            self._value = round(self.value + context.delay, FLOAT_PRECISION_TIME)
        
        return rv
    
    def __repr__(self):
        return f'<Timer {self._value:01.1f}>'


class Flasher:
    
    @property
    def fpm(self):
        return self._fpm
    
    @property
    def fps(self):
        return 60.0 / self._fpm
    
    @property
    def delay(self):
        return self.fps / 2
    
    def __init__(self, fpm: float, initial: bool = True):
        self._fpm = fpm
        self._timer = Timer()
        self._initial = initial
        self._flasher = initial
    
    def __bool__(self):
        return self._flasher
    
    def reset(self):
        self._flasher = self._initial
    
    def poll(self, context: Context):
        rv = False
        if context.timing:
            rv = self._timer.poll(context, self.delay)
            if rv:
                self._timer.value = 0.0
                self._flasher = not self._flasher
        return rv
