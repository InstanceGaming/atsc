#  Copyright 2022 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import random
from loguru import logger
import atsc.utils as utils
from typing import FrozenSet
from functools import lru_cache
from dateutil.parser import parse as _dt_parser
from atsc.models import *
from atsc.eventbus import TimeDelayBusEvent


def parse_datetime_text(text: str, tz):
    rv = _dt_parser(text, dayfirst=False, fuzzy=True)
    return rv.replace(tzinfo=tz)


class RandomActuation:
    
    @property
    def enabled(self):
        return self._enabled
    
    @property
    def min(self):
        return self._min
    
    @property
    def max(self):
        return self._max
    
    @property
    def pool_range(self):
        return range(self._pool_size)
    
    def __init__(self,
                 id_: int,
                 controller: IController,
                 configuration_node: dict,
                 pool_size: int):
        super().__init__(id_, controller)
        controller.onTimeClock.subscribe(self.onTimeClock)
        self._enabled = configuration_node['enabled']
        self._min = configuration_node['min']  # seconds
        self._max = configuration_node['max']  # seconds
        self._counter = configuration_node['delay']  # seconds
        self._pool_size = pool_size
        
        seed = configuration_node.get('seed')
        if seed is not None and seed > 0:
            # global pseudo-random generator seed
            random.seed(seed)
    
    def onTimeClock(self):
        if self._counter > 0:
            self._counter -= 1
        elif self._counter == 0 and self._enabled:
            delay = random.randrange(self._min, self._max)
            self._counter = delay


class TimeFreezeReason(IntEnum):
    SYSTEM = 0
    INPUT = 1


class PhaseStatus(IntEnum):
    INACTIVE = 0
    NEXT = 1
    LEADER = 2
    SECONDARY = 3


class ControlService(IntFlag):
    VEHICLE = 0x1
    PEDESTRIAN = 0x2
    FLASH_TRANSITION = 0x4
    FYA = 0x8
    

class TimingAgenda:
    
    def __init__(self):
        pass

    
@dataclass()
class Parameters:
    timing_plans: TimingAgenda
    recycle: bool
    service: ControlService
    ped_clearance: bool
    stop_time: bool = False
    mode_duration: Optional[float] = None


class Controller(IController):

    @property
    def max_phases(self):
        return 8
    
    @property
    def max_load_switches(self):
        return 12

    @property
    def timing_clock_delay(self):
        return self._timing_clock

    @property
    def flasher_clock_delay(self):
        return self._flasher_clock

    @property
    def name(self):
        return self._name
    
    @property
    def time_freeze(self):
        """If the controller is currently freezing time"""
        return len(self._time_freeze_reasons) > 0
    
    @property
    def operation_mode(self):
        """Current operation mode of the controller"""
        return self._mode
    
    @property
    def transferred(self):
        """Has the controller transferred the flash transfer relays"""
        return self._transfer
    
    @property
    def barrier_manager(self) -> RingSynchronizer:
        return self._bm
    
    @property
    def phases(self):
        return self._phases
    
    def __init__(self,
                 start_mode: OperationMode,
                 mode_parameters: Dict[OperationMode, Parameters],
                 tps: int = 20,
                 fps: int = 1,
                 name: str = 'ATSC Controller'):
        self._tps = tps
        self._fps = fps
        
        self.onTimeClock = TimeDelayBusEvent('controller.time_clock', self._tps)
        self.onFlashClock = TimeDelayBusEvent('controller.flash_clock', self._fps)
        
        self._name = name
        
        # local flash transfer relay status
        self._transfer = False
        
        self._flasher = Flasher(1, self)
        
        # operation functionality of the controller
        self._mode: OperationMode = start_mode
        
        self._load_switches: List[LoadSwitch] = [
            LoadSwitch.make_simple(1, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.STANDARD),
            LoadSwitch.make_simple(2, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.STANDARD),
            LoadSwitch.make_simple(3, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.STANDARD),
            LoadSwitch.make_simple(4, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.STANDARD),
            LoadSwitch.make_simple(5, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.PED | LSFlag.PED_CLEAR),
            LoadSwitch.make_simple(6, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.PED | LSFlag.PED_CLEAR),
            LoadSwitch.make_simple(7, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.STANDARD),
            LoadSwitch.make_simple(8, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.STANDARD),
            LoadSwitch.make_simple(9, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.STANDARD),
            LoadSwitch.make_simple(10, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.STANDARD),
            LoadSwitch.make_simple(11, FieldTriad(1, 2, 3), self._flasher_a, LSFlag.PED | LSFlag.PED_CLEAR),
            LoadSwitch.make_simple(12, FieldTriad(1, 2, 3), self._flasher_b, LSFlag.PED | LSFlag.PED_CLEAR)
        ]
        default_time_set = TimingPlan(
            {
                SignalState.STOP   : 1.0,
                SignalState.CAUTION: 3.0,
                SignalState.GO     : 2.0,
                SignalState.FYA    : 4.0
            },
            {
                SignalState.STOP   : 1.0,
                SignalState.CAUTION: 4.0,
                SignalState.GO     : 2.0,
                SignalState.FYA    : 4.0
            },
            {
                SignalState.STOP   : 300.0,
                SignalState.CAUTION: 6.0,
                SignalState.GO     : 180.0,
                SignalState.FYA    : 300.0
            },
        )
        
        signal_tps = 4
        self._signals: List[Signal] = [
            Signal(1, signal_tps, default_time_set, self._load_switches[0]),
            Signal(2, signal_tps, default_time_set, self._load_switches[1]),
            Signal(3, signal_tps, default_time_set, self._load_switches[2]),
            Signal(4, signal_tps, default_time_set, self._load_switches[3]),
            Signal(5, signal_tps, default_time_set, self._load_switches[6]),
            Signal(6, signal_tps, default_time_set, self._load_switches[7]),
            Signal(7, signal_tps, default_time_set, self._load_switches[8]),
            Signal(8, signal_tps, default_time_set, self._load_switches[9]),
            Signal(9, signal_tps, default_time_set, self._load_switches[4]),
            Signal(10, signal_tps, default_time_set, self._load_switches[5]),
            Signal(11, signal_tps, default_time_set, self._load_switches[10]),
            Signal(12, signal_tps, default_time_set, self._load_switches[11])
        ]
        
        self._phases: List[Phase] = [
            Phase(1,
                  [self._signals[0]],
                  True),
            Phase(2,
                  [self._signals[1], self._signals[8]],
                  True),
            Phase(3,
                  [self._signals[2]],
                  True),
            Phase(4,
                  [self._signals[3], self._signals[9]],
                   True),
            Phase(5,
                  [self._signals[4]],
                  True),
            Phase(6,
                  [self._signals[5], self._signals[10]],
                  True),
            Phase(7,
                  [self._signals[6]],
                  True),
            Phase(8,
                  [self._signals[7], self._signals[11]],
                  True)
        ]
        
        self._rings: Set[Ring] = {
            Ring(1, self, self._phases[:5]),
            Ring(2, self, self._phases[5:])
        }
        
        # barrier manager
        self._bm: RingSynchronizer = RingSynchronizer(self, (1, 3), self._rings)
        
        # for software demo and testing purposes
        self._random_actuation: RandomActuation = RandomActuation(tps=1,
                                                                  configuration_node=config['random-actuation'],
                                                                  pool_size=len(self._phases))
    
    def getBarriers(self, configuration_node: List[int]) -> List[int]:
        unique_indices = frozenset(configuration_node)
        rv = sorted(unique_indices)
        assert len(rv) < len(self._phases)
        return rv
    
    @lru_cache(maxsize=16)
    def getConflictingPhases(self, phase: Phase) -> FrozenSet[Phase]:
        conflicts = set()
        for other_phase in self._phases:
            if other_phase == phase:
                continue
            if self.checkPhaseConflict(phase, other_phase):
                conflicts.add(other_phase)
        return frozenset(conflicts)
    
    @lru_cache(maxsize=16)
    def checkPhaseConflict(self, a: Phase, b: Phase) -> bool:
        """
        Check if two phases conflict based on Ring, RingSynchronizer and defined friend
        channels.

        :param a: Phase to compare against
        :param b: Other Phase to compare
        :return: True if conflict
        """
        if a == b:
            raise RuntimeError('Conflict check on the same phase object')
        
        # verify Phase b is not in the same ring
        if b in self.getRingByPhase(a).phases:
            return True
        
        if b not in self._bm.getPool(self.getBarrierByPhase(a)):
            return True
        
        # future: consider FYA-enabled phases conflicts for a non-FYA phase
        
        return False
    
    def getAvailablePhases(self,
                           phases: Iterable,
                           active: List[Phase]) -> FrozenSet[Phase]:
        """
        Determine what phases from a given pool can run given
        the current controller state.

        :param phases: an iterable of Phases to scrutinize
        :param active: currently active phases for iteration
        :return: an immutable set of available Phases
        """
        results: Set[Phase] = set()
        
        for phase in phases:
            if phase in active:
                continue
            
            if any([self.checkPhaseConflict(phase, act) for act in active]):
                continue
            
            results.add(phase)
        
        return frozenset(results)
    
    @lru_cache(maxsize=16)
    def getRingByPhase(self, phase: Phase) -> Ring:
        for ring in self._rings:
            if phase in ring.phases:
                return ring
        
        raise RuntimeError('Failed to get ring')

    def getPhaseRingIndex(self, phase: Phase) -> Optional[int]:
        for ring in self._rings:
            if phase in ring.phases:
                return ring.getPhaseIndex(phase)
        return None
    
    def filterCallsByPhases(self, calls: Iterable[Call], phases: Iterable[Phase]) -> List[Call]:
        return [c for c in calls if c.target in phases]
    
    def filterCallsByBarrier(self, calls: Iterable[Call], barrier: int) -> List[Call]:
        return [c for c in calls if c.target.id in self._bm.getPool(barrier)]
    
    @lru_cache(maxsize=16)
    def getBarrierByPhase(self, phase: Phase) -> int:
        phase_ring_index = self.getPhaseRingIndex(phase)
        for pos in self._bm.positions:
            barrier_range = self._bm.rangeOf(pos)
            if phase_ring_index in barrier_range:
                return pos
        raise RuntimeError('failed to get barrier for phase')
    
    def nextBarrier(self):
        """Change to the next `RingSynchronizer` in the pos cycle instance"""
        self._bm.next()
    
    def getActivePhases(self) -> List[Phase]:
        return [ph for ph in self._phases if ph.active]
    
    def getInactivePhases(self) -> List[Phase]:
        return [ph for ph in self._phases if not ph.active]
    
    def placeCall(self, target: Signal):
        """
        Create a new call for traffic service.

        :param target: the desired Phase to service
        """
        target.demand = True
        logger.debug(f'New call for {target.getTag()}')
    
    def placeAllCall(self):
        """Place calls on all phases"""
        for signal in self._signals:
            signal.demand = True
    
    def allPhasesInactive(self) -> bool:
        for ph in self._phases:
            if ph.active:
                return False
        return True

    async def tickTask(self):
        while True:
            for signal in self._signals:
                signal.tick()
            
            field_text = ''
            for ls in self._load_switches:
                ft = utils.format_fields(ls.a.q, ls.b.q, ls.c.q)
                field_text += f'{ls.id:02d}{ft} '
            logger.field(field_text)
            
            await asyncio.sleep(self.time_increment)

    async def transfer(self):
        """Set the controllers flash transfer relays flag"""
        logger.info('Transferred')
        self._transfer = True

    async def untransfer(self):
        """Unset the controllers flash transfer relays flag"""
        logger.info('Untransfered')
        self._transfer = False

    async def shutdown(self):
        """Run termination tasks to stop control loop"""
        logger.info('beginning shutdown...')
        await asyncio.sleep(2000)
        asyncio.get_event_loop().close()
        logger.info('shutdown complete')
    
    async def run(self):
        logger.info(f'controller is named "{self._name}"')
    
        # noinspection PyUnreachableCode
        if __debug__:
            logger.warning('controller in DEBUG ENVIRONMENT!')

        await self.transfer()
        
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._flasher_a.run(), name='flasher_a')
            tg.create_task(self._flasher_b.run(), name='flasher_b')
            tg.create_task(self._bm.run(), name='barrier_manager')
            tg.create_task(self.tickTask(), name='tick')
