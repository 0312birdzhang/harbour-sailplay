"""Select the adapter BlueZ actually exports, rather than assuming hci0."""


def adapter_name(properties):
    """Use the user-visible Bluetooth name, never replace the adapter alias."""
    for key in ('Alias', 'Name'):
        value = str(properties.get(key, '')).strip().replace('\x00', '')
        if value:
            return value
    return 'SailfishOS'


def select_head_unit(objects, configured=None, previous=None):
    """Prefer the connected, paired accessory over a previous vehicle."""
    uuid = '00000000-deca-fade-deca-deafdecacaff'
    candidates = [str(path) for path, interfaces in objects.items()
                  for props in [interfaces.get('org.bluez.Device1', {})]
                  if props.get('Paired') and props.get('Connected')
                  and uuid in [str(value).lower() for value in props.get('UUIDs', [])]]
    if len(candidates) == 1:
        return candidates[0]
    if configured in candidates:
        return configured
    if len(candidates) > 1:
        raise RuntimeError('Multiple connected CarPlay head units; cannot choose safely')
    previous_props = objects.get(previous, {}).get('org.bluez.Device1', {})
    if previous_props.get('Paired') and uuid in list(map(str, previous_props.get('UUIDs', []))):
        return previous
    return configured


def previous_head_unit(path='/var/lib/sailplay/last-head-unit'):
    try:
        with open(path) as source:
            return source.read().strip()
    except FileNotFoundError:
        return None


def remember_head_unit(device, path='/var/lib/sailplay/last-head-unit'):
    import os
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = path + '.{}'.format(os.getpid())
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(str(device) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


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
