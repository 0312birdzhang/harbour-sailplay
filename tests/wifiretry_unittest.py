import unittest
from carplay_proto.wifiretry import ReassociationWindow


class RetryTests(unittest.TestCase):
    def test_ordinary_failures_have_no_grace_period(self):
        self.assertFalse(ReassociationWindow(clock=lambda:100).waiting())

    def test_retired_attempt_can_fail_while_new_association_is_pending(self):
        now=[100]
        retry=ReassociationWindow(clock=lambda:now[0])
        retry.arm()
        self.assertTrue(retry.waiting())
        now[0]=114
        retry.arm()
        self.assertEqual(retry.deadline,115)
        now[0]=115
        self.assertFalse(retry.waiting())

    def test_connected_session_does_not_hide_subsequent_errors(self):
        retry=ReassociationWindow(clock=lambda:100)
        retry.arm();retry.started=True
        self.assertFalse(retry.waiting())
