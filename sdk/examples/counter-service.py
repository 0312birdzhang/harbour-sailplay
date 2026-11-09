#!/usr/bin/env python3
"""A background application exposing one counter to phone and car sessions."""
import argparse
import json
import signal
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root if (root / 'sailplay_sdk').is_dir() else Path('/opt/sailplay')))

import dbus
from dbus.mainloop.glib import DBusGMainLoop, threads_init
from gi.repository import GLib
from sailplay_sdk.service import Backend
from sailplay_sdk.model import Fault


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', default='org.example.SailplayCounter')
    parser.add_argument('--value', type=int, default=0)
    options = parser.parse_args()
    DBusGMainLoop(set_as_default=True)
    threads_init()
    loop = GLib.MainLoop()

    def increment(parameters, invocation):
        def integer(name, default, minimum, maximum):
            value = parameters.get(name, default)
            if (isinstance(value, (bool, dbus.Boolean)) or not isinstance(value, (int, float))
                    or not minimum <= value <= maximum or int(value) != value):
                raise Fault('InvalidArgument', name + ' must be an integer within the example range')
            return int(value)

        amount = integer('amount', 1, -1000, 1000)
        delay = integer('delayMs', 0, 0, 5000)

        def finish():
            value = int(backend.model.state['value']) + amount
            if not -(1 << 63) <= value < (1 << 63):
                invocation.fail('InvalidArgument', 'counter exceeds the signed 64-bit range')
                return False
            value = dbus.Int64(value)
            invocation.complete({'value': value}, state={'value': value, 'title': 'Sailplay SDK example'})
            return False

        GLib.timeout_add(delay, finish)

    backend = Backend(options.service, 'sailplay-sdk-counter',
        {'value': dbus.Int64(options.value), 'title': 'Sailplay SDK example'}, {'increment': increment})
    backend.bus.call_on_disconnection(lambda connection: loop.quit())
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: loop.quit())
    print(json.dumps({'service': options.service, 'path': backend.model.path,
                      'instance': backend.model.instance_id}), flush=True)
    try:
        loop.run()
    finally:
        backend.close()


if __name__ == '__main__':
    main()
