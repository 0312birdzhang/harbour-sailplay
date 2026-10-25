"""Subscription-gated Organic Maps to iAP2 guidance, on the existing link queue."""
import logging
from .navigation import route_update, maneuver_information

# Organic Maps CarDirection -> Apple RouteGuidanceManeuverType.
# DiPlay BydManeuverCodes and its iPhone fixtures provide the receiver vocabulary.
TURNS = {0: 0, 1: 3, 2: 2, 3: 48, 4: 14, 5: 1, 6: 47, 7: 13,
         8: 4, 9: 4, 10: 6, 11: 7, 12: 6, 13: 0, 14: 10, 15: 13, 16: 14}


def meters(value, unit):
    return min(0xffffffff, round(value * (1, 1000, .3048, 1609.344)[unit]))


def display(value):
    # iAP2 display units differ from Organic Maps: 0 kilometers, 2 meters.
    # HSAE maps raw 0 -> internal 2 (km), raw 2 -> internal 0 (m).
    # Normalize imperial inputs to meters before selecting the display unit.
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
        nav = snapshot['navigation'] if snapshot else {}
        if nav.get('state') != 'active':
            if not self.active:
                return []
            self.active = False
            self.last = None
            # HSAE suppresses state 0 before forwarding to the meter. State 2
            # reaches its end-guidance path and clears cached instructions.
            logging.info('navigation tx clear component=%s reason=%s', component, nav.get('state', 'expired'))
            return [route_update(2, 0, '', '', 0, '0', 2, '0', 2,
                                 component=component, next_meters=0, remaining_meters=0)]
        signature = (snapshot['pid'], snapshot['startTicks'], snapshot['sequence'])
        if signature == self.last:
            return []
        next_m = meters(nav['nextDistance'], nav['nextDistanceUnit'])
        remaining_m = meters(nav['remainingDistance'], nav['remainingDistanceUnit'])
        next_text, next_unit = display(next_m)
        remaining_text, remaining_unit = display(remaining_m)
        turn = TURNS[nav['turn']]
        if nav['turn'] == 11 and 1 <= nav['exitNumber'] <= 19:
            turn = 27 + nav['exitNumber']
        # Right-hand traffic by default; UTurnRight uses the left-hand variant.
        side = 1 if nav['turn'] == 9 else 0
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
