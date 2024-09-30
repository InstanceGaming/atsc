from jacob.datetime.formatting import format_dhms
from rich.text import Text
from textual.app import RenderResult
from textual.reactive import reactive
from textual.widget import Widget

from atsc.common.constants import RPC_FLOAT_PRECISION_TIME


class Signal(Widget):
    
    state = reactive('?')
    interval_time = reactive(0.0)
    service_time = reactive(0.0)
    resting = reactive(False)
    demand = reactive(False)
    presence = reactive(False)
    
    def __init__(self, index: int):
        super().__init__()
        self.index = index
    
    def render(self):
        return '\n'.join((
            f'{self.index:02d}',
            self.state,
            str(round(self.interval_time, RPC_FLOAT_PRECISION_TIME)),
            str(round(self.service_time, RPC_FLOAT_PRECISION_TIME)),
            'RESTING' if self.resting else 'TIMING',
            'DEMAND' if self.demand else '-',
            'PRESENCE' if self.presence else '-'
        ))


class ControllerRuntime(Widget):
    
    run_seconds = reactive(0)
    
    def render(self) -> RenderResult:
        days, hours, minutes, seconds = format_dhms(self.run_seconds)
        text = Text(f'{days}d{hours}h{minutes}m{seconds}s', no_wrap=True, overflow='ellipsis')
        return text
