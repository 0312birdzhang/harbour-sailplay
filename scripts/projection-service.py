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
from carplay_proto.runtime_logging import collection_enabled


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
    monitor_index = len(commands)
    commands.append([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'connection-monitor.py')])
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--device')
    options, _ = parser.parse_known_args(sys.argv[1:])
    if options.device:
        commands[-1] += ['--device', options.device]
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: stop.set())
    children = {}
    started, failures, retry_at = {}, {}, {}

    def retry(index):
        failures[index] = min(failures.get(index, 0) + 1, 5)
        delay = min(60, 5 * 2 ** (failures[index] - 1))
        retry_at[index] = time.monotonic() + delay
        logging.info('Projection backend retry executable=%s failures=%d delaySeconds=%d',
                     commands[index][1], failures[index], delay)

    try:
        while not stop.is_set():
            for index, command in enumerate(commands):
                child = children.get(index)
                if index == monitor_index and not collection_enabled():
                    if child is not None:
                        try:
                            os.killpg(child.pid, signal.SIGTERM)
                            child.wait(timeout=5)
                        except ProcessLookupError:
                            pass
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                        del children[index]
                    failures[index] = 0
                    retry_at[index] = 0
                    continue
                if child is not None and child.poll() is not None:
                    runtime = time.monotonic() - started[index]
                    logging.info('Projection backend exited executable=%s status=%d runtimeSeconds=%.1f',
                                 command[1], child.returncode, runtime)
                    if child.returncode < 0:
                        logging.error('Projection backend killed executable=%s signal=%d',
                                      command[1], -child.returncode)
                    if runtime >= 60:
                        failures[index] = 0
                    retry(index)
                    del children[index]
                    child = None
                if child is not None or time.monotonic() < retry_at.get(index, 0):
                    continue
                try:
                    children[index] = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                                       start_new_session=True)
                    started[index] = time.monotonic()
                except OSError:
                    logging.exception('Projection backend launch failed executable=%s', command[1])
                    retry(index)
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
