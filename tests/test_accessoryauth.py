import base64
import hashlib
import json
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from carplay_proto.accessoryauth import PinnedAccessory


@pytest.fixture
def accessory(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / 'key.json'
    path.write_text(json.dumps({
        'algorithm': 'ecdsa-p256-sha256',
        'certificate_sha256': hashlib.sha256(b'certificate').hexdigest(),
        'public_key_der': base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode(),
    }))
    return PinnedAccessory(str(path)), key


def test_raw_signature_verified_and_cannot_be_replayed(accessory):
    verifier, key = accessory
    challenge = verifier.begin(b'certificate')
    signed = key.sign(challenge, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(signed)
    verifier.verify(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    with pytest.raises(ValueError):
        verifier.verify(signed)


def test_modified_challenge_rejected(accessory):
    verifier, key = accessory
    challenge = verifier.begin(b'certificate')
    other = bytes([challenge[0] ^ 1]) + challenge[1:]
    signed = key.sign(other, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    with pytest.raises(ValueError):
        verifier.verify(signed)


def test_changed_certificate_rejected(accessory):
    verifier, key = accessory
    with pytest.raises(ValueError):
        verifier.begin(b'other certificate')
    assert verifier.challenge is None
