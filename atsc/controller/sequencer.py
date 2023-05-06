from typing import Any, Optional

from atsc.common.models import ControlMode
from atsc.controller.interfaces import ISequencer, IController
from atsc.controller.models import Roadway, Approach


class EntranceSequence(ISequencer):
    
    @property
    def mode(self):
        return ControlMode.CET
    
    @property
    def next_modes(self):
        return [ControlMode.NORMAL]

    @property
    def transitioning(self) -> bool:
        return self._transitioning
    
    def __init__(self, controller: IController):
        super().__init__(controller.tick_delay)
        self._controller = controller
        self._transitioning = False
    
    def tick(self, *args, **kwargs) -> Any:
        pass
    
    def enter(self, prev: Optional[ControlMode]):
        if prev is not None:
            raise NotImplementedError()

        self._transitioning = True
        
        road: Roadway
        for road in self._controller.roadways:
            approach: Approach
            for approach in road.approaches:
                approach.phases
                

    def leave(self, nxt: Optional[ControlMode]):
        self._transitioning = True


class NormalSequence(ISequencer):

    @property
    def mode(self):
        return ControlMode.NORMAL
    
    @property
    def next_modes(self):
        return [ControlMode.CXT, ControlMode.LS_FLASH]

    @property
    def transitioning(self) -> bool:
        return False

    def __init__(self, controller: IController):
        super().__init__(controller.tick_delay)
        self._controller = controller
        self._transitioning = False

    def tick(self, *args, **kwargs) -> Any:
        pass

    def enter(self, prev: Optional[ControlMode]):
        pass

    def leave(self, nxt: Optional[ControlMode]):
        pass
