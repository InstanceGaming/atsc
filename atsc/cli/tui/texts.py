from abc import ABC, abstractmethod
from typing import Any, Optional

from atsc.constants import SECONDS_WEEK, SECONDS_DAY, SECONDS_HOUR, SECONDS_MINUTE


def control_mode(mode: int) -> str:
    if mode == 10:
        return 'OFF'
    elif mode == 20:
        return 'CET'
    elif mode == 30:
        return 'NRM'
    elif mode == 40:
        return 'CXT'
    elif mode == 50:
        return 'LSF'


class ValueFormatter(ABC):

    @property
    def placeholder(self) -> str:
        return self.format(None)

    @abstractmethod
    def format(self, v: Any) -> str:
        pass


class ElapsedSecondsFormatter(ValueFormatter):

    def format(self, v: Optional[int]) -> str:
        if v is None:
            v = 0

        if v < 0:
            raise ValueError()

        digits = str(v)
        unit = 'S'

        if SECONDS_WEEK <= v:
            digits = str(round(v / SECONDS_WEEK))
            unit = 'W'
        elif SECONDS_DAY <= v:
            digits = str(round(v / SECONDS_DAY))
            unit = 'D'
        elif SECONDS_HOUR <= v:
            digits = str(round(v / SECONDS_HOUR))
            unit = 'H'
        elif SECONDS_MINUTE <= v:
            digits = str(round(v / SECONDS_MINUTE))
            unit = 'M'

        return digits + unit


class FloatFormatter(ValueFormatter):

    def __init__(self,
                 pad_whole: str = '0000',
                 pad_decimal: str = '00'):
        self._pad_whole = pad_whole
        self._pad_decimal = pad_decimal

    def format(self, v: Optional[float]) -> str:
        if v is None:
            v = 0

        whole = self._pad_whole[0]
        decimal = self._pad_decimal[0]
        decimal_count = len(self._pad_decimal)
        count = len(self._pad_whole) + decimal_count + 1
        return f'{v:{whole}{count}.{decimal}{decimal_count}f}'


class IntegerFormatter(ValueFormatter):

    def __init__(self,
                 pad: str = '0',
                 null_char: str = '?'):
        self._null_char = null_char
        self._char = pad[0]
        self._count = len(pad)

    def format(self, v: Optional[float]) -> str:
        if v is None:
            return str([self._null_char] * self._count)
        return str(v).rjust(self._count, self._char)
