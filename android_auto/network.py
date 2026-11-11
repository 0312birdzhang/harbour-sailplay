"""ConnMan handover for a paired head unit's WPP network credentials."""
import errno
import ipaddress
import socket
import threading
import time

from carplay_proto.networkdbus import network_interface, network_object
from carplay_proto.networksession import restore_network
from carplay_proto.wifidiscovery import discover, find_service


def connect_endpoint(address, port, interface=None, timeout=5):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if interface:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0')
        if family == socket.AF_INET6:
            host, _, zone = address.partition('%')
            scope_name = interface or zone
            scope = 0
            if scope_name:
                scope = int(scope_name) if scope_name.isdigit() else socket.if_nametoindex(scope_name)
            destination = (host, int(port), 0, scope)
        else:
            destination = (address, int(port))
        sock.connect(destination)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock
    except Exception:
        sock.close()
        raise


def associated_network(bus, interface):
    properties = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1',
                                   '/fi/w1/wpa_supplicant1'), 'org.freedesktop.DBus.Properties')
    for path in properties.Get('fi.w1.wpa_supplicant1', 'Interfaces'):
        current = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', path),
                                    'org.freedesktop.DBus.Properties')
        if str(current.Get('fi.w1.wpa_supplicant1.Interface', 'Ifname')) != interface:
            continue
        if str(current.Get('fi.w1.wpa_supplicant1.Interface', 'State')) != 'completed':
            return None, None
        bss = str(current.Get('fi.w1.wpa_supplicant1.Interface', 'CurrentBSS'))
        details = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', bss),
                                    'org.freedesktop.DBus.Properties')
        ssid = bytes(details.Get('fi.w1.wpa_supplicant1.BSS', 'SSID')).decode('utf-8')
        bssid = ':'.join('{:02x}'.format(byte) for byte in details.Get('fi.w1.wpa_supplicant1.BSS', 'BSSID'))
        return ssid, bssid
    return None, None


class NetworkHandover:
    def __init__(self, lease, bus, stop, log=print):
        self.lease, self.bus, self.stop, self.log = lease, bus, stop, log
        self.manager = network_interface(network_object(bus, 'net.connman', '/'), 'net.connman.Manager')
        self.agent = None
        self.agent_path = '/org/sailplay/AndroidAuto/WifiAgent_' + lease.identity

    def service(self, path):
        return network_interface(network_object(self.bus, 'net.connman', path), 'net.connman.Service')

    def endpoint(self, credentials, interface, timeout=30):
        deadline = time.monotonic() + timeout
        last_error = None
        while not self.stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return connect_endpoint(credentials.address, credentials.port, interface, timeout=min(5, remaining))
            except OSError as error:
                if not isinstance(error, TimeoutError) and error.errno not in (
                        errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ECONNREFUSED, errno.ETIMEDOUT):
                    raise
                last_error = error
                self.log('Android Auto waiting for the TCP endpoint on the associated Wi-Fi error={}'.format(error.errno))
            self.stop.wait(min(.5, max(0, deadline - time.monotonic())))
        if self.stop.is_set():
            raise InterruptedError('Android Auto endpoint connection stopped')
        raise TimeoutError('head-unit TCP endpoint did not become ready') from last_error

    def connect(self, credentials, timeout=40):
        import dbus
        import dbus.service
        restore_network(self.lease, self.bus, self.log)
        technologies = [(str(path), properties) for path, properties in self.manager.GetTechnologies()
                        if properties.get('Type') == 'wifi']
        if not technologies:
            raise RuntimeError('Wi-Fi technology is unavailable')
        wifi_path, technology_properties = technologies[0]
        powered = bool(technology_properties.get('Powered'))
        services = self.manager.GetServices()
        old = next((str(path) for path, properties in services if properties.get('Type') == 'wifi'
                    and properties.get('State') in ('ready', 'online')), None)
        self.lease.plan_network(old, None, wifi_path=wifi_path, powered=powered)
        technology = network_interface(network_object(self.bus, 'net.connman', wifi_path), 'net.connman.Technology')
        if not powered:
            technology.SetProperty('Powered', dbus.Boolean(True, variant_level=1))
        target = find_service(services, credentials.ssid, require_available=True)
        if target is None:
            target, services = discover(self.manager, wifi_path, credentials.ssid,
                scan=lambda path: technology.Scan(timeout=8), cached_bss_visible=lambda ssid: False,
                set_powered=lambda path, value: technology.SetProperty('Powered', dbus.Boolean(value, variant_level=1)),
                log=self.log, timeout=15, sleep=lambda seconds: self.stop.wait(seconds), require_available=True)
        if self.stop.is_set():
            raise InterruptedError('Android Auto Wi-Fi connection stopped')
        if target is None:
            raise RuntimeError('head-unit Wi-Fi network is unavailable')
        properties = self.service(target).GetProperties()
        if target == old:
            self.lease.network_restored()
        else:
            self.lease.plan_network(old, target, forget=not properties.get('Favorite'),
                                    wifi_path=wifi_path, powered=powered)
        agent_target, password, ssid = target, credentials.password, credentials.ssid

        class Agent(dbus.service.Object):
            @dbus.service.method('net.connman.Agent', in_signature='oa{sv}', out_signature='a{sv}')
            def RequestInput(self, path, fields):
                if str(path) != agent_target or set(fields) - {'Passphrase', 'Name', 'SSID', 'PreviousPassphrase', 'WPS'}:
                    raise dbus.exceptions.DBusException('unsupported Android Auto credential request')
                result = {}
                if 'Passphrase' in fields:
                    result['Passphrase'] = dbus.String(password)
                if 'Name' in fields:
                    result['Name'] = dbus.String(ssid)
                if 'SSID' in fields:
                    result['SSID'] = dbus.ByteArray(ssid.encode('utf-8'))
                return result

            @dbus.service.method('net.connman.Agent', in_signature='os', out_signature='')
            def ReportError(self, path, error):
                pass

            @dbus.service.method('net.connman.Agent', in_signature='', out_signature='')
            def Release(self):
                pass

            @dbus.service.method('net.connman.Agent', in_signature='', out_signature='')
            def Cancel(self):
                pass

        self.agent = Agent(self.bus, self.agent_path)
        self.manager.RegisterAgent(dbus.ObjectPath(self.agent_path))
        if not properties.get('Favorite') and str(properties.get('IPv4.Configuration', {}).get('Method', '')) in ('', 'off', 'unknown'):
            self.service(target).SetProperty('IPv4.Configuration', dbus.Dictionary(
                {'Method': dbus.String('dhcp')}, signature='sv', variant_level=1))
        if credentials.security != 1 and properties.get('State') not in ('ready', 'online'):
            self.service(target).SetProperty('Passphrase', dbus.String(password, variant_level=1))
        completed, errors = threading.Event(), []

        def failed(error):
            errors.append(error)
            completed.set()

        if properties.get('State') not in ('ready', 'online'):
            self.service(target).Connect(reply_handler=completed.set, error_handler=failed, timeout=timeout)
        else:
            completed.set()
        deadline = time.monotonic() + timeout
        while not self.stop.is_set() and time.monotonic() < deadline:
            properties = self.service(target).GetProperties()
            interface = str(properties.get('Ethernet', {}).get('Interface', ''))
            local = str(properties.get('IPv4', {}).get('Address', ''))
            if interface and (local or properties.get('IPv6', {}).get('Address')):
                associated_ssid, associated_bssid = associated_network(self.bus, interface)
                if associated_ssid == ssid:
                    if credentials.bssid and associated_bssid != credentials.bssid.lower():
                        raise RuntimeError('Wi-Fi associated with a different head-unit access point')
                    if local and ipaddress.ip_address(local).is_unspecified:
                        raise RuntimeError('head-unit Wi-Fi has no usable local address')
                    self.log('Android Auto head-unit Wi-Fi association and local address confirmed')
                    return interface, local
            if completed.is_set() and errors:
                if getattr(errors[0], 'get_dbus_name', lambda: '')() != 'net.connman.Error.NoCarrier':
                    raise errors[0]
            self.stop.wait(.2)
        if self.stop.is_set():
            raise InterruptedError('Android Auto Wi-Fi connection stopped')
        raise TimeoutError('head-unit Wi-Fi association timed out')

    def close(self):
        import dbus
        try:
            if self.agent is not None:
                try:
                    self.manager.UnregisterAgent(dbus.ObjectPath(self.agent_path))
                finally:
                    self.agent.remove_from_connection()
                    self.agent = None
        finally:
            restore_network(self.lease, self.bus, self.log)
