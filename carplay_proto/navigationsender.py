"""Subscription-gated provider-neutral guidance on the existing iAP2 link queue."""
import logging
from .navigation import route_update, maneuver_information
from .navigationadapter import meters, organicmaps_snapshot

# Navigation1 maneuver names use the receiver vocabulary verified with DiPlay.
MANEUVERS = {'unknown': 0, 'continue': 3, 'slight-right': 2, 'turn-right': 48,
             'sharp-right': 14, 'slight-left': 1, 'turn-left': 47, 'sharp-left': 13,
             'uturn': 4, 'roundabout-enter': 6, 'roundabout-exit': 7,
             'roundabout-continue': 6, 'arrive': 10, 'exit-left': 13, 'exit-right': 14}


def display(value):
    # HSAE maps iAP2 unit 0 to kilometers and unit 2 to meters.
    return (format(value / 1000, '.1f'), 0) if value >= 1000 else (str(value), 2)


class NavigationSender:
    def __init__(self):
        self.component = None
        self.active = False
        self.last = None

    def reset(self):
        self.component = None
        self.active = False
        self.last = None

    def frames(self, snapshot, subscription, received_messages):
        component = subscription.component
        if component is None or not {0x5201, 0x5202} <= received_messages:
            self.reset()
            return []
        if component != self.component:
            self.reset()
            self.component = component
        if snapshot and 'turn' in snapshot['navigation']:
            snapshot = organicmaps_snapshot(snapshot)
        nav = snapshot['navigation'] if snapshot else {}
        if nav.get('state') != 'active' or nav.get('mode', 'driving') != 'driving':
            if not self.active:
                return []
            self.active = False
            self.last = None
            # HSAE suppresses state 0 before forwarding to the meter. State 2
            # reaches its end-guidance path and clears cached instructions.
            logging.info('navigation tx clear component=%s reason=%s', component, nav.get('state', 'expired'))
            return [route_update(2, 0, '', '', 0, '0', 2, '0', 2,
                                 component=component, next_meters=0, remaining_meters=0)]
        signature = (snapshot['providerId'], snapshot['instanceId'], snapshot['sequence'])
        if signature == self.last:
            return []
        next_m = round(min(0xffffffff, nav['nextDistanceMeters']))
        remaining_m = round(min(0xffffffff, nav['remainingDistanceMeters']))
        next_text, next_unit = display(next_m)
        remaining_text, remaining_unit = display(remaining_m)
        turn = MANEUVERS[nav['maneuver']]
        if nav['maneuver'] == 'roundabout-exit' and 1 <= nav['exitNumber'] <= 19:
            turn = 27 + nav['exitNumber']
        side = 1 if nav['drivingSide'] == 'left' else 0
        result = [maneuver_information(turn, nav['nextRoad'], side, component, 0),
                  route_update(1, 1, nav['currentRoad'], nav['destination'],
                               min(nav['remainingSeconds'], 0xffffffffffffffff),
                               remaining_text, remaining_unit, next_text, next_unit,
                               component, 0, next_m, remaining_m)]
        self.last = signature
        self.active = True
        logging.info('navigation tx component=%s sequence=%s turn=%s next_m=%s '
                     'next_display=%s next_unit=%s remaining_m=%s remaining_display=%s '
                     'remaining_unit=%s frames=5202,5201', component, snapshot['sequence'],
                     turn, next_m, next_text, next_unit, remaining_m, remaining_text, remaining_unit)
        return result
