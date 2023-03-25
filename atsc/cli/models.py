from grpc import Channel
from atsc.rpc.controller_pb2 import StatusRequest, StatusResponse
from atsc.rpc.controller_pb2_grpc import ControllerStub


class RemoteController:

    def __init__(self, rpc_channel: Channel):
        self._stub = ControllerStub(rpc_channel)

    def get_status(self) -> StatusResponse:
        request = StatusRequest()
        response: StatusResponse = self._stub.GetStatus(request)
        return response
