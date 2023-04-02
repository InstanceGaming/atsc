import os
import sys
from frames import DeviceAddress, OutputStateFrame


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import signal
import timing
import finelog
import logging
from core import ChannelState, FrozenChannelState
from utils import configureLogger
from serialbus import Bus


class MockBus(Bus):
    pass


LOG = logging.getLogger('atsc')
configureLogger(LOG)

BUS = Bus('COM5', 115200, 1000)
loop_enabled = True


def intSig(signum, frame):
    global loop_enabled
    LOG.info('Interrupt signal')
    loop_enabled = False
    BUS.shutdown()


def termSig(signum, frame):
    global loop_enabled
    LOG.info('Terminate signal')
    loop_enabled = False
    BUS.shutdown()


def run():
    signal.signal(signal.SIGINT, intSig)
    signal.signal(signal.SIGTERM, termSig)
    
    LOG.setLevel(finelog.BUS)
    LOG.info('Starting bus.')
    BUS.start()
    
    pt1 = timing.MillisecondTimer(500, pause=True)
    
    states = []
    for si in range(12):
        states.append(FrozenChannelState(si, 1, 0, 0, ChannelState.STOP_REST, 0))
    
    flasher = True
    while loop_enabled:
        if pt1.poll():
            for si in range(12):
                states[si].a = flasher if si % 2 == 0 else not flasher
            BUS.sendFrame(OutputStateFrame(DeviceAddress.TFIB1, states, True))
            flasher = not flasher
    
    BUS.join()
    LOG.info('Exiting.')


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
