from typing import List, TypeVar, Iterator


C_T = TypeVar('C_T')


def cycle(v: List[C_T], initial=0) -> Iterator[C_T]:
    """
    Repeat the items within list v indefinitely, in order.
    
    - Seamlessly handles the list mutations (not thread-safe).
    - If the initial value is greater than the length of the list
      at the time, the first index will be the modulo of the list length.
    - Also see `itertools.cycler()`.
    """
    i = initial % len(v)
    while True:
        if i == len(v):
            i = 0
        yield v[i]
        i += 1
