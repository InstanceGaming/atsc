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
from atsc.fieldbus.constants import *
from grpc import RpcError
from loguru import logger
from typing import List, Iterator, Optional
from asyncio import AbstractEventLoop, get_event_loop
from atsc.rpc import controller
from aioserial import AioSerial
from jacob.text import format_binary_literal
from collections import Counter
from grpclib.metadata import Deadline
from atsc.common.models import AsyncDaemon
from atsc.fieldbus.hdlc import HDLC_FLAG, Frame, HDLCContext
from atsc.common.structs import Context
from atsc.fieldbus.errors import FieldBusError
from atsc.fieldbus.frames import GenericFrame, OutputStateFrame
from atsc.fieldbus.models import DecodedBusFrame
from atsc.common.constants import DAEMON_SHUTDOWN_TIMEOUT


class FieldBus(AsyncDaemon):
    
    @property
    def hdlc(self):
        return self._hdlc
    
    @property
    def received_frames_count(self):
        return len(self._receive_queue)
    
    def __init__(self,
                 context: Context,
                 controller_rpc: controller.ControllerStub,
                 serial_port: str,
                 baud: int,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        AsyncDaemon.__init__(self,
                             context,
                             shutdown_timeout=shutdown_timeout,
                             pid_file=pid_file,
                             loop=loop)
        self._controller = controller_rpc
        self._port = serial_port
        self._baud = baud
        
        try:
            self._serial = AioSerial(port=self._port,
                                     baudrate=self._baud,
                                     loop=self.loop)
            logger.bus('serial bus rpc_connected ({})', self._format_param_text())
        except ValueError as e:
            raise FieldBusError('invalid settings configured for serial bus '
                                f'({self._format_param_text()}): {str(e)}')
        except serial.SerialException as e:
            raise FieldBusError(f'serial bus error: {str(e)}')
        
        self._hdlc = HDLCContext(HDLC_CRC_POLY,
                                 HDLC_CRC_INIT,
                                 HDLC_CRC_REVERSE,
                                 HDLC_CRC_XOR_OUT,
                                 byte_order=BUS_BYTE_ORDER)
        
        self.frames_unread = asyncio.Condition()
        
        self.routines.extend((
            self.poll_controller(),
            self.transmit(),
            self.receive()
        ))
        
        self._transmit_queue: List[GenericFrame] = []
        self._receive_queue: List[DecodedBusFrame] = []
        self._counters = Counter({
            'tx_bytes': 0,
            'tx_frames': 0,
            'rx_bytes': 0,
            'rx_frames': 0
        })
    
    async def after_run(self):
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        await super().after_run()
    
    def _format_param_text(self):
        return f'port={self._port}, baud={self._baud}'
    
    def enqueue_frame(self, f: GenericFrame):
        self._transmit_queue.append(f)
    
    async def poll_controller(self):
        while True:
            try:
                request = controller.ControllerFieldOutputsRequest()
                response = await self._controller.get_field_outputs(request, deadline=Deadline.from_timeout(0.2))
                
                frame = OutputStateFrame(DeviceAddress.TFIB1, response.field_outputs, True)
                self.enqueue_frame(frame)
            except RpcError as e:
                logger.error('rpc error: {}', str(e))
            await asyncio.sleep(self.context.delay)
    
    async def transmit(self):
        while True:
            if not self._serial.is_open or not self._transmit_queue:
                await asyncio.sleep(BUS_TRANSMIT_POLL_RATE)
            
            for f in self._transmit_queue:
                try:
                    payload = f.build(self._hdlc)
                    await self._serial.write_async(payload)
                    
                    self._counters['tx_bytes'] += len(payload)
                    self._counters['tx_frames'] += 1
                    
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
            
            await asyncio.sleep(BUS_TRANSMIT_POLL_RATE)
    
    async def receive(self):
        inside_frame = False
        drydock = bytearray()
        adjacent_flags = 0
        while True:
            if not self._serial.is_open:
                await asyncio.sleep(BUS_RECEIVE_POLL_RATE)
            
            async with self.frames_unread:
                try:
                    byte = await self._serial.read_async()
                    if ord(byte) == HDLC_FLAG:
                        adjacent_flags += 1
                        if adjacent_flags > 1 or inside_frame:
                            frame, error = self._hdlc.decode(drydock)
                            
                            if error is not None:
                                logger.bus('framing error {}', error.name)
                            else:
                                self._counters['rx_bytes'] += len(drydock)
                                decoded_frame = self.decode_frame(frame)
                                self._receive_queue.append(decoded_frame)
                                self.frames_unread.notify()
                            
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
            
            await asyncio.sleep(BUS_RECEIVE_POLL_RATE)
    
    def decode_frame(self, frame: Frame):
        length = len(frame.data)
        addr = frame.data[0]
        try:
            da = DeviceAddress(addr)
        except ValueError:
            da = DeviceAddress.UNKNOWN
        
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
            
            self._counters['rx_frames'] += 1
            
            return DecodedBusFrame(addr,
                                   control,
                                   ft,
                                   payload,
                                   frame.crc,
                                   length)
    
    def process_frames(self) -> Iterator[DecodedBusFrame]:
        for frame in iter(self._receive_queue):
            yield frame
        self._receive_queue.clear()
