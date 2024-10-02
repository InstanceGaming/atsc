from datetime import datetime
from rich.text import Text
from textual.app import RenderResult
from atsc.tui.utils import (
    boolean_text,
    text_or_dash,
    get_time_text,
    combine_texts_new_line
)
from textual.widget import Widget
from textual.reactive import reactive
from atsc.rpc.controller import CycleMode
from jacob.datetime.formatting import format_dhms


class Signal(Widget):
    
    state = reactive('?')
    interval_time = reactive(0.0)
    service_time = reactive(0.0)
    resting = reactive(False)
    demand = reactive(False)
    presence = reactive(False)
    
    def __init__(self, signal_id: int):
        super().__init__()
        self.signal_id = signal_id
    
    def get_state_text(self):
        text = Text(self.state)
        match self.state:
            case 'STOP' | 'LS_FLASH':
                color = 'bright_red'
            case 'CAUTION' | 'FYA':
                color = 'bright_yellow'
            case 'GO' | 'EXTEND':
                color = 'bright_green'
            case _:
                color = 'white'
        text.stylize(f'bold {color}')
        return text
    
    def render(self) -> RenderResult:
        signal_id = format(self.signal_id, '03d')
        return combine_texts_new_line(
            boolean_text(self.resting, signal_id, 'bright_green', signal_id, 'bright_red'),
            self.get_state_text(),
            get_time_text(self.interval_time),
            get_time_text(self.service_time, force_style='bright_black' if self.resting else None),
            text_or_dash(self.demand, 'DEMAND', 'bright_cyan'),
            text_or_dash(self.presence, 'PRESENCE', 'white')
        )


class ControllerDurationReadout(Widget):
    
    seconds = reactive(0, layout=True)
    
    def render(self) -> RenderResult:
        days, hours, minutes, seconds = format_dhms(self.seconds)
        
        text = Text('+', style='white')
        
        if days:
            text.append(format(days, '04d'), 'white')
            text.append('d', 'yellow')
        
        if hours:
            text.append(format(hours, '02d'), 'white')
            text.append('h', 'yellow')
        
        if minutes:
            text.append(format(minutes, '02d'), 'white')
            text.append('m', 'yellow')
        
        color = 'white'
        
        if self.seconds < 1:
            color = 'bright_yellow'
        
        text.append(format(seconds, '02d'), color)
        text.append('s', 'yellow')
        
        return text


class ControllerDatetimeReadout(Widget):
    
    def __init__(self, dt: datetime):
        super().__init__()
        self.datetime = dt
    
    def render(self) -> RenderResult:
        formatted = self.datetime.strftime('%a, %b %m %Y %I:%M:%S %p')
        return Text(formatted, style='bright_white')


class ControllerTimeFreeze(Widget):
    
    time_freeze = reactive(bool, layout=True)
    
    def __init__(self):
        super().__init__()
        self._flasher = True
        self._style = ''
    
    def render(self) -> RenderResult:
        if self.time_freeze:
            return Text('TIME_FREEZE', style=self._style)
        else:
            return Text('TIMING', style='bright_green')

    def toggle_color(self):
        if self._flasher:
            self._style = 'bold bright_red'
        else:
            self._style = 'bold bright_white'
        self._flasher = not self._flasher
        self.refresh()
    
    def watch_time_freeze(self):
        if self.time_freeze:
            self.set_interval(0.2, self.toggle_color)


class ControllerCycleMode(Widget):
    
    mode = reactive(CycleMode.PAUSE, layout=True)
    
    def __init__(self):
        super().__init__()
        self._flasher = True
        self._style = ''
    
    def render(self) -> RenderResult:
        match self.mode:
            case CycleMode.PAUSE:
                style = self._style
            case CycleMode.SEQUENTIAL:
                style = 'bright_blue'
            case CycleMode.CONCURRENT:
                style = 'bright_green'
            case _:
                style = 'bright_red'
        
        return Text(self.mode.name, style=style)
    
    def toggle_color(self):
        if self._flasher:
            self._style = 'bold bright_yellow'
        else:
            self._style = 'bold bright_white'
        self._flasher = not self._flasher
        self.refresh()
    
    def watch_mode(self):
        if self.mode == CycleMode.PAUSE:
            self.set_interval(0.2, self.toggle_color)


class ControllerCycleCount(Widget):
    
    cycle_count = reactive(int)
    
    def render(self) -> RenderResult:
        return Text.assemble(('CYCLE #', 'yellow'),
                             (format(self.cycle_count, '04d'), 'bright_white'))
