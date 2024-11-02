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
import time
import asyncio
import blinker
from typing import Dict, List, Type, TypeVar, Callable, Optional, Coroutine
from atsc.common.constants import EdgeType
from atsc.controller.constants import POLL_RATE


class Identifiable:
    global_objects_mapping: Dict[int, 'Identifiable'] = {}
    
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


class EdgeTrigger:
    
    def __init__(self, polarity: Optional[bool] = None):
        """
        Pulse when a logic signal has changed from one state to another.

        :param polarity: True for rising-edge, False for falling-edge, None for either.
        """
        super().__init__()
        self._polarity = polarity
        self._previous = polarity
    
    def poll(self, v: bool) -> Optional[EdgeType]:
        """
        Check the signal state against the previous.

        :param v: Logic signal to monitor for edge changes.
        :return: None if no change, EdgeType if changed.
        """
        edge = None
        if (self._polarity is None or self._polarity) and (not self._previous and v):
            edge = EdgeType.RISING
        elif (self._polarity is None or not self._polarity) and (self._previous and not v):
            edge = EdgeType.FALLING
        
        self._previous = v
        return edge


class AsyncStopwatch:
    freeze_time = blinker.signal('atsc.controller.time_freeze')
    unfreeze_time = blinker.signal('atsc.controller.time_unfreeze')
    
    @property
    def paused(self):
        return self._paused
    
    @property
    def frozen(self):
        return self._frozen
    
    @property
    def marker(self):
        return self._marker
    
    @property
    def elapsed(self):
        if self.paused:
            return self._pause_placeholder_elapsed
        else:
            return max(0.0, time.monotonic() - self._pause_duration) - self.marker
        
    def __init__(self, paused: bool = False):
        self.freeze_time.connect(self._on_freeze)
        self.unfreeze_time.connect(self._on_unfreeze)
        
        self._marker: Optional[float] = time.monotonic()
        self._frozen = False
        self._paused = False
        self._pause_marker = None
        self._pause_duration = 0.0
        self._pause_placeholder_elapsed = None
        
        if paused:
            self.pause()
    
    def reset(self):
        self._pause_duration = 0.0
        self._marker = time.monotonic()
    
    def pause(self):
        if not self.paused:
            self._pause_marker = time.monotonic()
            self._pause_placeholder_elapsed = self._pause_marker - self._marker
            self._paused = True
    
    def resume(self):
        if self.paused and not self.frozen:
            self._pause_duration = time.monotonic() - self._pause_marker
            self._pause_placeholder_elapsed = None
            self._paused = False
    
    def _on_freeze(self, _):
        if not self.frozen:
            self.pause()
            self._frozen = True
    
    def _on_unfreeze(self, _):
        if self.frozen:
            self.resume()
            self._frozen = False
    
    def __repr__(self):
        return f'<Stopwatch {self.elapsed=:03.2f} {self.frozen=}>'


class AsyncTimer(AsyncStopwatch):
    
    @property
    def running(self):
        return self._task is not None
    
    @property
    def goal(self):
        return self._goal
    
    @property
    def remaining(self):
        if not self.goal:
            return None
        
        return -(self.goal - self.elapsed)
    
    def __init__(self,
                 goal: Optional[float] = None,
                 goal_handler: Coroutine | Callable | None = None,
                 repeat: bool = False,
                 paused: bool = False):
        super().__init__(paused=paused)
        self.started = blinker.Signal()
        self.reached_goal = blinker.Signal()
        self.canceled = blinker.Signal()
        self.repeat = repeat
        
        self._goal = None
        self._task: Optional[asyncio.Task] = None
        
        if goal_handler:
            self.reached_goal.connect(goal_handler, sender=self)
        
        if goal is not None:
            self.set(goal)
    
    def set(self, goal: float):
        self.reset()
        self._goal = goal
    
    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.wait())
        self.started.send(self)
        return self._task
    
    async def wait(self):
        self.reset()
        while True:
            if not self.frozen and self.goal > POLL_RATE:
                if self.elapsed > self.goal:
                    self.reached_goal.send(self)
                    if self.repeat:
                        self.reset()
                    else:
                        break
            await asyncio.sleep(POLL_RATE)
    
    def cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.reset()
            self.canceled.send(self)
            self._task = None
    
    def __repr__(self):
        return f'<Timer {self.goal=:03.2f} {self.elapsed=:03.2f} {self.frozen=}>'
