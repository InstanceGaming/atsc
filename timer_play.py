import asyncio
import random
from typing import Callable, Optional, Union, Awaitable

from jacob.datetime.formatting import format_ms
from jacob.datetime.timing import millis


class Timer:
    
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


i = 1
marker = millis()


def on_timer():
    global i, marker
    print(i, format_ms(millis() - marker))
    marker = millis()
    i += 1


async def example():
    global i
    
    timer = Timer(interval=0.5, callback=on_timer)
    await timer.start()
    
    try:
        while True:
            if i % 10 == 0:
                await timer.change_interval(random.choice((0.1, 0.2, 0.3, 0.4, 0.5, 0.6)))
            await asyncio.sleep(0.1)  # Simulate other work
    except KeyboardInterrupt:
        await timer.cancel()
    
    # await timer.change_interval(2.0)  # Change interval while running
    # print('Interval changed.')
    #await asyncio.sleep(3)
    print('exiting')


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(example())
