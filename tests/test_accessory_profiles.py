"""Real OpenSSL verification, including non-default EC public-key encodings."""
import base64
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import socket
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from carplay_proto.accessoryauth import (PinnedAccessory, certificate_info,
                                       certificate_key, paired_accessory)
from carplay_proto.iap2link import ACK, DETECT, SYN, Decoder, Packet, encode, synchronization
from carplay_proto.wire import Frame, Framer, encode_param


def certificate(key):
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Sailplay test only')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return (pkcs7.PKCS7SignatureBuilder().set_data(b'test')
            .add_signer(cert, key, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))


@pytest.fixture(params=[1024, 2048])
def legacy(request):
    key = rsa.generate_private_key(public_exponent=65537, key_size=request.param)
    return key, certificate(key)


def test_legacy_rsa_proof_pin_and_replay(legacy, tmp_path):
    key, cert = legacy
    path = tmp_path / 'pin.json'
    auth = paired_accessory(cert, str(path))
    info = certificate_info(cert)
    assert info['algorithm'] == 'rsa-pkcs1v15-sha1'
    assert info['key_bits'] == key.key_size
    assert info['certificate_signature_algorithm'] == 'RSA-SHA256'
    challenge = auth.begin(cert)
    assert len(challenge) == 20 and not path.exists()
    signature = key.sign(challenge, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
    assert len(signature) == key.key_size // 8
    auth.verify(signature)
    assert json.loads(path.read_text())['algorithm'] == 'rsa-pkcs1v15-sha1'
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(PinnedAccessory(str(path)).begin(cert)) == 20
    with pytest.raises(ValueError, match='no pending'):
        auth.verify(signature)


@pytest.mark.parametrize('failure', ['changed_digest', 'double_hash', 'pss', 'truncated', 'wrong_key'])
def test_rsa_failures_never_persist_a_pin(legacy, tmp_path, failure):
    key, cert = legacy
    path = tmp_path / 'pin.json'
    auth = paired_accessory(cert, str(path))
    challenge = auth.begin(cert)
    signer, digest, scheme, algorithm = key, challenge, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1())
    if failure == 'changed_digest': digest = bytes([challenge[0] ^ 1]) + challenge[1:]
    if failure == 'double_hash': algorithm = hashes.SHA1()
    if failure == 'pss': scheme = padding.PSS(mgf=padding.MGF1(hashes.SHA1()), salt_length=20)
    if failure == 'wrong_key': signer = rsa.generate_private_key(public_exponent=65537, key_size=key.key_size)
    signature = signer.sign(digest, scheme, algorithm)
    if failure == 'truncated': signature = signature[:-1]
    with pytest.raises(ValueError): auth.verify(signature)
    assert not path.exists() and auth.challenge is None


def test_rsa_pin_cannot_claim_ecdsa_profile(legacy):
    _, cert = legacy
    pin = dict(algorithm='ecdsa-p256-sha256', certificate_sha256=hashlib.sha256(cert).hexdigest(),
               public_key_der=base64.b64encode(certificate_key(cert)).decode())
    with pytest.raises(ValueError, match='does not match'):
        PinnedAccessory(pin=pin)


def test_offline_export_matches_runtime_profile(legacy, tmp_path):
    _, cert = legacy
    source, output = tmp_path / 'certificate.p7b', tmp_path / 'pin.json'
    source.write_bytes(cert)
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'export-accessory-pin.py'
    subprocess.run([sys.executable, str(script), str(source), str(output)], check=True, capture_output=True)
    assert PinnedAccessory(str(output)).algorithm == 'rsa-pkcs1v15-sha1'


@pytest.mark.parametrize('encoding', ['compressed', 'explicit'])
def test_alternate_p256_encodings_prove_possession(tmp_path, encoding):
    if not shutil.which('openssl'): pytest.skip('OpenSSL CLI required for alternate EC encodings')
    key = ec.generate_private_key(ec.SECP256R1())
    pem = tmp_path / 'key.pem'
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                     serialization.NoEncryption()))
    alternate, cert, bundle = [tmp_path / name for name in ('alternate.pem', 'cert.pem', 'certificate.p7b')]
    option = ['-conv_form', 'compressed'] if encoding == 'compressed' else ['-param_enc', 'explicit']
    def openssl(*args):
        subprocess.run(['openssl', *map(str, args)], check=True, capture_output=True)
    openssl('ec', '-in', pem, '-out', alternate, *option)
    openssl('req', '-new', '-x509', '-key', alternate, '-subj', '/CN=Sailplay test only', '-days', 1, '-out', cert)
    openssl('crl2pkcs7', '-nocrl', '-certfile', cert, '-outform', 'DER', '-out', bundle)
    encoded = bundle.read_bytes()
    assert len(certificate_key(encoded)) != 91  # Reproduces the old false rejection.
    assert certificate_info(encoded)['algorithm'] == 'ecdsa-p256-sha256'
    path = tmp_path / 'pin.json'
    auth = paired_accessory(encoded, str(path))
    challenge = auth.begin(encoded)
    assert len(challenge) == 32 and not path.exists()
    auth.verify(key.sign(challenge, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
    assert path.exists()


@pytest.mark.parametrize('curve', [ec.SECP256K1(), ec.SECP384R1()])
def test_other_ec_curves_are_not_mistaken_for_p256(curve, tmp_path):
    with pytest.raises(ValueError, match='unsupported accessory EC curve'):
        paired_accessory(certificate(ec.generate_private_key(curve)), str(tmp_path / 'pin.json'))
    assert not (tmp_path / 'pin.json').exists()


def test_trailing_certificate_and_key_data_are_rejected(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = certificate(key)
    with pytest.raises(ValueError, match='trailing data'):
        certificate_key(cert + b'extra')
    encoded = certificate_key(cert)
    pin = dict(algorithm='ecdsa-p256-sha256', certificate_sha256=hashlib.sha256(cert).hexdigest(),
               public_key_der=base64.b64encode(encoded + b'extra').decode())
    with pytest.raises(ValueError, match='trailing data'):
        PinnedAccessory(pin=pin)


def test_existing_rsa_pin_rejects_changed_certificate(legacy, tmp_path):
    key, cert = legacy
    path = tmp_path / 'pin.json'
    auth = paired_accessory(cert, str(path))
    auth.verify(key.sign(auth.begin(cert), padding.PKCS1v15(), utils.Prehashed(hashes.SHA1())))
    original = path.read_bytes()
    with pytest.raises(ValueError, match='differs'):
        paired_accessory(cert, str(path)).begin(cert + b'changed')
    assert path.read_bytes() == original


@pytest.mark.parametrize('family', ['RSA', 'P256'])
@pytest.mark.parametrize('valid', [True, False])
def test_iap2_wire_challenge_and_success_require_verified_proof(tmp_path, family, valid):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'wireless-probe.py'
    spec = importlib.util.spec_from_file_location('auth_profile_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = (rsa.generate_private_key(public_exponent=65537, key_size=1024)
           if family == 'RSA' else ec.generate_private_key(ec.SECP256R1()))
    cert = certificate(key)
    pin = tmp_path / 'pin.json'
    phone, car = socket.socketpair()
    stop, authenticated = threading.Event(), threading.Event()
    worker = threading.Thread(target=module.probe, args=(phone, stop, 5),
                              kwargs=dict(paired_pin_path=str(pin), on_authenticated=authenticated.set))
    decoder, queue = Decoder(), []
    car.settimeout(2)
    def receive():
        while not queue:
            raw = car.recv(4096)
            assert raw, 'unexpected EOF'
            queue.extend(decoder.feed(raw))
        return queue.pop(0)
    worker.start()
    try:
        car.sendall(DETECT)
        assert receive() == DETECT
        car.sendall(encode(Packet(SYN, 0x20, 0, 0, synchronization())))
        syn = receive()
        car.sendall(encode(Packet(ACK, 0x20, syn.sequence, 0, None)))
        ident = receive()
        car.sendall(encode(Packet(ACK, 0x21, ident.sequence, 10, Frame(0x1d01, b'').encoded())))
        assert receive().acknowledgement == 0x21
        accepted = receive()
        car.sendall(encode(Packet(ACK, 0x21, accepted.sequence, 0, None)))
        request = receive()
        assert request.payload == Frame(0xaa00, b'').encoded()
        car.sendall(encode(Packet(ACK, 0x22, request.sequence, 10,
                                 Frame(0xaa01, encode_param(0, cert)).encoded())))
        assert receive().acknowledgement == 0x22
        packet = receive()
        frame = Framer().offer(packet.payload)[0]
        assert frame.message_id == 0xaa02
        challenge = frame.parameters()[0].payload
        assert len(challenge) == (20 if family == 'RSA' else 32)
        assert not pin.exists() and not authenticated.is_set()
        if family == 'RSA':
            signature = key.sign(challenge, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
        else:
            der = key.sign(challenge, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            r, s = utils.decode_dss_signature(der)
            signature = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
        if not valid: signature = bytes([signature[0] ^ 1]) + signature[1:]
        car.sendall(encode(Packet(ACK, 0x23, packet.sequence, 10,
                                 Frame(0xaa03, encode_param(0, signature)).encoded())))
        if valid:
            assert receive().acknowledgement == 0x23
            success = receive()
            assert success.payload == Frame(0xaa05, b'').encoded()
            assert pin.exists() and authenticated.is_set()
            car.sendall(encode(Packet(ACK, 0x23, success.sequence, 0, None)))
            assert Framer().offer(receive().payload)[0].message_id == 0x5702
        else:
            assert car.recv(4096) == b''
            assert not pin.exists() and not authenticated.is_set()
    finally:
        stop.set()
        worker.join(2)
        car.close()
    assert not worker.is_alive()
