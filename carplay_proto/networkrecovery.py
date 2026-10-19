"""Recover a proven split ConnMan service registry, not ordinary Wi-Fi errors."""
import json
import os
import time


def split_service(services, target, ssid, direct):
    listed = next((p for path, p in services if str(path) == str(target)), {})
    idle = ('idle', 'failure', 'disconnect')
    return (listed.get('Type') == direct.get('Type') == 'wifi'
            and listed.get('Name') == direct.get('Name') == ssid
            and listed.get('State') in idle and direct.get('State') in idle
            and bool(listed.get('Ethernet', {}).get('Interface'))
            and not direct.get('Ethernet', {}).get('Interface'))


def recover_split_registry(manager, service, target, ssid, owner, log=print,
                           state_path='/run/sailplay-connman-recovery.json',
                           restart=None, clock=time.monotonic):
    # Two fresh snapshots avoid reacting to one scan/removal race. Compare the
    # same service path: GetServices has a live network, GetProperties does not.
    for _ in range(2):
        if not split_service(manager.GetServices(), target, ssid,
                             service(target).GetProperties()):
            return False
    import fcntl
    import subprocess
    descriptor = os.open(state_path + '.lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with open('/proc/sys/kernel/random/boot_id') as stream:
            boot = stream.read().strip()
        now = clock()
        try:
            with open(state_path) as stream:
                previous = json.load(stream)
        except (FileNotFoundError, ValueError):
            previous = {}
        if previous.get('boot') == boot and (previous.get('owner') == owner
                or now - previous.get('time', now) < 300):
            log('HU ConnMan split registry recovery suppressed by owner/cooldown guard')
            return False
        # Save before dispatch: workers and SSH can disappear with Wi-Fi.
        fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(boot=boot, time=now, owner=owner), stream)
        log('HU ConnMan split registry confirmed twice: live list entry but detached direct object; requesting bounded daemon recovery')
        if restart is None:
            restart = lambda: subprocess.run(
                ['systemctl', '--no-block', 'try-restart', 'connman.service'],
                check=True, timeout=5)
        restart()
        return True
    finally:
        os.close(descriptor)
