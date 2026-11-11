#!/usr/bin/env python3
"""Reset Sailplay sessions and connect Bluetooth to the configured head unit."""
import os
import logging
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.bluezadapter import (authenticated_head_unit, select_adapter, select_head_unit,
                                       previous_head_unit, remember_head_unit)
from carplay_proto.session import selected_protocol


def projection_target(objects, configured, protocol):
    from android_auto.bluez import CARPLAY_UUID, LAST_HEAD_UNIT, supports
    carplay = None
    carplay_properties = {}
    if protocol != 'android-auto':
        carplay = select_head_unit(objects, configured, previous_head_unit())
        carplay_properties = objects.get(carplay, {}).get('org.bluez.Device1', {})
        carplay_capable = supports(carplay_properties, CARPLAY_UUID) or authenticated_head_unit(carplay)
        if protocol == 'carplay' or carplay_properties.get('Connected') and carplay_capable:
            return carplay
    from android_auto.bluez import select_head_unit as select_android_auto
    android = select_android_auto(objects, configured, previous_head_unit(LAST_HEAD_UNIT), protocol)
    if protocol == 'auto' and android is not None:
        android_properties = objects.get(android, {}).get('org.bluez.Device1', {})
        if android_properties.get('Connected'):
            return android
        if carplay_properties.get('Paired') and carplay_capable:
            return carplay
    if android is not None:
        return android
    if protocol == 'android-auto':
        raise RuntimeError('no paired Android Auto head unit is configured')
    return carplay or configured


def configured_device(exec_start):
    match = re.search(r'--device\s+(/org/bluez/hci\d+/dev_[0-9A-Fa-f_]+)', exec_start)
    return match.group(1) if match else None


def main():
    import dbus
    command = subprocess.check_output(['systemctl', 'show', 'sailplay.service',
                                      '--property=ExecStart'], universal_newlines=True)
    target = configured_device(command)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
    objects = manager.GetManagedObjects()
    adapter, target = select_adapter(objects, target)
    protocol = selected_protocol()
    if protocol != 'carplay':
        from android_auto.bluetooth import discover_head_units
        from android_auto.bluez import LAST_HEAD_UNIT
        objects, _ = discover_head_units(objects, adapter, known_device=target or previous_head_unit(LAST_HEAD_UNIT))
    target = projection_target(objects, target, protocol)
    if target is None:
        raise RuntimeError('no paired projection receiver is available')
    adapter, target = select_adapter(objects, target)
    logging.info('Reconnect target: %s', target)
    props = dbus.Interface(bus.get_object('org.bluez', adapter), 'org.freedesktop.DBus.Properties')
    props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
    from carplay_proto.wifidiscovery import ensure_wifi_powered
    manager_wifi = dbus.Interface(bus.get_object('net.connman', '/'), 'net.connman.Manager')
    ensure_wifi_powered(manager_wifi, lambda path, enabled:
        dbus.Interface(bus.get_object('net.connman', path), 'net.connman.Technology').SetProperty(
            'Powered', dbus.Boolean(enabled, variant_level=1)), log=logging.info)
    from android_auto.bluez import LAST_HEAD_UNIT, select_head_unit as select_android_auto
    android_auto = protocol == 'android-auto' or (protocol == 'auto' and not authenticated_head_unit(target)
        and target == select_android_auto(objects, target, previous_head_unit(LAST_HEAD_UNIT), protocol))
    device = dbus.Interface(bus.get_object('org.bluez', target), 'org.bluez.Device1')
    device_properties = dbus.Interface(bus.get_object('org.bluez', target), 'org.freedesktop.DBus.Properties')
    # Retire the existing session before waking the receiver's Bluetooth listener.
    subprocess.run(['systemctl', 'stop', 'sailplay.service'], check=True, timeout=60)
    try:
        connected = device_properties.Get('org.bluez.Device1', 'Connected')
        if android_auto:
            if connected:
                device.Disconnect(timeout=10)
            from android_auto.bluetooth import find_channel
            local = str(props.Get('org.bluez.Adapter1', 'Address'))
            remote = str(device_properties.Get('org.bluez.Device1', 'Address'))
            # SDP establishes the authenticated ACL link even while the receiver
            # is reopening its AA listener after the Bluetooth reconnect event.
            find_channel(local, remote, timeout=10)
        elif not connected:
            try:
                device.Connect(timeout=20)
            except dbus.DBusException as error:
                if error.get_dbus_name() != 'org.bluez.Error.AlreadyConnected':
                    raise
    finally:
        subprocess.run(['systemctl', 'start', 'sailplay.service'], check=True, timeout=60)
    if android_auto:
        remember_head_unit(target, LAST_HEAD_UNIT)
    else:
        remember_head_unit(target)
    logging.info('Head-unit reconnect requested; Sailplay will negotiate projection protocol=%s', protocol)


if __name__ == '__main__':
    from carplay_proto.runtime_logging import configure
    configure('reconnect')
    try:
        from carplay_proto.projectionpower import with_connection_power
        with_connection_power(main)
    except Exception:
        logging.exception('head-unit reconnect failed')
        sys.exit(1)
