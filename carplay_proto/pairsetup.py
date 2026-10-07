"""Pair-Setup: the CarPlay pairing exchange.

The two peers run SRP-6a over the fixed username ``Pair-Setup`` and setup code
``3939``, then use the resulting session key to seal an exchange of their
long-term Ed25519 keys. Each side signs ``signKey || itsId || itsPublicKey``
with a key derived from the session key under a label named after its role, so
the signature is what binds the identifier to the key.

The controller opens the exchange; xcertplay plays the accessory and answers
m2, m4 and m6. Every byte layout, label and nonce here follows xcertplay's
``airplay/PairSetup.kt``, ``Srp6a.kt`` and ``Tlv8Codec.kt``.
"""

from . import crypto
from . import pubkey
from . import srp6a
from . import tlv8


ROLE_CONTROLLER = "controller"
ROLE_ACCESSORY = "accessory"

STATE_M1 = 1
STATE_M2 = 2
STATE_M3 = 3
STATE_M4 = 4
STATE_M5 = 5
STATE_M6 = 6

METHOD_PAIR_SETUP = b"Pair-Setup"

SETUP_USERNAME = b"Pair-Setup"
SETUP_CODE = b"3939"

SETUP_GROUP_NAME = "rfc5054-3072-sha512"

ENCRYPT_SALT = b"Pair-Setup-Encrypt-Salt"
ENCRYPT_INFO = b"Pair-Setup-Encrypt-Info"
CONTROLLER_SIGN_SALT = b"Pair-Setup-Controller-Sign-Salt"
CONTROLLER_SIGN_INFO = b"Pair-Setup-Controller-Sign-Info"
ACCESSORY_SIGN_SALT = b"Pair-Setup-Accessory-Sign-Salt"
ACCESSORY_SIGN_INFO = b"Pair-Setup-Accessory-Sign-Info"

# The nonce label names the message being sent, not the sender.
MSG05_NONCE_LABEL = "PS-Msg05"
MSG06_NONCE_LABEL = "PS-Msg06"

_ROLES = (ROLE_CONTROLLER, ROLE_ACCESSORY)


class PairSetupError(ValueError):
    """A Pair-Setup message cannot be accepted."""


def setup_nonce(label):
    """The 12-byte AEAD nonce for a pairing message."""
    return crypto.nonce_label(label)


def setup_encryption_key(session_key):
    """The key that seals and opens m5 and m6."""
    return crypto.hkdf_sha512(
        session_key, ENCRYPT_SALT, ENCRYPT_INFO, crypto.KEY_BYTES)


def controller_sign_key(session_key):
    return crypto.hkdf_sha512(
        session_key, CONTROLLER_SIGN_SALT, CONTROLLER_SIGN_INFO, crypto.KEY_BYTES)


def accessory_sign_key(session_key):
    return crypto.hkdf_sha512(
        session_key, ACCESSORY_SIGN_SALT, ACCESSORY_SIGN_INFO, crypto.KEY_BYTES)


def signature_data(sign_key, pairing_id, long_term_public_key):
    """What each peer signs: the sign key, its id, its long-term key."""
    return (bytes(sign_key) + _utf8(pairing_id)
            + bytes(long_term_public_key))


def error_message(state):
    """The pairing error reply: the state received, plus the error code."""
    return tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([(state or 0) & 0xff])),
        tlv8.Item(tlv8.TYPE_ERROR, bytes([tlv8.ERROR_AUTHENTICATION])),
    ])


class PairSetup(object):
    """One Pair-Setup exchange from one peer's point of view.

    ``pairing_id`` and ``identity_private_key`` are ours; the other peer's
    long-term key is learned during the exchange and is only needed afterwards
    by PairVerify. ``store`` is optional and, if given, receives the learned
    key once the exchange is verified.
    """

    def __init__(self, role, pairing_id, identity_private_key, store=None,
                 group=None, password=None):
        if role not in _ROLES:
            raise ValueError(
                "role must be {} or {}, got {!r}".format(
                    ROLE_CONTROLLER, ROLE_ACCESSORY, role))

        self.role = role
        self.pairing_id = _utf8(pairing_id)
        self.identity_private_key = bytes(identity_private_key)
        self.store = store
        self.group = group if group is not None else srp6a.get_group(SETUP_GROUP_NAME)
        self.password = SETUP_CODE if password is None else _utf8(password)

        self._srp = None
        self._session_key = None
        self._encryption_key = None
        self.peer_id = None
        self.peer_long_term_public_key = None
        self.paired = False

    @property
    def long_term_public_key(self):
        return pubkey.ed25519_public(self.identity_private_key)

    @property
    def session_key(self):
        return self._session_key

    @property
    def encryption_key(self):
        return self._encryption_key

    @property
    def is_paired(self):
        return self.paired

    def begin(self):
        """m1: the controller's opening message. The accessory answers m2
        instead of sending an opening message of its own."""
        if self.role != ROLE_CONTROLLER:
            raise PairSetupError("the accessory does not open Pair-Setup")
        return self.m1()

    def m1(self):
        """m1: our identifier and the pairing method."""
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M1])),
            tlv8.Item(tlv8.TYPE_METHOD, METHOD_PAIR_SETUP),
            tlv8.Item(tlv8.TYPE_IDENTIFIER, self.pairing_id),
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
        except (PairSetupError, crypto.AuthenticationError):
            return error_message(_state_of(tlv8.decode(body)))

    def _handle_state(self, items, state):
        if self.role == ROLE_CONTROLLER:
            if state == STATE_M2:
                return self._controller_handle_m2(items)
            if state == STATE_M4:
                self._controller_handle_m4(items)
                return None
            if state == STATE_M6:
                return self._controller_handle_m6(items)
        else:
            if state == STATE_M1:
                return self._accessory_handle_m1(items)
            if state == STATE_M3:
                return self._accessory_handle_m3(items)
            if state == STATE_M5:
                return self._accessory_handle_m5(items)

        raise PairSetupError(
            "state {} is not expected from the {} side".format(state, self.role))

    def _controller_handle_m2(self, items):
        """m2 from the accessory: start the SRP client, then answer with m3."""
        public_key_b = _require(items, tlv8.TYPE_PUBLIC_KEY, "m2")
        salt = _require(items, tlv8.TYPE_SALT, "m2")
        if len(salt) != self.group.salt_bytes:
            raise PairSetupError(
                "m2 salt must be {} bytes, got {}".format(
                    self.group.salt_bytes, len(salt)))
        if len(public_key_b) != self.group.pad_bytes:
            raise PairSetupError(
                "m2 public key must be {} bytes, got {}".format(
                    self.group.pad_bytes, len(public_key_b)))

        try:
            self._srp = srp6a.ClientSession(
                self.group, SETUP_USERNAME, self.password, salt, public_key_b)
        except ValueError as exc:
            raise PairSetupError("m2 public key rejected: {}".format(exc))

        return self.m3()

    def m3(self):
        """m3: our SRP public key and proof."""
        self._require_srp("m3")
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M3])),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self._srp.public_key_bytes),
            tlv8.Item(tlv8.TYPE_PROOF, self._srp.client_proof),
        ])

    def _controller_handle_m4(self, items):
        """m4 from the accessory: check its proof, then keep the session key."""
        self._require_srp("m4")
        server_proof = _require(items, tlv8.TYPE_PROOF, "m4")
        if not self._srp.verify_server_proof(server_proof):
            raise PairSetupError("the accessory's proof does not check out")
        self._session_key = self._srp.session_key
        self._encryption_key = setup_encryption_key(self._session_key)

    def m5(self):
        """m5: our identifier, long-term key and signature, sealed."""
        self._require_session("m5")
        sign_key = controller_sign_key(self._session_key)
        signature = pubkey.ed25519_sign(
            self.identity_private_key,
            signature_data(sign_key, self.pairing_id, self.long_term_public_key))
        sub = tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, self.pairing_id),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self.long_term_public_key),
            tlv8.Item(tlv8.TYPE_SIGNATURE, signature),
        ])
        sealed = crypto.chacha_seal(
            self._encryption_key, setup_nonce(MSG05_NONCE_LABEL), sub)
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M5])),
            tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
        ])

    def _controller_handle_m6(self, items):
        """m6 from the accessory: check its signature and store its key."""
        self._require_session("m6")
        peer_id, peer_key, peer_signature = _open_identity(
            self._encryption_key, MSG06_NONCE_LABEL,
            _require(items, tlv8.TYPE_ENCRYPTED_DATA, "m6"))
        sign_key = accessory_sign_key(self._session_key)
        _check_signature(peer_key,
                         signature_data(sign_key, peer_id, peer_key),
                         peer_signature, "the accessory")
        self._remember_peer(peer_id, peer_key)
        self.paired = True
        return None

    def _accessory_handle_m1(self, items):
        """m1 from the controller: start the SRP server, then answer with m2."""
        method = items.get(tlv8.TYPE_METHOD)
        if method is not None and bytes(method) != METHOD_PAIR_SETUP:
            raise PairSetupError(
                "m1 method must be {!r}, got {!r}".format(
                    METHOD_PAIR_SETUP, bytes(method)))

        self._srp = srp6a.Srp6aSession(self.group, SETUP_USERNAME, self.password)
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M2])),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self._srp.public_key_bytes),
            tlv8.Item(tlv8.TYPE_SALT, self._srp.salt),
        ])

    def _accessory_handle_m3(self, items):
        """m3 from the controller: check its proof, then answer with m4."""
        self._require_srp("m4")
        public_key_a = _require(items, tlv8.TYPE_PUBLIC_KEY, "m3")
        client_proof = _require(items, tlv8.TYPE_PROOF, "m3")
        if len(public_key_a) != self.group.pad_bytes:
            raise PairSetupError(
                "m3 public key must be {} bytes, got {}".format(
                    self.group.pad_bytes, len(public_key_a)))

        result = self._srp.verify(public_key_a, client_proof)
        if not result.ok:
            raise PairSetupError("the controller's proof does not check out")
        self._session_key = result.session_key
        self._encryption_key = setup_encryption_key(self._session_key)

        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M4])),
            tlv8.Item(tlv8.TYPE_PROOF, result.server_proof),
        ])

    def _accessory_handle_m5(self, items):
        """m5 from the controller: check its signature, then answer with m6."""
        self._require_session("m6")
        peer_id, peer_key, peer_signature = _open_identity(
            self._encryption_key, MSG05_NONCE_LABEL,
            _require(items, tlv8.TYPE_ENCRYPTED_DATA, "m5"))
        sign_key = controller_sign_key(self._session_key)
        _check_signature(peer_key,
                         signature_data(sign_key, peer_id, peer_key),
                         peer_signature, "the controller")
        self._remember_peer(peer_id, peer_key)

        sign_key = accessory_sign_key(self._session_key)
        signature = pubkey.ed25519_sign(
            self.identity_private_key,
            signature_data(sign_key, self.pairing_id, self.long_term_public_key))
        sub = tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, self.pairing_id),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, self.long_term_public_key),
            tlv8.Item(tlv8.TYPE_SIGNATURE, signature),
        ])
        sealed = crypto.chacha_seal(
            self._encryption_key, setup_nonce(MSG06_NONCE_LABEL), sub)
        self.paired = True
        return tlv8.encode([
            tlv8.Item(tlv8.TYPE_STATE, bytes([STATE_M6])),
            tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
        ])

    def _require_srp(self, message):
        if self._srp is None:
            raise PairSetupError(
                "{} needs the SRP exchange first".format(message))

    def _require_session(self, message):
        if self._session_key is None or self._encryption_key is None:
            raise PairSetupError(
                "{} needs the session key first".format(message))

    def _remember_peer(self, peer_id, peer_key):
        self.peer_id = bytes(peer_id)
        self.peer_long_term_public_key = bytes(peer_key)
        if self.store is not None:
            self.store.save(self.peer_id, self.peer_long_term_public_key)


def _open_identity(encryption_key, nonce_label, encrypted):
    """Open m5/m6 and pull out the identity triple."""
    sub = tlv8.decode(crypto.chacha_open(
        encryption_key, setup_nonce(nonce_label), bytes(encrypted)))
    return (_require(sub, tlv8.TYPE_IDENTIFIER, "the identity payload"),
            _require(sub, tlv8.TYPE_PUBLIC_KEY, "the identity payload"),
            _require(sub, tlv8.TYPE_SIGNATURE, "the identity payload"))


def _state_of(items):
    state = items.get(tlv8.TYPE_STATE)
    if not state:
        return 0
    return state[0] & 0xff


def _require(items, type_, label):
    value = items.get(type_)
    if value is None:
        raise PairSetupError("{} needs type 0x{:02x}".format(label, type_))
    return bytes(value)


def _check_signature(long_term_public_key, data, signature, who):
    if not pubkey.ed25519_verify(long_term_public_key, data, bytes(signature)):
        raise crypto.AuthenticationError(
            "signature does not match {}'s key".format(who))


def _utf8(value):
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("expected str or bytes, got {!r}".format(type(value)))
