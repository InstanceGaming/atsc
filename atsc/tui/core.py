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
from grpc import RpcError
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime
from atsc.common import utils
from textual.app import App, ComposeResult
from grpclib.client import Channel
from textual.widget import MountError
from textual.worker import Worker
from atsc.tui.panels import ControllerPanel
from textual.widgets import Footer, Header
from atsc.tui.widgets import (
    SignalWidget,
    FieldOutputWidget,
    ControllerCycleMode,
    ControllerCycleCount,
    ControllerTimeFreeze,
    ControllerDurationReadout
)
from textual.reactive import reactive
from atsc.tui.messages import (
    ShowBanner,
    RpcConnectionLost,
    RpcControllerPoll,
    RpcConnectionAfter,
    RpcDisconnectAfter,
    RpcConnectionBefore,
    RpcConnectionFailed,
    RpcConnectionSuccess
)
from grpclib.exceptions import StreamTerminatedError
from atsc.rpc.controller import (
    ControllerStub,
    ControllerMetadataRequest,
    ControllerGetStateStreamRequest
)
from atsc.tui.components import Banner
from atsc.tui.containers import MainContentSwitcher
from atsc.common.constants import (
    RPC_CALL_TIMEOUT,
    RPC_CALL_DEADLINE_POLL,
    ExitCode
)


class TUI(App[int]):
    
    BINDINGS = [
        ('c', 'rpc_connect', 'Connect to controller.'),
        ('d', 'rpc_disconnect', 'Disconnect from controller.'),
        ('q', 'quit', 'Exit application.')
    ]
    
    rpc_connected = reactive(False, bindings=True)
    
    def __init__(self,
                 rpc_address: str,
                 rpc_port: int,
                 stylesheet_path: Path,
                 dev_mode: bool = False):
        super().__init__(css_path=stylesheet_path,
                         watch_css=dev_mode)
        # noinspection PyTypeChecker
        self.title = 'Actuated Traffic Signal Controller'
        # noinspection PyTypeChecker
        self.dark = False
        
        self.rpc_address = rpc_address
        self.rpc_port = rpc_port
        
        self.channel: Optional[Channel] = None
        self.controller: Optional[ControllerStub] = None
        
        self.field_outputs: Dict[int, FieldOutputWidget] = {}
        self.signals: Dict[int, SignalWidget] = {}
        
        self.switcher = MainContentSwitcher()
        self.poll_worker: Worker | None = None
    
    def compose(self) -> ComposeResult:
        yield Header(icon='')
        yield self.switcher
        yield Footer()
    
    async def on_show_banner(self, message: ShowBanner):
        banner = Banner(message.title,
                        description=message.description,
                        classes=message.classes,
                        timeout=message.timeout or 5.0)
        try:
            await self.mount(banner, after=0)
        except MountError:
            pass
    
    async def rpc_connect(self):
        try:
            metadata = await self.controller.get_metadata(
                ControllerMetadataRequest()
            )
            self.post_message(RpcConnectionSuccess(metadata))
        except (TimeoutError, RpcError, ConnectionError) as e:
            self.post_message(RpcConnectionFailed(e))
        finally:
            self.post_message(RpcConnectionAfter())
    
    async def rpc_disconnect(self):
        self.rpc_connected = False
        
        if self.poll_worker is not None:
            self.poll_worker.cancel()
        
        self.switcher.current = 'home-panel'
        
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.controller is not None:
            self.controller = None
        
        self.post_message(RpcDisconnectAfter())
    
    async def action_rpc_connect(self):
        assert not self.rpc_connected
        self.post_message(RpcConnectionBefore())
        try:
            self.channel = Channel(host=self.rpc_address, port=self.rpc_port)
            self.controller = ControllerStub(self.channel)
            self.run_worker(self.rpc_connect(), exclusive=True)
        except RpcError as e:
            self.post_message(RpcConnectionFailed(e))
    
    async def on_rpc_connection_before(self, _):
        self.switcher.current = 'connecting-panel'
    
    async def on_rpc_connection_failed(self, message: RpcConnectionFailed):
        self.rpc_connected = False
        self.switcher.current = 'home-panel'
        self.post_message(ShowBanner(
            'Failed to connect',
            f'Underlying exception: {str(message.exception)}',
            classes='failure'
        ))
    
    async def poll_controller(self):
        if self.rpc_connected:
            try:
                request = ControllerGetStateStreamRequest(
                    runtime_info=True,
                    field_outputs=True,
                    signals=True
                )
                async for response in self.controller.get_state_stream(
                    request,
                    timeout=RPC_CALL_TIMEOUT,
                    deadline=utils.deadline_from_timeout(RPC_CALL_DEADLINE_POLL)
                ):
                    self.post_message(RpcControllerPoll(response.runtime_info,
                                                        response.field_outputs,
                                                        response.signals))
            except (RpcError, TimeoutError, StreamTerminatedError) as e:
                self.post_message(RpcConnectionLost(e))
    
    async def on_rpc_controller_poll(self, message: RpcControllerPoll):
        self.query(ControllerCycleCount).only_one().cycle_count = message.runtime_info.cycle_count
        self.query(ControllerDurationReadout).only_one().seconds = message.runtime_info.run_seconds
        self.query(ControllerTimeFreeze).only_one().time_freeze = message.runtime_info.time_freeze
        self.query(ControllerCycleMode).only_one().mode = message.runtime_info.cycle_mode
        
        for data in message.field_outputs:
            field_output = self.field_outputs[data.id]
            field_output.value = data.value
        
        for data in message.signals:
            signal = self.signals[data.id]
            signal.title.active = data.active
            signal.title.resting = data.resting
            signal.state.state = data.state.name
            signal.interval_time.elapsed = data.interval_time
            signal.service_time.elapsed = data.service_time
            signal.demand.demand = data.demand
            signal.presence.presence = data.presence
            signal.presence_time.elapsed = data.presence_time
    
    async def on_rpc_connection_success(self, message: RpcConnectionSuccess):
        self.rpc_connected = True
        
        started_at = datetime.fromtimestamp(message.metadata.started_at_epoch)
        
        for field_output_metadata in message.metadata.field_outputs:
            self.field_outputs.update({
                field_output_metadata.id: FieldOutputWidget(
                    f'field-output{field_output_metadata.id}',
                    field_output_metadata.id
                )
            })
        
        for signal_metadata in message.metadata.signals:
            field_outputs = [self.field_outputs[fo] for fo in signal_metadata.field_output_ids]
            self.signals.update({
                signal_metadata.id: SignalWidget(
                    f'signal{signal_metadata.id}',
                    signal_metadata.id,
                    signal_metadata.type,
                    field_outputs
                )
            })
        
        self.refresh(layout=True)
        
        await self.switcher.remove_children('#controller-panel')
        controller_panel = ControllerPanel(
            'controller-panel',
            started_at,
            self.signals.values()
        )
        await self.switcher.add_content(controller_panel, set_current=True)
        
        self.poll_worker = self.run_worker(self.poll_controller(),
                                           group='poller',
                                           exclusive=True)
    
    async def on_rpc_connection_lost(self, message: RpcConnectionLost):
        if self.rpc_connected:
            await self.action_rpc_disconnect()
        self.post_message(ShowBanner(
            'Lost connection',
            f'Underlying exception: {str(message.exception)}',
            classes='advisory'
        ))
    
    async def action_rpc_disconnect(self):
        assert self.rpc_connected
        await self.run_worker(self.rpc_disconnect(), exclusive=True).wait()
    
    async def action_quit(self):
        if self.rpc_connected:
            await self.action_rpc_disconnect()
        self.exit(ExitCode.OK)
    
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        match action:
            case 'rpc_connect':
                return not self.rpc_connected
            case 'rpc_disconnect':
                return self.rpc_connected
            case _:
                return True
