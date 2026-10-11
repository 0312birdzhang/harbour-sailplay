import unittest
from unittest.mock import patch
from carplay_proto.touch import TouchInput


class TouchAnchoringTests(unittest.TestCase):
    def test_external_cursor_offset_is_corrected_without_drag_jump(self):
        touch = TouchInput.__new__(TouchInput)
        touch.width, touch.height = 1920, 720
        touch.x, touch.y, touch.down = 960, 360, False
        touch.debug_reports = 5
        touch.layouts = {'screen': {}}
        cursor = [0, 703]  # external pointer moved it; sender still assumes center
        presses, drag = [], []
        def event(kind, code, value):
            if kind == 2:
                cursor[code] = max(0, min((1920, 720)[code]-1, cursor[code]+value))
                if touch.down:
                    drag.append(tuple(cursor))
            if kind == 1 and value:
                presses.append(tuple(cursor))
        touch.event = event
        value = {'type': 'hidSendReport', 'uuid': 'screen', 'hidReport': b''}
        with patch('carplay_proto.touch.decode_touch', side_effect=[(True,70,650), (True,80,640), (False,80,640)]):
            touch.command(value)
            touch.command(value)
            touch.command(value)
        self.assertEqual(presses, [(70,650)])
        self.assertEqual(tuple(cursor), (80,640))
        self.assertTrue(all(x >= 70 and y >= 640 for x,y in drag))
