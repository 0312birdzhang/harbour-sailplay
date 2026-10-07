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
    def __init__(self, filename):
        with open(filename) as source:
            pin = json.load(source)
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
        finally:
            if context:
                self.crypto.EVP_PKEY_CTX_free(context)
            self.crypto.EVP_PKEY_free(key)
