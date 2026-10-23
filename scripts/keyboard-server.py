#!/usr/bin/env python3
"""A display-scoped Maliit peer; never claims the phone's session-bus name."""
import os
from pathlib import Path
import socket
import stat
import sys


def main():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/{}'.format(os.getuid())))
    directory = runtime / 'sailplay-maliit'
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('unsafe keyboard runtime directory')
    directory.chmod(0o700)
    path = directory / 'socket'
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('unsafe keyboard socket')
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1)
        try:
            probe.connect(str(path))
        except ConnectionRefusedError:
            path.unlink()
        else:
            raise RuntimeError('private keyboard already running')
        finally:
            probe.close()
    # The production compositor is setgid privileged and cannot read another
    # process's environ through ptrace checks. Use its existing PID/start-time
    # identity record as well; execve preserves both PID and start time.
    pid = os.getpid()
    process_stat = Path('/proc/{}/stat'.format(pid)).read_text()
    started = process_stat[process_stat.rindex(')')+2:].split()[19]
    record = runtime / 'sailplay-app-{}'.format(pid)
    descriptor = os.open(str(record), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('sailplay-input-method\n'+started+'\n')
    env = dict(os.environ, QT_QPA_PLATFORM='wayland', WAYLAND_DISPLAY='imira-comp-0',
               QT_IM_MODULE='none', MALIIT_FORCE_DBUS_CONNECTION='1',
               CARLIFE_APP_KEY='sailplay-input-method')
    # The phone's optional preload policy belongs to its systemd instance.
    env.pop('LD_PRELOAD', None)
    # Qt 5.6 has built-in wl_shell, not the newer 'wl-shell' plugin key.
    env.pop('QT_WAYLAND_SHELL_INTEGRATION', None)
    os.execve('/usr/bin/maliit-server', ['maliit-server', '-override-address', 'unix:path='+str(path)], env)


if __name__ == '__main__':
    main()
