import math
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, Optional, Tuple, List, Union, Any
from asciimatics.widgets import Layout, Frame, Text

from atsc.cli.tui.texts import ValueFormatter
from atsc.cli.tui.utils import text


class Populator(ABC):

    def __init__(self):
        self.layouts: List[Layout] = []

    def register_layouts(self, frame: Frame):
        for layout in self.layouts:
            frame.add_layout(layout)

    @abstractmethod
    def populate(self):
        pass


class PropertyPopulator(Populator):

    @property
    def props_per_layout(self):
        return math.ceil(len(self._keys) / self._rows)

    @property
    def widgets_per_layout(self):
        return self.props_per_layout * 2

    def __init__(self,
                 rows: int,
                 properties: Optional[
                     Dict[str, Tuple[str, Union[str, ValueFormatter]]]
                 ] = None):
        super().__init__()
        self._populated = False
        self._rows = rows
        self._keys = []
        self._labels = []
        self._placeholders = []
        self._format_map: Dict[str, ValueFormatter] = defaultdict()
        if properties is not None:
            for key, attributes in properties.items():
                label = attributes[0]
                self._labels.append(label)
                arg_two = attributes[1]
                self._placeholder_or_formatter(key, arg_two)
                self._keys.append(key)
        self.layouts = self._build_layouts()
        self._effect_map: Dict[str, Text] = {}

    def _placeholder_or_formatter(self,
                                  key: str,
                                  arg: Union[str, ValueFormatter]):
        if isinstance(arg, str):
            self._placeholders.append(arg)
        elif isinstance(arg, ValueFormatter):
            self._placeholders.append(arg.placeholder)
            self._format_map.update({key: arg})
        else:
            raise TypeError()

    def add(self,
            key: str,
            label: str,
            placeholder: Union[str, ValueFormatter]):
        self._keys.append(key)
        self._labels.append(label)
        self._placeholder_or_formatter(key, placeholder)
        self.layouts = self._build_layouts()

    def get(self, key: str):
        if not self._populated:
            raise RuntimeError('not populated yet')
        return self._effect_map.get(key)

    def set_value(self, key: str, v: Any):
        if not self._populated:
            raise RuntimeError('not populated yet')

        formatter = self._format_map.get(key)
        if formatter is not None:
            self._effect_map[key].value = formatter.format(v)
        else:
            self._effect_map[key].value = v

    def _build_layouts(self):
        return [Layout([1] * self.widgets_per_layout) for _ in range(self._rows)]

    def populate(self):
        k = 0
        for layout in self.layouts:
            col = 0
            for _ in range(self.props_per_layout):
                if k > len(self._keys) - 1:
                    break

                key = self._keys[k]
                label = self._labels[k]
                placeholder = self._placeholders[k]
                k += 1
                value = text(placeholder)
                layout.add_widget(text(label), col)
                col += 1
                layout.add_widget(value, col)
                col += 1
                self._effect_map.update({key: value})
        self._populated = True
