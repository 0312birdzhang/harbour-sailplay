"""Select the adapter BlueZ actually exports, rather than assuming hci0."""


def select_adapter(objects, device=None):
    adapters = {str(path): props['org.bluez.Adapter1']
                for path, props in objects.items() if 'org.bluez.Adapter1' in props}
    if not adapters:
        raise RuntimeError('No BlueZ Bluetooth adapter available')
    preferred = device.rsplit('/', 1)[0] if device else None
    if preferred in adapters:
        adapter = preferred
    else:
        adapter = sorted(adapters, key=lambda path:
                         (not bool(adapters[path].get('Powered', False)), path))[0]
    if device:
        device = adapter + '/' + device.rsplit('/', 1)[1]
    return adapter, device
