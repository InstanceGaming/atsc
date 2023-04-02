import os
import sys


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import hdlc
import time
import serial
from utils import prettyBinaryLiteral as PBL


CRC_POLY = 0x11021
CRC_INIT = 0xFFFF
CRC_REVERSE = True
CRC_XOR_OUT = 0

if __name__ == '__main__':
    hdlc_klass = hdlc.HDLCContext(CRC_POLY, CRC_INIT, CRC_REVERSE, CRC_XOR_OUT)
    si = serial.Serial(port='COM5', baudrate=115200, timeout=0)
    
    FRAME_BOUNDARY = 0x7E
    
    msg = ''
    buf = bytearray()
    frame_read = False
    frames = 0
    while True:
        try:
            if si.is_open and si.in_waiting > 0:
                data = si.read(1)
                
                if len(data) > 0:
                    b = ord(data)
                    
                    if not frame_read:
                        if b == FRAME_BOUNDARY:
                            frame_read = True
                    else:
                        if b == FRAME_BOUNDARY:
                            data_bytes = bytes(buf)
                            print(f'[{time.time():>.3f}][{frames:0>6}]: '
                                  f'RAW\t\t{PBL(data_bytes)}')
                            
                            frame, error = hdlc_klass.decode(data_bytes)
                            
                            if error is not None:
                                print(f'[{time.time():>.3f}][{frames:0>6}]: '
                                      f'ERROR\t{error.name}')
                            
                            if frame is not None and frame.data is not None:
                                print(f'[{time.time():>.3f}][{frames:0>6}]: '
                                      f'DECODE\t{PBL(frame.data)}')
                            
                            buf = bytearray()
                            frame_read = False
                            frames += 1
                            msg = ''
                            si.flush()
                        else:
                            buf.append(b)
        
        except KeyboardInterrupt:
            break
    
    si.close()
