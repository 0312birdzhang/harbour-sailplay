#!/usr/bin/env python3
"""Recover the last projection network after every backend has stopped."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.networksession import restore_previous_network as restore_network
from carplay_proto.projectionpower import with_connection_power
from carplay_proto.session import SessionBusy, SessionLease


def main():
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    lease = SessionLease('recovery')
    try:
        lease.acquire()
    except SessionBusy:
        logging.info('Active projection owns network restoration')
        return
    try:
        with_connection_power(restore_network, lease, dbus.SystemBus(), logging.info)
    finally:
        lease.close()


if __name__ == '__main__':
    from carplay_proto.runtime_logging import configure
    configure('network-restore')
    main()
