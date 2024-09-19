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
import abc
import math
from typing import List, Union, Optional
from bitarray import bitarray
from atsc.fieldbus.hdlc import HDLCContext
from atsc.controller.models import FieldOutput
from atsc.fieldbus.constants import FrameType


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

        :return: PrettyByteArray
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
    
    def __init__(self,
                 address: int,
                 fields: List[FieldOutput],
                 transfer: bool):
        super(OutputStateFrame, self).__init__(address, self.VERSION, FrameType.OUTPUTS, FrameType.INPUTS)
        self._fields = fields
        self._transfer = transfer
    
    def getPayload(self):
        bytes_count = math.ceil(len(self._fields) / 6)
        payload = bytearray([128 if self._transfer else 0] + ([0] * bytes_count))
        
        i = 0
        for byte in range(bytes_count):
            for bit in (64, 32, 16, 4, 2, 1):
                field = self._fields[i]
                if field is not None:
                    payload[byte + 1] += int(field) * bit
                i += 1
        
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
