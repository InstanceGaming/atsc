import struct
from socketserver import ThreadingTCPServer, StreamRequestHandler


class CommandProcessor(StreamRequestHandler):
    chunk_size: int = 1024
    
    def __init__(self,
                 request,
                 client_address,
                 server):
        super().__init__(request, client_address, server)
        self._packet_cursor: int = 0
        self._packet_size: int = 0
        self._packet_buffer = bytearray()
        self._message_buffer = bytearray()
    
    def _message_pop_front(self, length: int) -> bytearray:
        rv = self._message_buffer[:length]
        self._message_buffer = self._message_buffer[length:]
        self._packet_cursor += len(rv)
        return rv
    
    def _message_pop_unsigned_int(self) -> int:
        packed = self._message_pop_front(4)
        return struct.unpack('!', packed)[0]
    
    def _message_ingest(self):
        segment_bytes = self.request.recv(self.chunk_size)
        self._message_buffer.extend(segment_bytes)
        return len(self._message_buffer)
    
    def handle(self):
        length = self._message_ingest()
        
        if length < 4:
            pass
        elif length == 4:
            self._packet_size = self._message_pop_unsigned_int()
        elif length > 4:
            while self._packet_cursor < self._packet_size:
                if self._packet_cursor > length - 1:
                    length = self._message_ingest()
            self._packet_buffer = self._message_buffer[:self._packet_size]
            self._message_buffer = self._message_buffer[self._packet_size:]
            self._packet_cursor = 0
        else:
            raise NotImplementedError()


class NetworkControlServer(ThreadingTCPServer):
    
    def __init__(self, server_address: tuple[str, int]):
        super().__init__(server_address, CommandProcessor)
