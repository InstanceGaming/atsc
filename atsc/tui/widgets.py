#  Copyright 2024 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
from typing import List
from datetime import datetime
from rich.text import Text
from textual.app import RenderResult, ComposeResult
from atsc.tui.utils import boolean_text, text_or_dash, get_time_text
from textual.widget import Widget
from atsc.rpc.signal import SignalType
from textual.reactive import reactive
from atsc.tui.constants import FieldOutputStyle
from atsc.rpc.controller import CycleMode
from jacob.datetime.formatting import format_dhms


class FieldOutputWidget(Widget):
    
    value = reactive(False)
    
    def __init__(self,
                 id,
                 field_output_id: int,
                 style: FieldOutputStyle = FieldOutputStyle.GENERIC):
        super().__init__(id=id)
        self.field_output_id = field_output_id
        self.char_style = style
        
    def render(self) -> RenderResult:
        if self.value:
            match self.char_style:
                case FieldOutputStyle.GENERIC:
                    return Text('X', style='bright_white')
                case FieldOutputStyle.STOP:
                    return Text('R', style='bright_red')
                case FieldOutputStyle.CAUTION:
                    return Text('Y', style='bright_yellow')
                case FieldOutputStyle.GO:
                    return Text('G', style='bright_green')
                case FieldOutputStyle.DONT_WALK:
                    return Text('D', style='orange_red1')
                case FieldOutputStyle.WALK:
                    return Text('W', style='sky_blue1')
        else:
            return Text('-', style='bright_black')


class SignalTitleWidget(Widget):
    
    active = reactive(False)
    resting = reactive(False)
    
    def __init__(self, signal_id: int):
        super().__init__()
        self.signal_id = signal_id
    
    def render(self) -> RenderResult:
        if self.active and self.resting:
            return Text(str(self.signal_id), style='bright_white')
        else:
            return boolean_text(self.active,
                                self.signal_id,
                                'bright_green',
                                self.signal_id,
                                'bright_red')


class SignalStateWidget(Widget):
    
    state = reactive('')
    
    def render(self) -> RenderResult:
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


class SignalTimeWidget(Widget):
    
    elapsed = reactive(0.0)
    
    def render(self) -> RenderResult:
        return get_time_text(self.elapsed)
    
    
class SignalDemandWidget(Widget):
    
    demand = reactive(False)
    
    def render(self) -> RenderResult:
        return text_or_dash(self.demand, 'DEMAND', 'bright_cyan')


class SignalPresenceWidget(Widget):
    
    presence = reactive(False)
    
    def render(self) -> RenderResult:
        return text_or_dash(self.presence, 'PRESENCE', 'bright_white')


class SignalWidget(Widget):
    
    def __init__(self,
                 id,
                 signal_id: int,
                 signal_type: SignalType,
                 field_outputs: List[FieldOutputWidget]):
        super().__init__(id=id)
        self.signal_id = signal_id
        self.field_outputs = field_outputs
        
        for i, field_output in enumerate(field_outputs):
            style = FieldOutputStyle.GENERIC
            
            match signal_type:
                case SignalType.VEHICLE:
                    match i:
                        case 0:
                            style = FieldOutputStyle.STOP
                        case 1:
                            style = FieldOutputStyle.CAUTION
                        case 2:
                            style = FieldOutputStyle.GO
                        case 3:
                            style = FieldOutputStyle.CAUTION
                case SignalType.PEDESTRIAN:
                    match i:
                        case 0:
                            style = FieldOutputStyle.DONT_WALK
                        case 1:
                            style = FieldOutputStyle.WALK

            field_output.char_style = style
        
        self.title = SignalTitleWidget(self.signal_id)
        self.state = SignalStateWidget()
        self.interval_time = SignalTimeWidget()
        self.service_time = SignalTimeWidget()
        self.demand = SignalDemandWidget()
        self.presence = SignalPresenceWidget()
        self.presence_time = SignalTimeWidget()
    
    def compose(self) -> ComposeResult:
        yield self.title
        yield self.state
        yield self.interval_time
        yield self.service_time
        yield self.demand
        yield self.presence
        yield self.presence_time
        
        for field_output in self.field_outputs:
            yield field_output


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
            self.set_interval(0.5, self.toggle_color)


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
            self.set_interval(0.5, self.toggle_color)


class ControllerCycleCount(Widget):
    
    cycle_count = reactive(int)
    
    def render(self) -> RenderResult:
        return Text.assemble(('CYCLE #', 'yellow'),
                             (format(self.cycle_count, '04d'), 'bright_white'))
