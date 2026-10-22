"""Pinned-accessory challenge verification using the system OpenSSL library.

The pin binds a previously observed certificate to an offline extracted public
key. This proves key possession for that accessory, not an Apple CA chain.
No private key is loaded. Challenges are already digests: SHA256 for MFi v3
P-256, and SHA1 for the legacy MFi v2 RSA/PKCS#1 v1.5 path.
"""
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import json
import os


def _crypto():
    library = ctypes.util.find_library('crypto')
    if not library:
        raise OSError('system libcrypto not found')
    crypto = ctypes.CDLL(library)
    vp, size = ctypes.c_void_p, ctypes.c_size_t
    functions = {
        'd2i_PUBKEY': ([ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.c_long], vp),
        'i2d_PUBKEY': ([vp, ctypes.POINTER(vp)], ctypes.c_int),
        'EVP_PKEY_free': ([vp], None), 'EVP_PKEY_CTX_new': ([vp, vp], vp),
        'EVP_PKEY_CTX_free': ([vp], None), 'EVP_PKEY_verify_init': ([vp], ctypes.c_int),
        'EVP_PKEY_CTX_set_signature_md': ([vp, vp], ctypes.c_int),
        'EVP_PKEY_CTX_set_rsa_padding': ([vp, ctypes.c_int], ctypes.c_int),
        'EVP_PKEY_verify': ([vp, vp, size, vp, size], ctypes.c_int),
        'EVP_sha256': ([], vp), 'EVP_sha1': ([], vp),
        'OBJ_txt2nid': ([ctypes.c_char_p], ctypes.c_int),
        'OBJ_nid2sn': ([ctypes.c_int], ctypes.c_char_p),
        'EVP_PKEY_get1_EC_KEY': ([vp], vp), 'EC_KEY_get0_group': ([vp], vp),
        'EC_KEY_free': ([vp], None), 'EC_GROUP_new_by_curve_name': ([ctypes.c_int], vp),
        'EC_GROUP_get_curve_name': ([vp], ctypes.c_int),
        'EC_GROUP_cmp': ([vp, vp, vp], ctypes.c_int), 'EC_GROUP_free': ([vp], None),
        'd2i_CMS_ContentInfo': ([vp, ctypes.POINTER(vp), ctypes.c_long], vp),
        'CMS_get1_certs': ([vp], vp), 'CMS_ContentInfo_free': ([vp], None),
        'OPENSSL_sk_num': ([vp], ctypes.c_int), 'OPENSSL_sk_value': ([vp, ctypes.c_int], vp),
        'OPENSSL_sk_free': ([vp], None), 'X509_free': ([vp], None),
        'X509_get_pubkey': ([vp], vp), 'X509_get_signature_nid': ([vp], ctypes.c_int),
    }
    for name, (arguments, result) in functions.items():
        function = getattr(crypto, name)
        function.argtypes, function.restype = arguments, result
    # These APIs changed their exported names in OpenSSL 3.0.
    for alias, names in (('key_id', ('EVP_PKEY_get_base_id', 'EVP_PKEY_base_id')),
                         ('key_bits', ('EVP_PKEY_get_bits', 'EVP_PKEY_bits'))):
        function = next((getattr(crypto, name) for name in names if hasattr(crypto, name)), None)
        if function is None:
            raise OSError('OpenSSL key inspection API unavailable')
        function.argtypes, function.restype = [vp], ctypes.c_int
        setattr(crypto, alias, function)
    return crypto


def _key_profile(crypto, key):
    kind, bits = crypto.key_id(key), crypto.key_bits(key)
    name = (crypto.OBJ_nid2sn(kind) or b'unknown').decode('ascii', errors='replace')
    if kind == crypto.OBJ_txt2nid(b'id-ecPublicKey'):
        ec_key = crypto.EVP_PKEY_get1_EC_KEY(key)
        reference = crypto.EC_GROUP_new_by_curve_name(crypto.OBJ_txt2nid(b'prime256v1'))
        try:
            group = crypto.EC_KEY_get0_group(ec_key) if ec_key else None
            if not group or not reference:
                raise ValueError('could not inspect accessory EC parameters')
            curve = (crypto.OBJ_nid2sn(crypto.EC_GROUP_get_curve_name(group))
                     or b'explicit parameters').decode('ascii', errors='replace')
            # Compare the actual domain parameters, not SPKI bytes or bit count.
            # Compressed points and explicit P-256 parameters are valid too.
            if bits != 256 or crypto.EC_GROUP_cmp(group, reference, None) != 0:
                raise ValueError('unsupported accessory EC curve: {} ({} bits); expected P-256'.format(curve, bits))
        finally:
            if reference: crypto.EC_GROUP_free(reference)
            if ec_key: crypto.EC_KEY_free(ec_key)
        return dict(algorithm='ecdsa-p256-sha256', key_type='EC', key_bits=bits,
                    curve='prime256v1', challenge_bytes=32, signature_bytes=64)
    if kind == crypto.OBJ_txt2nid(b'rsaEncryption') and 1024 <= bits <= 4096:
        return dict(algorithm='rsa-pkcs1v15-sha1', key_type='RSA', key_bits=bits,
                    challenge_bytes=20, signature_bytes=(bits + 7) // 8)
    raise ValueError('unsupported accessory public key: {} ({} bits)'.format(name, bits))


def _decode_key(crypto, encoded):
    if not encoded or len(encoded) > 1024:
        raise ValueError('invalid accessory public key length')
    buffer = ctypes.create_string_buffer(encoded)
    cursor = ctypes.cast(buffer, ctypes.c_void_p)
    key = crypto.d2i_PUBKEY(None, ctypes.byref(cursor), len(encoded))
    if not key:
        raise ValueError('invalid pinned public key')
    if cursor.value != ctypes.addressof(buffer) + len(encoded):
        crypto.EVP_PKEY_free(key)
        raise ValueError('trailing data after accessory public key')
    return key


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
        if self.algorithm not in ('ecdsa-p256-sha256', 'rsa-pkcs1v15-sha1'):
            raise ValueError('unsupported accessory key algorithm')
        self.certificate_hash = pin['certificate_sha256']
        if len(self.certificate_hash) != 64:
            raise ValueError('invalid certificate pin')
        self.public_key = base64.b64decode(pin['public_key_der'], validate=True)
        self.challenge = None
        self.crypto = _crypto()
        key = _decode_key(self.crypto, self.public_key)
        try:
            self.key_info = _key_profile(self.crypto, key)
            if self.key_info['algorithm'] != self.algorithm:
                raise ValueError('accessory pin algorithm does not match its public key')
        finally:
            self.crypto.EVP_PKEY_free(key)

    def begin(self, certificate):
        if not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), self.certificate_hash):
            raise ValueError('accessory certificate differs from the observed pin')
        self.challenge = os.urandom(self.key_info['challenge_bytes'])
        return self.challenge

    def verify(self, signature):
        if self.challenge is None:
            raise ValueError('no pending accessory challenge')
        challenge, self.challenge = self.challenge, None
        if self.algorithm == 'ecdsa-p256-sha256':
            if len(signature) == 64:
                signature = raw_ecdsa_to_der(signature)
            elif not 8 <= len(signature) <= 72 or signature[:1] != b'\x30':
                raise ValueError('invalid P256 signature encoding')
        elif len(signature) != self.key_info['signature_bytes']:
            raise ValueError('invalid RSA signature length: expected {} bytes'.format(self.key_info['signature_bytes']))
        key = _decode_key(self.crypto, self.public_key)
        context = None
        try:
            context = self.crypto.EVP_PKEY_CTX_new(key, None)
            if not context or self.crypto.EVP_PKEY_verify_init(context) <= 0:
                raise OSError('OpenSSL verifier initialization failed')
            rsa = self.algorithm == 'rsa-pkcs1v15-sha1'
            if rsa and self.crypto.EVP_PKEY_CTX_set_rsa_padding(context, 1) <= 0:  # RSA_PKCS1_PADDING
                raise OSError('OpenSSL RSA PKCS#1 v1.5 selection failed')
            digest = self.crypto.EVP_sha1() if rsa else self.crypto.EVP_sha256()
            if self.crypto.EVP_PKEY_CTX_set_signature_md(context, digest) <= 0:
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


def _certificate_material(certificate):
    """Parse one CMS accessory certificate without trusting its CA chain."""
    if not certificate or len(certificate) > 65536:
        raise ValueError('invalid accessory certificate length')
    crypto = _crypto()
    vp = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(certificate)
    cursor = ctypes.cast(buffer, vp)
    cms = crypto.d2i_CMS_ContentInfo(None, ctypes.byref(cursor), len(certificate))
    if not cms:
        raise ValueError('invalid accessory PKCS7 certificate')
    stack = key = None
    try:
        if cursor.value != ctypes.addressof(buffer) + len(certificate):
            raise ValueError('trailing data after accessory PKCS7 certificate')
        stack = crypto.CMS_get1_certs(cms)
        if not stack or crypto.OPENSSL_sk_num(stack) != 1:
            raise ValueError('expected exactly one accessory certificate')
        cert = crypto.OPENSSL_sk_value(stack, 0)
        key = crypto.X509_get_pubkey(cert)
        if not key:
            raise ValueError('accessory certificate has no public key')
        profile = _key_profile(crypto, key)
        length = crypto.i2d_PUBKEY(key, None)
        if not 0 < length <= 1024:
            raise ValueError('invalid accessory public key length')
        output = ctypes.create_string_buffer(length)
        pointer = ctypes.cast(output, vp)
        if crypto.i2d_PUBKEY(key, ctypes.byref(pointer)) != length:
            raise ValueError('accessory key encoding failed')
        encoded = output.raw
        profile.update(certificate_sha256=hashlib.sha256(certificate).hexdigest(),
                       certificate_bytes=len(certificate), public_key_bytes=len(encoded),
                       certificate_signature_algorithm=(crypto.OBJ_nid2sn(crypto.X509_get_signature_nid(cert))
                                                        or b'unknown').decode('ascii', errors='replace'))
        return encoded, profile
    finally:
        if key: crypto.EVP_PKEY_free(key)
        if stack:
            for index in range(crypto.OPENSSL_sk_num(stack)):
                crypto.X509_free(crypto.OPENSSL_sk_value(stack, index))
            crypto.OPENSSL_sk_free(stack)
        crypto.CMS_ContentInfo_free(cms)


def certificate_key(certificate):
    """Extract a supported accessory SPKI without assuming one DER layout."""
    return _certificate_material(certificate)[0]


def certificate_info(certificate):
    """Public diagnostics only; never returns private keys or creates a pin."""
    return _certificate_material(certificate)[1]


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
    encoded, profile = _certificate_material(certificate)
    pin = {'algorithm': profile['algorithm'], 'certificate_sha256': digest,
           'public_key_der': base64.b64encode(encoded).decode('ascii')}
    authenticator = PinnedAccessory(pin=pin)
    authenticator.pending_pin = (path, pin)
    return authenticator
