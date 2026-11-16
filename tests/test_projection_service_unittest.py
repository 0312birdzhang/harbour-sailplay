import importlib.util
from pathlib import Path
import signal
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location('projection_service_recovery',
    Path(__file__).resolve().parents[1] / 'scripts' / 'projection-service.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SupervisorTests(unittest.TestCase):
    def run_supervisor(self, duration=210, lifetimes=None, launch_failure=False, stop_signal=False, diagnostics=False):
        clock = [0.0]
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] >= duration
        handlers = {}

        def wait(seconds):
            clock[0] += seconds
            if stop_signal and clock[0] >= duration:
                handlers[signal.SIGTERM](signal.SIGTERM, None)

        stop.wait.side_effect = wait
        children, launches = [], []
        commands = [['python3', 'carplay.py'], ['python3', 'android-auto.py']]
        remaining_lifetimes = list(lifetimes or [0] * 10)

        class Child:
            def __init__(self, lifetime):
                self.pid = 100 + len(children)
                self.lifetime, self.started = lifetime, clock[0]
                self.returncode = None
                self.signals = []

            def poll(self):
                if self.returncode is None and clock[0] - self.started >= self.lifetime:
                    self.returncode = 1
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        def launch(command, **kwargs):
            launches.append((command[1], clock[0]))
            if launch_failure and command == commands[1]:
                raise OSError('temporary launch failure')
            lifetime = 1000
            if command == commands[1] and remaining_lifetimes:
                lifetime = remaining_lifetimes.pop(0)
            child = Child(lifetime)
            children.append(child)
            return child

        def kill(pid, signum):
            child = next(child for child in children if child.pid == pid)
            child.signals.append(signum)
            child.returncode = -signum

        with patch.object(module, 'selected_protocol', return_value='auto'), \
                patch.object(module, 'backend_commands', return_value=commands), \
                patch.object(module, 'collection_enabled', side_effect=lambda: diagnostics and 2 <= clock[0] < 6), \
                patch.object(module.threading, 'Event', return_value=stop), \
                patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(module.signal, 'signal', side_effect=lambda signum, handler: handlers.update({signum: handler})), \
                patch.object(module.subprocess, 'Popen', side_effect=launch), \
                patch.object(module.os, 'killpg', side_effect=kill), \
                patch.object(module.logging, 'info') as logs, patch.object(module.logging, 'exception'):
            module.main()
        return launches, children, stop, logs

    def test_repeated_exits_back_off_independently_and_stop_running_backend(self):
        launches, children, _, logs = self.run_supervisor(lifetimes=[0] * 6 + [1000])
        self.assertEqual([when for command, when in launches if command == 'android-auto.py'],
                         [0, 8, 20, 42, 84, 146, 208])
        self.assertEqual([when for command, when in launches if command == 'carplay.py'], [0])
        retries = [call.args[3] for call in logs.call_args_list if 'Projection backend retry' in call.args[0]]
        self.assertEqual(retries, [5, 10, 20, 40, 60, 60])
        self.assertEqual(children[0].signals, [signal.SIGTERM])
        self.assertEqual(children[-1].signals, [signal.SIGTERM])

    def test_stable_backend_lifetime_resets_the_backoff(self):
        launches, _, _, logs = self.run_supervisor(duration=112, lifetimes=[0, 0, 70, 0])
        self.assertEqual([when for command, when in launches if command == 'android-auto.py'],
                         [0, 8, 20, 96, 108])
        retries = [call.args[3] for call in logs.call_args_list if 'Projection backend retry' in call.args[0]]
        self.assertEqual(retries, [5, 10, 5, 10])

    def test_launch_failure_keeps_the_other_backend_running_and_uses_backoff(self):
        launches, children, _, _ = self.run_supervisor(duration=50, launch_failure=True)
        self.assertEqual([when for command, when in launches if command == 'android-auto.py'], [0, 6, 16, 36])
        self.assertEqual([when for command, when in launches if command == 'carplay.py'], [0])
        self.assertEqual(children[0].signals, [signal.SIGTERM])

    def test_signal_during_backoff_stops_without_waiting_for_the_next_retry(self):
        launches, children, stop, _ = self.run_supervisor(duration=4, stop_signal=True)
        self.assertEqual(launches, [('carplay.py', 0), ('android-auto.py', 0)])
        stop.set.assert_called_once()
        self.assertEqual(children[0].signals, [signal.SIGTERM])

    def test_monitor_follows_live_switch_without_restarting_backends(self):
        launches, children, _, _ = self.run_supervisor(duration=10, lifetimes=[1000], diagnostics=True)
        monitors = [(command, when) for command, when in launches if command.endswith('connection-monitor.py')]
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0][1], 2)
        self.assertEqual([when for command, when in launches if command == 'carplay.py'], [0])
        self.assertEqual([when for command, when in launches if command == 'android-auto.py'], [0])
        self.assertEqual(children[2].signals, [signal.SIGTERM])


if __name__ == '__main__':
    unittest.main()
