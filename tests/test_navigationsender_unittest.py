import unittest
from carplay_proto.navigation import NavigationSubscription, START, STOP
from carplay_proto.navigationsender import NavigationSender, meters
from carplay_proto.wire import Frame, encode_param

class SenderTests(unittest.TestCase):
    def setUp(self):
        self.sender = NavigationSender()
        self.sub = NavigationSubscription()
        self.sub.offer(Frame(START, encode_param(0, b'\0\x09')))
        self.snapshot = dict(pid=123, startTicks='99', sequence=1, navigation=dict(
            state='active', turn=2, exitNumber=0, nextDistance=200, nextDistanceUnit=0,
            remainingDistance=12.3, remainingDistanceUnit=1, remainingSeconds=300,
            currentRoad='Current', nextRoad='Next', destination='Destination'))
    def frames(self, snapshot=None):
        return self.sender.frames(snapshot or self.snapshot, self.sub, {0x5201,0x5202})
    def test_maneuver_before_route_and_shared_index(self):
        frames = self.frames()
        self.assertEqual([f.message_id for f in frames], [0x5202,0x5201])
        m,r = [{p.id:p.payload for p in f.parameters()} for f in frames]
        self.assertEqual(m[1], r[13])
        self.assertEqual(m[3], b'\x02')
        self.assertEqual(m[8], b'\0')
        self.assertEqual(int.from_bytes(r[10], 'big'), 200)
        self.assertEqual(int.from_bytes(r[7], 'big'), 12300)
        self.assertEqual(self.frames(), [])
    def test_distance_display_uses_iap2_units_not_map_units(self):
        # Real vehicle regression: 600 m was rendered as 600 km with raw unit 0.
        for distance, unit, raw, text, wire_unit in (
                (600, 0, 600, b'600\0', b'\x02'),
                (999, 0, 999, b'999\0', b'\x02'),
                (1000, 0, 1000, b'1.0\0', b'\x00'),
                (1.2, 1, 1200, b'1.2\0', b'\x00'),
                (100, 2, 30, b'30\0', b'\x02'),
                (1, 3, 1609, b'1.6\0', b'\x00')):
            with self.subTest(distance=distance, unit=unit):
                self.sender.reset()
                self.snapshot['navigation'].update(nextDistance=distance,
                    nextDistanceUnit=unit, remainingDistance=distance,
                    remainingDistanceUnit=unit)
                route = {p.id:p.payload for p in self.frames()[1].parameters()}
                self.assertEqual(route[11], text)
                self.assertEqual(route[12], wire_unit)
                self.assertEqual(route[8], text)
                self.assertEqual(route[9], wire_unit)
                self.assertEqual(int.from_bytes(route[10], 'big'), raw)
                self.assertEqual(int.from_bytes(route[7], 'big'), raw)

    def test_requires_subscription_and_supported_messages(self):
        self.assertEqual(self.sender.frames(self.snapshot,self.sub,set()), [])
        self.sub.offer(Frame(STOP,encode_param(0,b'\0\x09')))
        self.assertEqual(self.frames(), [])
    def test_expiry_clears_once_and_restart_resends(self):
        self.frames()
        clear = self.sender.frames(None,self.sub,{0x5201,0x5202})
        self.assertEqual({p.id:p.payload for p in clear[0].parameters()}[1], b'\x02')
        self.assertEqual(self.sender.frames(None,self.sub,{0x5201,0x5202}), [])
        self.assertEqual(len(self.frames()), 2)
    def test_metric_conversion_and_roundabout(self):
        self.assertEqual(meters(1,3),1609)
        self.snapshot['navigation'].update(turn=11,exitNumber=3)
        self.assertEqual({p.id:p.payload for p in self.frames()[0].parameters()}[3], b'\x1e')
    def test_stop_arrival_unavailable_clear(self):
        for state in ('stopped','arrived','unavailable','idle'):
            self.sender.reset()
            self.snapshot['navigation']['state']='active'
            self.frames()
            self.snapshot['navigation']['state']=state
            self.assertEqual(len(self.frames()),1)
