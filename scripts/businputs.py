import os
import sys
import random
import signal
import logging


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import timing
import finelog
from utils import PrettyByteArray, configureLogger
from frames import FrameType, GenericFrame, DeviceAddress
from serialbus import Bus


class InputStateFrame(GenericFrame):
    VERSION = 11

    def __init__(self,
                 address: int,
                 input_bitfield: bytes):
        super(InputStateFrame, self).__init__(address,
                                              FrameType.INPUTS,
                                              None)

        self._input_states: bytes = input_bitfield

    def getPayload(self):
        return self._input_states


class MockBus(Bus):

    def sendInputsState(self, input_states: bytes):
        self.send(InputStateFrame(DeviceAddress.CONTROLLER,
                                  input_states))


LOG = logging.getLogger('atsc')
configureLogger(LOG)


def frame_handler(ft, data):
    LOG.info(f'frame_handler({ft}, {len(data)}B)')


BUS = MockBus('COM5', 115200, 1000)
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

    t1 = timing.MillisecondTimer(1000)
    while loop_enabled:
        if t1.poll():
            t1.reset()
            mock_data = random.randbytes(3)
            LOG.info(PrettyByteArray(mock_data))
            BUS.sendInputsState(mock_data)

    BUS.join()
    LOG.info('Exiting.')


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
