import os
import sys
import string


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import hdlc


def pretty_bytes(bs):
    text = ''
    
    for b in bs:
        text += format(b, '08b') + ' '
    
    return '{}'.format(text)


def test_msg(text, expected_error=None):
    message = bytes(text, 'utf-8')
    encoded = hdlc.encode(message, frame=False)
    frame, error = hdlc.decode(encoded)
    
    if error:
        if expected_error is not None:
            if error != expected_error:
                print(f'[FAILED] "{text}" Unexpected error {error.task_name}')
                exit(10)
    else:
        if frame.data == message:
            print(f'[OK] "{text}"')
        else:
            print(f'[FAILED] "{text}" Data corrupted')
            exit(20)


if __name__ == '__main__':
    test_msg('', expected_error=hdlc.HDLCError.EMPTY)
    
    for lowercase in string.ascii_letters:
        test_msg(lowercase)
    
    for punc in string.punctuation:
        test_msg(punc)
    
    # arguably the MOST critical tests
    test_msg(str(hdlc.HDLC_ESCAPE))
    test_msg(str(hdlc.HDLC_FLAG))
