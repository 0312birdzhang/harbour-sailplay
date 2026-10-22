"""Pinned-accessory challenge verification using the system OpenSSL library.

The pin binds a previously observed certificate to an offline extracted public
key. This proves key possession for that accessory, not an Apple CA chain.
No private key is loaded. SHA256 challenges are already digests (MFi v3).
"""
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import json
import logging
import os


P256_SPKI_PREFIX = bytes.fromhex(
    '3059301306072a8648ce3d020106082a8648ce3d03010703420004')
RSA_ALGORITHM_IDENTIFIER = bytes.fromhex('300d06092a864886f70d0101010500')
RSA_ALGORITHMS = ('rsa-pkcs1-sha1', 'rsa-pkcs1-sha256')


def _read_tlv(data, offset):
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7f
        length = int.from_bytes(data[offset:offset + count], 'big')
        offset += count
    return tag, data[offset:offset + length], offset + length


def rsa_bits(encoded):
    """Return the RSA modulus size from a SubjectPublicKeyInfo."""
    _, spki, _ = _read_tlv(encoded, 0)
    _, _, offset = _read_tlv(spki, 0)
    _, bits, _ = _read_tlv(spki, offset)
    _, rsa_key, _ = _read_tlv(bits[1:], 0)
    _, modulus, _ = _read_tlv(rsa_key, 0)
    if modulus[:1] == b'\x00':
        modulus = modulus[1:]
    return len(modulus) * 8


def key_algorithm(encoded):
    """Identify a supported SubjectPublicKeyInfo encoding."""
    if len(encoded) == 91 and encoded.startswith(P256_SPKI_PREFIX):
        return 'ecdsa-p256-sha256'
    if len(encoded) >= 128 and RSA_ALGORITHM_IDENTIFIER in encoded[:40]:
        return 'rsa-pkcs1-sha1' if rsa_bits(encoded) <= 1024 else 'rsa-pkcs1-sha256'
    raise ValueError('unsupported accessory key algorithm')


def raw_ecdsa_to_der(signature):
    if len(signature) != 64:
        raise ValueError('expected P256 raw signature')
    values = []
    for value in (signature[:32], signature[32:]):
        value = value.lstrip(b'\x00') or b'\x00'
        if value[0] & 0x80:
            value = b'\x00' + value
        values.append(b'\x02' + bytes([len(value)]) + value)
    body = b''.join(values)
    return b'\x30' + bytes([len(body)]) + body


class PinnedAccessory:
    def __init__(self, filename=None, pin=None):
        if pin is None:
            with open(filename) as source:
                pin = json.load(source)
        self.pending_pin = None
        self.algorithm = pin['algorithm']
        if self.algorithm != 'ecdsa-p256-sha256' and self.algorithm not in RSA_ALGORITHMS:
            raise ValueError('unsupported accessory key algorithm')
        self.rsa = self.algorithm.startswith('rsa-')
        self.certificate_hash = pin['certificate_sha256']
        if len(self.certificate_hash) != 64:
            raise ValueError('invalid certificate pin')
        self.public_key = base64.b64decode(pin['public_key_der'], validate=True)
        self.challenge = None
        library = ctypes.util.find_library('crypto')
        if not library:
            raise OSError('system libcrypto not found')
        self.crypto = ctypes.CDLL(library)
        vp, size = ctypes.c_void_p, ctypes.c_size_t
        functions = {
            'd2i_PUBKEY': ([ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.c_long], vp),
            'EVP_PKEY_free': ([vp], None),
            'EVP_PKEY_CTX_new': ([vp, vp], vp),
            'EVP_PKEY_CTX_free': ([vp], None),
            'EVP_PKEY_verify_init': ([vp], ctypes.c_int),
            'EVP_PKEY_CTX_set_signature_md': ([vp, vp], ctypes.c_int),
            'EVP_PKEY_verify': ([vp, vp, size, vp, size], ctypes.c_int),
            'EVP_PKEY_CTX_set_rsa_padding': ([vp, ctypes.c_int], ctypes.c_int),
            'EVP_PKEY_CTX_set_rsa_pss_saltlen': ([vp, ctypes.c_int], ctypes.c_int),
            'EVP_sha1': ([], vp),
            'EVP_sha256': ([], vp),
        }
        for name, (arguments, result) in functions.items():
            function = getattr(self.crypto, name)
            function.argtypes, function.restype = arguments, result

    def begin(self, certificate):
        if not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), self.certificate_hash):
            raise ValueError('accessory certificate differs from the observed pin')
        self.challenge = os.urandom(20 if self.rsa else 32)
        return self.challenge

    def verify(self, signature):
        if self.challenge is None:
            raise ValueError('no pending accessory challenge')
        challenge, self.challenge = self.challenge, None
        if self.rsa:
            if not 128 <= len(signature) <= 1024:
                raise ValueError('invalid RSA signature encoding')
        elif len(signature) == 64:
            signature = raw_ecdsa_to_der(signature)
        elif not 8 <= len(signature) <= 72 or signature[:1] != b'\x30':
            raise ValueError('invalid P256 signature encoding')
        key_buffer = ctypes.create_string_buffer(self.public_key)
        cursor = ctypes.cast(key_buffer, ctypes.c_void_p)
        key = self.crypto.d2i_PUBKEY(None, ctypes.byref(cursor), len(self.public_key))
        if not key:
            raise ValueError('invalid pinned public key')
        signature_buffer = ctypes.create_string_buffer(signature)

        def attempt(md, data, padding=1, salt_length=None):
            context = self.crypto.EVP_PKEY_CTX_new(key, None)
            if not context:
                raise OSError('OpenSSL verifier initialization failed')
            try:
                if self.crypto.EVP_PKEY_verify_init(context) <= 0:
                    raise OSError('OpenSSL verifier initialization failed')
                if self.crypto.EVP_PKEY_CTX_set_signature_md(context, md()) <= 0:
                    raise OSError('OpenSSL digest selection failed')
                if self.rsa:
                    if self.crypto.EVP_PKEY_CTX_set_rsa_padding(context, padding) <= 0:
                        raise OSError('OpenSSL RSA padding selection failed')
                    if salt_length is not None and self.crypto.EVP_PKEY_CTX_set_rsa_pss_saltlen(context, salt_length) <= 0:
                        raise OSError('OpenSSL RSA-PSS salt selection failed')
                data_buffer = ctypes.create_string_buffer(data)
                return self.crypto.EVP_PKEY_verify(context, signature_buffer, len(signature),
                                                    data_buffer, len(data))
            finally:
                self.crypto.EVP_PKEY_CTX_free(context)

        try:
            if self.rsa:
                # MFi 1.0 coprocessors (RSA-1024) sign the 20-byte challenge,
                # which is already a SHA-1 digest, with PKCS#1 v1.5; other
                # receivers hash it first or use SHA-256. Try the common
                # encodings; every candidate is a full signature check.
                candidates = [
                    ('rsa-sha1-challenge-pkcs1', self.crypto.EVP_sha1, challenge, 1),
                    ('rsa-sha1-digest-pkcs1', self.crypto.EVP_sha1, hashlib.sha1(challenge).digest(), 1),
                    ('rsa-sha256-digest-pkcs1', self.crypto.EVP_sha256, hashlib.sha256(challenge).digest(), 1),
                    ('rsa-sha256-challenge-pkcs1', self.crypto.EVP_sha256, challenge, 1),
                    ('rsa-sha1-digest-pss', self.crypto.EVP_sha1, hashlib.sha1(challenge).digest(), 6),
                    ('rsa-sha256-digest-pss', self.crypto.EVP_sha256, hashlib.sha256(challenge).digest(), 6),
                ]
                result = 0
                for name, md, data, padding in candidates:
                    result = attempt(md, data, padding, len(data) if padding == 6 else None)
                    if result == 1:
                        logging.info('accessory signature verified scheme=%s', name)
                        break
            else:
                result = attempt(self.crypto.EVP_sha256, challenge)
            if result != 1:
                raise ValueError('accessory challenge signature rejected')
            if self.pending_pin:
                path, pin = self.pending_pin
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, 'w') as output:
                    json.dump(pin, output)
                self.pending_pin = None
        finally:
            self.crypto.EVP_PKEY_free(key)


def certificate_key(certificate):
    """Extract exactly one supported certificate key through system libcrypto."""
    crypto = ctypes.CDLL(ctypes.util.find_library('crypto'))
    vp = ctypes.c_void_p
    signatures = {
        'd2i_CMS_ContentInfo': ([vp, ctypes.POINTER(vp), ctypes.c_long], vp),
        'CMS_get1_certs': ([vp], vp), 'CMS_ContentInfo_free': ([vp], None),
        'OPENSSL_sk_num': ([vp], ctypes.c_int), 'OPENSSL_sk_value': ([vp, ctypes.c_int], vp),
        'OPENSSL_sk_free': ([vp], None), 'X509_free': ([vp], None),
        'X509_get_pubkey': ([vp], vp), 'i2d_PUBKEY': ([vp, ctypes.POINTER(vp)], ctypes.c_int),
        'EVP_PKEY_free': ([vp], None),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(crypto, name)
        function.argtypes, function.restype = arguments, result
    buffer = ctypes.create_string_buffer(certificate)
    cursor = ctypes.cast(buffer, vp)
    cms = crypto.d2i_CMS_ContentInfo(None, ctypes.byref(cursor), len(certificate))
    if not cms:
        raise ValueError('invalid accessory PKCS7 certificate')
    stack = key = None
    try:
        stack = crypto.CMS_get1_certs(cms)
        if not stack or crypto.OPENSSL_sk_num(stack) != 1:
            raise ValueError('expected exactly one accessory certificate')
        key = crypto.X509_get_pubkey(crypto.OPENSSL_sk_value(stack, 0))
        if not key:
            raise ValueError('accessory certificate has no public key')
        length = crypto.i2d_PUBKEY(key, None)
        if not 0 < length <= 1024:
            raise ValueError('invalid accessory public key length')
        output = ctypes.create_string_buffer(length)
        pointer = ctypes.cast(output, vp)
        if crypto.i2d_PUBKEY(key, ctypes.byref(pointer)) != length:
            raise ValueError('accessory key encoding failed')
        encoded = output.raw
        key_algorithm(encoded)
        return encoded
    finally:
        if key: crypto.EVP_PKEY_free(key)
        if stack:
            for index in range(crypto.OPENSSL_sk_num(stack)):
                crypto.X509_free(crypto.OPENSSL_sk_value(stack, index))
            crypto.OPENSSL_sk_free(stack)
        crypto.CMS_ContentInfo_free(cms)


def paired_accessory(certificate, path, fallback=None):
    """First-use pin for a paired device; persist only after challenge proof.

    This proves key possession, not trust in an Apple CA. Existing pins are
    immutable: a changed certificate fails begin() rather than being relearned.
    """
    if os.path.exists(path):
        return PinnedAccessory(path)
    digest = hashlib.sha256(certificate).hexdigest()
    if fallback and hmac.compare_digest(digest, fallback.certificate_hash):
        return fallback
    key = certificate_key(certificate)
    pin = {'algorithm': key_algorithm(key), 'certificate_sha256': digest,
           'public_key_der': base64.b64encode(key).decode('ascii')}
    authenticator = PinnedAccessory(pin=pin)
    authenticator.pending_pin = (path, pin)
    return authenticator
