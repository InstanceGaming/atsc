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
import crcmod
from atsc.fieldbus.constants import *
from typing import Tuple, Optional
from jacob.text import format_byte_size, format_binary_literal


class Frame:
    
    @property
    def data(self):
        return self._data
    
    @property
    def crc(self):
        return self._crc
    
    def __init__(self, data: bytes, crc: int):
        self._data = data
        self._crc = crc
    
    def __eq__(self, other):
        if other is None:
            return False
        
        return self._crc == other.crc
    
    def __repr__(self):
        return f'<Frame {format_binary_literal(self._data)} CRC{self._crc:05d} ' \
               f'{format_byte_size(len(self._data))}>'


class HDLCContext:
    
    def __init__(self, polynomial: int, initial: int, reverse: bool, xor_out: int, byte_order='big'):
        self._crc_func = crcmod.mkCrcFun(polynomial, initial, reverse, xor_out)
        self._order = byte_order
    
    def encode(self, data: bytes, frame=True) -> bytearray:
        """
        Encode bytes into HDLC format.

        :param data: bytes
        :param frame: include the start and end flag bytes to form a valid frame
        :return: bytes
        """
        # calculate 16-bit checksum
        crc_number = self._crc_func(data)
        
        # append checksum to data
        data += crc_number.to_bytes(2, byteorder=self._order)
        
        # create a new buffer to hold the start flag, escaped data and end flag
        escaped = bytearray()
        
        if frame:
            # add start flag
            escaped.append(HDLC_FLAG)
        
        # escape data
        for b in data:
            # if the byte happens to be HDLC_FLAG or HDLC_ESCAPE,
            # add the escape marker and then the masked byte
            if b == HDLC_FLAG or b == HDLC_ESCAPE:
                # inject ESCAPE_OCTET
                escaped.append(HDLC_ESCAPE)
                # mask original byte with ESCAPE_MASK
                b ^= HDLC_ESCAPE_MASK
            escaped.append(b)
        
        if frame:
            # add end flag
            escaped.append(HDLC_FLAG)
        
        return escaped
    
    def decode(self, data: bytes, max_length=256) -> Tuple[Optional[Frame], Optional[HDLCError]]:
        """
        Decode captured bytes into an HDLC frame.

        :param data: the sequence of bytes captured between opening and
                     closing flag bytes
        :param max_length: error if frame length exceeds this many bytes
        :return: Frame instance or None if error, error enum
        """
        
        error = HDLCError.UNKNOWN
        frame = None
        length = len(data)
        
        if max_length and length > max_length:
            # frame is longer than allowed
            error = HDLCError.TOO_LONG
        elif length == 0:
            error = HDLCError.NO_DATA
        elif length < 2:
            # frame is too small to even have CRC bytes
            error = HDLCError.NO_CRC
        elif length == 2:
            # frame has the CRC bytes but nothing else
            error = HDLCError.EMPTY
        else:
            # unescape all bytes
            process = True
            escaping = False
            unescaped_bytes = bytearray()
            for i, b in enumerate(data):
                # instant abort if HDLC_FLAG is found
                if b == HDLC_FLAG:
                    process = False
                    error = HDLCError.FLAG
                    break
                
                # skip current char if escaping (once)
                if escaping:
                    # unmask the byte to its original form
                    unescaped_bytes.append(b ^ HDLC_ESCAPE_MASK)
                    # done escaping, can skip to next byte
                    escaping = False
                    continue
                
                if b == HDLC_ESCAPE:
                    # the next byte needs to be unescaped
                    # which could be either 0x7E or 0x7D
                    escaping = True
                else:
                    # by default, consider the current byte already unescaped
                    unescaped_bytes.append(b)
            
            if process:
                # get section of bytes that form the original data
                content_bytes = bytes(unescaped_bytes[:-2])
                
                # calculate our own CRC from the unescaped data to compare
                local_crc = self._crc_func(content_bytes)
                
                # get the last two bytes that form the CRC
                crc_bytes = unescaped_bytes[-2:]
                
                # transform the CRC bytes into an integer
                # noinspection PyTypeChecker
                remote_crc = int.from_bytes(crc_bytes, byteorder=self._order)
                
                # check for CRC match
                if local_crc != remote_crc:
                    error = HDLCError.BAD_CRC
                else:
                    error = None
                    frame = Frame(content_bytes, local_crc)
        
        return frame, error
