#!/usr/bin/env python3
"""Start the selected wireless projection backends through the Sailplay service."""
import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.session import selected_protocol


def backend_commands(arguments, protocol, directory):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--device')
    options, _ = parser.parse_known_args(arguments)
    commands = []
    if protocol in ('auto', 'carplay'):
        commands.append([sys.executable, os.path.join(directory, 'wireless-phone-advertise.py')] + arguments)
    if protocol in ('auto', 'android-auto'):
        android = [sys.executable, os.path.join(directory, 'android-auto-phone.py'), '--seconds', '0']
        if options.device:
            android += ['--device', options.device]
        commands.append(android)
    return commands


def main():
    protocol = selected_protocol()
    commands = backend_commands(sys.argv[1:], protocol, os.path.dirname(os.path.abspath(__file__)))
    logging.info('Projection service protocol=%s backends=%d', protocol, len(commands))
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: stop.set())
    children = {}
    try:
        while not stop.is_set():
            for index, command in enumerate(commands):
                child = children.get(index)
                if child is None or child.poll() is not None:
                    if child is not None:
                        logging.info('Projection backend exited executable=%s status=%d', command[1], child.returncode)
                    children[index] = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                                        start_new_session=True)
            stop.wait(2)
    finally:
        for child in children.values():
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 30
        for child in children.values():
            try:
                child.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()


if __name__ == '__main__':
    from carplay_proto.runtime_logging import configure
    configure('projection-service')
    main()
