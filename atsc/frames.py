#  Copyright 2022 Jacob Jewett
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

import abc
import enum
from typing import List, Union, Optional
from bitarray import bitarray
from atsc.core import LoadSwitch
from atsc.hdlc import HDLCContext


class DeviceAddress(enum.IntEnum):
    UNKNOWN = 0x00
    CONTROLLER = 0xFF
    TFIB1 = 0x08


class FrameType(enum.IntEnum):
    UNKNOWN = 0
    AWK = 1
    NAK = 2
    IGN = 3
    BEACON = 4
    OUTPUTS = 16
    INPUTS = 32


class GenericFrame(abc.ABC):
    
    @property
    def address(self):
        return self._address
    
    @property
    def type(self):
        return self._type
    
    @property
    def awk_type(self):
        return self._awk_type
    
    def __init__(self, address: int, fr_version: int, fr_type: FrameType, awk_type: Optional[FrameType]):
        self._address = address
        self._version = fr_version
        self._type = fr_type
        self._awk_type = awk_type
    
    def getHeader(self) -> bytearray:
        """
        Get the bytes that form the header structure.

        :return: ByteArray
        """
        return bytearray([self._address, self._version, self._type])
    
    @abc.abstractmethod
    def getPayload(self) -> bytearray:
        """
        Get the data to be included after the header in the frame.
        """
        pass
    
    def getContent(self) -> bytearray:
        """
        Get the bytes that form the overall frame data.
        """
        header = self.getHeader()
        payload = self.getPayload()
        
        if payload is not None:
            header.extend(payload)
        
        return header
    
    def build(self, hdlc: HDLCContext) -> bytes:
        """
        Build an HDLC frame.

        :return: Frame bytes
        """
        return hdlc.encode(self.getContent())
    
    def __repr__(self):
        return f'<GenericFrame type={self._type} address={self._address} ' \
               f'V{self._version}>'


class BeaconFrame(GenericFrame):
    VERSION = 11
    
    def __init__(self, address: int):
        super(BeaconFrame, self).__init__(address, self.VERSION, FrameType.BEACON, FrameType.AWK)
    
    def getPayload(self):
        return None


class OutputStateFrame(GenericFrame):
    VERSION = 11
    
    def __init__(self, address: int, lss: List[LoadSwitch], transfer: bool):
        super(OutputStateFrame, self).__init__(address, self.VERSION, FrameType.OUTPUTS, FrameType.INPUTS)
        assert len(lss) == 12
        self._channel_states = lss
        self._transfer = transfer
    
    def getPayload(self):
        sf = bytearray([0] * 6)
        ci = 0
        for i in range(6):
            l = self._channel_states[ci]
            sf[i] += l.a * 64
            sf[i] += l.b * 32
            sf[i] += l.c * 16
            r = self._channel_states[ci + 1]
            sf[i] += r.a * 4
            sf[i] += r.b * 2
            sf[i] += r.c * 1
            ci += 2
        
        payload = bytearray([128 if self._transfer else 0])
        payload.extend(sf)
        
        return payload


class InputStateFrame(GenericFrame):
    VERSION = 11
    
    @property
    def bitfield(self):
        return self._bitfield
    
    def __init__(self, address: int, bf: Union[bitarray, bytearray]):
        if isinstance(bf, bytearray):
            bitfield = bitarray()
            bitfield.frombytes(bytes(bf))
        else:
            bitfield = bf
        
        super(InputStateFrame, self).__init__(address, self.VERSION, FrameType.INPUTS, None)
        
        self._bitfield: bitarray = bitfield
    
    def getPayload(self):
        return self._bitfield
