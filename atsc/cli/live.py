import time

import grpc
from asciimatics.scene import Scene
from asciimatics.screen import Screen
from atsc.cli.models import RemoteController
from atsc.cli.tui.effects import ApplicationFrame
from atsc.common.models import ControlState
from atsc.common.parallel import ThreadedTickable


class Application(ThreadedTickable):

    def __init__(self, con_str: str, tick_size: float):
        super().__init__(tick_size)
        self._rpc_channel = grpc.insecure_channel(con_str)
        self._controller = RemoteController(self._rpc_channel)
        self._screen = Screen.open()
        self._screen.set_title(f'ATSC Live - {con_str}')
        self._frame = ApplicationFrame(self._screen)
        self._screen.set_scenes([Scene([self._frame])])

    def update_state_flags(self, state_flags: int):
        current_flags = ControlState(state_flags)

        for flag in ControlState:
            key = flag.name.lower()
            active = flag in current_flags
            self._frame.update_flag_bool(key, active)

    def update(self):
        status = self._controller.get_status()
        self._frame.update_num('runtime', status.runtime)
        self._frame.update_num('control_time', status.control_time)
        self._frame.update_num('transfer_count', status.transfer_count)
        self._frame.update_num('avg_demand', status.avg_demand)
        self._frame.update_num('peek_demand', status.peek_demand)
        self.update_state_flags(status.state_flags)

    def tick(self):
        self.update()
        self._screen.draw_next_frame(repeat=False)

    def after_run(self, code: int):
        self._screen.close()


def run_tui(con_str: str):
    app = Application(con_str, 0.1)
    app.run()
