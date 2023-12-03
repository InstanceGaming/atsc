from abc import ABC, abstractmethod


class LogicBase(ABC):
    
    def __init__(self):
        self.q = False
        
    def __bool__(self):
        return self.q
    
    @abstractmethod
    def poll(self, *args, **kwargs):
        pass


class EdgeTrigger(LogicBase):
    
    def __init__(self, polarity: bool):
        """
        Pulse Q when a logic signal has changed from one state to another.
        
        :param polarity: True for rising-edge, False for falling-edge.
        """
        super().__init__()
        self.polarity = polarity
        self.previous = not polarity
    
    def poll(self, signal: bool) -> bool:
        """
        Check the signal state against the previous.
        
        :param signal: Logic signal to monitor for edge changes.
        :return: True only if the edge has changed this poll.
        """
        if (self.polarity and (not self.previous and signal) or
                not self.polarity and (self.previous and not signal)):
            
            self.q = True
        else:
            self.q = False
        
        self.previous = signal
        return self.q


class Latch(LogicBase):
    
    def __init__(self, xor: bool):
        """
        Maintain Q when set, clear Q when reset.
        
        :param xor: True makes Q equal False when set AND reset are
        simultaneously True, otherwise set will override Q while True.
        """
        super().__init__()
        self.xor = xor
        self.set_rising = EdgeTrigger(True)
        self.reset_rising = EdgeTrigger(True)
    
    def poll(self, set_: bool, reset: bool) -> bool:
        if set_ and reset:
            self.q = not self.xor
        else:
            if set_:
                self.q = True
            else:
                if reset:
                    self.q = False
        
        return self.q


class Timer(LogicBase):
    
    @property
    def countdown(self):
        return self.step < 0
    
    @property
    def initial(self):
        return self.trigger if self.countdown else 0
    
    @property
    def delta(self):
        return self.initial - self.elapsed
    
    def __init__(self,
                 trigger,
                 step=1,
                 invert=False):
        super().__init__()
        assert step
        self.invert = invert
        self.step = step
        self.trigger = trigger
        self.elapsed = self.initial
    
    def reset(self):
        self.q = self.invert
        self.elapsed = self.initial
    
    def poll(self, signal: bool) -> bool:
        if signal:
            self.q = abs(self.delta) >= (self.trigger - self.step)
            self.elapsed += self.step
        else:
            self.reset()
        return self.q
