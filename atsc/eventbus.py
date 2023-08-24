from collections import defaultdict
from typing import Callable, Dict, Set


listeners: Dict[str | int, Set[Callable]] = defaultdict(set)


def invoke(event, *args, **kwargs):
    for callback in listeners[event]:
        callback(*args, **kwargs)
