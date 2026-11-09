"""Choose a paired Android Auto head unit from the current BlueZ snapshot."""
from .wireless import AA_UUID


CARPLAY_UUID = '00000000-deca-fade-deca-deafdecacaff'
LAST_HEAD_UNIT = '/var/lib/sailplay/last-android-auto-head-unit'


def supports(properties, identifier):
    return identifier in [str(value).lower() for value in properties.get('UUIDs', [])]


def select_head_unit(objects, configured=None, previous=None, protocol='auto'):
    def eligible(path, connected=True):
        properties = objects.get(path, {}).get('org.bluez.Device1', {})
        advertised = supports(properties, AA_UUID)
        explicitly_selected = protocol == 'android-auto' and path == configured
        return (properties.get('Paired') and (properties.get('Connected') or not connected)
                and (advertised or explicitly_selected)
                and (protocol != 'auto' or not supports(properties, CARPLAY_UUID)))

    candidates = [str(path) for path in objects if eligible(path)]
    if configured in candidates:
        return configured
    if len(candidates) == 1:
        return candidates[0]
    if previous in candidates:
        return previous
    if len(candidates) > 1:
        raise RuntimeError('multiple connected Android Auto head units')
    if previous and eligible(previous, connected=False):
        return previous
    if configured and eligible(configured, connected=False):
        return configured
    return None
