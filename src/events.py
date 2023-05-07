from collections import defaultdict
from typing import Callable
from src.utils import getUniformName
import asyncio


class EventBus:
    _EVENT_KEYS = set()
    
    def __init__(self):
        self._listener_map = defaultdict(set)
    
    def addListener(self, key: str, listener_func: Callable):
        uniform_key = getUniformName(key)
        if uniform_key in self._EVENT_KEYS:
            raise ValueError('event already defined')
        self._listener_map[key].add(listener_func)
    
    def removeListener(self, key: str, listener_func: Callable):
        self._listener_map[key].remove(listener_func)
        if len(self._listener_map[key]) == 0:
            del self._listener_map[key]
    
    def emit(self, key: str, *args, **kwargs):
        listeners = self._listener_map.get(key, [])
        for listener_func in listeners:
            asyncio.create_task(listener_func(*args, **kwargs))


class Listener:
    _EVENT_BUS = EventBus()
    
    def addListener(self, key: str, listener_func: Callable):
        self._EVENT_BUS.addListener(key, listener_func)
        
    def removeListener(self, key: str, listener_func: Callable):
        self._EVENT_BUS.removeListener(key, listener_func)
        
    def emit(self, key: str, *args, **kwargs):
        self._EVENT_BUS.emit(key, *args, **kwargs)
