"""Bounded grace period for the connection intentionally retired by WPA2 fallback."""
import time


class ReassociationWindow:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.deadline=0.0
        self.started=False

    def arm(self):
        # Repeated NetworkAdded signals cannot extend the grace period forever.
        if not self.deadline:
            self.deadline=self.clock()+15

    def waiting(self):
        return not self.started and self.clock()<self.deadline
