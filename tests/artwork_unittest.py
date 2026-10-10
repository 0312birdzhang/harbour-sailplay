import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('artwork',Path(__file__).resolve().parents[1]/'scripts/extract-artwork.py')
artwork=importlib.util.module_from_spec(spec)
spec.loader.exec_module(artwork)


class ArtworkTests(unittest.TestCase):
    def extract(self,data):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'track'
            path.write_bytes(data)
            return artwork.extract(path)

    def test_mp3_v23_picture(self):
        image=b'\xff\xd8\xffcover'
        payload=b'\0image/jpeg\0\x03\0'+image
        frame=b'APIC'+len(payload).to_bytes(4,'big')+b'\0\0'+payload
        header=b'ID3\x03\0\0'+bytes([0,0,0,len(frame)])
        self.assertEqual(self.extract(header+frame),image)

    def test_mp3_v24_utf16_description(self):
        image=b'\x89PNG\r\n\x1a\ncover'
        payload=b'\x01image/png\0\x03\xff\xfeA\0\0\0'+image
        frame=b'APIC'+bytes([0,0,0,len(payload)])+b'\0\0'+payload
        self.assertEqual(self.extract(b'ID3\x04\0\0'+bytes([0,0,0,len(frame)])+frame),image)

    def test_flac_picture_after_other_block(self):
        image=b'\xff\xd8\xffcover'
        payload=(3).to_bytes(4,'big')+(10).to_bytes(4,'big')+b'image/jpeg'+bytes(4)+bytes(16)+len(image).to_bytes(4,'big')+image
        data=b'fLaC'+b'\0\0\0\x02xx'+b'\x86'+len(payload).to_bytes(3,'big')+payload
        self.assertEqual(self.extract(data),image)

    def test_truncated_and_no_art(self):
        self.assertIsNone(self.extract(b'no embedded artwork'))
        self.assertIsNone(self.extract(b'ID3\x03\0\0\0\0\0\x20APIC'))

    def test_external_picture_reference_is_not_fetched(self):
        self.assertIsNone(artwork.picture(b'\0-->\0\x03\0http://example.invalid'))
