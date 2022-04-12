import signal
import timing
import finelog
import logging
from core import Channel, FlashMode, ChannelMode
from utils import configureLogger
from serialbus import Bus


class MockBus(Bus):
    pass


LOG = logging.getLogger('atsc')
configureLogger(LOG)


def frame_handler(bus: Bus, ft, data):
    LOG.info(f'frame_handler({ft}, {len(data)}B)')


BUS = Bus('COM5', 115200, 1000, 1000)
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

    pt1 = timing.MillisecondTimer(500)

    channels = [
        Channel(1, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(2, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(3, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(4, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(5, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(6, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(7, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(8, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(9, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(10, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(11, ChannelMode.VEHICLE, FlashMode.RED),
        Channel(12, ChannelMode.VEHICLE, FlashMode.RED)
    ]

    pt1.setDisable(True)

    flasher = True
    while loop_enabled:
        if pt1.poll():
            flasher = not flasher

            for i, ch in enumerate(channels, start=1):
                if i % 2 == 0:
                    ch.a = flasher
                else:
                    ch.a = not flasher
                ch.b = False
                ch.c = False

            BUS.sendOutputState(channels, False)

    BUS.join()
    LOG.info('Exiting.')


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
