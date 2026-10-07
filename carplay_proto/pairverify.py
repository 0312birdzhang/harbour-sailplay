"""Pair-Verify: the CarPlay identity exchange.

Each peer generates an ephemeral X25519 key pair and sends it in the first two
messages, seals everything else with a key derived from the resulting shared
secret, and proves it owns the long-term Ed25519 key the other peer stored
during PairSetup. Once both signatures check out the shared secret yields the
two control-channel keys.

The controller opens the exchange by posting to ``/pair-verify``; xcertplay
plays the accessory, which answers m2 and m4. Every byte layout, label and
nonce here follows xcertplay's ``airplay/PairVerify.kt``, ``AirPlayCrypto.kt``
and ``Tlv8Codec.kt``.
"""

from . import crypto
from . import pubkey
from . import tlv8


ROLE_CONTROLLER = "controller"
ROLE_ACCESSORY = "accessory"

STATE_M1 = 1
STATE_M2 = 2
STATE_M3 = 3
STATE_M4 = 4

VERIFY_ENCRYPT_SALT = b"Pair-Verify-Encrypt-Salt"
VERIFY_ENCRYPT_INFO = b"Pair-Verify-Encrypt-Info"
CONTROL_SALT = b"Control-Salt"
CONTROL_READ_KEY_INFO = b"Control-Read-Encryption-Key"
CONTROL_WRITE_KEY_INFO = b"Control-Write-Encryption-Key"

# The nonce label names the message being sent, not the sender.
MSG02_NONCE_LABEL = "PV-Msg02"
MSG03_NONCE_LABEL = "PV-Msg03"

_ROLES = (ROLE_CONTROLLER, ROLE_ACCESSORY)


class PairVerifyError(ValueError):
    """A Pair-Verify message cannot be accepted."""


class ControlKeys(object):
    """The two control-channel keys, held by direction."""

    __slots__ = ("read_key", "write_key")

    def __init__(self, read_key, write_key):
        self.read_key = bytes(read_key)
        self.write_key = bytes(write_key)

    def __repr__(self):
        return "ControlKeys({} bytes)".format(len(self.read_key))

    def __eq__(self, other):
        return (isinstance(other, ControlKeys)
                and self.read_key == other.read_key
                and self.write_key == other.write_key)

    def __ne__(self, other):
        return not self.__eq__(other)


def verify_nonce(label):
    """The 12-byte AEAD nonce for a pairing message."""
    return crypto.nonce_label(label)


def verify_encryption_key(shared):
    """The key that seals and opens the pairing messages."""
    return crypto.hkdf_sha512(
        shared, VERIFY_ENCRYPT_SALT, VERIFY_ENCRYPT_INFO, crypto.KEY_BYTES)


def derive_control_keys(shared, role=ROLE_CONTROLLER):
    """The control-channel keys for a shared secret.

    The labels name the direction from the controller's side, so the
    controller reads with ``Control-Read-Encryption-Key`` and the accessory
    uses the same two keys in reverse: it reads with the key the controller
    writes, and writes with the key the controller reads. xcertplay plays the
    accessory and does exactly that in ``PairVerify.m4``. If a real head unit
    turns out to derive them the controller way, flip ``role``.
    """
    read_key = crypto.hkdf_sha512(
        shared, CONTROL_SALT, CONTROL_READ_KEY_INFO, crypto.KEY_BYTES)
    write_key = crypto.hkdf_sha512(
        shared, CONTROL_SALT, CONTROL_WRITE_KEY_INFO, crypto.KEY_BYTES)
    if role == ROLE_ACCESSORY:
        read_key, write_key = write_key, read_key
    return ControlKeys(read_key, write_key)


def signature_data(own_ephemeral_public_key, own_pairing_id,
                   peer_ephemeral_public_key):
    """What each peer signs: its own ephemeral key, its own id, the peer's
    ephemeral key."""
    return (bytes(own_ephemeral_public_key) + _utf8(own_pairing_id)
            + bytes(peer_ephemeral_public_key))


def error_message(state):
    """The pairing error reply: the state received, plus the error code."""
    return tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([(state or 0) & 0xff])),
        tlv8.Item(tlv8.TYPE_ERROR, bytes([tlv8.ERROR_AUTHENTICATION])),
    ])


class PairVerify(object):
    """One Pair-Verify exchange from one peer's point of view.

    ``pairing_id`` and ``identity_private_key`` are ours. The other peer's
    long-term public key comes from whatever PairSetup stored, and is only
    needed to check its signature.
    """

    def __init__(self, role, pairing_id, identity_private_key,
                 peer_long_term_public_key=None):
        if role not in _ROLES:
            raise ValueError(
                "role must be {} or {}, got {!r}".format(
                    ROLE_CONTROLLER, ROLE_ACCESSORY, role))

        self.role = role
        self.pairing_id = _utf8(pairing_id)
        self.identity_private_key = bytes(identity_private_key)
        self.peer_long_term_public_key = (
            None if peer_long_term_public_key is None
            else bytes(peer_long_term_public_key))

        self._ephemeral = pubkey.x25519_generate()
        self._peer_ephemeral_public_key = None
        self._shared = None
        self._encryption_key = None
        self.peer_id = None
        self.control_keys = None
        self.verified = False

    @property
    def ephemeral_public_key(self):
        return self._ephemeral.public

    @property
    def long_term_public_key(self):
        """The Ed25519 key pairsetup stores on the other peer."""
        return pubkey.ed25519_public(self.identity_private_key)

    @property
    def peer_ephemeral_public_key(self):
        return self._peer_ephemeral_public_key

    @property
    def shared(self):
        return self._shared

    @property
    def encryption_key(self):
        return self._encryption_key

    def set_peer_key(self, peer_long_term_public_key):
        """The other peer's long-term public key, as PairSetup stored it."""
        self.peer_long_term_public_key = bytes(peer_long_term_public_key)

    @property
    def is_verified(self):
        return self.verified

    def begin(self):
        """m1: the controller's opening message. The accessory does not send
        one, it answers the controller's."""
        if self.role != ROLE_CONTROLLER:
            raise PairVerifyError("the accessory does not open Pair-Verify")
        return self.m1()

    def m1(self):
        """m1: our ephemeral public key."""
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M1])),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self.ephemeral_public_key),
        ])

    def handle(self, body):
        """Reply to one inbound message.

        Returns the reply bytes, or None when nothing is due in answer. A
        message that cannot be accepted yields the pairing error reply rather
        than raising, so a bad peer never kills the session.
        """
        try:
            items = tlv8.decode(body)
            state = _state_of(items)
            return self._handle_state(items, state)
        except (PairVerifyError, crypto.AuthenticationError):
            return error_message(_state_of(tlv8.decode(body)))

    def _handle_state(self, items, state):
        if self.role == ROLE_CONTROLLER:
            if state == STATE_M2:
                return self._controller_handle_m2(items)
            if state == STATE_M4:
                self._controller_handle_m4()
                return None
        else:
            if state == STATE_M1:
                return self._accessory_handle_m1(items)
            if state == STATE_M3:
                return self._accessory_handle_m3(items)

        raise PairVerifyError(
            "state {} is not expected from the {} side".format(state, self.role))

    def _controller_handle_m2(self, items):
        """Check the accessory's signature, then answer with m3."""
        _require_peer_key(self.peer_long_term_public_key)
        encrypted = _require(items, tlv8.TYPE_ENCRYPTED_DATA, "m2")

        self._peer_ephemeral_public_key = _require(
            items, tlv8.TYPE_PUBLIC_KEY, "m2")
        self._shared = pubkey.x25519_shared(
            self._ephemeral.secret, self._peer_ephemeral_public_key)
        self._encryption_key = verify_encryption_key(self._shared)

        sub = tlv8.decode(crypto.chacha_open(
            self._encryption_key, verify_nonce(MSG02_NONCE_LABEL),
            bytes(encrypted)))
        peer_id = _require(sub, tlv8.TYPE_IDENTIFIER, "the m2 payload")
        peer_signature = _require(sub, tlv8.TYPE_SIGNATURE, "the m2 payload")

        signature_data_ = signature_data(
            self._peer_ephemeral_public_key, peer_id,
            self.ephemeral_public_key)
        _check_signature(self.peer_long_term_public_key, signature_data_,
                         peer_signature, "the accessory")

        self.peer_id = bytes(peer_id)
        self.control_keys = derive_control_keys(self._shared, self.role)
        self.verified = True
        return self.m3()

    def m3(self):
        """m3: our identifier and signature, sealed."""
        self._require_session("m3")
        signature = pubkey.ed25519_sign(
            self.identity_private_key,
            signature_data(self.ephemeral_public_key, self.pairing_id,
                           self._peer_ephemeral_public_key))
        sub = tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, self.pairing_id),
            tlv8.Item(tlv8.TYPE_SIGNATURE, signature),
        ])
        sealed = crypto.chacha_seal(
            self._encryption_key, verify_nonce(MSG03_NONCE_LABEL), sub)
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M3])),
            tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
        ])

    def _controller_handle_m4(self):
        if not self.verified:
            raise PairVerifyError("m4 before m2")

    def _accessory_handle_m1(self, items):
        """m1 from the controller: answer with m2."""
        self._peer_ephemeral_public_key = _require(
            items, tlv8.TYPE_PUBLIC_KEY, "m1")
        self._shared = pubkey.x25519_shared(
            self._ephemeral.secret, self._peer_ephemeral_public_key)
        self._encryption_key = verify_encryption_key(self._shared)

        signature = pubkey.ed25519_sign(
            self.identity_private_key,
            signature_data(self.ephemeral_public_key, self.pairing_id,
                           self._peer_ephemeral_public_key))
        sub = tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, self.pairing_id),
            tlv8.Item(tlv8.TYPE_SIGNATURE, signature),
        ])
        sealed = crypto.chacha_seal(
            self._encryption_key, verify_nonce(MSG02_NONCE_LABEL), sub)
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M2])),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self.ephemeral_public_key),
            tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
        ])

    def _accessory_handle_m3(self, items):
        """m3 from the controller: check its signature, then answer with m4."""
        self._require_session("m3")
        _require_peer_key(self.peer_long_term_public_key)
        encrypted = _require(items, tlv8.TYPE_ENCRYPTED_DATA, "m3")

        sub = tlv8.decode(crypto.chacha_open(
            self._encryption_key, verify_nonce(MSG03_NONCE_LABEL),
            bytes(encrypted)))
        peer_id = _require(sub, tlv8.TYPE_IDENTIFIER, "the m3 payload")
        peer_signature = _require(sub, tlv8.TYPE_SIGNATURE, "the m3 payload")

        signature_data_ = signature_data(
            self._peer_ephemeral_public_key, peer_id,
            self.ephemeral_public_key)
        _check_signature(self.peer_long_term_public_key, signature_data_,
                         peer_signature, "the controller")

        self.peer_id = bytes(peer_id)
        self.control_keys = derive_control_keys(self._shared, self.role)
        self.verified = True
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M4])),
        ])

    def _require_session(self, message):
        """The ephemeral exchange must already be done before m3 or m4."""
        if self._peer_ephemeral_public_key is None or self._shared is None \
                or self._encryption_key is None:
            raise PairVerifyError(
                "{} needs the ephemeral exchange first".format(message))


def _state_of(items):
    state = items.get(tlv8.TYPE_STATE)
    if not state:
        return 0
    return state[0] & 0xff


def _require(items, type_, label):
    value = items.get(type_)
    if value is None:
        raise PairVerifyError("{} needs type 0x{:02x}".format(label, type_))
    return bytes(value)


def _require_peer_key(peer_long_term_public_key):
    if peer_long_term_public_key is None:
        raise PairVerifyError("the peer's stored long-term key is missing")


def _check_signature(peer_long_term_public_key, data, signature, who):
    if not pubkey.ed25519_verify(peer_long_term_public_key, data, bytes(signature)):
        raise crypto.AuthenticationError(
            "signature does not match {}'s stored key".format(who))


def _utf8(value):
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("pairing id must be str or bytes, got {!r}".format(type(value)))
