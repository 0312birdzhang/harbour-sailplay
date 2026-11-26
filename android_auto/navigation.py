"""Forward provider-neutral navigation guidance over Android Auto NavigationStatusService."""
import logging
import time

from carplay_proto.navigationproviders import ProviderNavigationFeed
from .protobuf import field


STATUS_NAVIGATION = 1
STATUS_INACTIVE = 2
STATUS_REROUTING = 3

TURN_LEFT = 1
TURN_RIGHT = 2
TURN_UNSPECIFIED = 3

# Map Sailplay SDK maneuver names to AAP NavigationNextTurnEvent.NextTurnEnum.
MANEUVER_EVENTS = {
    'depart': 1,
    'straight': 2,
    'continue': 2,
    'slight_left': 3,
    'slight_right': 3,
    'turn_left': 4,
    'turn_right': 4,
    'sharp_left': 5,
    'sharp_right': 5,
    'u_turn_left': 6,
    'u_turn_right': 6,
    'merge': 10,
    'roundabout_enter': 11,
    'roundabout_exit': 12,
    'roundabout': 13,
    'destination': 19,
    'arrive': 19,
}


def encode_status(status):
    return field(1, status)


def encode_next_turn(road, turn_side=TURN_UNSPECIFIED, event=0):
    payload = field(1, road or '') + field(2, turn_side)
    if event:
        payload += field(3, event)
    return payload


def encode_next_turn_distance(distance_meters, time_seconds=0):
    meters = max(0, int(distance_meters))
    payload = field(1, meters) + field(2, max(0, int(time_seconds)))
    # Field 3: display distance in thousandths of unit; field 4: 1=meters, 2=km.
    if meters >= 1000:
        payload += field(3, meters) + field(4, 2)
    else:
        payload += field(3, meters * 1000) + field(4, 1)
    return payload


def _turn_side(maneuver):
    name = str(maneuver or '').lower()
    if 'left' in name:
        return TURN_LEFT
    if 'right' in name:
        return TURN_RIGHT
    return TURN_UNSPECIFIED


class NavigationBridge:
    """Poll ProviderNavigationFeed and push updates to AAP navigation channel."""

    def __init__(self, channel, min_interval_ms=1000, feed=None):
        self.channel = channel
        self.interval = max(0.1, min_interval_ms / 1000.0)
        self.feed = feed if feed is not None else ProviderNavigationFeed()
        self.last_poll = 0.0
        self.last_status = None
        self.last_turn = None
        self.last_distance = None

    def pump(self, transport):
        now = time.monotonic()
        if now - self.last_poll < self.interval:
            return
        self.last_poll = now
        try:
            snapshot = self.feed.poll()
        except Exception:
            logging.debug('Android Auto navigation poll failed', exc_info=True)
            return
        if snapshot is None:
            if self.last_status != STATUS_INACTIVE:
                transport.send(self.channel, 0x8004, encode_status(STATUS_INACTIVE))
                self.last_status = STATUS_INACTIVE
                self.last_turn = None
                self.last_distance = None
            return
        nav = snapshot.get('navigation') or {}
        state = str(nav.get('state', '')).lower()
        if state in ('rerouting', 'recalculating'):
            status = STATUS_REROUTING
        elif state in ('active', 'navigating', 'guidance'):
            status = STATUS_NAVIGATION
        else:
            status = STATUS_INACTIVE
        if status != self.last_status:
            transport.send(self.channel, 0x8004, encode_status(status))
            self.last_status = status
        if status == STATUS_INACTIVE:
            self.last_turn = None
            self.last_distance = None
            return
        maneuver = str(nav.get('maneuver') or nav.get('turn') or '').lower()
        road = str(nav.get('roadName') or nav.get('instruction') or nav.get('destinationName') or '')
        turn_key = (road, _turn_side(maneuver), MANEUVER_EVENTS.get(maneuver, 0))
        if turn_key != self.last_turn:
            transport.send(self.channel, 0x8005, encode_next_turn(*turn_key))
            self.last_turn = turn_key
        distance = nav.get('maneuverDistanceMeters')
        if distance is None:
            distance = nav.get('remainingDistanceMeters')
        seconds = nav.get('remainingSeconds') or 0
        if distance is not None:
            dist_key = (int(distance), int(seconds))
            if dist_key != self.last_distance:
                transport.send(self.channel, 0x8006, encode_next_turn_distance(*dist_key))
                self.last_distance = dist_key

    def close(self, transport=None):
        if transport is not None and self.last_status not in (None, STATUS_INACTIVE):
            try:
                transport.send(self.channel, 0x8004, encode_status(STATUS_INACTIVE))
            except OSError:
                pass
        self.last_status = STATUS_INACTIVE
