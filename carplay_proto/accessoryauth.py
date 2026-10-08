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
import os


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
        if pin['algorithm'] != 'ecdsa-p256-sha256':
            raise ValueError('unsupported accessory key algorithm')
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
            'EVP_sha256': ([], vp),
        }
        for name, (arguments, result) in functions.items():
            function = getattr(self.crypto, name)
            function.argtypes, function.restype = arguments, result

    def begin(self, certificate):
        if not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), self.certificate_hash):
            raise ValueError('accessory certificate differs from the observed pin')
        self.challenge = os.urandom(32)
        return self.challenge

    def verify(self, signature):
        if self.challenge is None:
            raise ValueError('no pending accessory challenge')
        challenge, self.challenge = self.challenge, None
        if len(signature) == 64:
            signature = raw_ecdsa_to_der(signature)
        elif not 8 <= len(signature) <= 72 or signature[:1] != b'\x30':
            raise ValueError('invalid P256 signature encoding')
        key_buffer = ctypes.create_string_buffer(self.public_key)
        cursor = ctypes.cast(key_buffer, ctypes.c_void_p)
        key = self.crypto.d2i_PUBKEY(None, ctypes.byref(cursor), len(self.public_key))
        if not key:
            raise ValueError('invalid pinned public key')
        context = None
        try:
            context = self.crypto.EVP_PKEY_CTX_new(key, None)
            if not context or self.crypto.EVP_PKEY_verify_init(context) <= 0:
                raise OSError('OpenSSL verifier initialization failed')
            if self.crypto.EVP_PKEY_CTX_set_signature_md(context, self.crypto.EVP_sha256()) <= 0:
                raise OSError('OpenSSL digest selection failed')
            signature_buffer = ctypes.create_string_buffer(signature)
            digest_buffer = ctypes.create_string_buffer(challenge)
            result = self.crypto.EVP_PKEY_verify(context, signature_buffer, len(signature),
                                                  digest_buffer, len(challenge))
            if result != 1:
                raise ValueError('accessory challenge signature rejected')
            if self.pending_pin:
                path, pin = self.pending_pin
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, 'w') as output:
                    json.dump(pin, output)
                self.pending_pin = None
        finally:
            if context:
                self.crypto.EVP_PKEY_CTX_free(context)
            self.crypto.EVP_PKEY_free(key)


def certificate_key(certificate):
    """Extract exactly one P256 certificate key through system libcrypto."""
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
        prefix = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d03010703420004')
        if len(encoded) != 91 or not encoded.startswith(prefix):
            raise ValueError('only P256 accessory certificates are supported')
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
    pin = {'algorithm': 'ecdsa-p256-sha256', 'certificate_sha256': digest,
           'public_key_der': base64.b64encode(certificate_key(certificate)).decode('ascii')}
    authenticator = PinnedAccessory(pin=pin)
    authenticator.pending_pin = (path, pin)
    return authenticator
