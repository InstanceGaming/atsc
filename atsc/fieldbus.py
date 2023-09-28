import asyncio
from collections import defaultdict
from typing import Optional, Dict, List

from defaultlist import defaultlist
from loguru import logger
import serial
from aioserial import AioSerial
from atsc import eventbus, hdlc
from atsc.constants import *
from atsc.frames import FrameType, DeviceAddress, GenericFrame, OutputStateFrame
from atsc.models import FieldOutput, Ticking, Clock
from atsc.primitives import Runnable
from atsc.utils import millis


class SerialBus(Runnable, Ticking):
    
    @property
    def hdlc_context(self):
        return self._hdlc
    
    @property
    def stats(self):
        return self._stats.copy()
    
    def __init__(self, port: str, baud: int, loop=None):
        Ticking.__init__(self)
        eventbus.listeners[StandardObjects.E_FIELD_OUTPUT_Q_CHANGED].add(
            self.on_field_output_q_changed
        )
        self.loop = loop or asyncio.get_event_loop()
        self.enabled = True
        self._fields = defaultlist()
        self._tick = False
        self._changed = False
        self._ready = False
        self._port = port
        self._baud = baud
        self._hdlc = hdlc.HDLCContext(SERIAL_BUS_CRC_POLY,
                                      SERIAL_BUS_CRC_INIT,
                                      SERIAL_BUS_CRC_REVERSE,
                                      SERIAL_BUS_CRC_XOR_OUT,
                                      byte_order=SERIAL_BUS_BYTE_ORDER)
        
        self._serial = None
        self._rx_buf: Optional[hdlc.Frame] = None
        self._stats: Dict[int, dict] = defaultdict(self._statsPopulator)
    
    def _statsPopulator(self) -> dict:
        tx_map: Dict[FrameType, List[int, Optional[int]]] = {}
        
        for ft in FrameType:
            tx_map.update({ft: [0, None]})
        
        rx_map: Dict[FrameType, List[int, Optional[int]]] = {}
        
        for ft in FrameType:
            rx_map.update({ft: [0, None]})
        
        return {
            'tx_bytes': 0, 'rx_bytes': 0, 'tx_frames': tx_map, 'rx_frames': rx_map
        }
    
    def _updateStatsRx(self, f: hdlc.Frame):
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
    
    def _formatParameterText(self):
        return f'port={self._port}, baud={self._baud}'
    
    async def _write(self, data: bytes):
        try:
            await self._serial.write_async(data)
            self._stats[0]['tx_bytes'] += 1
        except serial.SerialTimeoutException:
            pass
        except serial.SerialException as e:
            logger.bus(f'serial error: {str(e)}')
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
                    if b == hdlc.HDLC_FLAG:
                        if in_frame:
                            in_frame = False
                            
                            frame, error = self._hdlc.decode(drydock)
                            
                            if error is not None:
                                logger.bus(f'framing error {error.name}')
                            else:
                                self._stats[0]['rx_bytes'] += len(drydock)
                                self._updateStatsRx(frame)
                                self._rx_buf = frame
                            drydock = bytearray()
                        else:
                            in_frame = True
                    else:
                        drydock.append(b)
        except serial.SerialTimeoutException:
            pass
        except serial.SerialException as e:
            logger.bus(f'serial error: {str(e)}')
            self.shutdown()
    
    async def send(self, data: bytes):
        await self._write(data)
    
    async def sendFrame(self, f: GenericFrame):
        payload = f.build(self._hdlc)
        await self._write(payload)
        
        addr = f.address
        ft = f.type
        self._stats[addr]['tx_frames'][ft][0] += 1
        self._stats[addr]['tx_frames'][ft][1] = millis()
        logger.bus(f'sent frame type {f.type.name} to {addr} ({len(payload)}B)')
    
    def get(self) -> Optional[hdlc.Frame]:
        rv = self._rx_buf
        self._rx_buf = None
        return rv
    
    def on_field_output_q_changed(self, field_output: FieldOutput):
        # todo: correct this insane hack
        self._fields[field_output.id - 101] = field_output
        self._changed = True
    
    def on_bus_tick(self, clock: Clock):
        self._tick = True
    
    async def run(self):
        try:
            self._serial = AioSerial(port=self._port,
                                     baudrate=self._baud,
                                     loop=self.loop)
        except ValueError as e:
            logger.error('invalid settings configured for serial bus '
                         f'({self._formatParameterText()}): '
                         f'{str(e)}')
            self.shutdown()
        except serial.SerialException as e:
            logger.bus(f'serial error: {str(e)}')
            self.shutdown()
        
        logger.bus('serial bus connected ({})',
                   self._formatParameterText())
        
        await self.sendFrame(OutputStateFrame(DeviceAddress.TFIB1,
                                              self._fields,
                                              True))
        
        while self.enabled:
            if self._tick:
                if self._serial is not None:
                    self._ready = True
                    if self._serial.is_open:
                        await self._read()
                else:
                    self._ready = False
                self._tick = False
            
            if self._changed:
                await self.sendFrame(OutputStateFrame(DeviceAddress.TFIB1,
                                                      self._fields,
                                                      True))
                self._changed = False
            
            await asyncio.sleep(0)
    
    def shutdown(self):
        if self.enabled:
            self.enabled = False
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
            logger.bus('bus shutdown')
