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
from concurrent import futures
import grpc
from loguru import logger
from typing import Optional
from datetime import datetime
from dateutil import tz
from atsc import utils
from atsc.core.fundemental import Nameable
from atsc.core.models import ControlMode
from atsc.core.parallel import ThreadedTickable
from atsc.daemon.context import RunContext
from atsc.daemon.interfaces import IController, ISequencer
from atsc.daemon.models import (DeviceInfo,
                                PhaseCollection,
                                ApproachCollection,
                                RoadwayCollection,
                                OutputCollection, InputCollection)
from atsc.daemon.rpcserver import (register_controller_service,
                                   ControllerServicer)
from atsc.daemon.sequencer import EntranceSequence, NormalSequence
from atsc.utils import text_to_enum


LOCK_TIMEOUT = 0.05
BASE_TICK = 0.1
LOG_MSG_DT_FORMAT = '%I:%M %p %b %d %Y'


class Controller(IController):
    
    @property
    def free(self):
        return self._free
    
    @property
    def idle(self):
        return False

    @property
    def saturated(self):
        return False

    @property
    def transferred(self):
        return self._transfer
    
    @transferred.setter
    def transferred(self, value):
        self._transfer_count += 1
        self._transfer = value
    
    @property
    def avg_demand(self):
        return self._avg_demand

    @property
    def peek_demand(self):
        return self._peek_demand

    @property
    def runtime(self):
        return self._runtime

    @property
    def control_time(self):
        return self._control_time

    @property
    def transfer_count(self):
        return self._transfer_count

    @property
    def inputs(self) -> InputCollection:
        return self._inputs

    @property
    def outputs(self) -> OutputCollection:
        return self._outputs

    @property
    def phases(self) -> PhaseCollection:
        return self._phases

    @property
    def approaches(self) -> ApproachCollection:
        return self._approaches

    @property
    def roadways(self) -> RoadwayCollection:
        return self._roads
    
    @property
    def sequencer(self):
        return self._sequencer
    
    @property
    def previous_mode(self):
        return self._previous_mode

    @property
    def current_mode(self):
        return self._sequencer.mode

    @property
    def next_mode(self):
        return self._next_mode

    def __init__(self,
                 context: RunContext,
                 device_info: DeviceInfo,
                 startup_mode: ControlMode,
                 startup_delay: int,
                 start_free: bool,
                 free: bool,
                 phases: PhaseCollection,
                 approaches: ApproachCollection,
                 roadways: RoadwayCollection,
                 outputs: OutputCollection,
                 inputs: InputCollection,
                 name: Optional[str] = None,
                 rpc_connection: Optional[str] = None):
        ThreadedTickable.__init__(self,
                                  context.tick_delay,
                                  thread_name='Controller')
        Nameable.__init__(self, name=name)
        self._timezone = tz.gettz(device_info.timezone)
        self._start_timestamp = None

        # models
        self._inputs = inputs
        self._outputs = outputs
        self._phases = phases
        self._approaches = approaches
        self._roads = roadways

        # startup
        self._start_delay = startup_delay
        self._start_free = start_free

        # control flags
        self._free = free
        self._transfer = False
        self._freeze = False

        # initial_state
        self._active_phases: PhaseCollection = PhaseCollection(limit=2)
        self._active_approaches: ApproachCollection = ApproachCollection(limit=2)
        self._active_roads: RoadwayCollection = RoadwayCollection()

        # sequencing
        self._previous_mode: Optional[ControlMode] = None
        self._sequencer: ISequencer = self.get_mode_sequencer(startup_mode)
        self._next_mode: Optional[ControlMode] = None

        # counters
        self._cycle_count: int = 0
        self._second_count: int = 0  # 1Hz counter (0-8)
        self._runtime: int = 0
        self._control_time: int = 0
        self._transfer_count: int = 0

        # stats
        self._avg_demand: float = 0
        self._peek_demand: float = 0
        
        # rpc server
        thread_pool = futures.ThreadPoolExecutor(max_workers=4)
        self._rpc_service = ControllerServicer(self)
        self._rpc_server: grpc.Server = grpc.server(thread_pool)
        register_controller_service(self._rpc_service, self._rpc_server)
        if rpc_connection is not None:
            self.setup_rpc(rpc_connection)

    def setup_rpc(self, rpc_connection: str):
        self._rpc_server.add_insecure_port(rpc_connection)
        logger.info('setup RPC insecure connection on "{}"', rpc_connection)

    def get_mode_sequencer(self, mode: ControlMode) -> ISequencer:
        if mode == ControlMode.CET:
            return EntranceSequence(self)
        elif mode == ControlMode.NORMAL:
            return NormalSequence(self)
        raise NotImplementedError()

    def change_mode(self, new_mode: ControlMode) -> int:
        pass

    def second(self):
        self._runtime += 1
        if self._transfer:
            self._control_time += 1

    def update_counters(self):
        if self._second_count == 8:
            self._second_count = 0
            self.second()
        else:
            self._second_count += 1

    def tick(self):
        """Polled once every 100ms (default tick_delay)"""

        if not self._freeze:
            self._inputs.tick()
            self._sequencer.tick()
            self._roads.tick()
            self._outputs.tick()
            self.update_counters()

    def before_run(self):
        self._rpc_server.start()
        self._start_timestamp = datetime.now(self._timezone)
        logger.info('started at {}',
                    self._start_timestamp.strftime(LOG_MSG_DT_FORMAT))
        self._sequencer.enter(None)

    def after_run(self, code: int):
        self._rpc_server.stop(1)
        logger.info(f'shutdown with exit code {code}')
        delta = datetime.now(self._timezone) - self._start_timestamp
        ed, eh, em, es = utils.format_dhms(delta.total_seconds())
        logger.info('runtime of {} days, {} hours, {} minutes and {:.1f} seconds',
                    ed, eh, em, es)

    @staticmethod
    def deserialize(data, context=None):
        if context is None:
            raise ValueError('context kwarg required')

        if isinstance(data, dict):
            free = data['free']
            startup_node = data['startup']
            startup_mode = text_to_enum(ControlMode, startup_node['mode'])
            startup_delay = startup_node['delay']
            startup_free = startup_node['free']

            inputs_node = data['inputs']
            inputs: InputCollection = InputCollection.deserialize(inputs_node,
                                                                  context=context)

            outputs_node = data['outputs']
            outputs: OutputCollection = OutputCollection.deserialize(outputs_node,
                                                                     context=context)

            phases_node = data['phases']
            phases: PhaseCollection = PhaseCollection.deserialize(phases_node)

            approaches_node = data['approaches']
            approaches: ApproachCollection = ApproachCollection.deserialize(approaches_node)

            roadways_node = data['roadways']
            roadways: RoadwayCollection = RoadwayCollection.deserialize(roadways_node)

            device_node = data['device']
            device_info = DeviceInfo.deserialize(device_node)

            return Controller(context,
                              device_info,
                              startup_mode,
                              startup_delay,
                              startup_free,
                              free,
                              phases,
                              approaches,
                              roadways,
                              outputs,
                              inputs)
        else:
            raise TypeError()
