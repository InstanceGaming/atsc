from typing import Iterable, TypeVar, List, Optional, Iterator


C_T = TypeVar('C_T')


class OrderedCollection:

    def __init__(self, items: Optional[List[C_T]] = None, limit=None):
        self._items: List[C_T] = items or []
        if limit is not None:
            if limit < 0:
                raise ValueError('positive integer required for limit')
        self._limit = limit or 0

    def _check_limit(self):
        if self._limit and len(self._items) + 1 > self._limit:
            raise RuntimeError('limit exceeded')

    def extend(self, i: Iterable[C_T]) -> None:
        self._check_limit()
        self._items.extend(i)

    def append(self, o: C_T) -> None:
        self._check_limit()
        self._items.append(o)

    def __setitem__(self, index: int, value: C_T):
        self._check_limit()
        self._items[index] = value

    def __getitem__(self, index: int):
        return self._items[index]

    def __iter__(self) -> Iterator[C_T]:
        return iter(self._items)


class TickableCollection(OrderedCollection):

    def tick(self):
        for item in self:
            item.tick()
