from grpc import Server

from atsc.core.models import ControlState, ControlMode
from atsc.rpc import controller_pb2 as pb_models
from atsc.rpc import controller_pb2_grpc as rpc_models


class ControllerServicer(rpc_models.ControllerServicer):

    def __init__(self, controller):
        self._controller = controller

    def GetStatus(self, request, context):
        mode = ControlMode.NORMAL
        state = (ControlState.ACTUATED |
                 ControlState.GLOBAL_PED_SERVICE |
                 ControlState.GLOBAL_PED_CLEAR)
        state |= (self._controller.idle & ControlState.IDLE)
        state |= (self._controller.saturated & ControlState.SATURATED)
        state |= (self._controller.transferred &
                  ControlState.TRANSFERRED)
        state |= (__debug__ & ControlState.DEBUG)
        plan_id = 0
        avg_demand = self._controller.avg_demand
        peek_demand = self._controller.peek_demand
        runtime = self._controller.runtime
        control_time = self._controller.control_time
        transfer_count = self._controller.transfer_count
        return pb_models.StatusResponse(mode=mode,
                                        state_flags=state,
                                        plan_id=plan_id,
                                        avg_demand=avg_demand,
                                        peek_demand=peek_demand,
                                        runtime=runtime,
                                        control_time=control_time,
                                        transfer_count=transfer_count)


def register_controller_service(servicer: ControllerServicer,
                                server: Server):
    rpc_models.add_ControllerServicer_to_server(servicer,
                                                server)
