#  Copyright 2024 Jacob Jewett
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
import string
from atsc.fieldbus.constants import *
from atsc.fieldbus.hdlc import HDLC_FLAG, HDLC_ESCAPE, HDLCError, HDLCContext


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
