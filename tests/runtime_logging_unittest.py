import io
import os
import tempfile
import unittest

from carplay_proto.runtime_logging import PersistentStream, private_handler


class LoggingTests(unittest.TestCase):
    def test_restart_keeps_existing_lines_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            for line in ('first boot\n', 'second boot\n'):
                handler = private_handler('session', directory)
                output = PersistentStream(io.StringIO(), handler)
                output.write(line)
                output.flush()
                handler.close()
            path = os.path.join(directory, 'session.log')
            with open(path) as stream:
                content = stream.read()
            self.assertIn('first boot', content)
            self.assertIn('second boot', content)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)

    def test_partial_lines_and_bounded_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = private_handler('wifi', directory)
            handler.maxBytes = 150
            handler.backupCount = 2
            original = io.StringIO()
            output = PersistentStream(original, handler)
            output.write('partial')
            output.write(' line\n')
            for i in range(20):
                output.write('event {} {}\n'.format(i, 'x' * 40))
            output.flush()
            handler.close()
            self.assertTrue(original.getvalue().startswith('partial line\n'))
            self.assertEqual(len(os.listdir(directory)), 3)
            with open(os.path.join(directory, 'wifi.log')) as stream:
                self.assertIn('event 19', stream.read())


if __name__ == '__main__':
    unittest.main()
