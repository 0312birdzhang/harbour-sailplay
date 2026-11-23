"""Bring mobile data back when it drops during a projection.

The phone stays associated with the head unit's Wi-Fi, which has no route
to the Internet, so everything else relies on the cellular connection made
before the handover. A circuit-switched call makes the modem clear its data
context; ConnMan then leaves the cellular service idle for as long as the
head unit's Wi-Fi is connected, and refuses Connect requests coming from
applications. Radio and streaming players stay silent until the projection
ends. Ask for the connection again ourselves.
"""
import threading
import time

from .networkdbus import network_interface, network_object


CONNMAN = 'net.connman'
CONNECTED = ('ready', 'online')
RETRY_SECONDS = 10


class MobileDataKeeper:
    def __init__(self, log=print):
        self.log = log
        self.stop = threading.Event()
        self.thread = None
        self.wanted = set()
        self.retry_at = {}
        self.last_message = None

    def report(self, message):
        if message != self.last_message:
            self.log(message)
            self.last_message = message

    def poll(self):
        now = time.monotonic()
        for path, properties in self.manager.GetServices():
            if str(properties.get('Type')) != 'cellular':
                continue
            path, state = str(path), str(properties.get('State'))
            if state in CONNECTED:
                if path in self.retry_at:
                    self.report('Mobile data restored service={} state={}'.format(path, state))
                self.wanted.add(path)
                self.retry_at.pop(path, None)
                continue
            # Only restore what was up during this projection and what the
            # user still wants: switching mobile data off clears AutoConnect.
            if path not in self.wanted or state not in ('idle', 'failure'):
                continue
            if not properties.get('AutoConnect'):
                self.wanted.discard(path)
                self.retry_at.pop(path, None)
                continue
            if now < self.retry_at.get(path, 0):
                continue
            self.retry_at[path] = now + RETRY_SECONDS
            service = network_interface(network_object(self.system, CONNMAN, path), 'net.connman.Service')
            try:
                service.Connect(timeout=RETRY_SECONDS)
                self.report('Mobile data reconnection requested service={} state={}'.format(path, state))
            except Exception as error:
                name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
                if name not in ('net.connman.Error.AlreadyConnected', 'net.connman.Error.InProgress'):
                    self.report('Mobile data reconnection service={} error={}'.format(path, name))

    def run(self):
        import dbus
        self.system = dbus.SystemBus(private=True)
        try:
            self.manager = network_interface(network_object(self.system, CONNMAN, '/'), 'net.connman.Manager')
            while not self.stop.is_set():
                try:
                    self.poll()
                except Exception as error:
                    name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
                    self.report('Mobile data monitor error=' + name)
                self.stop.wait(3)
        finally:
            self.system.close()

    def start(self):
        if self.thread is None and not self.stop.is_set():
            self.thread = threading.Thread(target=self.run, name='mobile-data', daemon=True)
            self.thread.start()
            self.report('Mobile data monitor started')

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(RETRY_SECONDS + 2)
