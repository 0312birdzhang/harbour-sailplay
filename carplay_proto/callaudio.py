"""Route native Sailfish calls to the authenticated projection head unit."""
import os
import threading
import time

from .bluezadapter import resolve_device
from .networkdbus import network_interface, network_object


VOICE_MANAGER = 'org.nemomobile.voicecall.VoiceCallManager'
ROUTE_MANAGER = 'org.nemomobile.Route.Manager'
ROUTE_PATH = '/org/nemomobile/Route/Manager'
HFP_HEADSET = '0000111e-0000-1000-8000-00805f9b34fb'
BLUETOOTH_OVERRIDE = 'bluetooth_override'


class CallAudioRouter:
    def __init__(self, device, log=print, keep_connected=False):
        self.device = device
        # Hold the hands-free profile for the whole projection, so that it is
        # already up when an outgoing call is dialled.
        self.keep_connected = keep_connected
        self.standby_device = None
        self.standby_owner = None
        self.standby_retry_at = 0
        self.log = log
        self.stop = threading.Event()
        self.thread = None
        self.call_ids = ()
        self.attempts = 0
        self.profile_requested = False
        self.profile_retry_at = 0
        self.profile_device = None
        self.profile_owner = None
        self.allowed_once = False
        self.owns_override = False
        self.applied = False
        self.last_message = None

    def report(self, message):
        if message != self.last_message:
            self.log(message)
            self.last_message = message

    def call_properties(self):
        return self.voice.GetAll(VOICE_MANAGER)

    def standby(self):
        now = time.monotonic()
        if now < self.standby_retry_at:
            return
        self.standby_retry_at = now + 5
        objects = self.devices.GetManagedObjects()
        target = resolve_device(objects, self.device)
        properties = objects.get(target, {}).get('org.bluez.Device1', {})
        if not properties.get('Connected'):
            self.standby_device = self.standby_owner = None
            return
        owner = self.system.get_name_owner('org.bluez')
        if self.standby_device == target and self.standby_owner == owner:
            return
        if not properties.get('Paired') or HFP_HEADSET not in properties.get('UUIDs', []):
            return
        self.standby_retry_at = now + 15
        device = network_interface(network_object(self.system, 'org.bluez', target), 'org.bluez.Device1')
        try:
            device.ConnectProfile(HFP_HEADSET, timeout=6)
        except Exception as error:
            name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
            if name != 'org.bluez.Error.AlreadyConnected':
                self.report('Call audio HFP standby target={} error={}'.format(target, name))
                return
        self.standby_retry_at = now + 5
        self.standby_device, self.standby_owner = target, owner
        self.report('Call audio HFP standby ready target={}'.format(target))

    def release(self, final=False):
        # Wi-Fi/video teardown must allow an ongoing native HFP call to finish.
        if self.call_properties().get('voiceCalls'):
            return False
        if self.keep_connected and final and not self.profile_device:
            self.profile_device, self.profile_owner = self.standby_device, self.standby_owner
        if self.keep_connected and final:
            self.standby_device = self.standby_owner = None
        if self.owns_override:
            features = self.routes.GetAll()[4]
            if self.call_properties().get('voiceCalls'):
                return False
            if any(str(name) == BLUETOOTH_OVERRIDE and allowed and not enabled
                   for name, allowed, enabled in features):
                self.routes.Enable(BLUETOOTH_OVERRIDE)
            self.owns_override = False
        if self.profile_device and self.keep_connected and not final:
            # Ours to disconnect, but only once the projection ends.
            self.standby_device, self.standby_owner = self.profile_device, self.profile_owner
            self.profile_device = self.profile_owner = None
        if self.profile_device:
            if self.call_properties().get('voiceCalls'):
                return False
            # A replacement BlueZ process owns a different profile lifetime.
            if self.system.get_name_owner('org.bluez') == self.profile_owner:
                device = network_interface(network_object(self.system, 'org.bluez', self.profile_device),
                                           'org.bluez.Device1')
                try:
                    device.DisconnectProfile(HFP_HEADSET, timeout=5)
                except Exception as error:
                    name = getattr(error, 'get_dbus_name', lambda: '')()
                    if name not in ('org.bluez.Error.NotConnected', 'org.bluez.Error.DoesNotExist',
                                    'org.freedesktop.DBus.Error.UnknownObject'):
                        raise
            self.profile_device = self.profile_owner = None
        self.profile_requested = False
        self.profile_retry_at = 0
        self.applied = False
        self.allowed_once = False
        self.attempts = 0
        self.call_ids = ()
        return True

    def poll(self):
        properties = self.call_properties()
        calls = tuple(map(str, properties.get('voiceCalls', [])))
        if not calls:
            if self.call_ids and self.release():
                self.report('Call audio session ended; temporary HFP routing released')
            if self.keep_connected:
                self.standby()
            return
        if not set(calls).intersection(self.call_ids):
            self.applied = False
            self.attempts = 0
        self.call_ids = calls
        objects = self.devices.GetManagedObjects()
        target = resolve_device(objects, self.device)
        device_properties = objects.get(target, {}).get('org.bluez.Device1', {})
        if not device_properties.get('Paired') or HFP_HEADSET not in device_properties.get('UUIDs', []):
            self.report('Call audio unavailable: projection head unit has no paired HFP profile')
            return
        other_headsets = [path for path, interfaces in objects.items()
                          for values in [interfaces.get('org.bluez.Device1', {})]
                          if str(path) != target and values.get('Connected')
                          and HFP_HEADSET in values.get('UUIDs', [])]
        if other_headsets:
            self.report('Call audio automatic routing deferred: another HFP device is connected')
            return
        if self.profile_requested and not device_properties.get('Connected'):
            self.profile_requested = False
            self.applied = False
        if not self.profile_requested and self.attempts < 3 and time.monotonic() >= self.profile_retry_at:
            self.attempts += 1
            self.profile_retry_at = time.monotonic() + 6
            device = network_interface(network_object(self.system, 'org.bluez', target), 'org.bluez.Device1')
            owner = self.system.get_name_owner('org.bluez')
            try:
                device.ConnectProfile(HFP_HEADSET, timeout=6)
                self.profile_device, self.profile_owner = target, owner
            except Exception as error:
                name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
                if name != 'org.bluez.Error.AlreadyConnected':
                    self.report('Call audio HFP connection attempt={} target={} error={}'.format(
                        self.attempts, target, name))
                    return
            self.profile_requested = True
            self.report('Call audio HFP request accepted attempt={} target={}'.format(self.attempts, target))
        if self.stop.is_set():
            return
        # Connecting a profile can outlast the call which requested it.
        properties = self.call_properties()
        if not properties.get('voiceCalls'):
            self.release()
            return
        output, output_type, microphone, microphone_type, features = self.routes.GetAll()
        allowed, enabled = next(((bool(allowed), bool(enabled)) for name, allowed, enabled in features
                                 if str(name) == BLUETOOTH_OVERRIDE), (False, False))
        if self.allowed_once and not allowed:
            # HFP can disappear while another profile keeps the ACL connected.
            self.profile_requested = False
            self.applied = False
            self.attempts = 0
            self.profile_retry_at = 0
        elif not allowed and time.monotonic() >= self.profile_retry_at:
            # An accepted request does not establish native call audio support.
            self.profile_requested = False
        self.allowed_once = allowed
        if not self.applied and allowed and device_properties.get('Connected') and properties.get('isAudioRouted'):
            # bluetooth_override selects the phone. The stock Bluetooth call
            # switch disables this feature to enable headset output and input.
            # Apply our automatic selection once per call.
            if properties.get('audioMode') == 'ihf':
                self.applied = True
            else:
                if enabled:
                    self.owns_override = True
                    self.routes.Disable(BLUETOOTH_OVERRIDE)
                self.applied = True
        self.report('Call audio route target={} output={} input={} BluetoothAllowed={} PhoneOverride={} '
                    'ACLConnected={} HFPRequested={} HFPAttempts={}'.format(
                        target, output, microphone, allowed, enabled, bool(device_properties.get('Connected')),
                        self.profile_requested, self.attempts))

    def run(self):
        import dbus
        self.system = dbus.SystemBus(private=True)
        session = None
        try:
            session_address = os.environ.get('DBUS_SESSION_BUS_ADDRESS') or \
                'unix:path=/run/user/100000/dbus/user_bus_socket'
            session = dbus.bus.BusConnection(session_address)
            self.voice = network_interface(network_object(session, 'org.nemomobile.voicecall', '/'),
                                           'org.freedesktop.DBus.Properties')
            self.routes = network_interface(network_object(self.system, ROUTE_MANAGER, ROUTE_PATH), ROUTE_MANAGER)
            self.devices = network_interface(network_object(self.system, 'org.bluez', '/'),
                                             'org.freedesktop.DBus.ObjectManager')
            while not self.stop.is_set():
                try:
                    self.poll()
                except Exception as error:
                    name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
                    self.report('Call audio routing error=' + name)
                self.stop.wait(1)
        except Exception as error:
            name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
            self.report('Call audio monitor initialization error=' + name)
        finally:
            try:
                if self.call_ids or self.profile_device or self.owns_override or self.standby_device:
                    self.release(final=True)
            except Exception as error:
                name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
                self.report('Call audio cleanup error=' + name)
            if session:
                session.close()
            self.system.close()

    def start(self):
        if self.device and self.thread is None and not self.stop.is_set():
            self.thread = threading.Thread(target=self.run, name='call-audio', daemon=True)
            self.thread.start()
            self.report('Call audio monitor started target=' + str(self.device))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(12)
