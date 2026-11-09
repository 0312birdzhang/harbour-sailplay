"""Generate an installation-local TLS identity using the existing libcrypto."""
import ctypes
import ctypes.util
import os


def create_identity():
    library = ctypes.util.find_library('crypto')
    if not library:
        raise RuntimeError('OpenSSL libcrypto is unavailable')
    lib = ctypes.CDLL(library)
    pointer = ctypes.c_void_p
    signatures = {
        'BN_new': ([], pointer), 'BN_set_word': ([pointer, ctypes.c_ulong], ctypes.c_int),
        'BN_free': ([pointer], None), 'RSA_new': ([], pointer), 'RSA_free': ([pointer], None),
        'RSA_generate_key_ex': ([pointer, ctypes.c_int, pointer, pointer], ctypes.c_int),
        'EVP_PKEY_new': ([], pointer), 'EVP_PKEY_free': ([pointer], None),
        'EVP_PKEY_set1_RSA': ([pointer, pointer], ctypes.c_int),
        'EVP_sha256': ([], pointer), 'X509_new': ([], pointer), 'X509_free': ([pointer], None),
        'X509_set_version': ([pointer, ctypes.c_long], ctypes.c_int),
        'X509_get_serialNumber': ([pointer], pointer),
        'ASN1_INTEGER_set': ([pointer, ctypes.c_long], ctypes.c_int),
        'X509_getm_notBefore': ([pointer], pointer), 'X509_getm_notAfter': ([pointer], pointer),
        'X509_gmtime_adj': ([pointer, ctypes.c_long], pointer),
        'X509_set_pubkey': ([pointer, pointer], ctypes.c_int),
        'X509_get_subject_name': ([pointer], pointer),
        'X509_NAME_add_entry_by_txt': ([pointer, ctypes.c_char_p, ctypes.c_int,
                                      ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        'X509_set_issuer_name': ([pointer, pointer], ctypes.c_int),
        'X509_sign': ([pointer, pointer, pointer], ctypes.c_int),
        'BIO_s_mem': ([], pointer), 'BIO_new': ([pointer], pointer), 'BIO_free': ([pointer], ctypes.c_int),
        'BIO_ctrl_pending': ([pointer], ctypes.c_size_t),
        'BIO_read': ([pointer, pointer, ctypes.c_int], ctypes.c_int),
        'PEM_write_bio_PrivateKey': ([pointer, pointer, pointer, pointer, ctypes.c_int, pointer, pointer], ctypes.c_int),
        'PEM_write_bio_X509': ([pointer, pointer], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result

    def checked(value):
        if not value:
            raise RuntimeError('OpenSSL TLS identity generation failed')
        return value

    exponent = rsa_key = key = certificate = None
    try:
        exponent = checked(lib.BN_new())
        checked(lib.BN_set_word(exponent, 65537))
        rsa_key = checked(lib.RSA_new())
        checked(lib.RSA_generate_key_ex(rsa_key, 2048, exponent, None))
        key = checked(lib.EVP_PKEY_new())
        checked(lib.EVP_PKEY_set1_RSA(key, rsa_key))
        certificate = checked(lib.X509_new())
        checked(lib.X509_set_version(certificate, 2))
        # Keep the serial representable by c_long on 32-bit Sailfish as well.
        serial = int.from_bytes(os.urandom(3), 'big') or 1
        checked(lib.ASN1_INTEGER_set(lib.X509_get_serialNumber(certificate), serial))
        checked(lib.X509_gmtime_adj(lib.X509_getm_notBefore(certificate), -3600))
        checked(lib.X509_gmtime_adj(lib.X509_getm_notAfter(certificate), 3650 * 86400))
        checked(lib.X509_set_pubkey(certificate, key))
        subject = checked(lib.X509_get_subject_name(certificate))
        checked(lib.X509_NAME_add_entry_by_txt(subject, b'CN', 0x1001, b'Sailplay Android Auto', -1, -1, 0))
        checked(lib.X509_set_issuer_name(certificate, subject))
        checked(lib.X509_sign(certificate, key, lib.EVP_sha256()))

        def pem(writer):
            bio = checked(lib.BIO_new(lib.BIO_s_mem()))
            try:
                checked(writer(bio))
                size = lib.BIO_ctrl_pending(bio)
                if not 0 < size <= 65536:
                    raise RuntimeError('OpenSSL TLS identity PEM size is invalid')
                buffer = ctypes.create_string_buffer(size)
                if lib.BIO_read(bio, buffer, size) != size:
                    raise RuntimeError('OpenSSL TLS identity PEM export failed')
                return buffer.raw
            finally:
                lib.BIO_free(bio)

        private_pem = pem(lambda bio: lib.PEM_write_bio_PrivateKey(bio, key, None, None, 0, None, None))
        certificate_pem = pem(lambda bio: lib.PEM_write_bio_X509(bio, certificate))
        return certificate_pem, private_pem
    finally:
        for value, free in ((certificate, lib.X509_free), (key, lib.EVP_PKEY_free),
                            (rsa_key, lib.RSA_free), (exponent, lib.BN_free)):
            if value:
                free(value)
