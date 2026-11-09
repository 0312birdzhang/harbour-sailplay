#!/usr/bin/env python3
"""Wireless Android Auto phone/source entry point for Sailplay."""
import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from android_auto.bluez import LAST_HEAD_UNIT, select_head_unit
from android_auto.network import NetworkHandover, connect_endpoint
from android_auto.session import Session
from android_auto.transport import Transport, server_context
from android_auto.wireless import AA_UUID, WppClient
from carplay_proto.bluezadapter import adapter_name, previous_head_unit, remember_head_unit, select_adapter
from carplay_proto.networksession import restore_previous_network as restore_network
from carplay_proto.session import SessionBusy, SessionLease, selected_protocol


PROFILE_PATH = '/org/sailplay/AndroidAutoPhone'


class Worker:
    def __init__(self, device, sock=None):
        self.device, self.sock = device, sock
        self.tcp = None
        self.stop = threading.Event()
        self.thread = None
        self.phase = 'bluetooth'
        self.user_exit = False

    def close_bluetooth(self):
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self.stop.set()
        self.close_bluetooth()
        if self.thread is not None:
            self.thread.join(30)
            if self.thread.is_alive():
                if self.tcp is not None:
                    try:
                        self.tcp.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                raise RuntimeError('Android Auto connection worker did not stop')


def keep_wpp_alive(client, worker):
    try:
        while not worker.stop.is_set():
            packet = client.receive(.5)
            if packet is not None and packet[0] == 8:
                client.send(9, packet[1])
    except (OSError, EOFError, InterruptedError, ValueError):
        pass


def run_connection(worker, options, phone_name='SailfishOS'):
    import dbus
    from carplay_proto.mediakeys import MediaKeys
    from carplay_proto.projectionpower import ProjectionPower
    from carplay_proto.videodemo import UiCommands
    lease = SessionLease('android-auto')
    bus = handover = session = power = keepalive = media_keys = commands = None
    try:
        lease.acquire()
        bus = dbus.SystemBus(private=True)
        restore_network(lease, bus, logging.info)
        lease.phase('connecting')
        context = server_context(options.certificate, options.key)
        if worker.sock is not None:
            client = WppClient(worker.sock, worker.stop)
            credentials = client.negotiate(serial=phone_name)
            worker.phase = 'handover'
            keepalive = threading.Thread(target=keep_wpp_alive, args=(client, worker), daemon=True)
            keepalive.start()
            handover = NetworkHandover(lease, bus, worker.stop, logging.info)
            try:
                interface, local_address = handover.connect(credentials)
            except Exception:
                try:
                    client.join_status(-1)
                except OSError:
                    pass
                raise
            try:
                client.join_status(0, local_address or None)
            except OSError:
                logging.info('Head unit closed WPP after delivering credentials')
            worker.tcp = connect_endpoint(credentials.address, credentials.port, interface)
        else:
            worker.phase = 'handover'
            worker.tcp = connect_endpoint(options.tcp[0], int(options.tcp[1]))
        worker.phase = 'projection'
        transport = Transport(worker.tcp, context, worker.stop)
        transport.handshake()
        media_keys = MediaKeys([])
        commands = UiCommands()
        connected = (lambda: remember_head_unit(worker.device, LAST_HEAD_UNIT)) if worker.device else None
        session = Session(transport, lease, media_keys=media_keys, commands=commands,
                          phone_name=phone_name, on_connected=connected)
        power = ProjectionPower(phase='projection')
        power.start()
        reason = session.run(options.seconds)
        worker.user_exit = reason == 'user-exit'
        logging.info('Android Auto session ended reason=%s', reason)
    except SessionBusy:
        logging.info('Android Auto connection deferred while another projection owns media')
    except (InterruptedError, KeyboardInterrupt):
        logging.info('Android Auto connection stopped')
    except Exception:
        logging.exception('Android Auto connection failed')
    finally:
        worker.stop.set()
        worker.close_bluetooth()
        if keepalive is not None:
            keepalive.join(2)
        owned = [session] if session is not None else [commands, media_keys, worker.tcp]
        for resource in owned + [power, handover, worker.sock, bus, lease]:
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                logging.exception('Android Auto cleanup failed resource=%s', type(resource).__name__)
        worker.sock = worker.tcp = None
        worker.phase = 'idle'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', help='paired head-unit BlueZ Device1 path')
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--tcp', nargs=2, metavar=('ADDRESS', 'PORT'),
                        help='connect to an explicitly selected DiAuto endpoint on the current network')
    parser.add_argument('--certificate')
    parser.add_argument('--key')
    options = parser.parse_args()
    if options.seconds < 0 or (options.tcp and not 1 <= int(options.tcp[1]) <= 65535):
        parser.error('invalid duration or TCP port')
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from dbus.mainloop.glib import threads_init
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    threads_init()
    stop = threading.Event()
    loop = GLib.MainLoop()

    def terminate(signum, frame):
        stop.set()
        loop.quit()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, terminate)
    if options.tcp:
        worker = Worker(None)
        worker.stop = stop
        run_connection(worker, options)
        return
    bus = dbus.SystemBus()
    object_manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
    objects = object_manager.GetManagedObjects()
    adapter, options.device = select_adapter(objects, options.device)
    phone_name = adapter_name(objects[adapter]['org.bluez.Adapter1'])
    workers, pending, suppressed = {}, set(), set()

    class Profile(dbus.service.Object):
        @dbus.service.method('org.bluez.Profile1', in_signature='', out_signature='')
        def Release(self):
            loop.quit()

        @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
        def NewConnection(self, device, descriptor, properties):
            device = str(device)
            sock = socket.socket(fileno=descriptor.take())
            current = object_manager.GetManagedObjects()
            if not current.get(device, {}).get('org.bluez.Device1', {}).get('Paired'):
                sock.close()
                raise dbus.exceptions.DBusException('head unit must be paired')
            previous = workers.get(device)
            if previous is not None and previous.thread.is_alive():
                sock.close()
                return
            pending.discard(device)
            worker = Worker(device, sock)
            worker.thread = threading.Thread(target=run_connection,
                args=(worker, options, phone_name), daemon=True)
            workers[device] = worker
            worker.thread.start()

        @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
        def RequestDisconnection(self, device):
            worker = workers.get(str(device))
            if worker is not None:
                if worker.phase == 'bluetooth':
                    worker.stop.set()
                worker.close_bluetooth()

    profile = Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
    manager.RegisterProfile(PROFILE_PATH, AA_UUID,
                            {'Name': 'Sailplay Android Auto phone', 'Role': 'client',
                             'RequireAuthentication': True, 'RequireAuthorization': False})

    def connect():
        if stop.is_set():
            return False
        target = None
        try:
            protocol = selected_protocol()
            if protocol == 'carplay':
                return True
            current = object_manager.GetManagedObjects()
            for device, worker in list(workers.items()):
                if not worker.thread.is_alive():
                    if worker.user_exit:
                        suppressed.add(device)
                    del workers[device]
            target = select_head_unit(current, options.device, previous_head_unit(LAST_HEAD_UNIT), protocol)
            if not target or target in pending or target in workers or target in suppressed:
                return True
            properties = current.get(target, {}).get('org.bluez.Device1', {})
            if not properties.get('Connected'):
                return True
            pending.add(target)

            def finished(error=None):
                pending.discard(target)
                if error is not None:
                    logging.info('Android Auto profile connection failed %s', error.get_dbus_name())

            device = dbus.Interface(bus.get_object('org.bluez', target), 'org.bluez.Device1')
            device.ConnectProfile(AA_UUID, reply_handler=finished, error_handler=finished, timeout=12)
        except Exception:
            if target is not None:
                pending.discard(target)
            logging.exception('Android Auto Bluetooth discovery failed')
        return True

    def changed(interface, properties, invalidated, path=None):
        if interface == 'org.bluez.Device1' and 'Connected' in properties and not properties['Connected']:
            suppressed.discard(str(path))
        if path == adapter and interface == 'org.bluez.Adapter1' and 'Powered' in properties:
            loop.quit()
        elif interface == 'org.bluez.Device1' and properties.get('Connected'):
            GLib.idle_add(lambda: (connect(), False)[1])

    bus.add_signal_receiver(changed, signal_name='PropertiesChanged',
                            dbus_interface='org.freedesktop.DBus.Properties', bus_name='org.bluez',
                            path_keyword='path')
    GLib.idle_add(lambda: (connect(), False)[1])
    GLib.timeout_add_seconds(10, connect)
    logging.info('Android Auto phone Bluetooth profile registered adapter=%s', adapter)
    try:
        loop.run()
    finally:
        stop.set()
        for worker in workers.values():
            try:
                worker.close()
            except Exception:
                logging.exception('Android Auto worker shutdown failed')
        try:
            manager.UnregisterProfile(PROFILE_PATH)
        except dbus.DBusException:
            pass


if __name__ == '__main__':
    from carplay_proto.runtime_logging import configure
    configure('android-auto')
    main()
