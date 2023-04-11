from typing import Type, Union, Optional, TypeVar
from atsc.core.fundemental import Identifiable


class Referencable(Identifiable):
    GLOBAL_DEFINITIONS = {}

    def __init__(self, id_: int):
        if id_ in self.GLOBAL_DEFINITIONS.keys():
            raise RuntimeError(f'attempted to create identifiable object with '
                               f'duplicate ID {id_}')
        super().__init__(id_)
        self.GLOBAL_DEFINITIONS.update({id_: self})


R_T = TypeVar('R_T', bound=Referencable)


def reference(r: Optional[Union[int, Referencable]],
              cls: Type[R_T]) -> Optional[R_T]:
    if r is None:
        return r
    if isinstance(r, Referencable):
        return r
    elif isinstance(r, int):
        for k, v in Referencable.GLOBAL_DEFINITIONS.items():
            if k == r:
                if type(v) != cls:
                    raise TypeError(f'type of {r} was not {cls.__name__}')
                return v
        raise LookupError(f'failed to find reference {r} (type {cls.__name__})')
    else:
        raise TypeError()
