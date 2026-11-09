#!/usr/bin/env python3
"""Open one SDK presentation, increment the example counter and close."""
import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root if (root / 'sailplay_sdk').is_dir() else Path('/opt/sailplay')))

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from sailplay_sdk.client import SessionClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', default='org.example.SailplayCounter')
    parser.add_argument('--presentation', choices=('phone', 'car'), default='car')
    parser.add_argument('--amount', type=int, default=1)
    parser.add_argument('--delay-ms', type=int, default=0)
    options = parser.parse_args()
    DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    status = [1]

    def ready(value):
        if value:
            client.invoke('increment', {'amount': options.amount, 'delayMs': options.delay_ms}, client.revision)

    def finished(request, revision, result, name, message):
        print(json.dumps({'request': request, 'revision': revision, 'result': result,
                          'error': name, 'message': message}), flush=True)
        status[0] = 1 if name else 0
        loop.quit()

    def failed(name, message):
        print(json.dumps({'error': name, 'message': message}), flush=True)
        loop.quit()

    client = SessionClient(options.service, options.presentation, ('state', 'actions'),
                           on_ready=ready, on_request=finished, on_error=failed)
    GLib.timeout_add_seconds(10, lambda: (loop.quit(), False)[1])
    try:
        client.open()
        loop.run()
    finally:
        client.close()
    return status[0]


if __name__ == '__main__':
    sys.exit(main())
