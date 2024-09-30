from typing import List

from textual.message import Message
from atsc.rpc.controller import (
    ControllerMetadataReply,
    ControllerRuntimeInfoReply,
    ControllerFieldOutputsReply, ControllerSignalsReply
)
from atsc.rpc.field_output import FieldOutput
from atsc.rpc.signal import Signal


class ShowBanner(Message):
    
    def __init__(self,
                 title: str,
                 description: str | None = None,
                 classes: str | None = None,
                 timeout: float = 0.0):
        super().__init__()
        self.title = title
        self.description = description
        self.classes = classes
        self.timeout = timeout


class RpcConnectionBefore(Message):
    pass


class RpcConnectionFailed(Message):
    
    def __init__(self, exception: Exception):
        self.exception = exception
        super().__init__()


class RpcConnectionSuccess(Message):
    
    def __init__(self, metadata: ControllerMetadataReply):
        super().__init__()
        self.metadata = metadata


class RpcConnectionAfter(Message):
    pass


class RpcConnectionLost(Message):
    
    def __init__(self, exception: Exception):
        super().__init__()
        self.exception = exception


class RpcDisconnectAfter(Message):
    pass


class RpcControllerPoll(Message):
    
    def __init__(self,
                 runtime_info: ControllerRuntimeInfoReply,
                 field_outputs: List[FieldOutput],
                 signals: List[Signal]):
        super().__init__()
        self.runtime_info = runtime_info
        self.field_outputs = field_outputs
        self.signals = signals
