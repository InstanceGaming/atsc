from timing import *
from time import sleep


t1 = MillisecondTimer(500)

try:
    while True:
        if t1.poll():
            t1.reset()
            print('reset')
        print(t1.getRemaining(),
              t1.getDelta(),
              t1.getMarkerGoal(),
              t1.marker)
        sleep(0.1)
except KeyboardInterrupt:
    pass
