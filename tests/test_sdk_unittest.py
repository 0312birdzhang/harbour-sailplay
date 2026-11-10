"""SDK wire contracts, session ownership and state consistency regressions."""
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sailplay_sdk.contract import APP_INTERFACE, APP_PATH, ERROR_PREFIX, SESSION_INTERFACE, signatures
from sailplay_sdk.model import ApplicationState, Fault, MAX_UINT64, state_copy


class ContractTests(unittest.TestCase):
    def test_app_xml_signature(self):
        self.assertEqual(signatures(APP_INTERFACE, 'OpenSession'), ('sas', 'o'))

    def test_session_xml_signatures(self):
        expected = {'GetSnapshot': ('', 'ta{sv}'), 'Invoke': ('tsa{sv}t', ''),
                    'SetActive': ('b', ''), 'Close': ('', '')}
        for member, value in expected.items():
            with self.subTest(member=member):
                self.assertEqual(signatures(SESSION_INTERFACE, member), value)

    def test_signal_xml_signatures(self):
        self.assertEqual(signatures(SESSION_INTERFACE, 'StateChanged', 'signal'), ('', 'ta{sv}'))
        self.assertEqual(signatures(SESSION_INTERFACE, 'RequestFinished', 'signal'), ('', 'tta{sv}ss'))

    def test_unknown_member_fails(self):
        with self.assertRaises(ValueError):
            signatures(APP_INTERFACE, 'Missing')


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = ApplicationState('example', {'value': 0}, ('counter',))
        self.car = self.app.open_session(':1.1', 'car', ['state', 'counter'])
        self.phone = self.app.open_session(':1.2', 'phone', [])

    def assert_fault(self, code, function, *arguments):
        with self.assertRaises(Fault) as caught:
            function(*arguments)
        self.assertEqual(caught.exception.name, ERROR_PREFIX + code)

    def test_paths_are_versioned_and_distinct(self):
        self.assertTrue(self.car.startswith(APP_PATH + '/sessions/'))
        self.assertNotEqual(self.car, self.phone)

    def test_instance_identity_changes_with_backend(self):
        other = ApplicationState('example', {'value': 0})
        self.assertNotEqual(self.app.instance_id, other.instance_id)

    def test_capability_generator_is_preserved(self):
        other = ApplicationState('example', {}, (name for name in ['counter', 'counter']))
        self.assertEqual(other.capabilities, ('actions', 'counter', 'state'))

    def test_unsupported_capability_creates_no_session(self):
        self.assert_fault('NotSupported', self.app.open_session, ':1.3', 'car', ['missing'])
        self.assertEqual(len(self.app.sessions), 2)

    def test_unknown_presentation_creates_no_session(self):
        self.assert_fault('NotSupported', self.app.open_session, ':1.3', 'tablet', [])
        self.assertEqual(len(self.app.sessions), 2)

    def test_session_requires_unique_caller(self):
        self.assert_fault('InvalidArgument', self.app.open_session, 'org.example.App', 'car', [])

    def test_other_caller_cannot_read_or_close(self):
        self.assert_fault('NotOwner', self.app.snapshot, self.car, ':1.2')
        self.assert_fault('NotOwner', self.app.close_session, self.car, ':1.2')
        self.assertIn(self.car, self.app.sessions)

    def test_owner_loss_releases_only_owned_presentations(self):
        second = self.app.open_session(':1.1', 'phone', [])
        self.assertEqual(set(self.app.owner_lost(':1.1')), {self.car, second})
        self.assertEqual(list(self.app.sessions), [self.phone])
        self.assertEqual(self.app.state, {'value': 0})

    def test_close_preserves_business_state_and_other_session(self):
        self.app.publish({'value': 3})
        self.app.close_session(self.phone, ':1.2')
        self.assertEqual(self.app.snapshot(self.car, ':1.1'), (2, {'value': 3}))

    def test_closed_session_is_rejected(self):
        self.app.close_session(self.car, ':1.1')
        self.assert_fault('InvalidSession', self.app.snapshot, self.car, ':1.1')

    def test_snapshot_and_publish_copy_mutable_state(self):
        source = {'nested': {'values': [1]}}
        self.app.publish(source)
        source['nested']['values'].append(2)
        _, snapshot = self.app.snapshot(self.car, ':1.1')
        snapshot['nested']['values'].append(3)
        self.assertEqual(self.app.state, {'nested': {'values': [1]}})

    def test_equal_state_keeps_revision(self):
        self.assertFalse(self.app.publish({'value': 0}))
        self.assertEqual(self.app.revision, 1)

    def test_invalid_state_keeps_previous_state(self):
        self.assert_fault('InvalidArgument', self.app.publish, {'': 4})
        self.assertEqual(self.app.snapshot(self.car, ':1.1'), (1, {'value': 0}))

    def test_revision_overflow_keeps_previous_state(self):
        self.app.revision = MAX_UINT64
        self.assert_fault('LimitExceeded', self.app.publish, {'value': 2})
        self.assertEqual(self.app.state, {'value': 0})
        self.assertEqual(self.app.revision, MAX_UINT64)

    def test_duplicate_request_cannot_execute_twice(self):
        self.app.begin_request(self.car, ':1.1', 1, 1)
        self.assert_fault('DuplicateRequest', self.app.begin_request, self.car, ':1.1', 1, 1)
        self.assertEqual(self.app.sessions[self.car].pending, {1: 1})

    def test_request_ids_are_local_to_a_session(self):
        self.app.begin_request(self.car, ':1.1', 1, 0)
        self.app.begin_request(self.phone, ':1.2', 1, 0)
        self.assertEqual(len(self.app.sessions[self.phone].pending), 1)

    def test_stale_request_does_not_consume_request_id(self):
        self.app.publish({'value': 1})
        self.assert_fault('StaleRevision', self.app.begin_request, self.car, ':1.1', 1, 1)
        record = self.app.sessions[self.car]
        self.assertEqual(record.last_request, 0)
        self.assertEqual(record.pending, {})
        self.app.begin_request(self.car, ':1.1', 1, 2)

    def test_request_id_and_revision_ranges(self):
        for value in (True, -1, MAX_UINT64 + 1, '1'):
            with self.subTest(value=value):
                self.assert_fault('InvalidArgument', self.app.begin_request, self.car, ':1.1', value, 0)
                self.assert_fault('InvalidArgument', self.app.check_revision, value)

    def test_request_limit_keeps_previous_request_state(self):
        for value in range(1, 65):
            self.app.begin_request(self.car, ':1.1', value, 0)
        self.assert_fault('LimitExceeded', self.app.begin_request, self.car, ':1.1', 65, 0)
        self.assertEqual(self.app.sessions[self.car].last_request, 64)

    def test_state_rejects_invalid_keys_and_non_dictionary(self):
        for value in ({1: 'value'}, {'bad\0key': 1}, [], None):
            with self.subTest(value=value):
                self.assert_fault('InvalidArgument', state_copy, value)


@unittest.skipUnless(shutil.which('dbus-run-session') and importlib.util.find_spec('dbus')
                     and importlib.util.find_spec('gi'), 'Linux D-Bus and GLib bindings are required')
class BusContractTests(unittest.TestCase):
    def test_state_copy_preserves_nested_dbus_container_signatures(self):
        import dbus
        from sailplay_sdk.service import wire_dictionary

        values = dbus.Dictionary({'label': 'road', 'distance': dbus.UInt64(200)}, signature='sv', variant_level=1)
        source = {'nested': values, 'names': dbus.Array(['one', 'two'], signature='s'),
                  'record': dbus.Struct(('one', dbus.UInt32(2)), variant_level=1)}
        cloned = state_copy(source)
        self.assertEqual(cloned['nested'].signature, 'sv')
        self.assertEqual(cloned['nested'].variant_level, 1)
        self.assertEqual(cloned['names'].signature, 's')
        self.assertEqual(cloned['record'].variant_level, 1)
        self.assertIsNot(cloned['nested'], values)
        self.assertEqual(wire_dictionary(cloned)['nested']['distance'], 200)

    def test_live_python_binding_and_backend(self):
        environment = dict(os.environ)
        environment.pop('XDG_RUNTIME_DIR', None)
        scenario = Path(__file__).with_name('sdk_bus_scenario.py')
        with tempfile.TemporaryDirectory(prefix='sailplay-sdk-bus-') as directory:
            environment['XDG_DATA_HOME'] = directory
            services = Path(directory) / 'dbus-1/services'
            services.mkdir(parents=True)
            backend = scenario.parents[1] / 'sdk/examples/counter-service.py'
            (services / 'org.example.SailplayActivatedCounter.service').write_text(
                '[D-BUS Service]\nName=org.example.SailplayActivatedCounter\nExec=' + sys.executable
                + ' ' + str(backend) + ' --service org.example.SailplayActivatedCounter\n', encoding='utf-8')
            process = subprocess.Popen(['dbus-run-session', '--', sys.executable, str(scenario)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                env=environment, start_new_session=True)
            try:
                output, _ = process.communicate(timeout=35)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    output, _ = process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate()
                self.fail('SDK D-Bus scenario timed out\n' + output)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn('SDK_BUS_CONTRACT_PASS', output)


@unittest.skipUnless(importlib.util.find_spec('dbus') and importlib.util.find_spec('gi'),
                     'Python D-Bus and GLib bindings are required')
class ClientOrderingTests(unittest.TestCase):
    def setUp(self):
        from sailplay_sdk.client import SessionClient
        self.client = object.__new__(SessionClient)
        self.client._closed = False
        self.client._wanted = True
        self.client._epoch = 3
        self.client.revision = 8
        self.client.state = {'value': 8}
        self.client.ready = False
        self.client.on_state = Mock()
        self.client.on_ready = Mock()
        self.client.on_request = Mock()
        self.client._pending = {1}

    def test_snapshot_reply_cannot_replace_newer_signal(self):
        self.client._snapshot(3, 7, {'value': 7})
        self.assertEqual(self.client.state, {'value': 8})
        self.assertEqual(self.client.revision, 8)
        self.assertTrue(self.client.ready)

    def test_old_owner_signal_cannot_change_new_instance(self):
        self.client._state(2, 99, {'value': 99})
        self.assertEqual(self.client.state, {'value': 8})
        self.client.on_state.assert_not_called()

    def test_old_owner_completion_cannot_finish_new_request(self):
        self.client._finished(2, 1, 99, {}, '', '')
        self.assertEqual(self.client._pending, {1})
        self.client.on_request.assert_not_called()

    def test_completion_before_method_ack_is_delivered_once(self):
        self.client._finished(3, 1, 8, {'value': 8}, '', '')
        self.client._invoke_failed(3, 1, RuntimeError('late acknowledgement failure'))
        self.assertEqual(self.client._pending, set())
        self.client.on_request.assert_called_once_with(1, 8, {'value': 8}, '', '')

    def test_late_open_reply_retires_its_session(self):
        self.client._retire = Mock()
        self.client._opened(2, ':1.10', APP_PATH + '/sessions/old')
        self.client._retire.assert_called_once_with(':1.10', APP_PATH + '/sessions/old')

    def test_local_argument_failure_finishes_after_invoke_returns(self):
        self.client.ready = True
        self.client._sequence = 0
        self.client._pending = set()
        self.client._call = Mock(side_effect=ValueError('bad argument'))
        with patch('sailplay_sdk.client.GLib.idle_add') as idle:
            request = self.client.invoke('example', {'bad': object()})
            self.assertEqual(request, 1)
            self.client.on_request.assert_not_called()
            function, epoch, request, error = idle.call_args[0]
            function(epoch, request, error)
        self.client.on_request.assert_called_once()

    def test_invalid_completion_copy_finishes_once(self):
        from sailplay_sdk.service import Invocation

        class NonCopyable:
            def __deepcopy__(self, memo):
                raise ValueError('cannot copy value')

        invocation = Invocation(Mock(), APP_PATH + '/sessions/example', 1, Mock())
        with patch('sailplay_sdk.service.GLib.idle_add') as idle:
            self.assertTrue(invocation.complete({'bad': NonCopyable()}))
            self.assertFalse(invocation.fail('Failed', 'second completion'))
            self.assertEqual(idle.call_args[0][-1].name, ERROR_PREFIX + 'InvalidArgument')


if __name__ == '__main__':
    unittest.main()
