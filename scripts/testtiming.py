import os
import sys
from time import sleep


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
from timing import *


t1 = MillisecondTimer(500)

try:
    while True:
        if t1.poll():
            t1.cycle()
            print('reset')
        print(t1.getRemaining(), t1.getDelta(), t1.getMarkerGoal(), t1.marker)
        sleep(0.1)
except KeyboardInterrupt:
    pass
