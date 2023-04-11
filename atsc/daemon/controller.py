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
from atsc.daemon.models import (DeviceInfo,
                                Roadway,
                                PhaseCollection,
                                ApproachCollection,
                                RoadwayCollection,
                                OutputCollection, InputCollection)
from atsc.daemon.rpcserver import (register_controller_service,
                                   ControllerServicer)
from atsc.utils import text_to_enum


LOCK_TIMEOUT = 0.05
BASE_TICK = 0.1
LOG_MSG_DT_FORMAT = '%I:%M %p %b %d %Y'


class Controller(ThreadedTickable, Nameable):

    def __init__(self,
                 context: RunContext,
                 device_info: DeviceInfo,
                 startup_mode: ControlMode,
                 startup_delay: int,
                 startup_actuated: bool,
                 actuated: bool,
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
        self._mode = startup_mode
        self._start_delay = startup_delay
        self._start_actuated = startup_actuated

        # control flags
        self._actuated = actuated
        self._transfer = False
        self._freeze = False

        # initial_state
        self._active_phases: PhaseCollection = PhaseCollection(limit=2)
        self._active_approaches: ApproachCollection = ApproachCollection(limit=2)
        self._active_roadway: Optional[Roadway] = None

        # counters
        self._cycle_count: int = 0
        self._second_count: int = 0  # 1Hz counter (0-8)

        thread_pool = futures.ThreadPoolExecutor(max_workers=4)
        self._rpc_service = ControllerServicer(self)
        self._rpc_server: grpc.Server = grpc.server(thread_pool)
        register_controller_service(self._rpc_service, self._rpc_server)
        if rpc_connection is not None:
            self.setup_rpc(rpc_connection)

    def setup_rpc(self, rpc_connection: str):
        self._rpc_server.add_insecure_port(rpc_connection)

    def change_mode(self, new_mode: ControlMode) -> int:
        pass

    def second(self):
        pass

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
            self._roads.tick()
            self._outputs.tick()
            self.update_counters()

    def before_run(self):
        self._rpc_server.start()
        self._start_timestamp = datetime.now(self._timezone)
        logger.info('started at {}',
                    self._start_timestamp.strftime(LOG_MSG_DT_FORMAT))
        self.change_mode(self._mode)

    def after_run(self, code: int):
        self._rpc_server.stop(1)
        logger.info(f'shutdown with exit code {code}')
        delta = datetime.now(self._timezone) - self._start_timestamp
        ed, eh, em, es = utils.format_dhms(delta.total_seconds())
        logger.info('runtime of {} days, {} hours, {} minutes and {} seconds',
                    ed, eh, em, es)

    @staticmethod
    def deserialize(data, context=None):
        if context is None:
            raise ValueError('context kwarg required')

        if isinstance(data, dict):
            actuated = data['actuated']
            startup_node = data['startup']
            startup_mode = text_to_enum(ControlMode, startup_node['mode'])
            startup_delay = startup_node['delay']
            startup_actuated = startup_node['actuated']

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
                              startup_actuated,
                              actuated,
                              phases,
                              approaches,
                              roadways,
                              outputs,
                              inputs)
        else:
            raise TypeError()
