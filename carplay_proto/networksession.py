"""Restore a projection network while its shared session lease is held."""
import re
import subprocess
import time

from .networkdbus import network_interface, network_object


def restore_network(lease, bus, log=print):
    plan = lease.state.get('network')
    if not plan:
        return
    lease.phase('restoring')

    def service(path):
        return network_interface(network_object(bus, 'net.connman', path), 'net.connman.Service')

    target, old = plan.get('target'), plan.get('old')
    if plan.get('debug'):
        import dbus
        properties = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1',
                                       '/fi/w1/wpa_supplicant1'), 'org.freedesktop.DBus.Properties')
        properties.Set('fi.w1.wpa_supplicant1', 'DebugLevel',
                       dbus.String(plan['debug'], variant_level=1))
    manager = network_interface(network_object(bus, 'net.connman', '/'), 'net.connman.Manager')
    services = {str(path): properties for path, properties in manager.GetServices()}
    if target and target != old and target in services:
        if services[target].get('State') not in ('idle', 'failure', 'disconnect'):
            try:
                service(target).Disconnect()
            except Exception as error:
                name = getattr(error, 'get_dbus_name', lambda: '')()
                current = dict(manager.GetServices()).get(target, {})
                if name != 'net.connman.Error.NotConnected' and not (
                        name == 'net.connman.Error.NotSupported'
                        and current.get('State', 'idle') in ('idle', 'failure', 'disconnect')):
                    raise
        if plan.get('forget') and services[target].get('Favorite'):
            service(target).Remove()
    if old and old in services and services[old].get('State') not in ('ready', 'online'):
        try:
            service(old).Connect(timeout=20)
        except Exception as error:
            if getattr(error, 'get_dbus_name', lambda: '')() != 'net.connman.Error.InProgress':
                raise
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = dict(manager.GetServices()).get(old, {}).get('State')
                if state in ('ready', 'online'):
                    break
                if state == 'failure':
                    raise RuntimeError('previous Wi-Fi restoration failed') from error
                time.sleep(.2)
            else:
                raise TimeoutError('previous Wi-Fi restoration timed out') from error
    if not plan.get('powered', True) and plan.get('wifi_path'):
        import dbus
        technology = network_interface(network_object(bus, 'net.connman', plan['wifi_path']),
                                       'net.connman.Technology')
        technology.SetProperty('Powered', dbus.Boolean(False, variant_level=1))
    lease.network_restored()
    log('Projection Wi-Fi restoration completed')


def restore_previous_network(lease, bus, log=print):
    """Restore the journal and retire running timers from pre-journal RPMs."""
    restore_network(lease, bus, log)
    systemd = network_interface(network_object(bus, 'org.freedesktop.systemd1',
                                 '/org/freedesktop/systemd1'), 'org.freedesktop.systemd1.Manager')
    jobs = []
    for unit in systemd.ListUnits(timeout=5):
        name = str(unit[0])
        if not re.fullmatch(r'sailplay-wifi-restore-\d+\.service', name) or unit[3] != 'active':
            continue
        properties = network_interface(network_object(bus, 'org.freedesktop.systemd1', str(unit[6])),
                                       'org.freedesktop.DBus.Properties')
        commands = properties.Get('org.freedesktop.systemd1.Service', 'ExecStart', timeout=5)
        if len(commands) != 1:
            continue
        arguments = [str(value) for value in commands[0][1]]
        if (len(arguments) < 2 or arguments[1] != '/opt/sailplay/scripts/wifi-session-probe.py'
                or '--restore' not in arguments or '--session-id' in arguments):
            continue
        index = arguments.index('--restore')
        paths = arguments[index + 1:index + 3]
        if len(paths) != 2 or not all(path.startswith('/net/connman/service/') for path in paths):
            raise ValueError('invalid legacy CarPlay network restoration paths')
        debug = None
        if '--restore-debug' in arguments:
            debug = arguments[arguments.index('--restore-debug') + 1]
        started = int(properties.Get('org.freedesktop.systemd1.Service',
                                     'ExecMainStartTimestampMonotonic', timeout=5))
        jobs.append((started, name, paths, '--forget-target' in arguments, debug))
    if not jobs:
        return
    manager = network_interface(network_object(bus, 'net.connman', '/'), 'net.connman.Manager')
    for started, name, paths, forget, debug in sorted(jobs, reverse=True):
        old, target = paths
        current = next((str(path) for path, properties in manager.GetServices()
                        if properties.get('Type') == 'wifi' and properties.get('State') in ('ready', 'online')), None)
        recover = current is None or current == target
        lease.plan_network(old if recover else current, target if recover else current,
                           forget=forget and recover, debug=debug)
        # Old running Python processes cannot observe the new ownership IDs.
        # Journal their rollback before stopping them, then restore under the lock.
        subprocess.run(['systemctl', 'stop', name], check=True, timeout=20)
        restore_network(lease, bus, log)
        log('Retired legacy CarPlay Wi-Fi restoration job ' + name)
