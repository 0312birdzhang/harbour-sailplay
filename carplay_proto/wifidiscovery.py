"""Bounded ConnMan discovery with recovery for a stale Wi-Fi service list."""
import time


def find_service(services, ssid, require_available=False):
    return next((str(path) for path, props in services
                 if props.get('Type') == 'wifi' and props.get('Name') == ssid
                 and (not require_available or props.get('State') in ('ready','online')
                      or int(props.get('Strength') or 0)>0)), None)


def discover(manager, technology, ssid, scan, cached_bss_visible,
             set_powered, log=print, clock=time.monotonic, sleep=time.sleep,
             timeout=60, require_available=False):
    deadline = clock() + timeout
    refreshed = False
    attempts = 0
    while clock() < deadline:
        services = manager.GetServices()
        target = find_service(services, ssid, require_available)
        if target:
            return target, services
        attempts += 1
        try:
            scan(technology)
        except Exception as error:
            log('HU Wi-Fi scan failed: {}'.format(type(error).__name__))
        services = manager.GetServices()
        target = find_service(services, ssid, require_available)
        if target:
            return target, services
        if attempts >= 3 and not refreshed and cached_bss_visible(ssid):
            refreshed = True
            log('HU BSS visible but ConnMan service missing; refreshing Wi-Fi once')
            try:
                set_powered(technology, False)
                sleep(1)
            finally:
                set_powered(technology, True)
            # Never restart ConnMan or flush its shared supplicant BSS cache.
        sleep(2)
    services = manager.GetServices()
    return find_service(services, ssid, require_available), services
