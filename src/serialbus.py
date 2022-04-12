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

import sys
import hdlc
import frames
import serial
import logging
from core import FrozenChannelState
from utils import bitarrayFromBytearray, prettyElapsedMilliseconds
from frames import (FrameType,
                    BeaconFrame,
                    GenericFrame,
                    DeviceAddress,
                    OutputStateFrame)
from timing import millis
from typing import List, Optional
from bitarray import bitarray
from threading import Thread
from collections import defaultdict
from dataclasses import dataclass
from bitarray.util import zeros


@dataclass
class BusDeviceMetadata:
    enabled: bool = True
    tx_marker: Optional[int] = None
    rx_marker: Optional[int] = None
    tx_total: int = 0
    rx_total: int = 0


@dataclass
class BusData:
    inputs: bitarray = bitarray()


class Bus(Thread):
    LOG = logging.getLogger('atsc.bus')
    CRC_POLY = 0x11021
    CRC_INIT = 0xFFFF
    CRC_REVERSE = True
    CRC_XOR_OUT = 0
    BYTE_ORDER = 'big'

    @property
    def running(self):
        return self._running

    @property
    def inputs_field(self):
        return self._inputs_field

    def __init__(self,
                 port,
                 baud,
                 frame_timeout=None,
                 inputs_count=None):
        Thread.__init__(self)
        self.setName('SerialBus')
        self.daemon = True
        self._port = port
        self._baud = baud
        self._hdlc = hdlc.HDLC(self.CRC_POLY,
                               self.CRC_INIT,
                               self.CRC_REVERSE,
                               self.CRC_XOR_OUT,
                               byte_order=self.BYTE_ORDER)

        self._serial = None
        self._running = False
        self._in_frame = False
        self._tx_frame_total = 0
        self._frame_buf: List[GenericFrame] = []
        self._bdm_map = defaultdict(BusDeviceMetadata)

        if inputs_count is not None:
            self._inputs_field = zeros(inputs_count)
        else:
            self._inputs_field = None

        if frame_timeout is None or frame_timeout < 1:
            self._frame_timeout = sys.maxsize
        else:
            self._frame_timeout = frame_timeout

    def handleFrame(self, frame):
        length = len(frame.data)

        if length >= 3:
            address = frame.data[0]
            control = frame.data[1]
            fr_type = frame.data[2]

            paren_text = ''
            bdm = self._bdm_map[address]

            if bdm.rx_marker is not None:
                delta_text = prettyElapsedMilliseconds(
                    bdm.rx_marker,
                    millis()
                )
                paren_text = f' (after {delta_text})'

            self.LOG.bus(f'Received v{control} frame type {fr_type} '
                         f'({length}B) from device {address}{paren_text}')

            bdm.rx_marker = millis()
            bdm.rx_total += 1

            if control == frames.FRAME_VERSION:
                if fr_type == int(FrameType.INPUTS):
                    if self._inputs_field is not None:
                        self._inputs_field = bitarrayFromBytearray(
                            frame.data[3:])

    def _formatParameterText(self):
        return f'port={self._port}, baud={self._baud}, ' \
               f'frame_timeout={self._frame_timeout}'

    def run(self):
        self._running = True
        try:
            self._serial = serial.Serial(port=self._port,
                                         baudrate=self._baud,
                                         stopbits=serial.STOPBITS_ONE,
                                         parity=serial.PARITY_NONE,
                                         bytesize=serial.EIGHTBITS)
        except serial.SerialException as e:
            self.LOG.error(
                f'Error occurred opening serial bus '
                f'({self._formatParameterText()}): {str(e)}')
            self._running = False
        except ValueError as e:
            self.LOG.error('Invalid settings configured for serial bus '
                           f'({self._formatParameterText()}): '
                           f'{str(e)}')
            self._running = False

        if self._running:
            self.LOG.bus(
                f'Serial bus started ({self._formatParameterText()})')
            while self._running:
                if len(self._frame_buf) > 0:
                    frame = self._frame_buf.pop(0)
                    data = frame.build(self._hdlc)

                    try:
                        self._serial.write(data)
                        self._serial.flushOutput()
                    except serial.SerialTimeoutException:
                        self.LOG.error(
                            'Write timeout exceeded writing to bus on '
                            f'{self._port}')
                        self.shutdown()
                    except serial.SerialException as e:
                        self.LOG.bus(f'Error: {str(e)}')

                    bdm = self._bdm_map[frame.address]
                    bdm.tx_marker = millis()

                    self.LOG.bus(
                        f'Sent frame type {frame.type.name} '
                        f'(did={bdm.tx_total}, uid={self._tx_frame_total}, '
                        f'{len(data)}B)')

                    bdm.tx_total += 1
                    self._tx_frame_total += 1

                captured = None
                try:
                    captured = self._serial.read(self._serial.in_waiting)
                    self._serial.flushInput()
                except serial.SerialTimeoutException:
                    self.LOG.error(
                        'Read timeout exceeded writing to bus on '
                        f'{self._port}')
                    self.shutdown()
                except serial.SerialException as e:
                    self.LOG.bus(f'Error: {str(e)}')

                if captured is not None:
                    drydock = bytearray()
                    for b in captured:
                        if b == hdlc.HDLC_FLAG:
                            if self._in_frame:
                                self._in_frame = False

                                frame, error = self._hdlc.decode(drydock)

                                if frame is None:
                                    self.LOG.bus(f'Framing error: {error.name}')
                                else:
                                    self.handleFrame(frame)

                                drydock = bytearray()
                            else:
                                self._in_frame = True
                        else:
                            drydock.append(b)

    def send(self, frame: GenericFrame):
        self._frame_buf.append(frame)

    def sendBeacon(self, address):
        f = BeaconFrame(address)
        self.send(f)

    def sendOutputState(self,
                        channel_states: List[FrozenChannelState],
                        transfer):
        f = OutputStateFrame(DeviceAddress.TFIB1, channel_states, transfer)
        self.send(f)

    def shutdown(self):
        if self._running:
            self._running = False
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
            self.LOG.info('Shutdown serial bus on {0}'.format(self._port))
