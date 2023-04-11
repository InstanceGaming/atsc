from typing import Iterable


class OrderedCollection:

    def __init__(self, items=None, limit=None):
        self._items = items or []
        if limit is not None:
            if limit < 0:
                raise ValueError('positive integer required for limit')
        self._limit = limit or 0

    def _check_limit(self):
        if self._limit and len(self._items) + 1 > self._limit:
            raise RuntimeError('limit exceeded')

    def extend(self, i: Iterable) -> None:
        self._check_limit()
        self._items.extend(i)

    def append(self, o) -> None:
        self._check_limit()
        self._items.append(o)

    def __setitem__(self, key, value):
        self._check_limit()
        self._items[key] = value

    def __getitem__(self, key: int):
        return self._items[key]

    def __iter__(self):
        return iter(self._items)


class TickableCollection(OrderedCollection):

    def tick(self):
        for item in self:
            item.tick()
