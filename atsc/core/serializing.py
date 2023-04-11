from abc import ABC, abstractmethod
from typing import TypeVar


D_T = TypeVar('D_T')


class Deserializable(ABC):

    @staticmethod
    @abstractmethod
    def deserialize(data, **kwargs):
        raise NotImplementedError()
