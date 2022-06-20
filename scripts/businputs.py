import os
import sys
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import random
import signal
import timing
import finelog
import logging
from utils import configureLogger
from utils import prettyBinaryLiteral as PBA
from frames import DeviceAddress, InputStateFrame
from serialbus import Bus


class MockBus(Bus):

    def sendInputsState(self, input_states: bytearray):
        self.sendFrame(InputStateFrame(DeviceAddress.CONTROLLER,
                                       input_states))


LOG = logging.getLogger('atsc')
configureLogger(LOG)

BUS = MockBus('COM5', 115200)
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

    LOG.setLevel(finelog.CustomLogLevels.BUS)
    LOG.info('Starting bus.')
    BUS.start()

    t1 = timing.MillisecondTimer(1000)
    while loop_enabled:
        if t1.poll():
            t1.reset()
            mock_data = random.randbytes(3)
            LOG.info(PBA(mock_data))
            BUS.sendInputsState(bytearray(mock_data))

    BUS.join()
    LOG.info('Exiting.')


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
