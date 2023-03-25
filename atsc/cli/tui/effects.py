from collections import defaultdict
from typing import Optional, Iterable, Union

from asciimatics.constants import *
from asciimatics.widgets import Frame

from atsc.cli.tui.populators import PropertyPopulator, Populator
from atsc.cli.tui.texts import ElapsedSecondsFormatter, FloatFormatter, IntegerFormatter


class ApplicationFrame(Frame):

    def __init__(self, screen):
        super().__init__(screen,
                         screen.height,
                         screen.width,
                         has_border=False)
        self._flag_props = PropertyPopulator(2, {
            'transferred': ('FTR', '?'),
            'idle': ('IDLE', '?'),
            'actuated': ('ACT', '?'),
            'saturated': ('SAT', '?'),
            'time_freeze': ('TFZ', '?'),
            'preempted': ('EMS', '?'),
            'global_ped_service': ('GPS', '?'),
            'global_ped_clear': ('GPC', '?'),
            'global_fya_enabled': ('GFA', '?'),
            'degraded': ('DEG', '?'),
            'faults': ('FAL', '?'),
            'faults_latched': ('FTL', '?'),
            'debug': ('DBG', '?')
        })
        self._num_props = PropertyPopulator(1, {
            'runtime': ('RT', ElapsedSecondsFormatter(0)),
            'control_time': ('CT', ElapsedSecondsFormatter(0)),
            'transfer_count': ('FTC', IntegerFormatter('0000')),
            'avg_demand': ('DD_AVG', FloatFormatter()),
            'peek_demand': ('DD_PK', FloatFormatter())
        })
        self.populate([self._flag_props, self._num_props])
        self.fix()
        self.configure_theme()

    def update_flag_bool(self,
                         key: str,
                         state: Optional[bool],
                         on: str = 'Y',
                         off: str = 'N'):
        if state is not None:
            letters = on if state else off
        else:
            letters = '???'
        self._flag_props.set_value(key, letters)

    def update_num(self, key: str, v: Union[int, float]):
        self._num_props.set_value(key, v)

    def configure_theme(self):
        self.palette = defaultdict(
            lambda: (COLOUR_WHITE, A_NORMAL, COLOUR_BLACK)
        )
        for key in ["selected_focus_field", "label"]:
            self.palette[key] = (COLOUR_WHITE, A_BOLD, COLOUR_BLACK)
        self.palette["title"] = (COLOUR_BLACK, A_NORMAL, COLOUR_WHITE)

    def populate(self, populators: Iterable[Populator]):
        for pop in populators:
            pop.register_layouts(self)
            pop.populate()
