from atsc.logging import setup_logger
from atsc.programs import Controller
from atsc.models import *
from atsc.constants import *
from atsc.primitives import ref


logger = setup_logger('FIELD,INFO;stderr=ERROR')


def generate_load_switches():
    switches = []
    flags = [
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.PED | LSFlag.PED_CLEAR,
        LSFlag.PED | LSFlag.PED_CLEAR,
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.STANDARD,
        LSFlag.PED | LSFlag.PED_CLEAR,
        LSFlag.PED | LSFlag.PED_CLEAR
    ]
    ls_index = 301
    field_index = 101
    for i in range(12):
        field_triad = FieldTriad(field_index,
                                 field_index + 1,
                                 field_index + 2)
        polarity = FlashPolarity.A
        if i % 4 == 3 or i % 4 == 0:
            polarity = FlashPolarity.B
        load_switch = LoadSwitch.make_generic(ls_index,
                                              field_triad,
                                              flags[i],
                                              flash_polarity=polarity)
        ls_index += 1
        field_index += 3
        switches.append(load_switch)
    
    return switches


load_switches = generate_load_switches()
plan_thru = TimingPlan(
    {
        SignalState.STOP   : 1,
        SignalState.CAUTION: 3,
        SignalState.GO     : 3
    },
    {
        SignalState.STOP   : 300,
        SignalState.CAUTION: 6,
        SignalState.GO     : 15
    }
)
plan_ped = TimingPlan(
    {
        SignalState.STOP   : 6,
        SignalState.CAUTION: 10,
        SignalState.GO     : 5
    }
)
signals = [
    Signal(501, plan_thru, ref(301, LoadSwitch)),
    Signal(502, plan_thru, ref(302, LoadSwitch)),
    Signal(503, plan_thru, ref(303, LoadSwitch)),
    Signal(504, plan_thru, ref(304, LoadSwitch)),
    Signal(505, plan_thru, ref(307, LoadSwitch)),
    Signal(506, plan_thru, ref(308, LoadSwitch)),
    Signal(507, plan_thru, ref(309, LoadSwitch)),
    Signal(508, plan_thru, ref(310, LoadSwitch)),
    Signal(509, plan_ped, ref(305, LoadSwitch)),
    Signal(510, plan_ped, ref(306, LoadSwitch)),
    Signal(511, plan_ped, ref(311, LoadSwitch)),
    Signal(512, plan_ped, ref(312, LoadSwitch)),
]
phases = [
    Phase(601, (ref(501, Signal),)),
    Phase(602, (ref(502, Signal), ref(509, Signal))),
    Phase(603, (ref(503, Signal),)),
    Phase(604, (ref(504, Signal), ref(510, Signal))),
    Phase(605, (ref(505, Signal),)),
    Phase(606, (ref(506, Signal), ref(511, Signal))),
    Phase(607, (ref(507, Signal),)),
    Phase(608, (ref(508, Signal), ref(512, Signal)))
]
red_clearance = 1.0
rings = [
    Ring(701, (601, 602, 603, 604), red_clearance),
    Ring(702, (605, 606, 607, 608), red_clearance)
]
barriers = [
    Barrier(801, (601, 602, 605, 606)),
    Barrier(802, (603, 604, 607, 608))
]
Controller(logger, signals, rings, barriers).start()
