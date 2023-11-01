import string
from atsc.constants import *
from atsc.hdlc import HDLC_FLAG, HDLC_ESCAPE, HDLCError, HDLCContext


def test_msg(text, expected_error=None):
    hdlc = HDLCContext(SERIAL_BUS_CRC_POLY,
                       SERIAL_BUS_CRC_INIT,
                       SERIAL_BUS_CRC_REVERSE,
                       SERIAL_BUS_CRC_XOR_OUT)
    message = bytes(text, 'utf-8')
    
    encoded = hdlc.encode(message, frame=False)
    frame, error = hdlc.decode(encoded)
    
    if error:
        if expected_error is not None:
            if error != expected_error:
                print(f'[FAILED] "{text}" Unexpected error {error.name}')
                exit(10)
    else:
        if frame.data == message:
            print(f'[OK] "{text}"')
        else:
            print(f'[FAILED] "{text}" Data corrupted')
            exit(20)


if __name__ == '__main__':
    test_msg('', expected_error=HDLCError.EMPTY)
    
    for lowercase in string.ascii_letters:
        test_msg(lowercase)
    
    for punc in string.punctuation:
        test_msg(punc)
    
    # arguably the MOST critical tests
    test_msg(str(HDLC_ESCAPE))
    test_msg(str(HDLC_FLAG))
