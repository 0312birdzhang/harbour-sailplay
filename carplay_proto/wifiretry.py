"""Bounded grace period for the connection intentionally retired by WPA2 fallback."""
import time


class HandoverRetry:
    """Retry a failed Wi-Fi handover while its authenticated Bluetooth link lives."""
    def __init__(self, active, launch, clock=time.monotonic, interval=45):
        self.active, self.launch, self.clock = active, launch, clock
        self.interval = interval
        self.deadline = None

    def arm(self):
        self.deadline = self.clock() + self.interval

    def poll(self):
        if self.deadline is None or self.clock() < self.deadline:
            return False
        self.arm()
        if self.active():
            return False
        self.launch()
        return True


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
