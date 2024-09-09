import serial
import asyncio
from atsc.fieldbus.constants import *
from loguru import logger
from typing import Dict, List, Optional
from asyncio import AbstractEventLoop, get_event_loop
from aioserial import AioSerial
from jacob.text import format_binary_literal
from collections import defaultdict
from atsc.common.models import AsyncDaemon
from atsc.fieldbus.hdlc import HDLC_FLAG, Frame, HDLCContext
from atsc.common.structs import Context
from atsc.fieldbus.frames import GenericFrame, OutputStateFrame
from jacob.datetime.timing import millis


class SerialBus(AsyncDaemon):
    
    @property
    def hdlc(self):
        return self._hdlc
    
    @property
    def stats(self):
        return self._stats
    
    def __init__(self,
                 context: Context,
                 port: str,
                 baud: int,
                 shutdown_timeout: float = 5.0,
                 pid_file: Optional[str] = None,
                 loop: AbstractEventLoop = get_event_loop()):
        super().__init__(context, shutdown_timeout, pid_file, loop)
        
        self.loop = loop or asyncio.get_event_loop()
        self.enabled = True
        self._tick = asyncio.Event()
        self._changed = asyncio.Event()
        self._tx_lock = asyncio.Lock()
        self._port = port
        self._baud = baud
        self._hdlc = HDLCContext(SERIAL_BUS_CRC_POLY,
                                 SERIAL_BUS_CRC_INIT,
                                 SERIAL_BUS_CRC_REVERSE,
                                 SERIAL_BUS_CRC_XOR_OUT,
                                 byte_order=SERIAL_BUS_BYTE_ORDER)
        
        self._serial = None
        self._rx_buf: Optional[Frame] = None
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
    
    async def _write(self, data: bytes):
        try:
            await self._serial.write_async(data)
            self._stats[0]['tx_bytes'] += 1
        except serial.SerialTimeoutException:
            pass
        except serial.SerialException as e:
            logger.bus('serial error: {}', str(e))
            self.shutdown()
    
    async def _read(self):
        try:
            iw = self._serial.in_waiting
            # in_waiting can be None in a pypy environment
            if iw is not None:
                in_frame = False
                drydock = bytearray()
                received = await self._serial.read_async(iw)
                for b in received:
                    if b == HDLC_FLAG:
                        if in_frame:
                            in_frame = False
                            
                            frame, error = self._hdlc.decode(drydock)
                            
                            if error is not None:
                                logger.bus('framing error {}', error.name)
                            else:
                                self._stats[0]['rx_bytes'] += len(drydock)
                                self._update_rx_stats(frame)
                                self._rx_buf = frame
                            drydock = bytearray()
                        else:
                            in_frame = True
                    else:
                        drydock.append(b)
        except serial.SerialTimeoutException:
            pass
        except serial.SerialException as e:
            logger.bus('serial error: {}', str(e))
            self.shutdown()
    
    async def send(self, data: bytes):
        await self._write(data)
    
    async def send_frame(self, f: GenericFrame):
        addr = f.address
        ft = f.type
        
        payload = f.build(self._hdlc)
        
        logger.bus('frame {} to {} payload: ',
                   f.type.name,
                   addr,
                   format_binary_literal(payload))
        
        self._stats[addr]['tx_frames'][ft][0] += 1
        self._stats[addr]['tx_frames'][ft][1] = millis()
        await self._write(payload)
        logger.bus('sent frame type {} to {} ({}B)',
                   f.type.name,
                   addr,
                   len(payload))
    
    def get(self) -> Optional[Frame]:
        rv = self._rx_buf
        self._rx_buf = None
        return rv
    
    async def run(self):
        try:
            self._serial = AioSerial(port=self._port,
                                     baudrate=self._baud,
                                     loop=self.loop)
        except ValueError as e:
            logger.error('invalid settings configured for serial bus '
                         f'({self._format_param_text()}): '
                         f'{str(e)}')
            self.shutdown()
        except serial.SerialException as e:
            logger.bus('serial error: {}', str(e))
            self.shutdown()
        
        logger.bus('serial bus connected ({})',
                   self._format_param_text())
        
        while self.enabled:
            if self._tick.is_set() or self._changed.is_set():
                async with self._tx_lock:
                    f = OutputStateFrame(DeviceAddress.TFIB1, [], True)
                    await self.send_frame(f)
                    self._tick.clear()
                    self._changed.clear()
            
            await asyncio.sleep(0)
    
    def shutdown(self):
        if self.enabled:
            self.enabled = False
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
            logger.bus('bus shutdown')
