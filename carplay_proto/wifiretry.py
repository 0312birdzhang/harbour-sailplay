"""Bounded grace period for the connection intentionally retired by WPA2 fallback."""
import time


class HandoverRetry:
    """Retry a failed Wi-Fi handover while its authenticated Bluetooth link lives.

    The first retry keeps the short interval the WPA2 fallback relies on.
    Later ones back off: a head unit that sees a rapid series of failed
    handovers can stop offering CarPlay to the phone until it has slept.

    active() says that a handover worker is running, so another must not be
    launched. established() says that a worker reached media streaming, and
    only that resets the backoff: a worker holds its lease from start-up, long
    before the Wi-Fi connection, pairing or streaming can have succeeded.
    """
    def __init__(self, active, launch, clock=time.monotonic, interval=10, maximum=60, established=None):
        self.active, self.launch, self.clock = active, launch, clock
        self.established = established or (lambda: False)
        self.interval = interval
        self.maximum = maximum
        self.failures = 0
        self.deadline = None

    def delay(self):
        return min(self.maximum, self.interval * 2 ** self.failures)

    def arm(self):
        self.deadline = self.clock() + self.delay()

    def poll(self):
        if self.deadline is None or self.clock() < self.deadline:
            return False
        if self.active():
            if self.established():
                self.failures = 0
            self.arm()
            return False
        self.failures += 1
        self.arm()
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
        self.idle_since=None

    def arm(self):
        # Repeated NetworkAdded signals cannot extend the grace period forever.
        if not self.deadline:
            self.deadline=self.clock()+15
        self.idle_since=None

    def waiting(self):
        return not self.started and self.clock()<self.deadline

    def abandoned(self, connman_state, supplicant, associated_ssid=None, target_ssid=None):
        current = str(supplicant.get('CurrentNetwork') or '')
        idle = (supplicant.get('State') in ('inactive', 'disconnected', 'scanning')
                and current == '/')
        returned = (supplicant.get('State') == 'completed'
                    and current.startswith('/') and current != '/'
                    and associated_ssid and target_ssid and associated_ssid != target_ssid)
        if (self.started or not self.deadline or connman_state not in ('idle', 'failure')
                or not (idle or returned)):
            self.idle_since = None
            return False
        now = self.clock()
        if self.idle_since is None:
            self.idle_since = now
        return now - self.idle_since >= 2


def mixed_wpa_security(configuration):
    """WPA2 is eligible only when the target offers both PSK and SAE."""
    methods = str(configuration.get('key_mgmt', '')).split()
    return 'WPA-PSK' in methods and 'SAE' in methods
