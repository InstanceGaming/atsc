import asyncio
from grpc import RpcError
from typing import Optional
from pathlib import Path

from grpclib.exceptions import StreamTerminatedError
from textual.app import App, ComposeResult
from grpclib.client import Channel
from textual.worker import Worker
from textual.widgets import Footer, Header
from grpclib.metadata import Deadline
from textual.reactive import reactive

from atsc.tui.components import MainContentSwitcher, Banner
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
from atsc.tui.constants import (
    CONTROLLER_POLL_RATE,
    RPC_CALL_DEADLINE_TIMEOUT,
    RPC_CALL_DEADLINE_TIMEOUT_POLL
)
from atsc.rpc.controller import (
    ControllerStub,
    ControllerMetadataRequest,
    ControllerRuntimeInfoRequest,
    ControllerFieldOutputsRequest, ControllerSignalsRequest
)
from atsc.rpc.signal import Signal as rpc_Signal
from atsc.common.constants import ExitCode
from atsc.tui.panels import ControllerPanel
from atsc.tui.widgets import ControllerRuntime, Signal


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
        super().__init__(css_path=stylesheet_path, watch_css=dev_mode)
        # noinspection PyTypeChecker
        self.title = 'Actuated Traffic Signal Controller'
        self.rpc_address = rpc_address
        self.rpc_port = rpc_port
        
        self.channel: Optional[Channel] = None
        self.controller: Optional[ControllerStub] = None
        
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
        await self.mount(banner, after=0)
    
    async def rpc_connect(self):
        try:
            metadata = await self.controller.get_metadata(
                ControllerMetadataRequest(),
                deadline=Deadline.from_timeout(RPC_CALL_DEADLINE_TIMEOUT)
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
    
    async def on_rpc_connection_before(self, message: RpcConnectionBefore):
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
        while self.rpc_connected:
            try:
                runtime_info = await self.controller.get_runtime_info(
                    ControllerRuntimeInfoRequest(),
                    deadline=Deadline.from_timeout(RPC_CALL_DEADLINE_TIMEOUT_POLL)
                )
                field_outputs_reply = await self.controller.get_field_outputs(
                    ControllerFieldOutputsRequest(),
                    deadline=Deadline.from_timeout(RPC_CALL_DEADLINE_TIMEOUT_POLL)
                )
                signal_reply = await self.controller.get_signals(ControllerSignalsRequest())
                self.post_message(RpcControllerPoll(runtime_info,
                                                    field_outputs_reply.field_outputs,
                                                    signal_reply.signals))
                await asyncio.sleep(CONTROLLER_POLL_RATE)
            except (RpcError, TimeoutError, StreamTerminatedError) as e:
                self.post_message(RpcConnectionLost(e))
                break
                
    async def on_rpc_controller_poll(self, message: RpcControllerPoll):
        for runtime in self.query(ControllerRuntime).results():
            runtime.run_seconds = message.runtime_info.run_seconds
        
        signal: Signal
        signal_data: rpc_Signal
        for signal, signal_data in zip(self.query(Signal).results(), message.signals):
            signal.state = signal_data.state.name
            signal.interval_time = signal_data.interval_time
            signal.service_time = signal_data.service_time
            signal.resting = signal_data.resting
            signal.demand = signal_data.demand
            signal.presence = signal_data.presence
    
    async def on_rpc_connection_success(self, message: RpcConnectionSuccess):
        self.rpc_connected = True
        
        await self.switcher.remove_children('#controller-panel')
        controller_panel = ControllerPanel(
            'controller-panel',
            field_output_count=message.metadata.supported_field_outputs,
            signal_count=message.metadata.supported_signals,
            phase_count=message.metadata.supported_phases
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
