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
    def __init__(self, health=None):
        self.health = health
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
            lease = CpuLease(interface, 'sailplay-projection-{}'.format(os.getpid()))
            while not self.stop.is_set():
                delay = 5
                try:
                    delay = lease.renew()
                    state = (str(interface.get_display_status(timeout=2)),
                             str(interface.get_tklock_mode(timeout=2)),
                             bool(interface.get_inactivity_status(timeout=2)))
                    now = time.monotonic()
                    if state != last_state or now >= next_report:
                        print('Projection power CPU lease active display={} lock={} inactive={} input={}'.format(
                            *state, self.health() if self.health else None), flush=True)
                        last_state, next_report = state, now + 60
                except Exception as error:
                    logging.warning('Projection power lease/state unavailable: %s', type(error).__name__)
                self.stop.wait(delay)
        except Exception as error:
            logging.warning('Projection power unavailable: %s', type(error).__name__)
        finally:
            if lease:
                try:
                    lease.close()
                    print('Projection CPU lease released', flush=True)
                except Exception:
                    logging.warning('Projection CPU lease release failed; bounded lease will expire')
            if bus:
                bus.close()

    def close(self):
        self.stop.set()
        self.thread.join(12)
