from abc import abstractmethod
from time import sleep
from typing import Any
from threading import Event, Thread
from atsc.common.fundemental import Tickable


class ThreadedTickable(Thread, Tickable):

    @property
    def stopped(self):
        return self._stop_event.is_set()

    @property
    def paused(self):
        return self._pause_event.is_set()

    def __init__(self, tick_delay: float, thread_name=None, daemon=True):
        Tickable.__init__(self, tick_delay)
        Thread.__init__(self, name=thread_name, daemon=daemon)
        self._stop_event = Event()
        self._pause_event = Event()

    @abstractmethod
    def tick(self, *args, **kwargs) -> Any:
        pass

    def before_run(self):
        pass

    def run(self):
        self.before_run()
        while True:
            if self._stop_event.is_set():
                break
            if not self._pause_event.is_set():
                self.tick()
                sleep(self.tick_delay)
            else:
                sleep(self.tick_delay * 2)

    def pause(self) -> bool:
        if not self._pause_event.is_set():
            self._pause_event.set()
            return True
        return False

    def unpause(self) -> bool:
        if self._pause_event.is_set():
            self._pause_event.clear()
            return True
        return False

    def after_run(self, code: int):
        pass

    def after_stop(self, code: int):
        pass

    def stop(self, code: int):
        if self.stopped:
            raise RuntimeError('already stopped')
        self.after_run(code)
        self._stop_event.set()
        self.after_stop(code)
