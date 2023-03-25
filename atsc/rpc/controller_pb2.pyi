from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor
MODE_CET: ControlMode
MODE_CXT: ControlMode
MODE_LS_FLASH: ControlMode
MODE_NORMAL: ControlMode
MODE_OFF: ControlMode
MODE_UNKNOWN: ControlMode

class StatusRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ["avg_demand", "control_time", "mode", "peek_demand", "plan_id", "runtime", "state_flags", "transfer_count"]
    AVG_DEMAND_FIELD_NUMBER: _ClassVar[int]
    CONTROL_TIME_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    PEEK_DEMAND_FIELD_NUMBER: _ClassVar[int]
    PLAN_ID_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    STATE_FLAGS_FIELD_NUMBER: _ClassVar[int]
    TRANSFER_COUNT_FIELD_NUMBER: _ClassVar[int]
    avg_demand: float
    control_time: int
    mode: ControlMode
    peek_demand: float
    plan_id: int
    runtime: int
    state_flags: int
    transfer_count: int
    def __init__(self, mode: _Optional[_Union[ControlMode, str]] = ..., state_flags: _Optional[int] = ..., plan_id: _Optional[int] = ..., avg_demand: _Optional[float] = ..., peek_demand: _Optional[float] = ..., runtime: _Optional[int] = ..., control_time: _Optional[int] = ..., transfer_count: _Optional[int] = ...) -> None: ...

class ControlMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
