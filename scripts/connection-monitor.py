#!/usr/bin/env python3
"""Opt-in live connection metadata from HCI, D-Bus and daemon state."""
import argparse
import importlib.util
import json
import logging
import os
import signal
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.networktrace import NetworkTrace, plain_value
from carplay_proto.runtime_logging import RepeatGate, collection_enabled, configure

PROPERTY_KEYS = {
    'org.bluez.Adapter1': {'Powered', 'Connectable', 'Discoverable', 'Pairable', 'Discovering', 'UUIDs'},
    'org.bluez.Device1': {'Connected', 'Paired', 'ServicesResolved', 'Trusted', 'Blocked', 'UUIDs'},
    'net.connman.Service': {'State', 'Error', 'Strength', 'IPv4', 'IPv6', 'Ethernet', 'Nameservers'},
    'net.connman.Technology': {'Powered', 'Connected', 'Tethering'},
    'fi.w1.wpa_supplicant1.Interface': {'State', 'DisconnectReason', 'AuthStatusCode', 'AssocStatusCode', 'CurrentBSS', 'Ifname'},
    'org.freedesktop.systemd1.Unit': {'ActiveState', 'SubState'},
    'org.freedesktop.systemd1.Service': {'Result', 'MainPID', 'ExecMainCode', 'ExecMainStatus', 'NRestarts'},
}


def relevant_unit(value):
    return str(value) in ('connman.service', 'bluetooth.service', 'wpa_supplicant.service') or str(value).startswith('sailplay')


def public_method(interface, path, member, arguments):
    """Whitelist metadata so credential and authentication bodies never enter logs."""
    if interface == 'org.bluez.Device1' and member in ('Connect', 'Disconnect', 'ConnectProfile', 'DisconnectProfile'):
        return {'profile': str(arguments[0])} if arguments else {}
    if interface == 'org.bluez.Adapter1' and member == 'RemoveDevice' and arguments:
        return {'device': str(arguments[0])}
    if interface in ('net.connman.Service', 'net.connman.Technology'):
        if member in ('Connect', 'Disconnect', 'Remove', 'Scan'):
            return {}
        if member == 'SetProperty' and len(arguments) == 2:
            key = str(arguments[0])
            return {'property': key, 'value': plain_value(arguments[1]) if key in PROPERTY_KEYS[interface] else '<redacted>'}
    if interface == 'org.freedesktop.DBus.Properties' and member == 'Set' and len(arguments) == 3:
        kind, key = str(arguments[0]), str(arguments[1])
        if kind in ('org.bluez.Adapter1', 'org.bluez.Device1'):
            return {'interface': kind, 'property': key,
                    'value': plain_value(arguments[2]) if key in PROPERTY_KEYS[kind] else '<redacted>'}
    if interface == 'org.freedesktop.systemd1.Manager' and member in (
            'StartUnit', 'StopUnit', 'RestartUnit', 'TryRestartUnit', 'ReloadOrRestartUnit', 'StartTransientUnit'):
        if arguments and relevant_unit(arguments[0]):
            return {'unit': str(arguments[0])}
    return None


def public_signal(interface, path, member, arguments):
    if interface == 'org.freedesktop.DBus' and member == 'NameOwnerChanged' and len(arguments) == 3:
        if str(arguments[0]) in ('org.bluez', 'net.connman', 'fi.w1.wpa_supplicant1'):
            return {'name': str(arguments[0]), 'oldOwner': str(arguments[1]), 'newOwner': str(arguments[2])}
    kind, values = interface, {}
    if interface == 'org.freedesktop.DBus.Properties' and member == 'PropertiesChanged' and len(arguments) >= 2:
        kind, values = str(arguments[0]), arguments[1]
    elif interface in ('net.connman.Service', 'net.connman.Technology') and member == 'PropertyChanged' and len(arguments) == 2:
        values = {str(arguments[0]): arguments[1]}
    elif interface == 'fi.w1.wpa_supplicant1.Interface' and member == 'PropertiesChanged' and len(arguments) == 1:
        values = arguments[0]
    if kind not in PROPERTY_KEYS or not isinstance(values, dict):
        return None
    if kind.startswith('org.freedesktop.systemd1.') and not any(
            unit in path for unit in ('sailplay', 'connman', 'bluetooth', 'wpa_5fsupplicant')):
        return None
    safe = {str(key): plain_value(value) for key, value in values.items() if str(key) in PROPERTY_KEYS[kind]}
    return {'interface': kind, 'properties': safe} if safe else None


def service_churn(metadata):
    """An adapter change limited to its service list and class of device."""
    return (metadata.get('interface') == 'org.bluez.Adapter1'
            and set(metadata.get('properties', ())) <= {'UUIDs', 'Class'})


def main():
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device')
    options = parser.parse_args()
    if not collection_enabled(refresh=True):
        return
    DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: loop.quit())
    identity_bus = dbus.SystemBus(private=True)
    monitor_bus = dbus.SystemBus(private=True)
    identities = OrderedDict()
    owner_api = dbus.Interface(identity_bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'), 'org.freedesktop.DBus')

    def identity(sender):
        if sender in identities:
            return identities[sender]
        result = {'sender': sender}
        try:
            pid = int(owner_api.GetConnectionUnixProcessID(sender, timeout=1))
            result.update(pid=pid, uid=int(owner_api.GetConnectionUnixUser(sender, timeout=1)))
            result['executable'] = os.readlink('/proc/{}/exe'.format(pid))
        except (dbus.DBusException, OSError):
            result['executable'] = 'unavailable'
        identities[sender] = result
        if len(identities) > 128:
            identities.popitem(last=False)
        return result

    churn = RepeatGate()

    def receive(connection, message):
        if not collection_enabled():
            return
        interface = message.get_interface() or ''
        path, member = message.get_path() or '', message.get_member() or ''
        arguments = message.get_args_list(byte_arrays=True)
        kind = message.get_type()
        if kind == dbus.lowlevel.MESSAGE_TYPE_METHOD_CALL:
            metadata = public_method(interface, path, member, arguments)
            if metadata is not None:
                logging.info('DBUS method source=%s destination=%s path=%s interface=%s member=%s metadata=%s',
                    json.dumps(identity(message.get_sender()), sort_keys=True), message.get_destination(),
                    path, interface, member, json.dumps(metadata, sort_keys=True))
        elif kind == dbus.lowlevel.MESSAGE_TYPE_SIGNAL:
            metadata = public_signal(interface, path, member, arguments)
            skipped = 0
            if metadata is not None and service_churn(metadata):
                skipped = churn.admit((path, tuple(sorted(metadata['properties']))))
            if metadata is not None and skipped is not None:
                if skipped:
                    metadata['similarSignalsNotLogged'] = skipped
                logging.info('DBUS signal sender=%s path=%s interface=%s member=%s metadata=%s',
                    message.get_sender(), path, interface, member, json.dumps(metadata, sort_keys=True))

    rules = ["type='method_call',interface='{}'".format(kind) for kind in (
        'org.bluez.Device1', 'org.bluez.Adapter1', 'net.connman.Service', 'net.connman.Technology',
        'org.freedesktop.systemd1.Manager')]
    rules += ["type='method_call',interface='org.freedesktop.DBus.Properties',member='Set',arg0='{}'".format(kind)
              for kind in ('org.bluez.Adapter1', 'org.bluez.Device1')]
    rules += ["type='signal',interface='{}'".format(kind) for kind in (
        'net.connman.Service', 'net.connman.Technology',
        'fi.w1.wpa_supplicant1.Interface')]
    rules += ["type='signal',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',arg0='{}'".format(kind)
              for kind in PROPERTY_KEYS]
    rules += ["type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='{}'".format(name)
              for name in ('org.bluez', 'net.connman', 'fi.w1.wpa_supplicant1')]
    hci = trace = None
    try:
        monitor_bus.add_message_filter(receive)
        try:
            dbus.Interface(monitor_bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
                'org.freedesktop.DBus.Monitoring').BecomeMonitor(dbus.Array(rules, signature='s'), dbus.UInt32(0))
            logging.info('Live D-Bus connection monitor attached')
        except dbus.DBusException:
            logging.exception('Live D-Bus connection monitor unavailable')
        try:
            from carplay_proto.bluezadapter import select_adapter
            objects = dbus.Interface(identity_bus.get_object('org.bluez', '/'),
                'org.freedesktop.DBus.ObjectManager').GetManagedObjects()
            adapter, _ = select_adapter(objects, options.device)
            for path, interfaces in objects.items():
                for interface in ('org.bluez.Adapter1', 'org.bluez.Device1'):
                    if interface in interfaces:
                        properties = {key: plain_value(value) for key, value in interfaces[interface].items()
                                      if key in PROPERTY_KEYS[interface]}
                        logging.info('Bluetooth initial state path=%s interface=%s properties=%s', path, interface,
                                     json.dumps(properties, sort_keys=True))
            module_path = os.path.join(os.path.dirname(__file__), 'bluetooth-monitor.py')
            spec = importlib.util.spec_from_file_location('sailplay_hci_monitor', module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hci = module.Monitor(int(adapter.rsplit('/hci', 1)[1]))
            logging.info('Passive HCI connection monitor attached adapter=%s', adapter)
        except (OSError, ImportError, dbus.DBusException, ValueError):
            logging.exception('Passive HCI connection monitor unavailable')
        trace = NetworkTrace()
        def check_enabled():
            if not collection_enabled():
                loop.quit()
                return False
            return True
        GLib.timeout_add(500, check_enabled)
        loop.run()
    finally:
        if trace:
            trace.close()
        if hci:
            hci.close()
        monitor_bus.close()
        identity_bus.close()


if __name__ == '__main__':
    configure('connection-monitor')
    main()
