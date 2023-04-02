import os
import sys
from dateutil import tz


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
from timespan import *


def run():
    calendar = 'mon,wed,fri may,jun'
    day_exceptions = [120, 344, 345]
    start = '3pm'
    end = '8pm'
    tzi = tz.gettz('America/Boise')
    
    ts, error_message = parse_timespan_text(calendar, day_exceptions, start, end, tzi)
    
    if error_message is None:
        print(ts.__repr__())
    else:
        print(error_message)


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
    exit(1)
