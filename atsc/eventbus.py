from collections import defaultdict
from typing import Callable, Dict, List


listeners: Dict[str | int, List[Callable]] = defaultdict(list)


def invoke(event, *args, **kwargs):
    for callback in listeners[event]:
        callback(*args, **kwargs)
