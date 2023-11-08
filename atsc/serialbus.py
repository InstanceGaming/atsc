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

import time
import serial
from atsc import hdlc, timing
from loguru import logger
from serial import SerialException
from typing import Dict, List, Optional
from threading import Lock, Thread
from atsc.frames import FrameType, GenericFrame, DeviceAddress
from collections import defaultdict


class Bus(Thread):
    CRC_POLY = 0x11021
    CRC_INIT = 0xFFFF
    CRC_REVERSE = True
    CRC_XOR_OUT = 0
    BYTE_ORDER = 'big'
    LOCK_TIMEOUT = 0.05
    
    @property
    def stats(self):
        return self._stats.copy()
    
    @property
    def ready(self):
        return self._ready
    
    def __init__(self, port: str, baud: int):
        Thread.__init__(self)
        self.name = 'SerialBus'
        self.daemon = True
        self._running = False
        self._ready = False
        self._port = port
        self._baud = baud
        self._hdlc = hdlc.HDLCContext(self.CRC_POLY,
                                      self.CRC_INIT,
                                      self.CRC_REVERSE,
                                      self.CRC_XOR_OUT,
                                      byte_order=self.BYTE_ORDER)
        
        self._serial = None
        self._tx_lock = Lock()
        self._rx_lock = Lock()
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
            
            logger.bus('Received frame type '
                         f'{ft.name} from '
                         f'{da} ({size}B)')
            
            self._stats[addr]['rx_frames'][ft][0] += 1
            self._stats[addr]['rx_frames'][ft][1] = timing.millis()
    
    def _formatParameterText(self):
        return f'port={self._port}, baud={self._baud}'
    
    def _write(self, data: bytes):
        try:
            self._serial.write(data)
            self._stats[0]['tx_bytes'] += 1
        except serial.SerialTimeoutException:
            pass
        except SerialException as e:
            logger.bus(f'Serial error: {str(e)}')
            self.shutdown()
    
    def _read(self):
        try:
            iw = self._serial.in_waiting
            # in_waiting can be None in a pypy environment
            if iw is not None:
                if self._rx_lock.acquire(timeout=self.LOCK_TIMEOUT):
                    in_frame = False
                    drydock = bytearray()
                    for b in self._serial.read(iw):
                        if b == hdlc.HDLC_FLAG:
                            if in_frame:
                                in_frame = False
                                
                                frame, error = self._hdlc.decode(drydock)
                                
                                if error is not None:
                                    logger.bus(f'Framing error {error.name}')
                                else:
                                    self._stats[0]['rx_bytes'] += len(drydock)
                                    self._updateStatsRx(frame)
                                    self._rx_buf = frame
                                drydock = bytearray()
                            else:
                                in_frame = True
                        else:
                            drydock.append(b)
                    self._rx_lock.release()
        except serial.SerialTimeoutException:
            pass
        except SerialException as e:
            logger.bus(f'Serial error: {str(e)}')
            self.shutdown()
    
    def run(self):
        try:
            self._serial = serial.Serial(port=self._port,
                                         baudrate=self._baud,
                                         timeout=self.LOCK_TIMEOUT,
                                         write_timeout=self.LOCK_TIMEOUT)
            self._running = True
        except ValueError as e:
            logger.error('Invalid settings configured for serial bus '
                           f'({self._formatParameterText()}): '
                           f'{str(e)}')
        except SerialException as e:
            logger.bus(f'Serial error: {str(e)}')
            self.shutdown()
        
        if self._running:
            logger.bus(f'Serial bus started ({self._formatParameterText()})')
            while self._running:
                time.sleep(0.1)
                if self._serial is not None:
                    self._ready = True
                    if self._serial.is_open:
                        self._read()
                else:
                    self._ready = False
    
    def send(self, data: bytes):
        if self._tx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            self._write(data)
            self._tx_lock.release()
        else:
            logger.bus('Failed to acquire transmit lock within timeout')
    
    def sendFrame(self, f: GenericFrame):
        if self._tx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            payload = f.build(self._hdlc)
            self._write(payload)
            
            addr = f.address
            ft = f.type
            self._stats[addr]['tx_frames'][ft][0] += 1
            self._stats[addr]['tx_frames'][ft][1] = timing.millis()
            logger.bus(f'Sent frame type {f.type.name} to {addr} ({len(payload)}B)')
            
            self._tx_lock.release()
        else:
            logger.bus('Failed to acquire transmit lock within timeout (with frame)')
    
    def get(self) -> Optional[hdlc.Frame]:
        if self._rx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            rv = self._rx_buf
            self._rx_buf = None
            self._rx_lock.release()
            return rv
        else:
            logger.bus('Failed to acquire receive lock within timeout')
    
    def shutdown(self):
        if self._running:
            self._running = False
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
            logger.bus('Bus shutdown')
