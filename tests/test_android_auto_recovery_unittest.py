import importlib.util
from collections import deque
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from carplay_proto import mediakeys, videodemo


spec = importlib.util.spec_from_file_location('android_auto_phone_recovery',
    Path(__file__).resolve().parents[1] / 'scripts' / 'android-auto-phone.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConnectionRecoveryTests(unittest.TestCase):
    def test_wireless_and_projection_failures_request_guarded_bluetooth_recovery(self):
        for stage in ('wireless', 'handover', 'projection'):
            with self.subTest(stage=stage):
                worker = module.Worker('/org/bluez/hci1/dev_3C_28_6D_2C_FC_2E', Mock())
                options = SimpleNamespace(certificate=None, key=None, tcp=None, seconds=0)
                client, transport, handover, lease = Mock(), Mock(), Mock(), Mock()
                handover.connect.return_value = ('wlan0', '192.168.49.201')
                if stage == 'wireless':
                    client.negotiate.side_effect = EOFError('wireless handshake failed')
                elif stage == 'handover':
                    handover.endpoint.side_effect = TimeoutError('head-unit TCP endpoint did not become ready')
                else:
                    transport.handshake.side_effect = EOFError('receiver closed TLS handshake')
                with patch.dict(sys.modules, dbus=SimpleNamespace(SystemBus=Mock())), \
                        patch.object(module, 'SessionLease', return_value=lease), \
                        patch.object(module, 'restore_network'), \
                        patch.object(module, 'server_context'), \
                        patch.object(module, 'remember_head_unit'), \
                        patch.object(module, 'WppClient', return_value=client), \
                        patch.object(module, 'NetworkHandover', return_value=handover), \
                        patch.object(module, 'Transport', return_value=transport), \
                        patch.object(module, 'ProjectionPower'), \
                        patch.object(module.threading, 'Thread'), \
                        patch.object(module.logging, 'exception'):
                    module.run_connection(worker, options)
                self.assertTrue(worker.reconnect_bluetooth)
                self.assertEqual(worker.phase, 'idle')
                lease.close.assert_called_once()

    def test_direct_tcp_failure_has_no_bluetooth_receiver_to_reset(self):
        worker = module.Worker(None)
        options = SimpleNamespace(certificate=None, key=None, tcp=['192.168.3.122', '5288'], seconds=0)
        transport = Mock()
        transport.handshake.side_effect = EOFError('TCP peer closed')
        with patch.dict(sys.modules, dbus=SimpleNamespace(SystemBus=Mock())), \
                patch.object(module, 'SessionLease'), patch.object(module, 'restore_network'), \
                patch.object(module, 'server_context'), patch.object(module, 'connect_endpoint'), \
                patch.object(module, 'Transport', return_value=transport), \
                patch.object(module, 'ProjectionPower'), \
                patch.object(module.logging, 'exception'):
            module.run_connection(worker, options)
        self.assertFalse(worker.reconnect_bluetooth)

    def test_power_covers_wireless_setup_and_network_restoration(self):
        worker = module.Worker('/org/bluez/hci1/dev_3C_28_6D_2C_FC_2E', Mock())
        options = SimpleNamespace(certificate=None, key=None, tcp=None, seconds=0)
        events = []
        power, lease, client, handover, transport, session = (Mock() for _ in range(6))
        power.start.side_effect = lambda: events.append('power-start')
        power.close.side_effect = lambda: events.append('power-stop')
        lease.acquire.side_effect = lambda: events.append('media-acquire')
        lease.close.side_effect = lambda: events.append('media-release')
        client.negotiate.side_effect = lambda **kwargs: events.append('wpp')
        handover.connect.side_effect = lambda credentials: (events.append('wifi'), ('wlan0', '192.168.49.201'))[1]
        handover.close.side_effect = lambda: events.append('network-restore')
        transport.handshake.side_effect = lambda: events.append('tls')
        session.close.side_effect = lambda: events.append('session-close')
        with patch.dict(sys.modules, dbus=SimpleNamespace(SystemBus=Mock())), \
                patch.object(module, 'SessionLease', return_value=lease), \
                patch.object(module, 'restore_network'), patch.object(module, 'server_context'), \
                patch.object(module, 'remember_head_unit'), patch.object(module.threading, 'Thread'), \
                patch.object(module, 'WppClient', return_value=client), \
                patch.object(module, 'NetworkHandover', return_value=handover), \
                patch.object(module, 'Transport', return_value=transport), \
                patch.object(module, 'Session', return_value=session), \
                patch.object(mediakeys, 'MediaKeys'), patch.object(videodemo, 'UiCommands'), \
                patch.object(module, 'ProjectionPower', return_value=power):
            module.run_connection(worker, options)
        self.assertEqual(events, ['media-acquire', 'power-start', 'wpp', 'wifi', 'tls',
                                  'session-close', 'network-restore', 'media-release', 'power-stop'])

    def test_busy_projection_does_not_start_power_lease(self):
        worker = module.Worker(None)
        lease = Mock()
        lease.acquire.side_effect = module.SessionBusy('another projection')
        with patch.dict(sys.modules, dbus=SimpleNamespace(SystemBus=Mock())), \
                patch.object(module, 'SessionLease', return_value=lease), \
                patch.object(module, 'ProjectionPower') as power:
            module.run_connection(worker, SimpleNamespace())
        power.assert_not_called()
        lease.close.assert_called_once()

    def test_user_exit_preserves_the_stop_request(self):
        worker = module.Worker(None)
        options = SimpleNamespace(certificate=None, key=None, tcp=['192.168.3.122', '5288'], seconds=0)
        session = Mock()
        session.run.return_value = 'user-exit'
        with patch.dict(sys.modules, dbus=SimpleNamespace(SystemBus=Mock())), \
                patch.object(module, 'SessionLease'), patch.object(module, 'restore_network'), \
                patch.object(module, 'server_context'), patch.object(module, 'connect_endpoint'), \
                patch.object(module, 'Transport'), patch.object(module, 'Session', return_value=session), \
                patch.object(mediakeys, 'MediaKeys'), patch.object(videodemo, 'UiCommands'), \
                patch.object(module, 'ProjectionPower'):
            module.run_connection(worker, options)
        self.assertTrue(worker.user_exit)
        self.assertFalse(worker.reconnect_bluetooth)


class StartupRecoveryTests(unittest.TestCase):
    def test_failed_workers_back_off_inside_the_backend_and_reset_after_a_stable_connection(self):
        adapter = '/org/bluez/hci1'
        target = adapter + '/dev_3C_28_6D_2C_FC_2E'
        cases = [([0] * 10, 210, [0, 8, 20, 42, 84, 146, 208]),
                 ([0, 0, 70, 0], 112, [0, 8, 20, 96, 108])]
        for lifetimes, duration, expected in cases:
            with self.subTest(lifetimes=lifetimes):
                objects = {adapter: {'org.bluez.Adapter1': {'Powered': True, 'Address': '50:56:A8:06:01:73'}},
                           target: {'org.bluez.Device1': {'Paired': True, 'Connected': True,
                               'Address': '3C:28:6D:2C:FC:2E', 'UUIDs': [module.AA_UUID]}}}
                clock, callbacks, signals, profiles, sockets, attempts = [0.0], deque(), [], [], [], []
                remaining_lifetimes = list(lifetimes)

                def idle_add(callback, *args):
                    callbacks.append((callback, args))

                def drain():
                    while callbacks:
                        callback, args = callbacks.popleft()
                        callback(*args)

                class Loop:
                    def run(self):
                        drain()
                        changed = next(callback for callback, options in signals
                                       if options['signal_name'] == 'PropertiesChanged')
                        while clock[0] < duration:
                            clock[0] += 2
                            if clock[0] == 4:
                                profiles[0].NewConnection(target, SimpleNamespace(take=lambda: 100), {})
                            changed('org.bluez.Device1', {'Connected': True}, [], path=target)
                            drain()

                    def quit(self):
                        pass

                class WorkerThread:
                    def __init__(self, target, args=(), **kwargs):
                        self.target, self.args, self.stopped = target, args, False
                        self.end = clock[0] + (remaining_lifetimes.pop(0) if remaining_lifetimes else 1000)

                    def start(self):
                        self.target(*self.args)

                    def is_alive(self):
                        return not self.stopped and clock[0] < self.end

                    def join(self, timeout):
                        self.stopped = True

                class ProfileObject:
                    def __init__(self, *args):
                        profiles.append(self)

                def failed_connection(worker, options, phone_name):
                    attempts.append(clock[0])
                    worker.reconnect_bluetooth = True
                    worker.phase = 'idle'

                def new_socket(**kwargs):
                    sock = Mock()
                    sockets.append(sock)
                    return sock

                def new_connection(uuid, **kwargs):
                    profiles[0].NewConnection(target, SimpleNamespace(take=lambda: 100), {})
                    kwargs['reply_handler']()

                bus, object_manager, profile_manager, device = Mock(), Mock(), Mock(), Mock()
                object_manager.GetManagedObjects.return_value = objects
                bus.add_signal_receiver.side_effect = lambda callback, **options: signals.append((callback, options))
                device.ConnectProfile.side_effect = new_connection
                device.Disconnect.side_effect = lambda **kwargs: kwargs['reply_handler']()
                dbus = ModuleType('dbus')
                dbus.SystemBus, dbus.DBusException = Mock(return_value=bus), RuntimeError
                interfaces = {'org.freedesktop.DBus.ObjectManager': object_manager,
                              'org.bluez.ProfileManager1': profile_manager, 'org.bluez.Device1': device}
                dbus.Interface = lambda obj, name: interfaces[name]
                dbus.service = ModuleType('dbus.service')
                dbus.service.Object = ProfileObject
                dbus.service.method = lambda *args, **kwargs: lambda method: method
                glib = ModuleType('dbus.mainloop.glib')
                glib.DBusGMainLoop, glib.threads_init = Mock(), Mock()
                repository = ModuleType('gi.repository')
                repository.GLib = SimpleNamespace(MainLoop=Loop, idle_add=idle_add, timeout_add_seconds=Mock())
                modules = {'dbus': dbus, 'dbus.service': dbus.service,
                           'dbus.mainloop': ModuleType('dbus.mainloop'), 'dbus.mainloop.glib': glib,
                           'gi': ModuleType('gi'), 'gi.repository': repository}
                with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['android-auto-phone.py']), \
                        patch.object(module.signal, 'signal'), patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(module.threading, 'Thread', WorkerThread), \
                        patch.object(module.socket, 'socket', side_effect=new_socket), \
                        patch.object(module, 'run_connection', side_effect=failed_connection), \
                        patch.object(module, 'selected_protocol', return_value='android-auto'), \
                        patch.object(module, 'previous_head_unit', return_value=target), \
                        patch.object(module.logging, 'exception') as errors:
                    module.main()
                self.assertEqual(attempts, expected)
                sockets[1].close.assert_called_once()
                profile_manager.RegisterProfile.assert_called_once()
                errors.assert_not_called()

    def test_bluez_replacement_or_profile_release_rebuilds_live_proxies(self):
        adapter = '/org/bluez/hci1'
        target = adapter + '/dev_3C_28_6D_2C_FC_2E'
        for reason in ('owner-change', 'profile-release'):
            with self.subTest(reason=reason):
                objects = {adapter: {'org.bluez.Adapter1': {'Powered': True, 'Address': '50:56:A8:06:01:73'}},
                           target: {'org.bluez.Device1': {'Paired': True, 'Connected': True,
                               'Address': '3C:28:6D:2C:FC:2E', 'UUIDs': [module.AA_UUID]}}}
                callbacks, receivers, profiles = [], [], []
                quit_loop = Mock()

                class Loop:
                    def run(self):
                        for callback, args in callbacks:
                            callback(*args)
                        if reason == 'owner-change':
                            callback = next(callback for callback, options in receivers
                                            if options['signal_name'] == 'NameOwnerChanged')
                            callback('org.bluez', ':1.10', ':1.11')
                        else:
                            profiles[0].Release()

                    def quit(self):
                        quit_loop()

                class ProfileObject:
                    def __init__(self, *args):
                        profiles.append(self)

                bus, object_manager, profile_manager, device = Mock(), Mock(), Mock(), Mock()
                object_manager.GetManagedObjects.return_value = objects
                bus.add_signal_receiver.side_effect = lambda callback, **options: receivers.append((callback, options))
                dbus = ModuleType('dbus')
                dbus.SystemBus, dbus.DBusException = Mock(return_value=bus), RuntimeError
                interfaces = {'org.freedesktop.DBus.ObjectManager': object_manager,
                              'org.bluez.ProfileManager1': profile_manager, 'org.bluez.Device1': device}
                dbus.Interface = lambda obj, name: interfaces[name]
                dbus.service = ModuleType('dbus.service')
                dbus.service.Object = ProfileObject
                dbus.service.method = lambda *args, **kwargs: lambda method: method
                glib = ModuleType('dbus.mainloop.glib')
                glib.DBusGMainLoop, glib.threads_init = Mock(), Mock()
                repository = ModuleType('gi.repository')
                repository.GLib = SimpleNamespace(MainLoop=Loop,
                    idle_add=lambda callback, *args: callbacks.append((callback, args)), timeout_add_seconds=Mock())
                modules = {'dbus': dbus, 'dbus.service': dbus.service,
                           'dbus.mainloop': ModuleType('dbus.mainloop'), 'dbus.mainloop.glib': glib,
                           'gi': ModuleType('gi'), 'gi.repository': repository}
                with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['android-auto-phone.py']), \
                        patch.object(module.signal, 'signal'), \
                        patch.object(module, 'selected_protocol', return_value='android-auto'), \
                        patch.object(module, 'previous_head_unit', return_value=target):
                    module.main()
                quit_loop.assert_called_once()
                profile_manager.RegisterProfile.assert_called_once_with(module.PROFILE_PATH, module.AA_UUID,
                    {'Name': 'Sailplay Android Auto phone', 'Role': 'client',
                     'RequireAuthentication': True, 'RequireAuthorization': False},
                    signature='osa{sv}', timeout=3)
                profile_manager.UnregisterProfile.assert_called_once_with(module.PROFILE_PATH,
                                                                          signature='o', timeout=3)
                for call in bus.get_object.call_args_list:
                    self.assertEqual(call.kwargs, {'introspect': False, 'follow_name_owner_changes': True})
                for call in object_manager.GetManagedObjects.call_args_list:
                    self.assertEqual(call.kwargs, {'timeout': 3})
                self.assertTrue(any(options.get('arg0') == 'org.bluez' for _, options in receivers))

    def test_startup_wakes_a_verified_paired_receiver_once_after_repeated_missing_service(self):
        adapter = '/org/bluez/hci1'
        target = adapter + '/dev_3C_28_6D_2C_FC_2E'
        for verified, paired in ((True, True), (False, True), (True, False)):
            with self.subTest(verified=verified, paired=paired):
                objects = {adapter: {'org.bluez.Adapter1': {'Powered': True, 'Address': '50:56:A8:06:01:73'}},
                    target: {'org.bluez.Device1': {'Paired': paired, 'Connected': True,
                        'Address': '3C:28:6D:2C:FC:2E', 'UUIDs': []}}}
                callbacks, timers = deque(), []

                def idle_add(callback, *args):
                    callbacks.append((callback, args))
                    return len(callbacks)

                class Loop:
                    def run(self):
                        for _ in range(5):
                            while callbacks:
                                callback, args = callbacks.popleft()
                                callback(*args)
                            timers[0]()

                    def quit(self):
                        pass

                class ProbeThread:
                    def __init__(self, target, args=(), **kwargs):
                        self.target, self.args = target, args

                    def start(self):
                        self.target(*self.args)

                    def is_alive(self):
                        return False

                    def join(self, timeout):
                        pass

                class ProfileObject:
                    def __init__(self, *args):
                        pass

                receiver, manager, profiles = Mock(), Mock(), Mock()
                manager.GetManagedObjects.side_effect = lambda **kwargs: objects
                error = SimpleNamespace(get_dbus_name=lambda: 'org.bluez.Error.BREDR.ProfileUnavailable')
                receiver.ConnectProfile.side_effect = lambda uuid, **kwargs: kwargs['error_handler'](error)

                def disconnect(**kwargs):
                    objects[target]['org.bluez.Device1']['Connected'] = False
                    kwargs['reply_handler']()

                receiver.Disconnect.side_effect = disconnect
                dbus = ModuleType('dbus')
                dbus.SystemBus, dbus.DBusException = Mock(), RuntimeError
                interfaces = {'org.freedesktop.DBus.ObjectManager': manager,
                              'org.bluez.ProfileManager1': profiles, 'org.bluez.Device1': receiver}
                dbus.Interface = lambda obj, name: interfaces[name]
                dbus.service = ModuleType('dbus.service')
                dbus.service.Object = ProfileObject
                dbus.service.method = lambda *args, **kwargs: lambda method: method
                glib = ModuleType('dbus.mainloop.glib')
                glib.DBusGMainLoop, glib.threads_init = Mock(), Mock()
                repository = ModuleType('gi.repository')
                repository.GLib = SimpleNamespace(MainLoop=Loop, idle_add=idle_add,
                    timeout_add_seconds=lambda seconds, callback: timers.append(callback))
                modules = {'dbus': dbus, 'dbus.service': dbus.service,
                           'dbus.mainloop': ModuleType('dbus.mainloop'), 'dbus.mainloop.glib': glib,
                           'gi': ModuleType('gi'), 'gi.repository': repository}
                with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['android-auto-phone.py']), \
                        patch.object(module.signal, 'signal'), patch.object(module.threading, 'Thread', ProbeThread), \
                        patch.object(module, 'selected_protocol', return_value='android-auto'), \
                        patch.object(module, 'previous_head_unit', return_value=target if verified else None), \
                        patch.object(module, 'discover_head_units', side_effect=lambda current, *args: (current, {})):
                    module.main()
                if verified and paired:
                    receiver.Disconnect.assert_called_once()
                else:
                    receiver.Disconnect.assert_not_called()


class StandaloneRestorationTests(unittest.TestCase):
    def test_restoration_initializes_dbus_loop_and_holds_connection_power(self):
        spec = importlib.util.spec_from_file_location('restore_projection_network_recovery',
            Path(__file__).resolve().parents[1] / 'scripts' / 'restore-projection-network.py')
        restore = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restore)
        lease, bus, mainloop = Mock(), Mock(), Mock()
        glib = ModuleType('dbus.mainloop.glib')
        glib.DBusGMainLoop = mainloop
        modules = {'dbus': SimpleNamespace(SystemBus=Mock(return_value=bus)),
                   'dbus.mainloop': ModuleType('dbus.mainloop'), 'dbus.mainloop.glib': glib}
        with patch.dict(sys.modules, modules), patch.object(restore, 'SessionLease', return_value=lease), \
                patch.object(restore, 'with_connection_power') as power:
            restore.main()
        mainloop.assert_called_once_with(set_as_default=True)
        power.assert_called_once_with(restore.restore_network, lease, bus, restore.logging.info)
        lease.close.assert_called_once()
