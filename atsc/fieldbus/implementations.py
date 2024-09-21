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
import serial
import asyncio

from jacob.text import format_binary_literal

from atsc.fieldbus.constants import *
from loguru import logger
from typing import Dict, List, Optional
from asyncio import AbstractEventLoop, get_event_loop
from aioserial import AioSerial
from collections import defaultdict
from atsc.fieldbus.hdlc import HDLC_FLAG, Frame, HDLCContext
from atsc.common.structs import Context
from atsc.fieldbus.errors import FieldBusError
from atsc.fieldbus.frames import GenericFrame
from jacob.datetime.timing import millis

from atsc.fieldbus.models import DecodedBusFrame


class SerialBus:
    
    @property
    def hdlc(self):
        return self._hdlc
    
    @property
    def stats(self):
        return self._stats
    
    @property
    def received_frames_count(self):
        return len(self._receive_queue)
    
    def __init__(self,
                 context: Context,
                 port: str,
                 baud: int,
                 enabled: bool = True,
                 loop: AbstractEventLoop = get_event_loop()):
        self._loop = loop or asyncio.get_event_loop()
        self._port = port
        self._baud = baud
        
        try:
            self._serial = AioSerial(port=self._port,
                                     baudrate=self._baud,
                                     loop=self._loop)
            logger.bus('serial bus connected ({})', self._format_param_text())
        except ValueError as e:
            raise FieldBusError('invalid settings configured for serial bus '
                                f'({self._format_param_text()}): {str(e)}')
        except serial.SerialException as e:
            raise FieldBusError(f'serial bus error: {str(e)}')
        
        self._hdlc = HDLCContext(SERIAL_BUS_CRC_POLY,
                                 SERIAL_BUS_CRC_INIT,
                                 SERIAL_BUS_CRC_REVERSE,
                                 SERIAL_BUS_CRC_XOR_OUT,
                                 byte_order=SERIAL_BUS_BYTE_ORDER)
        
        self.context = context
        self.enabled = enabled
        self.frames_unread = asyncio.Condition()
        
        self._transmit_queue: List[GenericFrame] = []
        self._receive_queue: List[DecodedBusFrame] = []
        self._stats: Dict[int, dict] = defaultdict(self._stats_populator)
    
    def _stats_populator(self) -> dict:
        tx_map: Dict[FrameType, List[int, Optional[int]]] = {}
        
        for ft in FrameType:
            tx_map.update({ft: [0, None]})
        
        rx_map: Dict[FrameType, List[int, Optional[int]]] = {}
        
        for ft in FrameType:
            rx_map.update({ft: [0, None]})
        
        return {
            'tx_bytes': 0, 'rx_bytes': 0, 'tx_frames': tx_map, 'rx_frames': rx_map
        }
    
    def _update_rx_stats(self, f: Frame):
        data = f.data
        size = len(data)
        addr = data[0]
        try:
            da = DeviceAddress(addr)
        except ValueError:
            da = DeviceAddress.UNKNOWN
        self._stats[addr]['rx_bytes'] += size
        
        if size >= 3:
            type_number = data[2]
            try:
                ft = FrameType(type_number)
            except ValueError:
                ft = FrameType.UNKNOWN
            
            self._stats[addr]['rx_frames'][ft][0] += 1
            self._stats[addr]['rx_frames'][ft][1] = millis()
    
    def _format_param_text(self):
        return f'port={self._port}, baud={self._baud}'
    
    def enqueue_frame(self, f: GenericFrame):
        self._transmit_queue.append(f)
    
    async def transmit(self):
        while True:
            if self.enabled and self._serial.is_open:
                if self._transmit_queue:
                    for f in self._transmit_queue:
                        try:
                            self._stats[f.address]['tx_frames'][f.type][0] += 1
                            self._stats[f.address]['tx_frames'][f.type][1] = millis()
                            
                            payload = f.build(self._hdlc)
                            await self._serial.write_async(payload)
                            
                            self._stats[0]['tx_bytes'] += len(payload)
                            logger.bus('sent frame type {} to {} ({}B)',
                                       f.type.name,
                                       f.address,
                                       len(payload))
                            logger.bus_tx(format_binary_literal(payload[:32]))
                        except serial.SerialTimeoutException:
                            pass
                        except serial.SerialException as e:
                            raise FieldBusError(f'serial bus error: {str(e)}')
                    self._transmit_queue.clear()
                else:
                    await asyncio.sleep(self.context.delay)
            else:
                await asyncio.sleep(self.context.delay)
    
    async def receive(self):
        inside_frame = False
        drydock = bytearray()
        adjacent_flags = 0
        while True:
            if self.enabled and self._serial.is_open:
                try:
                    byte = await self._serial.read_async()
                    if ord(byte) == HDLC_FLAG:
                        adjacent_flags += 1
                        if adjacent_flags > 1 or inside_frame:
                            frame, error = self._hdlc.decode(drydock)
                            
                            if error is not None:
                                logger.bus('framing error {}', error.name)
                            else:
                                self._stats[0]['rx_bytes'] += len(drydock)
                                self._update_rx_stats(frame)
                                decoded_frame = self.decode_frame(frame)
                                self._receive_queue.append(decoded_frame)
                                async with self.frames_unread:
                                    self.frames_unread.notify_all()
                            
                            inside_frame = False
                            drydock.clear()
                            adjacent_flags = 0
                        else:
                            inside_frame = True
                    else:
                        drydock.extend(byte)
                        adjacent_flags = 0
                except serial.SerialTimeoutException:
                    pass
                except serial.SerialException as e:
                    raise FieldBusError(f'serial bus error: {str(e)}')
            else:
                await asyncio.sleep(self.context.delay)
    
    def decode_frame(self, frame: Frame):
        length = len(frame.data)
        addr = frame.data[0]
        try:
            da = DeviceAddress(addr)
        except ValueError:
            da = DeviceAddress.UNKNOWN
        
        self._stats[addr]['rx_bytes'] += length
        
        if length >= 3:
            control = frame.data[1]
            type_number = frame.data[2]
            try:
                ft = FrameType(type_number)
            except ValueError:
                ft = FrameType.UNKNOWN
            
            payload = frame.data[3:]
            
            logger.bus(f'received frame type {ft.name} from {da} ({length}B)')
            logger.bus_rx(format_binary_literal(frame.data[:32]))
            
            self._stats[addr]['rx_frames'][ft][0] += 1
            self._stats[addr]['rx_frames'][ft][1] = millis()
            
            return DecodedBusFrame(addr,
                                   control,
                                   ft,
                                   payload,
                                   frame.crc,
                                   length)
    
    def process_frames(self):
        for frame in iter(self._receive_queue):
            yield frame
        self._receive_queue.clear()
    
    def close(self):
        self.enabled = False
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
