from typing import Optional, Any
from atsc.constants import *
from atsc.eventbus import BusEvent
from atsc.interfaces import DelayProvider
from atsc.primitives import Referencable


class Parameter(Referencable):
    onChange = BusEvent('parameter.change')
    
    @property
    def value(self):
        return self._value
    
    def __init__(self,
                 id_: int,
                 initial_value):
        super().__init__(id_)
        self._value = initial_value
        self._previous_value = None
    
    def change(self, value: Any, editor: Referencable):
        msg = self.validate(value)
        if msg is not None:
            raise ValueError(msg)
        
        self._previous_value = self._value
        self._value = value
        self.onChange.invoke(self, editor, value, self._previous_value)
    
    def validate(self, value) -> Optional[str]:
        return None


class RangeParameter(Parameter):
    
    @property
    def min(self):
        return self._min
    
    @property
    def max(self):
        return self._max
    
    def __init__(self,
                 id_: int,
                 initial_value,
                 minimum: float,
                 maximum: float):
        super().__init__(id_, initial_value)
        self._min = minimum
        self._max = maximum
    
    def validate(self, value) -> Optional[str]:
        if self.max < value < self.min:
            return f'parameter value out of range ({self.min}-{self.max})'
        return None


class RateParameter(RangeParameter, DelayProvider):
    
    @property
    def delay(self):
        return 1 / self.value
    
    def __init__(self,
                 id_: int,
                 initial_value,
                 minimum: float,
                 maximum: float):
        RangeParameter.__init__(self,
                                id_,
                                initial_value,
                                minimum,
                                maximum)
        DelayProvider.__init__(self)


class TimeRate(RateParameter):
    
    def __init__(self, initial_value):
        super().__init__(StandardObjects.P_TIME_RATE,
                         initial_value,
                         0.0,
                         ABSOLUTE_MAXIMUM_RATE)


class InputsRate(RateParameter):
    
    def __init__(self, rate: float):
        super().__init__(StandardObjects.P_INPUTS_RATE,
                         rate,
                         MINIMUM_INPUTS_RATE,
                         MAXIMUM_INPUTS_RATE)


class BusRate(RateParameter):
    
    def __init__(self, rate: float):
        super().__init__(StandardObjects.P_BUS_RATE,
                         rate,
                         MINIMUM_BUS_RATE,
                         MAXIMUM_BUS_RATE)


class NetworkRate(RateParameter):
    
    def __init__(self, rate: float):
        super().__init__(StandardObjects.P_NETWORK_RATE,
                         rate,
                         MINIMUM_NETWORK_RATE,
                         MAXIMUM_NETWORK_RATE)


class FlashRate(RangeParameter, DelayProvider):
    
    @property
    def delay(self):
        return (60 / self.value) / 2
    
    def __init__(self, flashes_per_minute: float):
        super().__init__(StandardObjects.P_FPM,
                         flashes_per_minute,
                         MINIMUM_FLASH_RATE,
                         MAXIMUM_FLASH_RATE)
        DelayProvider.__init__(self)
