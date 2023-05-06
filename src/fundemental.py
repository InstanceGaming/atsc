from collections import defaultdict
from typing import Callable

import asyncio
from natsort import natsorted
from src.utils import getUniformName


TAGS = set()


class ATSCEventBus:
    
    def __init__(self):
        self._listener_map = defaultdict(set)
    
    def add_listener(self, key: str, listener_func: Callable):
        uniform_key = getUniformName(key)
        if uniform_key in TAGS:
            raise ValueError('event already defined')
        self._listener_map[key].add(listener_func)
    
    def remove_listener(self, key: str, listener_func: Callable):
        self._listener_map[key].remove(listener_func)
        if len(self._listener_map[key]) == 0:
            del self._listener_map[key]
    
    def emit(self, key: str, *args, **kwargs):
        listeners = self._listener_map.get(key, [])
        for listener_func in listeners:
            asyncio.create_task(listener_func(*args, **kwargs))


class ATSCObject:
    _EVENT_BUS = ATSCEventBus()
    
    @property
    def tag(self):
        return self._tag
    
    def __init__(self, tag: str):
        uniform_tag = getUniformName(tag)
        if uniform_tag in TAGS:
            raise ValueError('tag already defined')
        self._tag = tag
        
    def add_listener(self, key: str, listener_func: Callable):
        self._EVENT_BUS.add_listener(key, listener_func)
        
    def remove_listener(self, key: str, listener_func: Callable):
        self._EVENT_BUS.remove_listener(key, listener_func)
        
    def emit(self, key: str, *args, **kwargs):
        self._EVENT_BUS.emit(key, *args, **kwargs)

    def __hash__(self):
        return hash(self._tag)
    
    def __lt__(self, other: 'ATSCObject'):
        return natsorted((self, other))[0] == self
    
    def __repr__(self):
        return f'<{self.tag}>'
