from dataclasses import dataclass

from atsc.fieldbus.constants import FrameType


@dataclass(frozen=True)
class DecodedBusFrame:
    address: int
    control: int
    type: FrameType
    payload: bytes
    crc: int
    length: int
