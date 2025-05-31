import socket


class SystemdWatchdog:
    
    def __init__(self, socket_addr: str):
        self.name = 'SystemdWatchdogServer'
        self.daemon = True
        self._running = False
        
        if socket_addr.startswith('@'):
            socket_addr = '\0' + socket_addr[1:]
        
        self._socket_addr = socket_addr
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    def send(self, txt: str):
        self._socket.sendto(txt.encode(), self._socket_addr)
    
    def ready(self):
        self.send('READY=1')
    
    def feed(self):
        self.send('WATCHDOG=1')
    
    def unready(self):
        self.send('READY=0')
    
    def close(self):
        self.unready()
        self._running = False
        self._socket.close()
