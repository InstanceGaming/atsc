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

import finelog  # will break if omitted! must be imported in its entirety.
import hdlc
import serial
import timing
import logging
from frames import FrameType, GenericFrame, DeviceAddress
from serial import SerialException
from typing import Dict, List, Optional
from threading import Lock, Thread
from collections import defaultdict


class Bus(Thread):
    LOG = logging.getLogger('atsc.bus')
    CRC_POLY = 0x11021
    CRC_INIT = 0xFFFF
    CRC_REVERSE = True
    CRC_XOR_OUT = 0
    BYTE_ORDER = 'big'
    LOCK_TIMEOUT = 0.025

    @property
    def tx_wait(self):
        return self._tx_buf is not None

    @property
    def rx_wait(self):
        return self._rx_buf is not None

    @property
    def rx_miss(self):
        return self._rx_miss

    @property
    def hdlc_context(self):
        return self._hdlc

    @property
    def stats(self):
        return self._stats.copy()

    def __init__(self,
                 port: str,
                 baud: int):
        Thread.__init__(self)
        self.name = 'SerialBus'
        self.running = False
        self._port = port
        self._baud = baud
        self._hdlc = hdlc.HDLCContext(self.CRC_POLY,
                                      self.CRC_INIT,
                                      self.CRC_REVERSE,
                                      self.CRC_XOR_OUT,
                                      byte_order=self.BYTE_ORDER)

        self._serial = None
        self._tx_frame: Optional[GenericFrame] = None
        self._tx_lock = Lock()
        self._tx_buf: Optional[bytes] = None
        self._rx_lock = Lock()
        self._rx_buf: Optional[hdlc.Frame] = None
        self._rx_miss: bool = False
        self._stats: Dict[int, dict] = defaultdict(self._statsPopulator)

    def _statsPopulator(self) -> dict:
        tx_map: Dict[FrameType, List[int, Optional[int]]] = {}

        for ft in FrameType:
            tx_map.update({ft: [0, None]})

        rx_map: Dict[FrameType, List[int, Optional[int]]] = {}

        for ft in FrameType:
            rx_map.update({ft: [0, None]})

        return {
            'tx_bytes': 0,
            'rx_bytes': 0,
            'tx_frames': tx_map,
            'rx_frames': rx_map
        }

    def _updateStatsTx(self, data: bytes):
        size = len(data)
        if self._tx_frame is not None:
            addr = self._tx_frame.address
            ft = self._tx_frame.type
            try:
                da = DeviceAddress(addr)
            except ValueError:
                da = DeviceAddress.UNKNOWN

            self.LOG.bus(f'Sent frame type '
                         f'{self._tx_frame.type.name} to '
                         f'{da} '
                         f'({size}B)')

            self._stats[addr]['tx_frames'][ft][0] += 1
            self._stats[addr]['tx_frames'][ft][1] = timing.millis()

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

            self.LOG.bus('Received frame type '
                         f'{ft.name} from '
                         f'{da} ({size}B)')

            self._stats[addr]['rx_frames'][ft][0] += 1
            self._stats[addr]['rx_frames'][ft][1] = timing.millis()

    def _formatParameterText(self):
        return f'port={self._port}, baud={self._baud}'

    def _write(self) -> bool:
        if self.tx_wait > 0:
            if self._tx_lock.acquire(timeout=self.LOCK_TIMEOUT):
                data = self._tx_buf
                try:
                    self._serial.write(data)
                    self._serial.flushOutput()
                    self._updateStatsTx(data)
                    self._tx_frame = None
                except serial.SerialTimeoutException:
                    pass
                except SerialException as e:
                    self.LOG.bus(f'Serial error: {str(e)}')
                    self.shutdown()
                self._tx_lock.release()
                return True
        return False

    def _read(self) -> bool:
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
                                    self.LOG.bus(
                                        f'Framing error {error.name}')
                                else:
                                    self._updateStatsRx(frame)

                                    self._rx_buf = frame
                                    if self.rx_wait:
                                        self._rx_miss = True

                                drydock = bytearray()
                            else:
                                in_frame = True
                        else:
                            drydock.append(b)
                    self._serial.flushInput()
                    self._rx_lock.release()
                    return True
        except serial.SerialTimeoutException:
            pass
        except SerialException as e:
            self.LOG.bus(f'Serial error: {str(e)}')
            self.shutdown()
        return False

    def run(self):
        self.running = True
        try:
            self._serial = serial.Serial(port=self._port,
                                         baudrate=self._baud,
                                         stopbits=serial.STOPBITS_ONE,
                                         parity=serial.PARITY_NONE,
                                         bytesize=serial.EIGHTBITS,
                                         timeout=self.LOCK_TIMEOUT,
                                         write_timeout=self.LOCK_TIMEOUT)
        except ValueError as e:
            self.LOG.error('Invalid settings configured for serial bus '
                           f'({self._formatParameterText()}): '
                           f'{str(e)}')
            self.running = False
        except SerialException as e:
            self.LOG.bus(f'Serial error: {str(e)}')
            self.shutdown()

        if self.running:
            self.LOG.bus(
                f'Serial bus started ({self._formatParameterText()})')
            while self.running:
                if self._serial is not None and self._serial.is_open:
                    if self._write():
                        time.sleep(0.05)
                    if not self._read():
                        time.sleep(0.05)
                else:
                    time.sleep(0.25)

    def send(self, data: bytes, no_lock=False):
        if no_lock or self._tx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            self._tx_buf = data
            if not no_lock:
                self._tx_lock.release()
        else:
            self.LOG.bus('Failed to acquire transmit lock within timeout')

    def sendFrame(self, f: GenericFrame):
        payload = f.build(self._hdlc)
        if self._tx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            self._tx_frame = f
            self.send(payload, no_lock=True)
            self._tx_lock.release()
        else:
            self.LOG.bus('Failed to acquire transmit lock within timeout '
                         '(with frame)')

    def get(self) -> Optional[hdlc.Frame]:
        if self._rx_lock.acquire(timeout=self.LOCK_TIMEOUT):
            rv = self._rx_buf
            self._rx_buf = None
            self._rx_miss = False
            self._rx_lock.release()
            return rv
        else:
            self.LOG.bus('Failed to acquire receive lock within timeout')

    def shutdown(self):
        if self.running:
            self.running = False
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
            self.LOG.bus('Bus shutdown')
