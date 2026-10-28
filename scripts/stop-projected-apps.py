#!/usr/bin/python3
"""Clean detached car clients after service exit, never an active display owner."""
import fcntl
import os
import sys
sys.path.insert(0, '/opt/sailplay')
from carplay_proto.display import stop_projected_apps

if __name__ == '__main__':
    fd = os.open('/run/sailplay-display.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Projection cleanup skipped: display session still owns lock', flush=True)
        else:
            stop_projected_apps()
    finally:
        os.close(fd)
