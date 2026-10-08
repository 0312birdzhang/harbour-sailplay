#!/usr/bin/env python3
"""Reset Sailplay sessions and connect Bluetooth to the configured head unit."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.bluezadapter import select_adapter


def configured_device(exec_start):
    match = re.search(r'--device\s+(/org/bluez/hci\d+/dev_[0-9A-Fa-f_]+)', exec_start)
    if not match:
        raise RuntimeError('Sailplay service has no configured head unit')
    return match.group(1)


def main():
    import dbus
    command = subprocess.check_output(['systemctl', 'show', 'sailplay.service',
                                      '--property=ExecStart'], universal_newlines=True)
    target = configured_device(command)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
    adapter, target = select_adapter(manager.GetManagedObjects(), target)
    props = dbus.Interface(bus.get_object('org.bluez', adapter), 'org.freedesktop.DBus.Properties')
    props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
    # The service owns RFCOMM and all handover units. Restarting it retires
    # stale workers/media before a fresh Bluetooth connection can trigger iAP2.
    subprocess.run(['systemctl', 'restart', 'sailplay.service'], check=True, timeout=30)
    device = dbus.Interface(bus.get_object('org.bluez', target), 'org.bluez.Device1')
    try:
        device.Connect(timeout=20)
    except dbus.DBusException as error:
        if error.get_dbus_name() != 'org.bluez.Error.AlreadyConnected':
            raise
    print('Head-unit Bluetooth connected; Sailplay will negotiate iAP2, Wi-Fi and AirPlay', flush=True)


if __name__ == '__main__':
    main()
