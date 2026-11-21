import ctypes
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from carplay_proto.audio import AUDIO_COMPAT_BUILD, IOS_COMPAT_BUILDS, audio_compat_build


class ReceiverCompatibilityTests(unittest.TestCase):
    def test_build_selects_eight_byte_rtp_aad_in_hsae_receiver(self):
        # libAirPlay CompareOSBuildVersionStrings (0x17d20) parses each
        # operand with sscanf, returning +1 if the second cannot be parsed.
        # Its caller compares ("13A1", senderBuild), then uses the sign bit
        # to select the eight-byte rather than twelve-byte RTP AAD.
        libc = ctypes.CDLL(None)
        def parse(text):
            major, letter, minor = ctypes.c_int(), ctypes.c_char(), ctypes.c_int()
            count = libc.sscanf(text.encode(), b'%d%c%d', ctypes.byref(major),
                                ctypes.byref(letter), ctypes.byref(minor))
            return (major.value, letter.value.upper(), minor.value) if count == 3 else None
        self.assertLess(parse('5.2'), parse('13A1'))
        self.assertIsNotNone(parse(AUDIO_COMPAT_BUILD))
        for build in IOS_COMPAT_BUILDS.values():
            self.assertLess(parse('13A1'), parse(build))

    def test_persisted_versions_and_default(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / 'projection.ini'
            self.assertEqual(audio_compat_build(str(path)), '21A329')
            for version, build in IOS_COMPAT_BUILDS.items():
                path.write_text('[Projection]\nprotocol=carplay\n[CarPlay]\niosVersion={}\n'.format(version))
                self.assertEqual(audio_compat_build(str(path)), build)
            for text in ('[Projection]\nprotocol=auto\n', '[CarPlay]\niosVersion=bad\n',
                         '[CarPlay]\niosVersion=99\n', 'invalid ini'):
                path.write_text(text)
                self.assertEqual(audio_compat_build(str(path)), AUDIO_COMPAT_BUILD)

    def test_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'projection.ini'
            path.write_text('[CarPlay]\niosVersion=9\n')
            for build in IOS_COMPAT_BUILDS.values():
                with patch.dict(os.environ, {'SAILPLAY_OS_BUILD': build}):
                    self.assertEqual(audio_compat_build(str(path)), build)
            with patch.dict(os.environ, {'SAILPLAY_OS_BUILD': 'invalid'}):
                self.assertEqual(audio_compat_build(str(path)), '13A344')
