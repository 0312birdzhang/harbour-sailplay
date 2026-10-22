import base64
import hashlib
import json
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from carplay_proto.accessoryauth import PinnedAccessory, key_algorithm


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


@pytest.fixture
def rsa_accessory(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    path = tmp_path / 'rsa.json'
    path.write_text(json.dumps({
        'algorithm': key_algorithm(der),
        'certificate_sha256': hashlib.sha256(b'certificate').hexdigest(),
        'public_key_der': base64.b64encode(der).decode(),
    }))
    return PinnedAccessory(str(path)), key, der


def test_key_algorithm_identifies_supported_keys(rsa_accessory):
    _, _, der = rsa_accessory
    assert key_algorithm(der) == 'rsa-pkcs1-sha1'
    p256 = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert key_algorithm(p256) == 'ecdsa-p256-sha256'
    with pytest.raises(ValueError):
        key_algorithm(b'\x30' + bytes(90))


def test_rsa_mfi_signature_verified_and_cannot_be_replayed(rsa_accessory):
    from cryptography.hazmat.primitives.asymmetric import padding
    verifier, key, _ = rsa_accessory
    challenge = verifier.begin(b'certificate')
    # RSA-1024 coprocessors sign the 20-byte challenge as a SHA-1 digest.
    assert len(challenge) == 20
    signed = key.sign(challenge, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
    verifier.verify(signed)
    with pytest.raises(ValueError):
        verifier.verify(signed)


def test_rsa_signature_over_other_challenge_rejected(rsa_accessory):
    from cryptography.hazmat.primitives.asymmetric import padding
    verifier, key, _ = rsa_accessory
    challenge = verifier.begin(b'certificate')
    other = bytes([challenge[0] ^ 1]) + challenge[1:]
    signed = key.sign(other, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
    with pytest.raises(ValueError):
        verifier.verify(signed)
