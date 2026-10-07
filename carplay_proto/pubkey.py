"""Curve25519 key agreement and Ed25519 signatures.

Pure stdlib, standing in for the BouncyCastle calls in xcertplay's
``AirPlayCrypto`` (``X25519PrivateKeyParameters``, ``Ed25519Signer``). The
pairing messages in ``pairverify`` and ``pairsetup`` exchange these keys over
TLV8: X25519 produces the ``shared`` secret every channel key derives from,
and Ed25519 proves a long-term identity key.

X25519 follows RFC 7748 section 5: scalars are decoded with the low three
bits of the first octet cleared, the Montgomery ladder runs over 255 bits with
``a24 = 121665``, and points are Montgomery u coordinates. Ed25519 follows
RFC 8032 section 5.1 in extended homogeneous coordinates (X, Y, Z, T) with
``x = X/Z``, ``y = Y/Z``, ``x*y = T/Z``.
"""

import os

from . import crypto


X25519_KEY_BYTES = 32
ED25519_SEED_BYTES = 32
ED25519_PUBLIC_BYTES = 32
ED25519_SIGNATURE_BYTES = 64
_X25519_BASE_POINT_U = b"\x09" + b"\x00" * (X25519_KEY_BYTES - 1)

_MONTGOMERY_P = (1 << 255) - 19
_A24 = 121665
_SCALAR_MASK = (1 << 255) - 1


def _modinv(value, modulus):
    """Modular inverse by Fermat's little theorem (RFC 8032 section 5.1.1)."""
    return pow(value, modulus - 2, modulus)


_ED25519_P = _MONTGOMERY_P
_ED25519_Q = (1 << 252) + 27742317777372353535851937790883648493
_ED25519_D = (-121665 * _modinv(121666, _ED25519_P)) % _ED25519_P
_ED25519_SQRT_MINUS_ONE = pow(2, (_ED25519_P - 1) // 4, _ED25519_P)
_ED25519_INFINITE = (0, 1, 1, 0)
_ED25519_BASE_POINT_X = 0x216936d3cd6e53fec0a4e231fdd6dc5c692cc7609525a7b2c9562d608f25d51a
_ED25519_BASE_POINT_Y = 0x6666666666666666666666666666666666666666666666666666666666666658
_ED25519_BASE_POINT = (
    _ED25519_BASE_POINT_X, _ED25519_BASE_POINT_Y, 1,
    _ED25519_BASE_POINT_X * _ED25519_BASE_POINT_Y % _ED25519_P)


class KeyPair(object):
    """A secret or seed alongside its derived public key."""

    __slots__ = ("secret", "public")

    def __init__(self, secret, public):
        self.secret = bytes(secret)
        self.public = bytes(public)

    def __repr__(self):
        return "KeyPair({}, {})".format(
            hexlify(self.secret), hexlify(self.public))

    def __eq__(self, other):
        return (isinstance(other, KeyPair)
                and self.secret == other.secret
                and self.public == other.public)

    def __ne__(self, other):
        return not self.__eq__(other)


def hexlify(data):
    return " ".join("{:02x}".format(byte) for byte in data)


def x25519_generate():
    """A random X25519 key pair, with the scalar clamped as RFC 7748
    section 5.3 requires."""
    secret = clamp_scalar(os.urandom(X25519_KEY_BYTES))
    return KeyPair(secret, x25519_public(secret))


def x25519_public(secret):
    """The Montgomery u coordinate for a 32-byte scalar."""
    _check_x25519_key(secret, "x25519 secret")
    return scalar_mult(secret, _X25519_BASE_POINT_U)


def x25519_shared(secret, peer_public):
    """The shared secret, the same on both sides of an exchange."""
    _check_x25519_key(secret, "x25519 secret")
    _check_x25519_key(peer_public, "x25519 public")
    return scalar_mult(secret, peer_public)


def ed25519_generate():
    """A random Ed25519 seed and the public key derived from it."""
    seed = os.urandom(ED25519_SEED_BYTES)
    return ed25519_from_seed(seed)


def ed25519_from_seed(seed):
    """The public key for an Ed25519 seed."""
    _check_ed25519_seed(seed)
    return KeyPair(bytes(seed), ed25519_public(seed))


def ed25519_public(seed):
    """The compressed encoding of ``[s]B`` for the seed's scalar (RFC 8032
    section 5.1.5)."""
    _check_ed25519_seed(seed)
    return point_encode(point_mult(ed25519_scalar(seed), _ED25519_BASE_POINT))


def ed25519_scalar(seed):
    """The secret scalar: SHA-512(seed) pruned as RFC 8032 section 5.1.5
    steps 1 to 3 describe."""
    digest = crypto.sha512(seed)
    pruned = bytearray(digest[:ED25519_SEED_BYTES])
    pruned[0] &= 248
    pruned[ED25519_SEED_BYTES - 1] &= 127
    pruned[ED25519_SEED_BYTES - 1] |= 64
    return int.from_bytes(pruned, "little")


def ed25519_sign(seed, data):
    """Sign ``data`` with an Ed25519 seed (RFC 8032 section 5.1.6)."""
    _check_ed25519_seed(seed)
    data = bytes(data)
    digest = crypto.sha512(seed)
    scalar = ed25519_scalar(seed)
    prefix = digest[ED25519_SEED_BYTES:]
    public = point_encode(point_mult(scalar, _ED25519_BASE_POINT))

    r = int.from_bytes(crypto.sha512(prefix + data), "little") % _ED25519_Q
    point_r = point_encode(point_mult(r, _ED25519_BASE_POINT))
    k = int.from_bytes(crypto.sha512(point_r + public + data), "little") % _ED25519_Q
    s = (r + k * scalar) % _ED25519_Q

    return point_r + s.to_bytes(ED25519_PUBLIC_BYTES, "little")


def ed25519_verify(public, data, signature):
    """Return True only for a valid signature.

    Never raises for malformed input: the reference treats a bad decode as an
    invalid signature, and the pairing flow must report authentication
    failure rather than crash the session.
    """
    if len(public) != ED25519_PUBLIC_BYTES:
        return False
    if len(signature) != ED25519_SIGNATURE_BYTES:
        return False

    data = bytes(data)
    point_r_encoded = signature[:ED25519_PUBLIC_BYTES]
    s = int.from_bytes(signature[ED25519_PUBLIC_BYTES:], "little")
    if s >= _ED25519_Q:
        return False

    point_r = point_decode(point_r_encoded)
    point_a = point_decode(public)
    if point_r is None or point_a is None:
        return False

    k = int.from_bytes(
        crypto.sha512(point_r_encoded + public + data), "little") % _ED25519_Q
    return point_equal(
        point_mult(s, _ED25519_BASE_POINT),
        point_add(point_r, point_mult(k, point_a)))


def point_encode(point):
    """Extended coordinates as the 32-byte compressed encoding (RFC 8032
    section 5.1.2)."""
    x, y, z, t = point
    inverse_z = _modinv(z, _ED25519_P)
    affine_y = y * inverse_z % _ED25519_P
    affine_x = x * inverse_z % _ED25519_P
    return (affine_y | ((affine_x & 1) << 255)).to_bytes(
        ED25519_PUBLIC_BYTES, "little")


def point_decode(data):
    """32 bytes as extended coordinates, or None if it is not on the curve
    (RFC 8032 section 5.1.3)."""
    if len(data) != ED25519_PUBLIC_BYTES:
        return None

    encoded = int.from_bytes(data, "little")
    x_sign = encoded >> 255
    y = encoded & _SCALAR_MASK
    if y >= _ED25519_P:
        return None

    numerator = (y * y - 1) % _ED25519_P
    denominator = (_ED25519_D * y * y + 1) % _ED25519_P
    x = (numerator * pow(denominator, 3, _ED25519_P)) % _ED25519_P
    x = (x * pow(numerator * pow(denominator, 7, _ED25519_P) % _ED25519_P,
                  (_ED25519_P - 5) // 8, _ED25519_P)) % _ED25519_P

    x_squared = denominator * x * x % _ED25519_P
    if x_squared == numerator:
        pass
    elif (x_squared + numerator) % _ED25519_P == 0:
        x = x * _ED25519_SQRT_MINUS_ONE % _ED25519_P
    else:
        return None

    if x == 0 and x_sign == 1:
        return None
    if x_sign != x % 2:
        x = _ED25519_P - x

    return x, y, 1, x * y % _ED25519_P


def point_add(left, right):
    """Point addition (RFC 8032 section 5.1.4, complete formulas)."""
    x_1, y_1, z_1, t_1 = left
    x_2, y_2, z_2, t_2 = right
    a = (y_1 - x_1) * (y_2 - x_2) % _ED25519_P
    b = (y_1 + x_1) * (y_2 + x_2) % _ED25519_P
    c = 2 * t_1 * _ED25519_D * t_2 % _ED25519_P
    d = 2 * z_1 * z_2 % _ED25519_P
    e = (b - a) % _ED25519_P
    f = (d - c) % _ED25519_P
    g = (d + c) % _ED25519_P
    h = (b + a) % _ED25519_P
    return (e * f % _ED25519_P, g * h % _ED25519_P,
            f * g % _ED25519_P, e * h % _ED25519_P)


def point_double(point):
    """Point doubling (RFC 8032 section 5.1.4, EFD-TWISTED-DBL)."""
    x, y, z, t = point
    a = x * x % _ED25519_P
    b = y * y % _ED25519_P
    c = 2 * z * z % _ED25519_P
    h = (a + b) % _ED25519_P
    e = (h - (x + y) * (x + y)) % _ED25519_P
    g = (a - b) % _ED25519_P
    f = (c + g) % _ED25519_P
    return (e * f % _ED25519_P, g * h % _ED25519_P,
            f * g % _ED25519_P, e * h % _ED25519_P)


def point_mult(scalar, point):
    """Double-and-add over the base group (RFC 8032 section 5.1.6 step 3)."""
    scalar %= _ED25519_Q
    result = _ED25519_INFINITE
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_double(point)
        scalar >>= 1
    return result


def point_equal(left, right):
    """Compare in affine coordinates, so differing scalars still match."""
    x_1, y_1, z_1, t_1 = left
    x_2, y_2, z_2, t_2 = right
    if (x_1 * z_2 - x_2 * z_1) % _ED25519_P:
        return False
    return (y_1 * z_2 - y_2 * z_1) % _ED25519_P == 0


def scalar_mult(scalar, u):
    """X25519(k, u) as RFC 7748 section 5.3 defines it: a 32-byte scalar and
    a 32-byte u-coordinate in, the 32-byte u-coordinate of the product out
    (Algorithm 2, with the scalar decoded per section 5.3)."""
    _check_x25519_key(scalar, "x25519 scalar")
    scalar = int.from_bytes(clamp_scalar(scalar), "little")
    _check_x25519_key(u, "x25519 u-coordinate")
    u = int.from_bytes(u, "little") % _MONTGOMERY_P

    x_1, x_2, z_2, x_3, z_3 = u, 1, 0, u, 1
    swap = 0

    for bit in range(254, -1, -1):
        k_t = (scalar >> bit) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t

        a = (x_2 + z_2) % _MONTGOMERY_P
        aa = a * a % _MONTGOMERY_P
        b = (x_2 - z_2) % _MONTGOMERY_P
        bb = b * b % _MONTGOMERY_P
        e = (aa - bb) % _MONTGOMERY_P
        c = (x_3 + z_3) % _MONTGOMERY_P
        d = (x_3 - z_3) % _MONTGOMERY_P
        da = d * a % _MONTGOMERY_P
        cb = c * b % _MONTGOMERY_P
        da_plus_cb = (da + cb) % _MONTGOMERY_P
        da_minus_cb = (da - cb) % _MONTGOMERY_P

        x_3 = da_plus_cb * da_plus_cb % _MONTGOMERY_P
        z_3 = x_1 * (da_minus_cb * da_minus_cb % _MONTGOMERY_P) % _MONTGOMERY_P
        x_2 = aa * bb % _MONTGOMERY_P
        z_2 = e * ((aa + _A24 * e) % _MONTGOMERY_P) % _MONTGOMERY_P

    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2

    result = x_2 * _modinv(z_2, _MONTGOMERY_P) % _MONTGOMERY_P
    return result.to_bytes(X25519_KEY_BYTES, "little")


def clamp_scalar(secret):
    """Decode a 32-byte X25519 scalar (RFC 7748 section 5.3)."""
    clamped = bytearray(secret)
    clamped[0] &= 248
    clamped[ED25519_SEED_BYTES - 1] &= 127
    clamped[ED25519_SEED_BYTES - 1] |= 64
    return bytes(clamped)


def _check_x25519_key(key, label):
    if len(key) != X25519_KEY_BYTES:
        raise crypto.CryptoError(
            "{} must be {} bytes, got {}".format(label, X25519_KEY_BYTES, len(key)))


def _check_ed25519_seed(seed):
    if len(seed) != ED25519_SEED_BYTES:
        raise crypto.CryptoError(
            "ed25519 seed must be {} bytes, got {}".format(
                ED25519_SEED_BYTES, len(seed)))
