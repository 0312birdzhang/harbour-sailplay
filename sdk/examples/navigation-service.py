#!/usr/bin/env python3
"""A fake navigation backend whose route belongs to the backend across views."""
import argparse
import json
import signal
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root if (root / 'sailplay_sdk').is_dir() else Path('/opt/sailplay')))

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from sailplay_sdk.guidance import guidance, unsigned
from sailplay_sdk.model import Fault
from sailplay_sdk.navigation import NavigationBackend


class FakeNavigation:
    def __init__(self, service, application_id, loop, active=False, stay_alive=False):
        self.loop = loop
        self.active = False
        self.step = 0
        self.timer = 0
        self.stay_alive = stay_alive
        self.backend = NavigationBackend(service, application_id,
            {'navigation.start': self.start, 'navigation.stop': self.stop,
             'navigation.delay': self.delay}, on_lifecycle=self.lifecycle)
        if active:
            self._start()

    def lifecycle(self, backend):
        def quit_if_idle():
            if not self.stay_alive and not self.active and not backend.session_count and not backend.pending_count:
                self.loop.quit()
            return False

        if not self.stay_alive and not self.active and not backend.session_count and not backend.pending_count:
            GLib.idle_add(quit_if_idle)

    def _guidance(self):
        return guidance('active', maneuver='turn-left', nextDistanceMeters=max(0, 300 - self.step * 5),
                        remainingDistanceMeters=max(0, 12000 - self.step * 5),
                        remainingSeconds=max(0, 900 - self.step),
                        currentRoad='Example Road', nextRoad='下一条路', destination='Example destination')

    def _start(self):
        self.active = True
        self.backend.publish_guidance(self._guidance())
        if not self.timer:
            self.timer = GLib.timeout_add_seconds(1, self.tick)

    def tick(self):
        if not self.active:
            self.timer = 0
            return False
        self.step += 1
        self.backend.publish_guidance(self._guidance())
        return True

    def start(self, parameters, invocation):
        if parameters:
            raise Fault('InvalidArgument', 'navigation.start has no parameters')
        self._start()
        invocation.complete({'started': True})

    def stop(self, parameters, invocation):
        delay = parameters.get('delayMs', 0)
        if set(parameters) - {'delayMs'} or not unsigned(delay, 5000):
            raise Fault('InvalidArgument', 'delayMs must be between zero and 5000')

        def complete():
            self.active = False
            self.backend.publish_guidance(guidance('stopped'))
            invocation.complete({'stopped': True})
            return False

        GLib.timeout_add(max(1, int(delay)), complete)

    def delay(self, parameters, invocation):
        delay = parameters.get('delayMs', 250)
        if set(parameters) - {'delayMs'} or not unsigned(delay, 5000):
            raise Fault('InvalidArgument', 'delayMs must be between zero and 5000')

        def complete():
            invocation.complete({'completed': True})
            return False

        GLib.timeout_add(max(1, int(delay)), complete)

    def close(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.backend.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', default='org.example.SailplayNavigation')
    parser.add_argument('--application-id', default='sailplay-sdk-navigation')
    parser.add_argument('--active', action='store_true')
    parser.add_argument('--stay-alive', action='store_true')
    options = parser.parse_args()
    DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    provider = FakeNavigation(options.service, options.application_id, loop, options.active, options.stay_alive)
    provider.backend.bus.call_on_disconnection(lambda connection: loop.quit())
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda number, frame: loop.quit())
    print('NAVIGATION_READY ' + json.dumps({'service': options.service, 'applicationId': options.application_id}), flush=True)
    try:
        loop.run()
    finally:
        provider.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
