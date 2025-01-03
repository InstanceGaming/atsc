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
import blinker
from atsc.fieldbus.constants import *
from grpc import RpcError
from loguru import logger
from typing import List, Optional
from atsc.rpc import controller
from aioserial import AioSerial
from jacob.text import format_binary_literal
from atsc.common import utils
from collections import Counter
from atsc.common.models import AsyncDaemon
from atsc.fieldbus.hdlc import HDLC_FLAG, Frame, HDLCContext
from grpclib.exceptions import StreamTerminatedError
from atsc.fieldbus.errors import FieldBusError
from atsc.fieldbus.frames import GenericFrame, OutputStateFrame
from atsc.fieldbus.models import DecodedBusFrame
from atsc.common.constants import (
    RPC_CALL_TIMEOUT,
    FLOAT_PRECISION_TIME,
    RPC_CALL_DEADLINE_POLL,
    DAEMON_SHUTDOWN_TIMEOUT
)
from atsc.controller.constants import POLL_RATE
from atsc.controller.primitives import AsyncStopwatch


class FieldBus(AsyncDaemon):
    
    @property
    def hdlc(self):
        return self._hdlc
    
    def __init__(self,
                 loop: asyncio.AbstractEventLoop,
                 serial_port: str,
                 baud: int,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 truncate_field_outputs: Optional[int] = None):
        AsyncDaemon.__init__(self,
                             loop,
                             shutdown_timeout=shutdown_timeout,
                             pid_file=pid_file)
        self._port = serial_port
        self._baud = baud
        self._truncate_field_outputs = truncate_field_outputs
        
        self.received_frame = blinker.Signal()
        
        try:
            self._serial = AioSerial(port=self._port,
                                     baudrate=self._baud,
                                     loop=self.loop)
            logger.info('serial bus connected ({})', self._format_param_text())
        except ValueError as e:
            raise FieldBusError('invalid settings configured for serial bus '
                                f'({self._format_param_text()}): {str(e)}')
        except serial.SerialException as e:
            raise FieldBusError(f'serial bus error: {str(e)}')
        except PermissionError:
            raise FieldBusError(f'insufficient permission for serial device {self._port}')
        
        self._hdlc = HDLCContext(HDLC_CRC_POLY,
                                 HDLC_CRC_INIT,
                                 HDLC_CRC_REVERSE,
                                 HDLC_CRC_XOR_OUT,
                                 byte_order=BUS_BYTE_ORDER)
        
        self.add_task(self.transmit())
        self.add_task(self.receive())
        
        self._transmit_queue: List[GenericFrame] = []
        self._counters = Counter({
            'tx_bytes' : 0,
            'tx_frames': 0,
            'rx_bytes' : 0,
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
    
    async def transmit_now(self, f: GenericFrame):
        try:
            payload = f.build(self._hdlc)
            
            transmit_task = asyncio.create_task(self._serial.write_async(payload))
            await asyncio.wait_for(transmit_task, timeout=POLL_RATE)
            
            self._counters['tx_bytes'] += len(payload)
            self._counters['tx_frames'] += 1
            
            logger.verbose('sent frame type {} to {} ({}B)',
                           f.type.name,
                           f.address,
                           len(payload))
            logger.trace(format_binary_literal(payload[:32]))
        except (serial.SerialTimeoutException, TimeoutError):
            pass
        except serial.SerialException as e:
            raise FieldBusError(f'serial bus error while transmitting: {str(e)}')
    
    async def transmit(self):
        try:
            while True:
                if not self._serial.is_open or not self._transmit_queue:
                    await asyncio.sleep(POLL_RATE)
                
                frames_to_send = len(self._transmit_queue)
                frames_sent = 0
                
                for f in self._transmit_queue:
                    await self.transmit_now(f)
                    frames_sent += 1
                self._transmit_queue.clear()
                
                if frames_sent < frames_to_send:
                    logger.debug('{} frames discarded without transmit',
                                 frames_to_send - frames_sent)
        except asyncio.CancelledError:
            pass
    
    async def receive(self):
        inside_frame = False
        drydock = bytearray()
        adjacent_flags = 0
        
        try:
            while True:
                try:
                    if not self._serial.is_open:
                        await asyncio.sleep(POLL_RATE)
                    
                    byte = await self._serial.read_async()
                    if ord(byte) == HDLC_FLAG:
                        adjacent_flags += 1
                        if adjacent_flags > 1 or inside_frame:
                            frame, error = self._hdlc.decode(drydock)
                            
                            if error is not None:
                                logger.debug('framing error {}', error.name)
                            else:
                                self._counters['rx_bytes'] += len(drydock)
                                decoded_frame = self.decode_frame(frame)
                                self.received_frame.send(self, decoded_frame=decoded_frame)
                            
                            inside_frame = False
                            drydock.clear()
                            adjacent_flags = 0
                        else:
                            inside_frame = True
                    else:
                        drydock.extend(byte)
                        adjacent_flags = 0
                except serial.SerialTimeoutException:
                    await asyncio.sleep(POLL_RATE)
                except serial.SerialException as e:
                    raise FieldBusError(f'serial bus error: {str(e)}')
        except asyncio.CancelledError:
            pass
    
    def decode_frame(self, frame: Frame):
        length = len(frame.data)
        if length >= 3:
            addr = frame.data[0]
            try:
                da = DeviceAddress(addr)
            except ValueError:
                da = DeviceAddress.UNKNOWN
            
            control = frame.data[1]
            type_number = frame.data[2]
            try:
                ft = FrameType(type_number)
            except ValueError:
                ft = FrameType.UNKNOWN
            
            payload = frame.data[3:]
            
            logger.verbose(f'received frame type {ft.name} from {da} ({length}B)')
            logger.trace(format_binary_literal(frame.data))
            
            self._counters['rx_frames'] += 1
            
            return DecodedBusFrame(addr,
                                   control,
                                   ft,
                                   payload,
                                   frame.crc,
                                   length)


class ControllerFieldBus(FieldBus):
    
    def __init__(self,
                 loop: asyncio.AbstractEventLoop,
                 controller_rpc: controller.ControllerStub,
                 poll_rate: float,
                 serial_port: str,
                 baud: int,
                 shutdown_timeout: float = DAEMON_SHUTDOWN_TIMEOUT,
                 pid_file: Optional[str] = None,
                 truncate_field_outputs: Optional[int] = None):
        super().__init__(loop,
                         serial_port=serial_port,
                         baud=baud,
                         shutdown_timeout=shutdown_timeout,
                         pid_file=pid_file,
                         truncate_field_outputs=truncate_field_outputs)
        self.controller = controller_rpc
        self.poll_rate = round(max(POLL_RATE, poll_rate), FLOAT_PRECISION_TIME)
        self.response_stopwatch = AsyncStopwatch()
        
        self.add_task(self.poll_controller())
        self.received_frame.connect(self.frame_handler, sender=self)
    
    async def poll_controller(self):
        try:
            request = controller.ControllerGetStateStreamRequest(
                poll_rate=self.poll_rate,
                field_outputs=True
            )
            async for response in self.controller.get_state_stream(
                request,
                timeout=RPC_CALL_TIMEOUT,
                deadline=utils.deadline_from_timeout(RPC_CALL_DEADLINE_POLL)
            ):
                logger.verbose('{:01.3f}s since last controller state message',
                               self.response_stopwatch.elapsed)
                self.response_stopwatch.reset()
                
                if self._truncate_field_outputs:
                    field_outputs = response.field_outputs[:self._truncate_field_outputs]
                else:
                    field_outputs = response.field_outputs
                
                frame = OutputStateFrame(DeviceAddress.TFIB1, field_outputs, True)
                
                await self.transmit_now(frame)
        except (RpcError,
                TimeoutError,
                StreamTerminatedError,
                OSError) as e:
            logger.error('rpc error: {}', str(e))
        except asyncio.CancelledError:
            pass
    
    def frame_handler(self, _, decoded_frame: DecodedBusFrame):
        logger.verbose('handled frame type {}', decoded_frame.type)
