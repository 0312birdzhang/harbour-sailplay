"""Pair-Setup tests, run as a two-peer exchange.

Both peers are exercised in-process, so a broken label, nonce or byte order
shows up as a failed signature rather than a silent pass. The last test chains
Pair-Setup into Pair-Verify to prove the stored key really authorises a later
exchange.
"""

import pytest

from carplay_proto import crypto
from carplay_proto import pairsetup
from carplay_proto import pairverify
from carplay_proto import pairings
from carplay_proto import pubkey
from carplay_proto import tlv8


CONTROLLER_ID = b"iPad"
ACCESSORY_ID = b"Head Unit"


def _seed():
    return pubkey.ed25519_generate().secret


def _controller(store=None, password=None):
    return pairsetup.PairSetup(pairsetup.ROLE_CONTROLLER, CONTROLLER_ID,
                               _seed(), store=store, password=password)


def _accessory(store=None, password=None):
    return pairsetup.PairSetup(pairsetup.ROLE_ACCESSORY, ACCESSORY_ID,
                               _seed(), store=store, password=password)


def _state_of(body):
    items = tlv8.decode(body)
    state = items.get(tlv8.TYPE_STATE)
    return state[0] & 0xff if state else 0


# ---- constants -----------------------------------------------------------

def test_constants_match_the_head_unit():
    assert pairsetup.METHOD_PAIR_SETUP == b"Pair-Setup"
    assert pairsetup.SETUP_USERNAME == b"Pair-Setup"
    assert pairsetup.SETUP_CODE == b"3939"
    assert pairsetup.ENCRYPT_SALT == b"Pair-Setup-Encrypt-Salt"
    assert pairsetup.ENCRYPT_INFO == b"Pair-Setup-Encrypt-Info"
    assert pairsetup.CONTROLLER_SIGN_SALT == b"Pair-Setup-Controller-Sign-Salt"
    assert pairsetup.CONTROLLER_SIGN_INFO == b"Pair-Setup-Controller-Sign-Info"
    assert pairsetup.ACCESSORY_SIGN_SALT == b"Pair-Setup-Accessory-Sign-Salt"
    assert pairsetup.ACCESSORY_SIGN_INFO == b"Pair-Setup-Accessory-Sign-Info"
    assert pairsetup.MSG05_NONCE_LABEL == "PS-Msg05"
    assert pairsetup.MSG06_NONCE_LABEL == "PS-Msg06"
    for state in range(1, 7):
        assert getattr(pairsetup, "STATE_M{}".format(state)) == state


def test_nonce_labels_name_the_message_not_the_sender():
    assert pairsetup.setup_nonce("PS-Msg05") == crypto.nonce_label("PS-Msg05")
    assert pairsetup.setup_nonce("PS-Msg06") == crypto.nonce_label("PS-Msg06")
    assert pairsetup.setup_nonce("PS-Msg05") != pairsetup.setup_nonce("PS-Msg06")


def test_sign_keys_are_distinct_and_not_crossed():
    """Unlike the control keys, the sign keys are not swapped by role: each
    peer derives its own under its own label and verifies its peer's the same
    way. Asserting distinctness is what pins the labels to the right side."""
    key = b"\x01" * 64
    controller_key = pairsetup.controller_sign_key(key)
    accessory_key = pairsetup.accessory_sign_key(key)
    assert len(controller_key) == crypto.KEY_BYTES
    assert len(accessory_key) == crypto.KEY_BYTES
    assert controller_key != accessory_key
    assert pairsetup.setup_encryption_key(key) != controller_key
    assert pairsetup.setup_encryption_key(key) != accessory_key


def test_signature_data_layout():
    data = pairsetup.signature_data(b"key", b"me", b"ltpk")
    assert data == b"key" + b"me" + b"ltpk"


def test_signature_data_accepts_a_text_identifier():
    assert pairsetup.signature_data(b"k", "me", b"p") == b"k" + b"me" + b"p"


def test_bad_role_is_rejected():
    with pytest.raises(ValueError):
        pairsetup.PairSetup("phone", CONTROLLER_ID, _seed())


# ---- m1 ------------------------------------------------------------------

def test_m1_carries_state_method_and_identifier():
    body = _controller().begin()
    items = tlv8.decode(body)
    assert _state_of(body) == pairsetup.STATE_M1
    assert items[tlv8.TYPE_METHOD] == pairsetup.METHOD_PAIR_SETUP
    assert items[tlv8.TYPE_IDENTIFIER] == CONTROLLER_ID


def test_the_accessory_does_not_open_the_exchange():
    with pytest.raises(pairsetup.PairSetupError):
        _accessory().begin()


# ---- the full exchange ---------------------------------------------------

def test_a_full_exchange_pairs_both_peers():
    controller, accessory = _controller(), _accessory()

    m2 = accessory.handle(controller.begin())
    assert _state_of(m2) == pairsetup.STATE_M2

    m3 = controller.handle(m2)
    assert _state_of(m3) == pairsetup.STATE_M3
    assert tlv8.decode(m3)[tlv8.TYPE_PROOF]

    m4 = accessory.handle(m3)
    assert _state_of(m4) == pairsetup.STATE_M4

    assert controller.handle(m4) is None

    m5 = controller.m5()
    assert _state_of(m5) == pairsetup.STATE_M5

    m6 = accessory.handle(m5)
    assert _state_of(m6) == pairsetup.STATE_M6

    assert controller.handle(m6) is None

    assert controller.is_paired and accessory.is_paired


def test_both_peers_learn_each_others_identity():
    controller, accessory = _controller(), _accessory()

    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    m4 = accessory.handle(m3)
    controller.handle(m4)
    m6 = accessory.handle(controller.m5())
    controller.handle(m6)

    assert controller.peer_id == ACCESSORY_ID
    assert controller.peer_long_term_public_key == accessory.long_term_public_key
    assert accessory.peer_id == CONTROLLER_ID
    assert accessory.peer_long_term_public_key == controller.long_term_public_key


def test_both_peers_derive_the_same_session_and_encryption_keys():
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    m4 = accessory.handle(m3)
    controller.handle(m4)
    accessory.handle(controller.m5())

    assert controller.session_key == accessory.session_key
    assert len(controller.session_key) == 64
    assert controller.encryption_key == accessory.encryption_key


def test_the_accessory_signs_with_its_own_label():
    """Recomputing the accessory's m6 signature under the controller's label
    must fail: that is the only thing keeping the two labels honest."""
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    m4 = accessory.handle(m3)
    controller.handle(m4)
    m6 = accessory.handle(controller.m5())

    encrypted = tlv8.decode(m6)[tlv8.TYPE_ENCRYPTED_DATA]
    sub = tlv8.decode(crypto.chacha_open(
        controller.encryption_key, pairsetup.setup_nonce("PS-Msg06"), encrypted))
    peer_id = sub[tlv8.TYPE_IDENTIFIER]
    peer_key = sub[tlv8.TYPE_PUBLIC_KEY]
    peer_signature = sub[tlv8.TYPE_SIGNATURE]

    right = pairsetup.accessory_sign_key(controller.session_key)
    wrong = pairsetup.controller_sign_key(controller.session_key)
    assert pubkey.ed25519_verify(
        peer_key, pairsetup.signature_data(right, peer_id, peer_key),
        peer_signature)
    assert not pubkey.ed25519_verify(
        peer_key, pairsetup.signature_data(wrong, peer_id, peer_key),
        peer_signature)


def test_the_controller_signs_with_its_own_label():
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    m4 = accessory.handle(m3)
    controller.handle(m4)

    m5 = controller.m5()
    encrypted = tlv8.decode(m5)[tlv8.TYPE_ENCRYPTED_DATA]
    sub = tlv8.decode(crypto.chacha_open(
        accessory.encryption_key, pairsetup.setup_nonce("PS-Msg05"), encrypted))
    peer_id = sub[tlv8.TYPE_IDENTIFIER]
    peer_key = sub[tlv8.TYPE_PUBLIC_KEY]
    peer_signature = sub[tlv8.TYPE_SIGNATURE]

    right = pairsetup.controller_sign_key(accessory.session_key)
    wrong = pairsetup.accessory_sign_key(accessory.session_key)
    assert pubkey.ed25519_verify(
        peer_key, pairsetup.signature_data(right, peer_id, peer_key),
        peer_signature)
    assert not pubkey.ed25519_verify(
        peer_key, pairsetup.signature_data(wrong, peer_id, peer_key),
        peer_signature)


# ---- the store -----------------------------------------------------------

def test_the_controller_stores_the_accessory_key_for_pair_verify():
    store = pairings.PairingStore()
    controller = _controller(store=store)
    accessory = _accessory()

    m2 = accessory.handle(controller.begin())
    m4 = accessory.handle(controller.handle(m2))
    controller.handle(m4)
    m6 = accessory.handle(controller.m5())
    controller.handle(m6)

    assert ACCESSORY_ID.decode("utf-8") in store
    assert store.get(ACCESSORY_ID.decode("utf-8")) == accessory.long_term_public_key


def test_the_store_callback_fires_with_copied_key_material():
    seen = []
    store = pairings.PairingStore(on_save=lambda i, k: seen.append((i, k)))
    controller = _controller(store=store)
    accessory = _accessory()

    m2 = accessory.handle(controller.begin())
    m4 = accessory.handle(controller.handle(m2))
    controller.handle(m4)
    m6 = accessory.handle(controller.m5())
    controller.handle(m6)

    assert len(seen) == 1
    identifier, key = seen[0]
    assert identifier == ACCESSORY_ID.decode("utf-8")
    assert key == accessory.long_term_public_key
    key = bytearray(key)
    key[0] ^= 0x01
    assert store.get(ACCESSORY_ID.decode("utf-8")) == accessory.long_term_public_key
# ---- error replies -------------------------------------------------------

def _error_reply(body):
    items = tlv8.decode(body)
    assert tlv8.TYPE_ERROR in items
    assert items[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])
    return _state_of(body)


def test_an_unexpected_state_yields_an_error_reply():
    accessory = _accessory()
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M5]))]))
    assert _error_reply(reply) == pairsetup.STATE_M5


def test_a_missing_proof_yields_an_error_reply():
    accessory = _accessory()
    accessory.handle(_controller().begin())
    m3 = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M3])),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"\x00" * 384),
    ])
    assert _error_reply(accessory.handle(m3)) == pairsetup.STATE_M3


def test_a_bad_method_yields_an_error_reply():
    accessory = _accessory()
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M1])),
        tlv8.Item(tlv8.TYPE_METHOD, b"Something-Else"),
        tlv8.Item(tlv8.TYPE_IDENTIFIER, CONTROLLER_ID),
    ]))
    assert _error_reply(reply) == pairsetup.STATE_M1


def test_a_wrong_setup_code_fails_the_proof():
    accessory = _accessory()
    m2 = accessory.handle(_controller(password=b"0000").begin())
    m3 = _controller(password=b"0000").handle(m2)
    assert _error_reply(accessory.handle(m3)) == pairsetup.STATE_M3


def test_a_tampered_proof_fails():
    accessory = _accessory()
    controller = _controller()
    m2 = accessory.handle(controller.begin())
    m3 = tlv8.decode(controller.handle(m2))
    proof = bytearray(m3[tlv8.TYPE_PROOF])
    proof[0] ^= 0x01
    tampered = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M3])),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, m3[tlv8.TYPE_PUBLIC_KEY]),
        tlv8.Item(tlv8.TYPE_PROOF, bytes(proof)),
    ])
    assert _error_reply(accessory.handle(tampered)) == pairsetup.STATE_M3


def test_a_tampered_signature_is_rejected():
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    m4 = accessory.handle(controller.handle(m2))
    controller.handle(m4)

    m5 = tlv8.decode(controller.m5())
    encrypted = tlv8.decode(crypto.chacha_open(
        accessory.encryption_key, pairsetup.setup_nonce("PS-Msg05"),
        bytes(m5[tlv8.TYPE_ENCRYPTED_DATA])))
    signature = bytearray(encrypted[tlv8.TYPE_SIGNATURE])
    signature[0] ^= 0x01
    sealed = crypto.chacha_seal(
        accessory.encryption_key, pairsetup.setup_nonce("PS-Msg05"),
        tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, encrypted[tlv8.TYPE_IDENTIFIER]),
            tlv8.Item(tlv8.TYPE_PUBLIC_KEY, encrypted[tlv8.TYPE_PUBLIC_KEY]),
            tlv8.Item(tlv8.TYPE_SIGNATURE, bytes(signature)),
        ]))
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M5])),
        tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
    ]))
    assert _error_reply(reply) == pairsetup.STATE_M5


def test_ordering_is_enforced():
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    controller.handle(m2)

    with pytest.raises(pairsetup.PairSetupError):
        controller.m5()

    # Going through handle() turns the same failure into an error reply.
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M5]))]))
    assert _error_reply(reply) == pairsetup.STATE_M5


def test_a_message_before_any_exchange_is_an_error():
    with pytest.raises(pairsetup.PairSetupError):
        _controller().m5()


def test_a_mislengthed_salt_is_rejected():
    controller = _controller()
    reply = controller.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M2])),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"\x00" * 384),
        tlv8.Item(tlv8.TYPE_SALT, b"\x00" * 8),
    ]))
    assert _error_reply(reply) == pairsetup.STATE_M2


def test_a_mislengthed_public_key_is_rejected():
    accessory = _accessory()
    accessory.handle(_controller().begin())
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M3])),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"\x00" * 383),
        tlv8.Item(tlv8.TYPE_PROOF, b"\x00" * 64),
    ]))
    assert _error_reply(reply) == pairsetup.STATE_M3


def test_an_authentication_failure_becomes_a_reply_not_a_raise():
    controller, accessory = _controller(), _accessory()
    m2 = accessory.handle(controller.begin())
    m4 = accessory.handle(controller.handle(m2))
    controller.handle(m4)

    m5 = tlv8.decode(controller.m5())
    sealed = bytearray(m5[tlv8.TYPE_ENCRYPTED_DATA])
    sealed[-1] ^= 0x01
    reply = accessory.handle(tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairsetup.STATE_M5])),
        tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, bytes(sealed)),
    ]))
    assert _error_reply(reply) == pairsetup.STATE_M5


# ---- the long-term key ---------------------------------------------------

def test_the_long_term_public_key_matches_the_private_key():
    controller = _controller()
    assert controller.long_term_public_key == pubkey.ed25519_public(
        controller.identity_private_key)


def test_a_text_pairing_id_is_utf8_encoded():
    assert pairsetup.PairSetup(pairsetup.ROLE_CONTROLLER, "iPad", _seed()).pairing_id \
        == b"iPad"


def test_a_number_pairing_id_is_rejected():
    with pytest.raises(TypeError):
        pairsetup.PairSetup(pairsetup.ROLE_CONTROLLER, 42, _seed())


# ---- pairing store -------------------------------------------------------

def test_pairing_store_round_trip():
    store = pairings.PairingStore()
    store.save("peer", b"\x01" * 32)
    assert store.get("peer") == b"\x01" * 32
    assert store.get(b"peer") == b"\x01" * 32
    assert "peer" in store
    assert len(store) == 1

    other = pairings.PairingStore.from_json(store.to_json())
    assert other.get("peer") == b"\x01" * 32


def test_pairing_store_get_copies():
    store = pairings.PairingStore()
    store.save("peer", b"\x01" * 32)
    key = bytearray(store.get("peer"))
    key[0] ^= 0x01
    assert store.get("peer") == b"\x01" * 32


def test_pairing_store_discard_and_clear():
    store = pairings.PairingStore()
    store.save("a", b"\x01")
    store.save("b", b"\x02")
    assert store.discard("a") == b"\x01"
    assert store.discard("a") is None
    assert store.identifiers() == ("b",)
    store.clear()
    assert len(store) == 0


def test_pairing_store_rejects_a_number_identifier():
    with pytest.raises(TypeError):
        pairings.PairingStore().save(42, b"\x01")


# ---- end to end: Pair-Setup into Pair-Verify -----------------------------

def test_a_pair_setup_authorises_a_later_pair_verify():
    """The whole point of storing the key: without it, PairVerify m2 cannot be
    checked. This runs both halves back to back using the same identities."""
    controller_setup = _controller(store=None)
    accessory_setup = _accessory(store=None)

    m2 = accessory_setup.handle(controller_setup.begin())
    m4 = accessory_setup.handle(controller_setup.handle(m2))
    controller_setup.handle(m4)
    m6 = accessory_setup.handle(controller_setup.m5())
    controller_setup.handle(m6)

    accessory_ltpk = controller_setup.peer_long_term_public_key
    controller_ltpk = accessory_setup.peer_long_term_public_key
    assert accessory_ltpk and controller_ltpk

    controller_verify = pairverify.PairVerify(
        pairverify.ROLE_CONTROLLER, CONTROLLER_ID,
        controller_setup.identity_private_key,
        peer_long_term_public_key=accessory_ltpk)
    accessory_verify = pairverify.PairVerify(
        pairverify.ROLE_ACCESSORY, ACCESSORY_ID,
        accessory_setup.identity_private_key,
        peer_long_term_public_key=controller_ltpk)

    reply = accessory_verify.handle(controller_verify.begin())
    assert _state_of(reply) == pairverify.STATE_M2
    reply = controller_verify.handle(reply)
    assert _state_of(reply) == pairverify.STATE_M3
    final = accessory_verify.handle(reply)
    assert _state_of(final) == pairverify.STATE_M4
    assert controller_verify.handle(final) is None

    assert controller_verify.is_verified
    assert accessory_verify.is_verified
    assert controller_verify.shared == accessory_verify.shared
    # The control keys are role-crossed, so each peer reads the key the other
    # writes. That is the expected outcome, not a mismatch.
    assert controller_verify.control_keys.write_key == \
        accessory_verify.control_keys.read_key
    assert controller_verify.control_keys.read_key == \
        accessory_verify.control_keys.write_key
    assert controller_verify.peer_id == ACCESSORY_ID
    assert accessory_verify.peer_id == CONTROLLER_ID


def test_pair_verify_fails_without_the_key_from_pair_setup():
    """The negative half of the above: with no stored key the accessory cannot
    check the controller's m3 signature, so the exchange dies there rather than
    silently succeeding."""
    accessory_seed = _seed()
    accessory_verify = pairverify.PairVerify(
        pairverify.ROLE_ACCESSORY, ACCESSORY_ID, accessory_seed,
        peer_long_term_public_key=None)
    controller_verify = pairverify.PairVerify(
        pairverify.ROLE_CONTROLLER, CONTROLLER_ID, _seed(),
        peer_long_term_public_key=pubkey.ed25519_public(accessory_seed))

    m2 = accessory_verify.handle(controller_verify.begin())
    assert _state_of(m2) == pairverify.STATE_M2
    m3 = controller_verify.handle(m2)
    assert _state_of(m3) == pairverify.STATE_M3

    reply = accessory_verify.handle(m3)
    items = tlv8.decode(reply)
    assert items[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])
    assert _state_of(reply) == pairverify.STATE_M3
    assert not accessory_verify.is_verified


def test_pair_verify_fails_with_a_key_from_a_different_peer():
    """A stored key belonging to some other peer must not pass: the accessory
    signs with its own identity, so verifying under a stranger's key fails at
    m2, before the controller ever sends m3."""
    accessory_seed = _seed()
    accessory_verify = pairverify.PairVerify(
        pairverify.ROLE_ACCESSORY, ACCESSORY_ID, accessory_seed,
        peer_long_term_public_key=pubkey.ed25519_public(accessory_seed))
    stranger_ltpk = pubkey.ed25519_generate().public
    controller_verify = pairverify.PairVerify(
        pairverify.ROLE_CONTROLLER, CONTROLLER_ID, _seed(),
        peer_long_term_public_key=stranger_ltpk)

    m2 = accessory_verify.handle(controller_verify.begin())
    reply = controller_verify.handle(m2)

    items = tlv8.decode(reply)
    assert items[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])
    assert _state_of(reply) == pairverify.STATE_M2
    assert not controller_verify.is_verified


def test_the_same_identities_repair_cleanly():
    """Pairing the same two identities twice must not trip over the first run."""
    for _ in range(2):
        controller, accessory = _controller(), _accessory()
        m2 = accessory.handle(controller.begin())
        m4 = accessory.handle(controller.handle(m2))
        controller.handle(m4)
        m6 = accessory.handle(controller.m5())
        controller.handle(m6)
        assert controller.is_paired and accessory.is_paired
        assert controller.session_key == accessory.session_key


def test_a_distinct_setup_code_yields_a_distinct_session_key():
    """Same group, same identities, different code: different session key."""
    def run(code):
        controller = _controller(password=code)
        accessory = _accessory(password=code)
        m2 = accessory.handle(controller.begin())
        m4 = accessory.handle(controller.handle(m2))
        controller.handle(m4)
        m6 = accessory.handle(controller.m5())
        controller.handle(m6)
        return controller.session_key

    assert run(b"3939") != run(b"0000")
