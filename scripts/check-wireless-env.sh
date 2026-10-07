#!/bin/sh
# Read-only probe. Run on Sailfish or pipe over SSH; no root required.
uname -a
python3 - <<'PY'
import importlib.util
for name in ('dbus', 'gi', 'cryptography'):
    print('python dependency %s: %s' % (name, bool(importlib.util.find_spec(name))))
import dbus
import ctypes.util
print('libcrypto:', ctypes.util.find_library('crypto'))
bus = dbus.SystemBus()
objects = dbus.Interface(bus.get_object('org.bluez', '/'),
                         'org.freedesktop.DBus.ObjectManager').GetManagedObjects()
for path, interfaces in objects.items():
    for name in ('org.bluez.Adapter1', 'org.bluez.Device1'):
        if name in interfaces:
            props = interfaces[name]
            print(str(path), {str(k): str(props[k]) for k in
                  ('Address', 'Name', 'Powered', 'Discoverable', 'Paired', 'Connected', 'UUIDs')
                  if k in props})
PY
command -v connmanctl
# Do not print saved access-point credentials.
