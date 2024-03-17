import time
import random
from jacob.text import format_binary_literal
from jacob.logging import setup_logger
from atsc.constants import CUSTOM_LOG_LEVELS
from atsc.serialbus import Bus, DeviceAddress
from atsc.frames import InputStateFrame


def run():
    logger = setup_logger('bus;stderr=error', custom_levels=CUSTOM_LOG_LEVELS)
    
    rng = random.Random()
    bus = Bus('COM5', 115200)
    bus.start()
    
    while not bus.ready:
        logger.info(f'Waiting on bus...')
        time.sleep(0.1)
    
    time.sleep(5.0)
    bytefield = bytearray(5)
    max_delay = 5
    try:
        while True:
            for i in range(5):
                if round(rng.random()):
                    bytefield[i] = rng.getrandbits(8)
            
            logger.debug(format_binary_literal(bytefield))
            frame = InputStateFrame(DeviceAddress.CONTROLLER, bytefield)
            bus.send_frame(frame)
            
            delay = rng.randrange(1, max_delay)
            time.sleep(delay)
    except KeyboardInterrupt:
        bus.shutdown()
    
    bus.join()
    logger.info('Done')


if __name__ == '__main__':
    run()
