"""Shared compatibility fixtures."""


class Clock:
    now = 0.
    def __call__(self): return self.now
    def advance(self, m, seconds):
        for _ in range(seconds):
            self.now += 1
            m.tick()
