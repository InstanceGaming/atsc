from typing import Dict, Optional
from pydantic import BaseModel
from atsc.controller.constants import SignalState


IntervalTime = Dict[SignalState, float]


class TimingPlan(BaseModel):
    minimum: IntervalTime
    maximum: Optional[IntervalTime] = None
    
    def merge(self, *args, **kwargs) -> 'TimingPlan':
        other_min = {}
        other_max = {}
        
        arg_count = len(args)
        if arg_count == 1:
            first_arg = args[0]
            if isinstance(first_arg, TimingPlan):
                other_min = first_arg.minimum
                other_max = first_arg.maximum
            elif isinstance(first_arg, dict):
                other_min = first_arg
            else:
                raise TypeError()
        elif arg_count == 2:
            if isinstance(args[0], dict) and isinstance(args[1], dict):
                other_min = args[0]
                other_max = args[1]
            else:
                raise TypeError()
        elif arg_count == 0:
            if len(kwargs) == 0:
                raise TypeError()
            else:
                other_min = kwargs.get('minimum', {})
                other_max = kwargs.get('timer', {})
        
        return TimingPlan(minimum=self.minimum | other_min,
                          maximum=self.maximum | other_max)
