import datetime
import tempfile
from pathlib import Path
import unittest
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.serialization import pkcs7
from carplay_proto.bluezadapter import select_head_unit
from carplay_proto.accessoryauth import paired_accessory, certificate_key


class MultipleCarTests(unittest.TestCase):
    def test_connected_vehicle_overrides_previous_target(self):
        objects = {'/new': {'org.bluez.Device1': {'Paired': True, 'Connected': True,
                   'UUIDs': ['00000000-deca-fade-deca-deafdecacaff']}}}
        self.assertEqual(select_head_unit(objects, '/old'), '/new')

    def test_unpaired_and_non_car_devices_are_not_targets(self):
        objects = {'/speaker': {'org.bluez.Device1': {'Paired': True, 'Connected': True, 'UUIDs': []}}}
        self.assertEqual(select_head_unit(objects, '/old'), '/old')

    def test_disconnected_previous_vehicle_overrides_packaged_default(self):
        objects = {'/new': {'org.bluez.Device1': {'Paired': True, 'Connected': False,
                   'UUIDs': ['00000000-deca-fade-deca-deafdecacaff']}}}
        self.assertEqual(select_head_unit(objects, '/old', '/new'), '/new')

    def test_first_use_pin_requires_proof_and_rejects_certificate_changes(self):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Test accessory')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(1)
                .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
                .sign(key, hashes.SHA256()))
        encoded = (pkcs7.PKCS7SignatureBuilder().set_data(b'test')
                   .add_signer(cert, key, hashes.SHA256())
                   .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))
        self.assertEqual(certificate_key(encoded), key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'pin.json')
            auth = paired_accessory(encoded, path)
            challenge = auth.begin(encoded)
            self.assertFalse(Path(path).exists())
            auth.verify(key.sign(challenge, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
            self.assertTrue(Path(path).exists())
            with self.assertRaises(ValueError):
                paired_accessory(encoded, path).begin(b'changed certificate')

    def test_invalid_certificate_cannot_be_learned(self):
        with self.assertRaises(ValueError):
            certificate_key(b'not a certificate')
