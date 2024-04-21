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
import socket
import atsc.proto.controller_pb2 as pb
from loguru import logger
from typing import List, Optional
from atsc.core import Phase, LoadSwitch
from threading import Thread
from jacob.text import format_byte_size


def get_net_address(filter_if_name: str):
    from netifaces import AF_INET, ifaddresses
    
    interface = ifaddresses(filter_if_name)
    protocol = interface[AF_INET]
    return protocol[0]['addr']


class Monitor(Thread):
    
    @property
    def client_count(self):
        return len(self._clients)
    
    def __init__(self, host, port, name: str, phases: List[Phase]):
        Thread.__init__(self)
        self.name = 'NetMonitor'
        self.daemon = True
        self.net_name = name
        self.phases = phases
        
        self._running = False
        self._clients = []
        self._host = host
        self._port = port
        self._control_info: Optional[pb.ControlInfo] = self.build_controller_info()
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    def build_controller_info(self):
        control_pb = pb.ControlInfo()
        control_pb.version = 1
        control_pb.name = self.net_name
        
        for ph in self.phases:
            phase_pb = control_pb.phases.add()
            phase_pb.flash_mode = ph.flash_mode.value
            phase_pb.fya_setting = 0
            phase_pb.vehicle_ls = ph.veh_ls.id
            if ph.ped_ls is not None:
                phase_pb.ped_ls = ph.ped_ls.id
        
        return control_pb
    
    def run(self):
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self._host, self._port))
            logger.info('Network monitor started on {0}:{1}'.format(self._host, self._port))
            self.socket.listen(5)
            self._running = True
        except OSError as e:
            logger.warning('Error binding or listening to '
                             f'{self._host}:{self._port}: {str(e)}')
        
        while self._running:
            if self.socket:
                try:
                    time.sleep(0.1)
                    (connection, (ip, port)) = self.socket.accept()
                    client_count = len(self._clients) + 1
                    ct = MonitorClient(connection, ip, port, client_count)
                    if self._control_info is not None:
                        info_payload = self._control_info.SerializeToString()
                        ct.send(self._prefix(info_payload))
                    self._clients.append(ct)
                except OSError:
                    pass
    
    def clean(self):
        if len(self._clients) > 0:
            remove = [c for c in self._clients if c.stopped]
            
            if len(remove) > 0:
                
                for c in remove:
                    self._clients.remove(c)
                
                logger.net('Removed %d dead client threads' % len(remove))
    
    def _prefix(self, raw_data: bytes) -> bytes:
        length = len(raw_data)
        payload = length.to_bytes(4, 'big', signed=False) + raw_data
        return payload
    
    def broadcast(self, data):
        if self._running:
            for c in self._clients:
                c.send(self._prefix(data))
    
    def broadcast_control_update(self, phases: List[Phase], lss: List[LoadSwitch]):
        if self.client_count > 0:
            control_pb = pb.ControlUpdate()
            
            for ph in phases:
                phase_pb = control_pb.phase.add()
                phase_pb.status = 0
                phase_pb.ped_service = ph.ped_service
                phase_pb.state = ph.interval.value
                phase_pb.time_upper = ph.interval_setpoint
                phase_pb.time_lower = ph.interval_elapsed
                phase_pb.detections = ph.stats['detections']
                phase_pb.vehicle_calls = ph.stats['vehicle_service']
                phase_pb.ped_calls = ph.stats['ped_service']
            
            for ls in lss:
                ls_pb = control_pb.ls.add()
                ls_pb.a = ls.a
                ls_pb.b = ls.b
                ls_pb.c = ls.c
            
            serialized = control_pb.SerializeToString()
            self.broadcast(serialized)
    
    def shutdown(self):
        self._running = False
        
        for c in self._clients:
            c.stop()
        
        if self.socket:
            self.socket.close()


class MonitorClient:
    
    @property
    def stopped(self):
        return self._stopped
    
    def __init__(self, connection, ip, port, index):
        self._sock = connection
        self._index = index
        self._stopped = False
        self._total_sent = 0
        
        logger.net('M{0:02d} at {1}:{2}'.format(index, ip, port))
    
    def send(self, data: bytes):
        if len(data) > 0:
            try:
                self._sock.sendall(data)
                size = len(data)
                logger.net(f'M{self._index:02d} transmitted '
                              f'{format_byte_size(size)}')
                self._total_sent += size
            except OSError as e:
                logger.net('M{:02d} {}'.format(self._index, str(e)))
                self.stop()
    
    def stop(self):
        if not self._stopped:
            logger.net(f'M{self._index:02d} transmitted a total of '
                          f'{format_byte_size(self._total_sent)}')
            
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError as e:
                    logger.net('M{:02d} (closing): {}'.format(self._index, str(e)))
            
            self._stopped = True
            logger.net('M{:02d} stopped'.format(self._index))
