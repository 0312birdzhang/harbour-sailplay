"""Bounded grace period for the connection intentionally retired by WPA2 fallback."""
import time


def reassociate_target(interface, properties, target):
    """Restart authentication only when ConnMan has selected the HU network."""
    current=properties.Get('fi.w1.wpa_supplicant1.Interface','CurrentNetwork')
    if str(current)!=str(target):
        return False
    # Explicit Disconnect emits a disconnected transition which ConnMan's
    # SAE failure handler treats as invalid-key and removes the network.
    interface.Reassociate()
    return True


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
