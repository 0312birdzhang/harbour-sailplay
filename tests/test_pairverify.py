"""Tests for the Pair-Verify identity exchange."""

import pytest

from carplay_proto import crypto
from carplay_proto import pairverify
from carplay_proto import pubkey
from carplay_proto import tlv8


def _identity():
    private_key = pubkey.ed25519_generate().secret
    public_key = pubkey.ed25519_public(private_key)
    return private_key, public_key


def _session(role, peer_id, peer_public_key=None):
    private_key, public_key = _identity()
    return (pairverify.PairVerify(role, peer_id, private_key, peer_public_key),
            private_key, public_key)


def _linked_pair():
    """An accessory and a controller that each hold the other's long-term key."""
    accessory, _a_private, accessory_public_key = _session(
        pairverify.ROLE_ACCESSORY, "Head Unit")
    controller, _c_private, controller_public_key = _session(
        pairverify.ROLE_CONTROLLER, "iPhone")
    controller.set_peer_key(accessory_public_key)
    accessory.set_peer_key(controller_public_key)
    return accessory, controller


def _assert_control_keys_cross(accessory, controller):
    """Each peer reads with the key the other writes."""
    assert accessory.control_keys.read_key == controller.control_keys.write_key
    assert accessory.control_keys.write_key == controller.control_keys.read_key
    assert accessory.control_keys.read_key != accessory.control_keys.write_key


def test_pair_verify_end_to_end():
    accessory, controller = _linked_pair()

    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    m4 = accessory.handle(m3)
    assert controller.handle(m4) is None

    assert accessory.is_verified and controller.is_verified
    assert accessory.peer_id == b"iPhone"
    assert controller.peer_id == b"Head Unit"
    assert accessory.shared == controller.shared
    assert accessory.encryption_key == controller.encryption_key
    _assert_control_keys_cross(accessory, controller)
    assert len(accessory.control_keys.read_key) == crypto.KEY_BYTES


def test_the_controller_cannot_use_the_accessory_private_key():
    accessory, controller = _linked_pair()
    controller.set_peer_key(accessory.identity_private_key)
    controller.set_peer_key(pubkey.ed25519_public(accessory.identity_private_key))

    m2 = accessory.handle(controller.begin())
    assert not controller.is_verified
    assert controller.control_keys is None


def test_either_direction_is_encrypted_end_to_end():
    accessory, controller = _linked_pair()
    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    accessory.handle(m3)

    _assert_control_keys_cross(accessory, controller)

    # Each way round the channel: what one peer writes, the other reads.
    payload = b"the control channel is live"
    nonce = crypto.nonce64(7)
    for writer, reader in ((controller, accessory), (accessory, controller)):
        sealed = crypto.chacha_seal(writer.control_keys.write_key, nonce,
                                    payload, b"length")
        assert crypto.chacha_open(reader.control_keys.read_key, nonce,
                                  sealed, b"length") == payload


def test_encryption_key_uses_the_pair_verify_labels():
    shared = b"\x11" * 32
    expected = crypto.hkdf_sha512(
        shared, pairverify.VERIFY_ENCRYPT_SALT,
        pairverify.VERIFY_ENCRYPT_INFO, crypto.KEY_BYTES)
    assert pairverify.verify_encryption_key(shared) == expected


def test_the_controller_reads_with_the_read_label():
    shared = b"\x22" * 32
    keys = pairverify.derive_control_keys(shared)
    assert keys.read_key == crypto.hkdf_sha512(
        shared, pairverify.CONTROL_SALT,
        pairverify.CONTROL_READ_KEY_INFO, crypto.KEY_BYTES)
    assert keys.write_key == crypto.hkdf_sha512(
        shared, pairverify.CONTROL_SALT,
        pairverify.CONTROL_WRITE_KEY_INFO, crypto.KEY_BYTES)


def test_the_accessory_turns_the_same_two_keys_around():
    """xcertplay's ``PairVerify.m4`` derives its read key from the write
    label, so it reads what the controller writes."""
    shared = b"\x22" * 32
    controller_keys = pairverify.derive_control_keys(
        shared, pairverify.ROLE_CONTROLLER)
    accessory_keys = pairverify.derive_control_keys(
        shared, pairverify.ROLE_ACCESSORY)
    assert accessory_keys.read_key == controller_keys.write_key
    assert accessory_keys.write_key == controller_keys.read_key
    assert accessory_keys.read_key == crypto.hkdf_sha512(
        shared, pairverify.CONTROL_SALT,
        pairverify.CONTROL_WRITE_KEY_INFO, crypto.KEY_BYTES)


def test_the_same_shared_secret_yields_the_same_keys():
    shared = b"\x33" * 32
    assert pairverify.derive_control_keys(shared) == \
        pairverify.derive_control_keys(shared)
    assert pairverify.derive_control_keys(shared) != \
        pairverify.derive_control_keys(b"\x44" * 32)


def test_nonce_labels_are_the_twelve_byte_airplay_form():
    assert pairverify.verify_nonce("PV-Msg02") == b"\x00" * 4 + b"PV-Msg02"
    assert pairverify.verify_nonce("PV-Msg03") == b"\x00" * 4 + b"PV-Msg03"
    assert len(pairverify.verify_nonce("PV-Msg02")) == crypto.NONCE_BYTES


def test_signature_data_is_own_key_own_id_peer_key():
    assert pairverify.signature_data(b"EPK", "iPhone", b"PEER") == \
        b"EPKiPhonePEER"


def test_pairing_id_encodes_utf8():
    session, _private, _public = _session(
        pairverify.ROLE_ACCESSORY, "Head Unit \u2665")
    assert session.pairing_id == "Head Unit \u2665".encode("utf-8")


def test_invalid_role_is_rejected():
    with pytest.raises(ValueError):
        pairverify.PairVerify("speaker", "id", pubkey.ed25519_generate().secret)


def test_accessory_does_not_open_the_exchange():
    accessory, _private, _public = _session(pairverify.ROLE_ACCESSORY, "Head Unit")
    with pytest.raises(pairverify.PairVerifyError):
        accessory.begin()


@pytest.mark.parametrize("role", [pairverify.ROLE_CONTROLLER, pairverify.ROLE_ACCESSORY])
def test_unknown_state_gets_the_error_reply(role):
    session, _private, _public = _session(role, "id")
    body = tlv8.encode([tlv8.Item(tlv8.TYPE_STATE, b"\x7f")])
    reply = tlv8.decode(session.handle(body))
    assert reply[tlv8.TYPE_STATE] == b"\x7f"
    assert reply[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])


def test_error_message_round_trips():
    decoded = tlv8.decode(pairverify.error_message(3))
    assert decoded[tlv8.TYPE_STATE] == b"\x03"
    assert decoded[tlv8.TYPE_ERROR] == bytes([2])


def test_error_message_defaults_to_state_zero():
    assert tlv8.decode(pairverify.error_message(0))[tlv8.TYPE_STATE] == b"\x00"


def test_error_reply_shape():
    assert set(tlv8.decode(pairverify.error_message(2))) == {
        tlv8.TYPE_STATE, tlv8.TYPE_ERROR}


def test_missing_peer_key_yields_an_error_reply():
    controller, _private, _public = _session(pairverify.ROLE_CONTROLLER, "iPhone")
    accessory, _a_private, accessory_public_key = _session(
        pairverify.ROLE_ACCESSORY, "Head Unit")
    accessory.set_peer_key(_public)

    reply = tlv8.decode(controller.handle(accessory.handle(controller.begin())))
    assert reply[tlv8.TYPE_STATE] == bytes([pairverify.STATE_M2])
    assert reply[tlv8.TYPE_ERROR] == bytes([2])


def test_tampered_signature_yields_an_error_reply():
    accessory, controller = _linked_pair()
    m2_items = tlv8.decode(accessory.handle(controller.begin()))

    inner = tlv8.decode(crypto.chacha_open(
        accessory.encryption_key,
        pairverify.verify_nonce(pairverify.MSG02_NONCE_LABEL),
        bytes(m2_items[tlv8.TYPE_ENCRYPTED_DATA])))
    tampered = bytearray(inner[tlv8.TYPE_SIGNATURE])
    tampered[0] ^= 0x01

    sealed = crypto.chacha_seal(
        accessory.encryption_key,
        pairverify.verify_nonce(pairverify.MSG02_NONCE_LABEL),
        tlv8.encode([
            tlv8.Item(tlv8.TYPE_IDENTIFIER, inner[tlv8.TYPE_IDENTIFIER]),
            tlv8.Item(tlv8.TYPE_SIGNATURE, bytes(tampered)),
        ]))
    replayed = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, bytes([pairverify.STATE_M2])),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, bytes(m2_items[tlv8.TYPE_PUBLIC_KEY])),
        tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
    ])

    reply = tlv8.decode(controller.handle(replayed))
    assert reply[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])
    assert not controller.is_verified


def test_tampered_sealed_payload_yields_an_error_reply():
    accessory, controller = _linked_pair()
    m2 = bytearray(accessory.handle(controller.begin()))
    m2[-1] ^= 0x01

    reply = tlv8.decode(controller.handle(bytes(m2)))
    assert reply[tlv8.TYPE_ERROR] == bytes([tlv8.ERROR_AUTHENTICATION])
    assert not controller.is_verified


def test_controller_rejects_an_m4_that_arrives_first():
    controller, _private, _public = _session(pairverify.ROLE_CONTROLLER, "iPhone")
    body = tlv8.encode([tlv8.Item(tlv8.TYPE_STATE, bytes([pairverify.STATE_M4]))])
    reply = tlv8.decode(controller.handle(body))
    assert reply[tlv8.TYPE_STATE] == bytes([pairverify.STATE_M4])
    assert reply[tlv8.TYPE_ERROR] == bytes([2])


def test_controller_m3_refuses_to_run_before_m2():
    controller, _private, _public = _session(pairverify.ROLE_CONTROLLER, "iPhone")
    with pytest.raises(pairverify.PairVerifyError):
        controller.m3()


def test_messages_are_tlv8_with_the_expected_types():
    accessory, controller = _linked_pair()

    m1 = controller.begin()
    m1_items = tlv8.decode(m1)
    assert set(m1_items) == {tlv8.TYPE_STATE, tlv8.TYPE_PUBLIC_KEY}
    assert m1_items[tlv8.TYPE_STATE] == bytes([pairverify.STATE_M1])
    assert len(m1_items[tlv8.TYPE_PUBLIC_KEY]) == crypto.KEY_BYTES

    m2 = accessory.handle(m1)
    m2_items = tlv8.decode(m2)
    assert set(m2_items) == {tlv8.TYPE_STATE, tlv8.TYPE_PUBLIC_KEY,
                             tlv8.TYPE_ENCRYPTED_DATA}
    assert m2_items[tlv8.TYPE_STATE] == bytes([pairverify.STATE_M2])
    assert len(m2_items[tlv8.TYPE_PUBLIC_KEY]) == crypto.KEY_BYTES

    m3 = controller.handle(m2)
    m3_items = tlv8.decode(m3)
    assert set(m3_items) == {tlv8.TYPE_STATE, tlv8.TYPE_ENCRYPTED_DATA}
    assert m3_items[tlv8.TYPE_STATE] == bytes([pairverify.STATE_M3])

    m4_items = tlv8.decode(accessory.handle(m3))
    assert m4_items == {tlv8.TYPE_STATE: bytes([pairverify.STATE_M4])}


def test_m3_empties_the_controller_out_and_verifies_only_once():
    accessory, controller = _linked_pair()
    m2 = accessory.handle(controller.begin())
    m3 = controller.handle(m2)
    assert controller.verified
    assert accessory.handle(m3) is not None
    assert controller.handle(accessory.handle(m3)) is None
