"""Session-scoped MCE CPU lease; leave phone display and lock policy alone."""
import logging
import os
import threading
import time


class CpuLease:
    def __init__(self, interface, token):
        self.interface, self.token = interface, token

    def renew(self):
        period = int(self.interface.req_cpu_keepalive_period(self.token, timeout=2))
        if period < 2 or not self.interface.req_cpu_keepalive_start(self.token, timeout=2):
            raise RuntimeError('MCE rejected projection CPU lease')
        return min(20.0, period / 3.0)

    def close(self):
        self.interface.req_cpu_keepalive_stop(self.token, timeout=2)


class ProjectionPower:
    def __init__(self, health=None, phase='projection', maximum_seconds=None, clock=None):
        if maximum_seconds is not None and not 0 < maximum_seconds <= 120:
            raise ValueError('connection power deadline must be within 120 seconds')
        self.health = health
        self.phase = phase
        self.maximum_seconds = maximum_seconds
        self.clock = clock or (lambda: time.clock_gettime(time.CLOCK_BOOTTIME))
        # A setup lease and a media lease can overlap in the same process.
        self.token = 'sailplay-{}-{}-{}'.format(phase, os.getpid(), id(self))
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        import dbus
        bus = lease = None
        last_state = None
        next_report = 0
        try:
            bus = dbus.SystemBus(private=True)
            interface = dbus.Interface(bus.get_object('com.nokia.mce', '/com/nokia/mce/request'),
                                       'com.nokia.mce.request')
            lease = CpuLease(interface, self.token)
            deadline = self.clock() + self.maximum_seconds if self.maximum_seconds is not None else None
            while not self.stop.is_set():
                if deadline is not None and self.clock() >= deadline:
                    break
                delay = 5
                try:
                    delay = lease.renew()
                    state = (str(interface.get_display_status(timeout=2)),
                             str(interface.get_tklock_mode(timeout=2)),
                             bool(interface.get_inactivity_status(timeout=2)))
                    now = time.monotonic()
                    if state != last_state or now >= next_report:
                        if self.phase != 'projection':
                            logging.info('CPU lease active phase=%s maximumSeconds=%s', self.phase, self.maximum_seconds)
                        print('Projection power CPU lease active phase={} display={} lock={} inactive={} input={}'.format(
                            self.phase, *state, self.health() if self.health else None), flush=True)
                        last_state, next_report = state, now + 60
                except Exception as error:
                    logging.warning('Projection power lease/state unavailable: %s', type(error).__name__)
                if deadline is not None:
                    delay = min(delay, max(0, deadline - self.clock()))
                self.stop.wait(delay)
        except Exception as error:
            logging.warning('Projection power unavailable: %s', type(error).__name__)
        finally:
            if lease:
                try:
                    lease.close()
                    if self.phase != 'projection':
                        logging.info('CPU lease released phase=%s', self.phase)
                    print('Projection CPU lease released phase={}'.format(self.phase), flush=True)
                except Exception:
                    logging.warning('Projection CPU lease release failed; bounded lease will expire')
            if bus:
                bus.close()

    def close(self):
        self.stop.set()
        self.thread.join(12)


def with_connection_power(function, *args, **kwargs):
    """Keep a real attempt/teardown awake; never inhibit an idle listener."""
    power = ProjectionPower(phase='connection', maximum_seconds=90)
    power.start()
    try:
        return function(*args, **kwargs)
    finally:
        power.close()


class ProfileConnectionPower:
    """One bounded wake window per linked HU, including RFCOMM discovery."""
    def __init__(self, factory=None):
        self.factory = factory or (lambda: ProjectionPower(phase='profile', maximum_seconds=90))
        self.power = None

    def open(self):
        if self.power is None:
            self.power = self.factory()
            self.power.start()

    def close(self):
        power, self.power = self.power, None
        if power is not None:
            power.close()
