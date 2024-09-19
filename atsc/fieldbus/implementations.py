import serial
import asyncio
from atsc.fieldbus.constants import *
from loguru import logger
from typing import Dict, List, Optional
from asyncio import AbstractEventLoop, get_event_loop
from aioserial import AioSerial
from collections import defaultdict
from atsc.fieldbus.errors import FieldBusError
from atsc.fieldbus.hdlc import HDLC_FLAG, Frame, HDLCContext
from atsc.common.structs import Context
from atsc.fieldbus.frames import GenericFrame
from jacob.datetime.timing import millis


class SerialBus:
    
    @property
    def hdlc(self):
        return self._hdlc
    
    @property
    def stats(self):
        return self._stats
    
    @property
    def received_frames_count(self):
        return len(self._received_frames)
    
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
        self.frames_ready = asyncio.Condition()
        
        self._transmit_frames: List[GenericFrame] = []
        self._receive_buffer = bytearray()
        self._received_frames: List[Frame] = []
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
            
            logger.bus('received frame type {} from {} ({}B)',
                       ft.name,
                       da,
                       size)
            
            self._stats[addr]['rx_frames'][ft][0] += 1
            self._stats[addr]['rx_frames'][ft][1] = millis()
    
    def _format_param_text(self):
        return f'port={self._port}, baud={self._baud}'
    
    async def transmit(self):
        while True:
            if self.enabled and self._serial.is_open:
                for f in self._transmit_frames:
                    try:
                        self._stats[f.address]['tx_frames'][f.type][0] += 1
                        self._stats[f.address]['tx_frames'][f.type][1] = millis()
                        
                        payload = f.build(self._hdlc)
                        logger.bus('sent frame type {} to {} ({}B)',
                                   f.type.name,
                                   f.address,
                                   len(payload))
                        
                        await self._serial.write_async(payload)
                        self._stats[0]['tx_bytes'] += len(payload)
                    except serial.SerialTimeoutException:
                        pass
                    except serial.SerialException as e:
                        raise FieldBusError(f'serial bus error: {str(e)}')
                self._transmit_frames.clear()
            
            await asyncio.sleep(self.context.delay)
    
    def enqueue_frame(self, f: GenericFrame):
        addr = f.address
        
        addr_name = None
        try:
            addr_name = DeviceAddress(addr).name
        except ValueError:
            pass
        
        logger.bus('frame {} to {} payload',
                   f.type.name,
                   addr_name or addr)
        self._transmit_frames.append(f)
    
    def iter_frame(self):
        return iter(self._received_frames)
    
    async def receive(self):
        while True:
            if self.enabled and self._serial.is_open:
                async with self.frames_ready:
                    try:
                        bytes_count_received = await self._serial.readinto_async(self._receive_buffer)
                        
                        if bytes_count_received:
                            inside_frame = False
                            drydock = bytearray()
                            
                            for byte in self._receive_buffer:
                                if byte == HDLC_FLAG:
                                    if inside_frame:
                                        inside_frame = False
                                        
                                        frame, error = self._hdlc.decode(drydock)
                                        
                                        if error is not None:
                                            logger.bus('framing error {}', error.name)
                                        else:
                                            self._stats[0]['rx_bytes'] += len(drydock)
                                            self._update_rx_stats(frame)
                                            self._received_frames.append(frame)
                                            self.frames_ready.notify_all()
                                        
                                        drydock = bytearray()
                                    else:
                                        inside_frame = True
                                else:
                                    drydock.append(byte)
                            
                            self._receive_buffer.clear()
                    except serial.SerialTimeoutException:
                        pass
                    except serial.SerialException as e:
                        raise FieldBusError(f'serial bus error: {str(e)}')
        
            await asyncio.sleep(self.context.delay)
    
    def close(self):
        self.enabled = False
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
