"""The fixed Navigation1 model, independent of a map engine or transport."""
import sys
import time

from .model import Fault, MAX_UINT64

try:
    from dbus import Boolean
except ImportError:
    Boolean = bool


STATES = frozenset(('idle', 'active', 'unavailable', 'stopped', 'arrived'))
MODES = frozenset(('driving', 'walking', 'cycling', 'transit'))
MANEUVERS = frozenset(('unknown', 'continue', 'slight-left', 'slight-right',
                      'turn-left', 'turn-right', 'sharp-left', 'sharp-right',
                      'uturn', 'roundabout-enter', 'roundabout-exit',
                      'roundabout-continue', 'exit-left', 'exit-right', 'arrive'))
FIELDS = frozenset(('state', 'mode', 'maneuver', 'exitNumber', 'drivingSide',
                   'nextDistanceMeters', 'remainingDistanceMeters', 'remainingSeconds',
                   'currentRoad', 'nextRoad', 'destination', 'updatedMs'))
MAX_AGE_MS = 10000


def boottime_ms():
    """Use the same suspend-aware clock as the projected legacy exporter."""
    return int(time.clock_gettime(time.CLOCK_BOOTTIME) * 1000)


def unsigned(value, maximum=MAX_UINT64):
    return (isinstance(value, int) and not isinstance(value, (bool, Boolean))
            and 0 <= value <= maximum)


def validate_guidance(value, now_ms=None):
    """Validate a complete wire model and discard guidance in terminal states."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise Fault('InvalidArgument', 'guidance must contain the Navigation1 fields')
    state = value['state']
    if not isinstance(state, str) or state not in STATES:
        raise Fault('InvalidArgument', 'navigation state is unavailable')
    if not unsigned(value['updatedMs']):
        raise Fault('InvalidArgument', 'navigation update time must be unsigned milliseconds')
    if now_ms is not None and (value['updatedMs'] > now_ms
                              or state == 'active' and now_ms - value['updatedMs'] > MAX_AGE_MS):
        raise Fault('Unavailable', 'navigation guidance has expired')
    for key, choices in (('mode', MODES), ('maneuver', MANEUVERS),
                         ('drivingSide', ('left', 'right'))):
        if not isinstance(value[key], str) or value[key] not in choices:
            raise Fault('InvalidArgument', 'unsupported navigation ' + key)
    if not unsigned(value['exitNumber'], (1 << 32) - 1) or not unsigned(value['remainingSeconds']):
        raise Fault('InvalidArgument', 'navigation counts must be unsigned integers')
    for key in ('nextDistanceMeters', 'remainingDistanceMeters'):
        number = value[key]
        if (not isinstance(number, (int, float)) or isinstance(number, (bool, Boolean))
                or not 0 <= number <= sys.float_info.max):
            raise Fault('InvalidArgument', 'navigation distances must be finite nonnegative meters')
    for key in ('currentRoad', 'nextRoad', 'destination'):
        text = value[key]
        if not isinstance(text, str) or len(text) > 1024 or '\0' in text:
            raise Fault('InvalidArgument', 'navigation text must be bounded UTF-8')
    if state != 'active':
        return _empty_guidance(state, int(value['updatedMs']))
    return {key: (float(value[key]) if key.endswith('DistanceMeters') else value[key])
            for key in FIELDS}


def _empty_guidance(state, updated_ms):
    return dict(state=state, mode='driving', maneuver='unknown', exitNumber=0,
                drivingSide='right', nextDistanceMeters=0.0, remainingDistanceMeters=0.0,
                remainingSeconds=0, currentRoad='', nextRoad='', destination='', updatedMs=updated_ms)


def guidance(state='idle', updated_ms=None, **values):
    """Create a complete provider model with an explicit navigation timestamp."""
    result = _empty_guidance(state, boottime_ms() if updated_ms is None else updated_ms)
    result.update(values)
    return validate_guidance(result)
