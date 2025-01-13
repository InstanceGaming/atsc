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
from typing import Dict, List, Type, TypeVar, Callable, Optional, Coroutine, Union, Awaitable
from atsc.common.constants import EdgeType
from atsc.controller.constants import POLL_RATE


class Identifiable:
    objects: Dict[int, 'Identifiable'] = {}
    
    @property
    def id(self) -> int:
        return self._id
    
    def __init__(self, id_: int):
        if id_ in self.objects.keys():
            raise ValueError(f'attempt to redefine reserved identifier {id_}')
        else:
            self._id = id_
            self.objects.update({id_: self})
    
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
        instance = Identifiable.objects.get(o)
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
            rv = self._pause_placeholder_elapsed
        else:
            rv = max(0.0,
                     max(0.0,
                         time.monotonic() - self._pause_duration) - self.marker)
        if rv < 0.0:
            raise ValueError()
        return rv
    
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
            self._paused = True
            self._pause_marker = time.monotonic()
            self._pause_placeholder_elapsed = max(0.0, self._pause_marker - self._marker)
    
    def resume(self):
        if self.paused and not self.frozen:
            self._pause_duration = max(0.0, time.monotonic() - self._pause_marker)
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
        return self._running
    
    @property
    def goal(self):
        return self._goal
    
    @property
    def remaining(self):
        if not self.goal:
            return None
        
        return -(self.goal - self.elapsed)
    
    def __init__(self,
                 name: str,
                 goal: Optional[float] = None,
                 goal_handler: Coroutine | Callable | None = None,
                 repeat: bool = False,
                 paused: bool = False):
        super().__init__(paused=paused)
        self.name = name
        self.reached_goal = blinker.Signal()
        self.repeat = repeat
        
        self._running = False
        self._goal = None
        self._task: Optional[asyncio.Task] = None
        
        if goal_handler:
            self.reached_goal.connect(goal_handler, sender=self)
        
        if goal is not None:
            self.set(goal)
    
    def set(self, goal: float, reset=True):
        if reset:
            self.reset()
        self._goal = goal
    
    def start(self) -> asyncio.Task:
        if self._task is not None:
            self._task.cancel()
        self._task = asyncio.create_task(self.wait())
        return self._task
    
    async def wait(self):
        if self._running:
            self.cancel()
        
        self._running = True
        self.resume()
        self.reset()
        while self.running:
            if (not self.frozen and
                self.goal is None or
                self.elapsed > self.goal):
                    self.reached_goal.send(self)
                    if self.repeat:
                        self.reset()
                    else:
                        break
            await asyncio.sleep(POLL_RATE)
        
        self.cancel()
    
    def cancel(self):
        self._running = False

        if self._task is not None:
            self._task.cancel()
            self._task = None
        
    def __repr__(self):
        return f'<Timer {self.goal=:03.2f} {self.elapsed=:03.2f} {self.frozen=}>'


class Timer:
    freeze_time = blinker.signal('atsc.controller.time_freeze')
    unfreeze_time = blinker.signal('atsc.controller.time_unfreeze')
    
    @property
    def interval(self) -> float:
        return self._interval
    
    @property
    def elapsed(self) -> Optional[float]:
        if self._start_time is None:
            return None
        return asyncio.get_running_loop().time() - self._start_time
    
    @property
    def remaining(self) -> Optional[float]:
        if self._start_time is None or self._paused_time is not None:
            return None
        return max(0.0, self._interval - self.elapsed)
    
    @property
    def is_running(self) -> bool:
        """
        Check if the timer is currently running.

        :return: True if the timer is running, False otherwise.
        """
        return self._task is not None and not self._task.done()
    
    def __init__(
        self,
        interval: float,
        callback: Union[Callable[[], None], Callable[[], Awaitable[None]]],
    ):
        """
        Monotonic, recycling timer with callback in seconds.

        :param interval: The timer interval in seconds.
        :param callback: The function or coroutine to call when the timer completes.
        """
        self.freeze_time.connect(self._on_freeze)
        self.unfreeze_time.connect(self._on_unfreeze)
        
        self._time_freeze = False
        self._interval = interval
        self._callback = callback
        self._task: Optional[asyncio.Task[None]] = None
        self._start_time: Optional[float] = None
        self._paused_time: Optional[float] = None
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """
        Start or restart the timer. If the timer is already running, it resets and starts over.
        """
        await self.cancel()  # Ensure no overlapping tasks
        async with self._lock:
            self._start_time = asyncio.get_running_loop().time()
            self._paused_time = None
            self._task = asyncio.create_task(self._run())
    
    async def pause(self) -> None:
        """
        Pause the timer. Call `resume()` to unpause.
        """
        async with self._lock:
            if self._task and not self._task.done() and self._paused_time is None:
                self._paused_time = asyncio.get_running_loop().time()
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                finally:
                    self._task = None
    
    async def resume(self) -> None:
        """
        Resume the timer from where it was paused.
        """
        async with self._lock:
            if self._paused_time is not None:
                elapsed_paused = asyncio.get_running_loop().time() - self._paused_time
                self._start_time = (self._start_time or 0) + elapsed_paused
                self._paused_time = None
                self._task = asyncio.create_task(self._run())
    
    async def cancel(self) -> None:
        """
        Cancel the timer and wait for the internal task to complete.
        """
        async with self._lock:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                finally:
                    self._task = None
            self._start_time = None
            self._paused_time = None
    
    async def _run(self) -> None:
        """
        Internal method to handle the timer logic. This method is responsible for 
        firing the callback after the appropriate time, accounting for the current 
        interval value.
        """
        try:
            if self._start_time is None:
                raise RuntimeError('timer start time is not set.')
            
            while True:
                time_to_wait = max(0.0, self._interval - self.elapsed)
                
                # Wait until the correct time based on the current interval
                await asyncio.sleep(time_to_wait)
                
                # Invoke the callback
                if asyncio.iscoroutinefunction(self._callback):
                    await self._callback()
                else:
                    self._callback()
                
                # After firing the callback, reset the start time to the current time
                self._start_time = asyncio.get_running_loop().time()
        except asyncio.CancelledError:
            pass
    
    async def _on_freeze(self, _):
        if not self._time_freeze:
            await self.pause()
            self._time_freeze = True
    
    async def _on_unfreeze(self, _):
        if self._time_freeze:
            await self.resume()
            self._time_freeze = False
    
    async def change_interval(self, new_interval: float) -> None:
        """
        Change the interval while the timer is running. The callback will fire at the correct time
        accounting for the new interval.

        :param new_interval: The new interval in seconds.
        """
        async with self._lock:
            self._interval = new_interval
            if self._start_time is not None:
                # Adjust the start time to reflect the new interval
                elapsed_time = asyncio.get_running_loop().time() - self._start_time
                time_to_wait = max(0.0, self._interval - elapsed_time)
                if time_to_wait > 0.0:
                    # Reschedule the callback with the new interval
                    self._task.cancel()
                    self._task = asyncio.create_task(self._run())

    def __repr__(self):
        return f'<Timer {self.interval=:03.2f} {self.elapsed=:03.2f} {self.remaining=:03.2f} {self.is_running=}>'