"""Bounded ConnMan discovery with recovery for a stale Wi-Fi service list."""
import time


def find_service(services, ssid, require_available=False):
    return next((str(path) for path, props in services
                 if props.get('Type') == 'wifi' and props.get('Name') == ssid
                 and (not require_available or props.get('State') in ('ready','online')
                      or int(props.get('Strength') or 0)>0)), None)


def discover(manager, technology, ssid, scan, cached_bss_visible,
             set_powered, log=print, clock=time.monotonic, sleep=time.sleep,
             timeout=30, require_available=False):
    from .networkdbus import transient_error
    deadline = clock() + timeout
    services = []
    def services_now():
        try:
            return manager.GetServices(timeout=max(.1, min(3, deadline-clock())))
        except Exception as error:
            if not transient_error(error): raise
            log('HU discovery waiting for ConnMan: {}'.format(error.get_dbus_name()))
            return []
    while clock() < deadline:
        services = services_now()
        target = find_service(services, ssid, require_available)
        if target:
            return target, services
        started = clock()
        try:
            scan(technology)
        except Exception as error:
            name = getattr(error, 'get_dbus_name', lambda: type(error).__name__)()
            log('HU Wi-Fi scan failed: {}'.format(name))
        log('HU scan completed elapsedMs={:.0f}'.format((clock()-started)*1000))
        if clock() >= deadline: break
        services = services_now()
        target = find_service(services, ssid, require_available)
        if target:
            return target, services
        log('HU discovery targetUnavailable remainingSeconds={:.1f}'.format(max(0,deadline-clock())))
        # Never turn Wi-Fi off to repair a missing service list.
        sleep(min(2,max(0,deadline-clock())))
    return None, services



def ensure_wifi_powered(manager, set_powered, log=print):
    for path, props in manager.GetTechnologies():
        if props.get('Type') == 'wifi':
            if not props.get('Powered'):
                set_powered(str(path), True)
                log('CarPlay requested Wi-Fi; enabled the Wi-Fi technology')
            return str(path)
    raise RuntimeError('Wi-Fi technology is unavailable')


def verify_local_carplay(props, ssid, associated_ssid, addresses, port, probe, log=print):
    """A local authenticated-HU session needs neither DNS nor Internet status."""
    import ipaddress
    interface=str(props.get('Ethernet',{}).get('Interface',''))
    if props.get('Type')!='wifi' or props.get('Name')!=ssid or not interface or associated_ssid!=ssid:
        log('HU local bypass rejected: target association not confirmed')
        return False
    candidates=list(addresses)
    gateway=str(props.get('IPv4',{}).get('Gateway',''))
    if gateway:candidates.append(gateway)
    seen=set()
    for address in candidates:
        address=str(address)
        try:ip=ipaddress.ip_address(address.split('%')[0])
        except ValueError:continue
        if ip.is_unspecified or ip.is_loopback or ip.is_multicast or address in seen:continue
        seen.add(address)
        if len(seen)>3:break
        try:
            local=ipaddress.ip_address(probe(address,int(port),interface).split('%')[0])
            if local.is_unspecified or local.is_loopback:continue
        except (OSError,ValueError):continue
        log('HU local bypass verified: interface={} state={} localAddress={} peer={} port={}; Internet/DNS not required'.format(
            interface,props.get('State'),local,address,port))
        return True
    log('HU local bypass rejected: CarPlay endpoint not reachable on target Wi-Fi')
    return False


def probe_bound_endpoint(address,port,interface):
    import socket
    family=socket.AF_INET6 if ':' in address else socket.AF_INET
    with socket.socket(family,socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        # Do not accept reachability through home Wi-Fi, cellular or a VPN.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,interface.encode()+b'\0')
        dest=(address.split('%')[0],port,0,socket.if_nametoindex(interface)) if family==socket.AF_INET6 else (address,port)
        sock.connect(dest)
        return sock.getsockname()[0]
