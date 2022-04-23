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

import socket
import logging
import proto.atsc_pb2 as pb
from core import FrozenChannelState
from utils import prettyByteSize
from typing import List
from threading import Thread


class Monitor(Thread):
    LOG = logging.getLogger('atsc.net')

    @property
    def running(self):
        return self._running

    @property
    def client_count(self):
        return len(self._clients)

    def __init__(self, controller, host, port):
        Thread.__init__(self)
        self.setName('Monitor')
        self.daemon = True

        self._controller = controller

        self._running = False
        self._clients = []
        self._host = host
        self._port = port

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def run(self):
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self._host, self._port))
            self.LOG.info(
                'Network monitor started on {0}:{1}'.format(self._host,
                                                            self._port))
            self.socket.listen(5)
            self._running = True
        except OSError as e:
            self.LOG.warning('Error binding or listening to '
                             f'{self._host}:{self._port}: {str(e)}')

        while self._running:
            if self.socket:
                try:
                    (connection, (ip, port)) = self.socket.accept()
                    client_count = len(self._clients) + 1
                    ct = MonitorClient(connection, ip, port, client_count)
                    self._clients.append(ct)
                except OSError:
                    pass

    def clean(self):
        if len(self._clients) > 0:
            remove = [c for c in self._clients if c.stopped]

            if len(remove) > 0:

                for c in remove:
                    self._clients.remove(c)

                self.LOG.debug('Removed %d dead client threads' % len(remove))

    def broadcastRaw(self, data):
        if self._running:
            for c in self._clients:
                c.send(data)

    def broadcastOutputState(self, channel_states: List[FrozenChannelState]):
        if self.client_count > 0:
            fs = pb.FieldState()
            fs.version = 1

            for cs in channel_states:
                ch = fs.channels.add()
                ch.a = cs.a
                ch.b = cs.b
                ch.c = cs.c
                ch.duration = cs.duration
                ch.interval_time = cs.interval_time
                ch.calls = cs.calls

            serialized = fs.SerializeToString()
            length = len(serialized)
            payload = length.to_bytes(4, 'big', signed=False) + serialized
            self.broadcastRaw(payload)

    def shutdown(self):
        self._running = False

        for c in self._clients:
            c.stop()

        if self.socket:
            self.socket.close()


class MonitorClient:
    LOG = logging.getLogger('atsc.net.client')

    @property
    def stopped(self):
        return self._stopped

    def __init__(self, connection, ip, port, index):
        self._sock = connection
        self._index = index
        self._stopped = False
        self._ignoring = False
        self._last_data = None
        self._total_sent = 0

        self._ip = ip
        self._port = port

        self.LOG.info('M{0:02d} at {1}:{2}'.format(index, ip, port))

    def send(self, data: bytes):
        if len(data) > 0:
            try:
                self._sock.sendall(data)
                size = len(data)
                # self.LOG.fine(f'M{self._index:02d} transmitted '
                #               f'{prettyByteSize(size)}')
                self._total_sent += size
            except OSError as e:
                self.LOG.debug('M{:02d} {}'.format(self._index, str(e)))
                self.stop()

    def stop(self):
        if not self._stopped:
            self.LOG.info(f'M{self._index:02d} transmitted a total of '
                          f'{prettyByteSize(self._total_sent)}')

            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError as e:
                    self.LOG.debug('M{:02d} (closing): {}'.format(self._index,
                                                                  str(e)))

            self._stopped = True
            self.LOG.info('M{:02d} stopped'.format(self._index))
