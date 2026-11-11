#!/usr/bin/env python3
"""Activate the installed capture policy and preserve unchanged policy state."""
import shlex
import subprocess
import hashlib
from pathlib import Path

POLICY_PATH = Path('/etc/pulse/xpolicy.conf.d/sailplay.conf')
PREVIOUS_POLICY_PATH = Path('/run/sailplay-audio-policy.previous-sha256')


def policy_unchanged():
    try:
        return PREVIOUS_POLICY_PATH.read_text().strip() == hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    except FileNotFoundError:
        return False


def playback_routes():
    sinks = subprocess.check_output(['pactl', 'list', 'short', 'sinks'], timeout=5).decode()
    names = {fields[0]: fields[1] for fields in (line.split() for line in sinks.splitlines())
             if len(fields) >= 2}
    streams = subprocess.check_output(['pactl', 'list', 'short', 'sink-inputs'], timeout=5).decode()
    return {fields[0]: (names[fields[1]], fields[2:])
            for fields in (line.split() for line in streams.splitlines())
            if len(fields) >= 4 and fields[1] in names}


def restore_playback_routes(previous):
    current = playback_routes()
    for index, (sink, identity) in previous.items():
        # Reloading the policy moves existing clients to the null output.
        # Preserve a route selected meanwhile and skip finished/replaced streams.
        if current.get(index) != ('sink.null', identity) or sink == 'sink.null':
            continue
        try:
            subprocess.check_call(['pactl', 'move-sink-input', index, sink], timeout=5)
        except subprocess.CalledProcessError:
            if index in playback_routes():
                raise


def reload_policy():
    if policy_unchanged():
        print('Sailplay audio policy unchanged; preserving the running policy', flush=True)
        return
    output = subprocess.check_output(['pactl', 'list', 'short', 'modules'],
                                     timeout=5).decode()
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) < 2 or fields[1] != 'module-policy-enforcement':
            continue
        if PREVIOUS_POLICY_PATH.exists():
            # A changed RPM policy needs a fresh policy-daemon registration.
            # Hot reload shares the old system-bus connection and leaves its
            # enforcement point registered, losing routing for future streams.
            subprocess.check_call(['systemctl', '--user', 'restart', 'pulseaudio.service'], timeout=30)
            print('Sailplay changed audio policy activated', flush=True)
            return
        args = shlex.split(fields[2]) if len(fields) > 2 else []
        routes = playback_routes()
        command = ['pactl', 'load-module', fields[1]] + args
        try:
            subprocess.check_call(['pactl', 'unload-module', fields[0]], timeout=5)
            try:
                subprocess.check_call(command, timeout=5)
            except (subprocess.SubprocessError, OSError):
                # Restore the same policy module if activation failed transiently.
                subprocess.check_call(command, timeout=5)
                raise
        finally:
            restore_playback_routes(routes)
        print('Sailplay playback-monitor policy activated', flush=True)
        return
    print('No PulseAudio policy-enforcement module; reload unnecessary', flush=True)


if __name__ == '__main__':
    reload_policy()
