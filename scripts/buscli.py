import os
import sys
from serialbus import Bus


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
import hdlc as hdlc
import timing as timing
import finelog
import logging
from core import ChannelState, FrozenChannelState
from utils import configureLogger
from utils import prettyBinaryLiteral as PBA
from frames import DeviceAddress, OutputStateFrame
from argparse import ArgumentParser


LOG = logging.getLogger('atsc')
configureLogger(LOG)


def get_cla():
    ap = ArgumentParser(description='CLI serial bus frame generator.')
    ap.add_argument('-H', nargs='+', dest='high', help='Set these output indices high. Use "*" for all.')
    ap.add_argument('-L', nargs='+', dest='low', help='Set these output indices low. Use "*" for all.')
    ap.add_argument('-T', '--transfer', action='store_true', dest='transfer', help='Set FTR bit.')
    ap.add_argument('-p', '--port', required=True, type=str, dest='port', help='Serial port.')
    ap.add_argument('-b', '--baud', required=True, type=int, dest='baud', help='Serial port baud rate.')
    return ap.parse_args()


def run():
    LOG.setLevel(finelog.BUS)
    cla = get_cla()
    port = cla.port
    baud = cla.baud
    high_flag = cla.high
    low_flag = cla.low
    transfer = cla.transfer
    
    triac_count = 3
    channel_count = 12
    bit_max = channel_count * triac_count
    
    high = []
    low = []
    if high_flag is not None:
        for v in high_flag:
            LOG.verbose(f'Attempting to set "{v}" high')
            if v == '*':
                high = range(0, bit_max)
                break
            try:
                number = int(v)
                if number > bit_max:
                    LOG.error(f'High index "{v}" out of range')
                    exit(6)
                high.append(number)
            except ValueError:
                LOG.error(f'High index "{v}" failed to parse')
                exit(7)
    else:
        high = []
    
    if low_flag is not None:
        for v in low_flag:
            LOG.verbose(f'Attempting to set "{v}" low')
            if v == '*':
                low = range(0, bit_max)
                break
            try:
                number = int(v)
                if number > bit_max:
                    LOG.error(f'Low index "{v}" out of range')
                    exit(8)
                low.append(number)
            except ValueError:
                LOG.error(f'Low index "{v}" failed to parse')
                exit(9)
    else:
        low = []
    
    if len(set(high).intersection(set(low))) > 0:
        LOG.error(f'Cannot specify indices to be both high and low')
        exit(10)
    
    bus = Bus(port, baud, 1000)
    bus.start()
    
    while not bus.running:
        LOG.info(f'Waiting on bus...')
    
    ooi = 0
    states = []
    for si in range(channel_count):
        outputs = [False, False, False]
        for i in range(triac_count):
            if ooi in high:
                outputs[i] = True
            for ooi in low:
                outputs[i] = False
            ooi += 1
        states.append(FrozenChannelState(si, outputs[0], outputs[1], outputs[2], ChannelState.STOP_REST, 0))
    
    f = OutputStateFrame(DeviceAddress.TFIB1, states, transfer)
    payload = f.build(bus.hdlc_context)
    
    LOG.info(f'FRAME {PBA(payload)}')
    
    bus.sendFrame(f)
    
    LOG.info(f'Waiting for response...')
    
    t1 = timing.MillisecondTimer(100)
    try:
        while True:
            if not bus.running:
                break
            if t1.poll():
                t1.cycle()
                
                result = bus.get()
                if result is not None:
                    frame: hdlc.Frame = result
                    content = frame.data[3:]
                    LOG.info(f'BITFIELD {PBA(content)}')
                    
                    break
    except KeyboardInterrupt:
        LOG.info(f'Cancelled wait for response')
    
    bus.shutdown()
    LOG.info('Done')


if __name__ == '__main__':
    run()
else:
    print('This script must be ran directly.')
    exit(1)
