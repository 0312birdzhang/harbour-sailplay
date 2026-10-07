"""SRP-6a (RFC 5054): the AirPlay Pair-Setup authentication.

Pure integer arithmetic over ``pow()`` with no third-party dependency. The
group is a plain object carrying its own digest, so the same code runs the
SHA-512 / 3072-bit parameters CarPlay actually uses and the SHA-1 / 1024-bit
ones the RFC 5054 test vectors use. xcertplay plays the server; the
controller session below is our half of the exchange.

The byte layouts follow xcertplay's ``airplay/Srp6a.kt``: a big integer is
encoded as a minimal unsigned big-endian number (zero as one ``0x00`` byte),
``pad()`` right-aligns that into a fixed field, and every hash over the wire
numbers uses the padded form.
"""

import hashlib
import os

# RFC 5054 Appendix A. 1: 1024-bit group, generator 2.
RFC_5054_1024 = int(
    "EEAF0AB9ADB38DD69C33F80AFA8FC5E86072618775FF3C0B9EA2314C9C256576"
    "D674DF7496EA81D3383B4813D692C6E0E0D5D8E250B98BE48E495C1D6089DAD1"
    "5DC7D7B46154D6B6CE8EF4AD69B15D4982559B297BCF1885C529F566660E57EC"
    "68EDBC3C05726CC02FD4CBF4976EAA9AFD5138FE8376435B9FC61D2FC0EB06E3", 16)

# RFC 5054 Appendix A. 4: 3072-bit group, generator 5. CarPlay's group.
RFC_5054_3072 = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74"
    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F1437"
    "4FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF05"
    "98DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB"
    "9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AAAC42DAD33170D04507A33"
    "A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF12FFA06D98A0864"
    "D87602733EC86A64521F2B18177B200CBBE117577A615D6C770988C0BAD946E2"
    "08E24FA074E5AB3143DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF", 16)


def sha1(*parts):
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
    return digest.digest()


def sha256(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def sha512(*parts):
    digest = hashlib.sha512()
    for part in parts:
        digest.update(part)
    return digest.digest()


def to_bytes(value):
    """Minimal unsigned big-endian form: zero is one ``0x00`` byte."""
    if value == 0:
        return b"\x00"
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def to_bigint(data):
    return int.from_bytes(bytes(data), "big")


def pad(value, size):
    """Right-align the encoding into a fixed-width field."""
    encoded = to_bytes(value)
    if len(encoded) >= size:
        return encoded
    return b"\x00" * (size - len(encoded)) + encoded


def password_hash(group, identifier, password, salt=b""):
    """x = H(s || H(I:P)); with an empty salt x = H(I:P)."""
    inner = group.digest(_utf8(identifier) + b":" + _utf8(password))
    if salt:
        return to_bigint(group.digest(bytes(salt) + inner))
    return to_bigint(inner)


def password_verifier(group, identifier, password, salt=b""):
    """v = g^x mod n."""
    return pow(group.generator,
               password_hash(group, identifier, password, salt), group.modulus)


class Group(object):
    """One SRP-6a parameter set.

    ``digest`` comes with the group on purpose: a group whose hash does not
    match its size yields a session key no peer will derive, and mixing the
    two groups in a test should be a visible mistake.
    """

    __slots__ = ("name", "modulus", "generator", "digest", "pad_bytes",
                 "salt_bytes", "private_bytes", "multiplier",
                 "hash_modulus", "hash_generator", "hash_xor")

    def __init__(self, name, modulus, generator, digest, pad_bytes,
                 salt_bytes=16, private_bytes=32):
        self.name = name
        self.modulus = modulus
        self.generator = generator
        self.digest = digest
        self.pad_bytes = pad_bytes
        self.salt_bytes = salt_bytes
        self.private_bytes = private_bytes

        self.multiplier = to_bigint(
            digest(to_bytes(modulus), pad(generator, pad_bytes)))
        self.hash_modulus = digest(to_bytes(modulus))
        self.hash_generator = digest(to_bytes(generator))
        self.hash_xor = bytes(a ^ b for a, b in zip(self.hash_modulus,
                                                     self.hash_generator))

    def __repr__(self):
        return "Group({}, {} bit, {})".format(self.name, self.modulus.bit_length(),
                                              self.digest.__name__)


def group_rfc5054_3072():
    """RFC 5054 3072-bit MODP with SHA-512: the CarPlay pair-setup group."""
    return Group("RFC 5054 3072", RFC_5054_3072, 5, sha512, 384)


def group_rfc5054_1024():
    """RFC 5054 1024-bit MODP with SHA-1: the RFC's own test-vector group."""
    return Group("RFC 5054 1024", RFC_5054_1024, 2, sha1, 128)


def get_group(name):
    groups = {
        "rfc5054-3072-sha512": group_rfc5054_3072,
        "rfc5054-1024-sha1": group_rfc5054_1024,
    }
    if name not in groups:
        raise ValueError("unknown SRP group {!r}; know {}".format(
            name, ", ".join(sorted(groups))))
    return groups[name]()


class Result(object):
    """One verifier outcome: whether the client proved the password."""

    __slots__ = ("ok", "session_key", "server_proof")

    def __init__(self, ok, session_key=None, server_proof=None):
        self.ok = bool(ok)
        self.session_key = None if session_key is None else bytes(session_key)
        self.server_proof = (None if server_proof is None
                             else bytes(server_proof))

    def __repr__(self):
        if not self.ok:
            return "Result(failed)"
        return "Result(ok, session_key={0} bytes, server_proof={1} bytes)".format(
            len(self.session_key), len(self.server_proof))

    def __eq__(self, other):
        return (isinstance(other, Result) and self.ok == other.ok
                and self.session_key == other.session_key
                and self.server_proof == other.server_proof)

    def __ne__(self, other):
        return not self.__eq__(other)


class Srp6aSession(object):
    """The server side, mirroring xcertplay's ``Srp6a.start`` and
    ``Srp6aSession.verify``."""

    __slots__ = ("group", "identifier", "salt", "verifier", "private_exponent",
                 "public_key")

    def __init__(self, group, identifier, password, salt=None,
                 private_exponent=None):
        self.group = group
        self.identifier = _utf8(identifier)
        if salt is not None:
            salt = bytes(salt)
            if len(salt) != group.salt_bytes:
                raise ValueError("salt must be {} bytes, got {}".format(
                    group.salt_bytes, len(salt)))
        else:
            salt = os.urandom(group.salt_bytes)
        self.salt = salt
        self.verifier = password_verifier(group, self.identifier, password, salt)
        if private_exponent is None:
            private_exponent = to_bigint(
                os.urandom(group.private_bytes))
        if not private_exponent:
            raise ValueError("the server's private exponent must not be zero")
        self.private_exponent = private_exponent
        self.public_key = (group.multiplier * self.verifier
                           + pow(group.generator, private_exponent,
                                 group.modulus)) % group.modulus

    @property
    def public_key_bytes(self):
        return pad(self.public_key, self.group.pad_bytes)

    def verify(self, public_key_a, client_proof):
        """Recompute the session key and check M_A, then issue M_B."""
        group = self.group
        a = to_bigint(public_key_a)
        if a % group.modulus == 0:
            return Result(False)

        u = to_bigint(group.digest(
            pad(a, group.pad_bytes) + pad(self.public_key, group.pad_bytes)))
        base = (a * pow(self.verifier, u, group.modulus)) % group.modulus
        session_secret = pow(base, self.private_exponent, group.modulus)
        session_key = group.digest(to_bytes(session_secret))

        expected = group.digest(group.hash_xor + group.digest(self.identifier)
                                + self.salt
                                + pad(a, group.pad_bytes)
                                + pad(self.public_key, group.pad_bytes)
                                + session_key)
        if expected != bytes(client_proof):
            return Result(False)

        server_proof = group.digest(pad(a, group.pad_bytes)
                                    + bytes(client_proof) + session_key)
        return Result(True, session_key, server_proof)


class ClientSession(object):
    """The controller side: xcertplay only ships the server."""

    __slots__ = ("group", "identifier", "salt", "private_exponent", "public_key",
                 "public_key_b", "u", "session_key", "client_proof")

    def __init__(self, group, identifier, password, salt, public_key_b,
                 private_exponent=None):
        self.group = group
        self.identifier = _utf8(identifier)
        self.salt = bytes(salt)
        self.public_key_b = to_bigint(public_key_b)
        if self.public_key_b % group.modulus == 0:
            raise ValueError("B must not be zero mod n")
        if private_exponent is None:
            private_exponent = to_bigint(os.urandom(group.private_bytes))
        if not private_exponent:
            raise ValueError("the client's private exponent must not be zero")
        self.private_exponent = private_exponent
        self.public_key = pow(group.generator, private_exponent,
                              group.modulus)
        self.u = to_bigint(group.digest(pad(self.public_key, group.pad_bytes)
                                        + pad(self.public_key_b, group.pad_bytes)))
        if not self.u:
            raise ValueError("u must not be zero")
        # S = (B - k g^x)^(a + u x). The extra u x term is what makes this
        # equal the server's (A v^u)^b; using a plain a here yields a session
        # key no server will reproduce. RFC 5054 section 2.6.
        x = password_hash(group, self.identifier, password, self.salt)
        session_secret = pow(
            (self.public_key_b
             - group.multiplier * pow(group.generator, x, group.modulus))
            % group.modulus,
            private_exponent + self.u * x, group.modulus)
        self.session_key = group.digest(to_bytes(session_secret))
        self.client_proof = group.digest(
            group.hash_xor + group.digest(self.identifier) + self.salt
            + pad(self.public_key, group.pad_bytes)
            + pad(self.public_key_b, group.pad_bytes) + self.session_key)

    @property
    def public_key_bytes(self):
        return pad(self.public_key, self.group.pad_bytes)

    def verify_server_proof(self, server_proof):
        return (self.group.digest(pad(self.public_key, self.group.pad_bytes)
                                  + self.client_proof + self.session_key)
                == bytes(server_proof))


def _utf8(value):
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("expected str or bytes, got {!r}".format(type(value)))
