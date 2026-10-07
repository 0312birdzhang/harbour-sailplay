#!/usr/bin/env python3
"""Activate the installed capture policy without restarting PulseAudio."""
import shlex
import subprocess


def reload_policy():
    output = subprocess.check_output(['pactl', 'list', 'short', 'modules'],
                                     timeout=5).decode()
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) < 2 or fields[1] != 'module-policy-enforcement':
            continue
        args = shlex.split(fields[2]) if len(fields) > 2 else []
        subprocess.check_call(['pactl', 'unload-module', fields[0]], timeout=5)
        command = ['pactl', 'load-module', fields[1]] + args
        try:
            subprocess.check_call(command, timeout=5)
        except (subprocess.SubprocessError, OSError):
            # Restore the same policy module if activation failed transiently.
            subprocess.check_call(command, timeout=5)
            raise
        print('Sailplay playback-monitor policy activated', flush=True)
        return
    print('No PulseAudio policy-enforcement module; reload unnecessary', flush=True)


if __name__ == '__main__':
    reload_policy()
