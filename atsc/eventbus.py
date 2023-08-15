from typing import Callable, Set


class BusEvent:
    _global_events: Set['BusEvent'] = set()
    
    @property
    def key(self):
        return self._key
    
    @property
    def subscribed(self):
        return len(self._callbacks)
    
    def __init__(self, *args, **kwargs):
        arg_count = len(args)
        
        if arg_count == 0:
            raise ValueError('key must be provided')
        
        key = args[0]
        
        self._global_events.add(self)
        self._key = key
        self._callbacks: Set[Callable] = set()
        
        self._arg_types = args[1:]
        
        for arg_type in self._arg_types:
            if not isinstance(arg_type, type):
                raise TypeError('argument not a type')
        
        self._kwarg_types = kwargs
        
        for k, v in self._kwarg_types.items():
            if not isinstance(v, type):
                raise TypeError(f'kwarg {k} not a type')
    
    def subscribe(self, func: Callable):
        self._callbacks.add(func)

    def invoke(self, *args, **kwargs):
        if len(self._callbacks):
            if len(args):
                for arg, arg_type in zip(args, self._arg_types):
                    if not isinstance(arg, arg_type):
                        raise TypeError(f'argument not of type {arg_type.__name__}')
            
            if len(kwargs):
                for (k, v) in kwargs.items():
                    value_type = self._kwarg_types.get(k)
                    if value_type is not None:
                        if not isinstance(v, value_type):
                            raise TypeError(f'kwarg {k} is not of type {value_type.__name__}')
            
            for callback in self._callbacks:
                callback(*args, **kwargs)

    @staticmethod
    def match(key: str) -> 'BusEvent':
        for event in BusEvent._global_events:
            if event.key == key:
                return event
        raise KeyError(f'event "{key}" not found (yet?)')
