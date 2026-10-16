import ctypes
import unittest
from carplay_proto.audio import AUDIO_COMPAT_BUILD


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
        self.assertLess(parse('13A1'), parse(AUDIO_COMPAT_BUILD))
