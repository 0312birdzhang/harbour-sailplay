"""Adapt the opt-in Organic Maps v1 export to the public navigation model."""
from sailplay_sdk.guidance import guidance


ORGANIC_MAPS_MANEUVERS = {
    0: 'unknown', 1: 'continue', 2: 'slight-right', 3: 'turn-right',
    4: 'sharp-right', 5: 'slight-left', 6: 'turn-left', 7: 'sharp-left',
    8: 'uturn', 9: 'uturn', 10: 'roundabout-enter', 11: 'roundabout-exit',
    12: 'roundabout-continue', 13: 'unknown', 14: 'arrive',
    15: 'exit-left', 16: 'exit-right',
}


def meters(value, unit):
    return round(min(0xffffffff, value * (1, 1000, .3048, 1609.344)[unit]))


def organicmaps_snapshot(snapshot):
    if snapshot is None:
        return None
    raw = snapshot['navigation']
    state = raw.get('state', 'unavailable')
    values = {}
    if state == 'active':
        values = dict(mode='driving', maneuver=ORGANIC_MAPS_MANEUVERS[raw['turn']],
                      exitNumber=min(raw['exitNumber'], (1 << 32) - 1),
                      drivingSide='left' if raw['turn'] == 9 else 'right',
                      nextDistanceMeters=meters(raw['nextDistance'], raw['nextDistanceUnit']),
                      remainingDistanceMeters=meters(raw['remainingDistance'], raw['remainingDistanceUnit']),
                      remainingSeconds=min(raw['remainingSeconds'], (1 << 64) - 1),
                      currentRoad=raw['currentRoad'], nextRoad=raw['nextRoad'], destination=raw['destination'])
    return dict(providerId='organicmaps-legacy',
                instanceId='{}:{}'.format(snapshot['pid'], snapshot['startTicks']),
                sequence=snapshot['sequence'],
                navigation=guidance(state, updated_ms=snapshot.get('updatedMs', 0), **values))
