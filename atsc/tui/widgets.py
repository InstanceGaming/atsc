from typing import List

from jacob.datetime.formatting import format_dhms
from rich.text import Text
from textual.app import RenderResult
from textual.reactive import reactive
from textual.widget import Widget

from atsc.common.constants import FLOAT_PRECISION_TIME


def boolean_text(condition: bool,
                 txt1: str,
                 txt1_style: str,
                 txt2: str,
                 txt2_style: str):
    if condition:
        return Text(txt1, style=txt1_style)
    else:
        return Text(txt2, style=txt2_style)


def text_or_dash(condition: bool, txt: str, txt_style: str):
    return boolean_text(condition, txt, txt_style, '-', 'bright_black')


def get_time_text(v: float, force_style=None):
    rounded = round(v, FLOAT_PRECISION_TIME)
    text = Text(format(rounded, '.1f'))
    if v < 0.0:
        color = 'red'
    else:
        color = 'white'
    text.stylize(force_style or color)
    return text


def combine_texts_new_line(*texts) -> Text:
    text = texts[0]
    for i in range(1, len(texts)):
        text = text.append('\n')
        if i < len(texts):
            text = text.append_text(texts[i])
    return text


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
    
    def render(self):
        signal_id = format(self.signal_id, '03d')
        return combine_texts_new_line(
            boolean_text(self.resting, signal_id, 'bright_red', signal_id, 'bright_green'),
            self.get_state_text(),
            get_time_text(self.interval_time),
            get_time_text(self.service_time, force_style='bright_black' if self.resting else None),
            text_or_dash(self.demand, 'DEMAND', 'bright_cyan'),
            text_or_dash(self.presence, 'PRESENCE', 'white')
        )


class ControllerRuntime(Widget):
    
    run_seconds = reactive(0)
    
    def render(self) -> RenderResult:
        days, hours, minutes, seconds = format_dhms(self.run_seconds)
        text = Text(f'{days:04d}d{hours:02d}h{minutes:02d}m{seconds:02d}s',
                    no_wrap=True,
                    overflow='ellipsis')
        return text
