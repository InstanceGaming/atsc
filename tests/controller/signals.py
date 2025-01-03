import asyncio
from grpclib.client import Channel
from atsc.rpc.controller import (
    ControllerStub,
    ControllerSignalDemandRequest,
    ControllerSignalPresenceRequest
)
from atsc.common.constants import RPC_PORT, RPC_ADDRESS


async def run():
    channel = Channel(host=RPC_ADDRESS, port=RPC_PORT)
    try:
        controller = ControllerStub(channel)
        await controller.set_signal_demand(ControllerSignalDemandRequest(
            id=508, demand=True
        ))
        flasher = True
        for i in range(30):
            await controller.set_signal_presence(ControllerSignalPresenceRequest(
                id=502,
                presence=flasher
            ))
            await asyncio.sleep(2.0)
            flasher = not flasher
        await controller.set_signal_presence(ControllerSignalPresenceRequest(
            id=502,
            presence=False
        ))
    finally:
        channel.close()


if __name__ == '__main__':
    exit(asyncio.get_event_loop().run_until_complete(run()))
