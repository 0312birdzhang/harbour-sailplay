"""SRP-6a tests, anchored on RFC 5054 Appendix B.

The RFC publishes I, P, s, k, x, v, a, b, A, B, u and the premaster secret
for its 1024-bit / SHA-1 group, so every intermediate is checked against an
external answer rather than only against our own server. CarPlay's group
(SHA-512 / 3072-bit) has no published vectors, so it gets a round trip plus
the structural checks.
"""

import hashlib

import pytest

from carplay_proto import srp6a

# ---- RFC 5054 Appendix B -------------------------------------------------
IDENT = "alice"
PASSWORD = "password123"
SALT = bytes.fromhex("BEB25379D1A8581EB5A727673A2441EE")
K = int("7556AA045AEF2CDD07ABAF0F665C3E818913186F", 16)
X = int("94B7555AABE9127CC58CCF4993DB6CF84D16C124", 16)
V = int("7E273DE8696FFC4F4E337D05B4B375BEB0DDE1569E8FA00A9886D8129BADA1F18222"
        "23CA1A605B530E379BA4729FDC59F105B4787E5186F5C671085A1447B52A48CF1970"
        "B4FB6F8400BBF4CEBFBB168152E08AB5EA53D15C1AFF87B2B9DA6E04E058AD51CC72"
        "BFC9033B564E26480D78E955A5E29E7AB245DB2BE315E2099AFB", 16)
A_EXP = int("60975527035CF2AD1989806F0407210BC81EDC04E2762A56AFD529DDDA2D4393", 16)
B_EXP = int("E487CB59D31AC550471E81F00F6928E01DDA08E974A004F49E61F5D105284D20", 16)
A = bytes.fromhex("61D5E490F6F1B79547B0704C436F523DD0E560F0C64115BB72557EC44352"
                  "E8903211C04692272D8B2D1A5358A2CF1B6E0BFCF99F921530EC8E393561"
                  "79EAE45E42BA92AEACED825171E1E8B9AF6D9C03E1327F44BE087EF06530"
                  "E69F66615261EEF54073CA11CF5858F0EDFDFE15EFEAB349EF5D76988A36"
                  "72FAC47B0769447B")
B = bytes.fromhex("BD0C61512C692C0CB6D041FA01BB152D4916A1E77AF46AE105393011BAF3"
                  "8964DC46A0670DD125B95A981652236F99D9B681CBF87837EC996C6DA044"
                  "53728610D0C6DDB58B318885D7D82C7F8DEB75CE7BD4FBAA37089E6F9C60"
                  "59F388838E7A00030B331EB76840910440B1B27AAEAEEB4012B7D7665238"
                  "A8E3FB004B117B58")
U = int("CE38B9593487DA98554ED47D70A7AE5F462EF019", 16)
PREMASTER = bytes.fromhex(
    "B0DC82BABCF30674AE450C0287745E7990A3381F63B387AAF271A10D233861E359B48220"
    "F7C4693C9AE12B0A6F67809F0876E2D013800D6C41BB59B6D5979B5C00A172B4A2A5903A"
    "0BDCAF8A709585EB2AFAFA8F3499B200210DCC1F10EB33943CD67FC88A2F39A4BE5BEC4E"
    "C0A3212DC346D7E474B29EDE8A469FFECA686E5A")

# CarPlay's parameters, per xcertplay's Srp6a.kt.
SETUP_USERNAME = "Pair-Setup"
SETUP_CODE = "3939"

G1024 = srp6a.get_group("rfc5054-1024-sha1")
G3072 = srp6a.get_group("rfc5054-3072-sha512")


def _server(password=PASSWORD, salt=SALT, private_exponent=B_EXP, group=G1024):
    return srp6a.Srp6aSession(group, IDENT, password, salt=salt,
                              private_exponent=private_exponent)


def _client(password=PASSWORD, salt=SALT, b=B, private_exponent=A_EXP, group=G1024):
    return srp6a.ClientSession(group, IDENT, password, salt, b,
                               private_exponent=private_exponent)


# ---- encoding ------------------------------------------------------------

def test_to_bytes_zero_is_one_zero_byte():
    assert srp6a.to_bytes(0) == b"\x00"


def test_to_bytes_drops_the_sign_byte():
    # 0x80 must not gain a leading 0x00, or every hash below it shifts.
    assert srp6a.to_bytes(0x7f) == b"\x7f"
    assert srp6a.to_bytes(0x80) == b"\x80"


def test_to_bytes_is_minimal():
    assert srp6a.to_bytes(0x0102) == b"\x01\x02"


def test_to_bigint_zero():
    assert srp6a.to_bigint(b"\x00") == 0


def test_to_bigint_is_unsigned():
    assert srp6a.to_bigint(b"\x80") == 0x80
    assert srp6a.to_bigint(b"\x00\x01") == 1


def test_pad_right_aligns():
    assert srp6a.pad(0x0102, 4) == b"\x00\x00\x01\x02"


def test_pad_is_noop_when_already_full():
    assert srp6a.pad(0x0102, 2) == b"\x01\x02"


def test_pad_keeps_a_wider_value_intact():
    # A value wider than the field is returned untouched, matching xcertplay.
    assert srp6a.pad(0x010203, 2) == b"\x01\x02\x03"


def test_pad_zero():
    assert srp6a.pad(0, 3) == b"\x00\x00\x00"


@pytest.mark.parametrize("value", [0, 1, 2, 0x80, 0x0102, 1 << 8123])
def test_encoding_round_trips(value):
    assert srp6a.to_bigint(srp6a.to_bytes(value)) == value
    assert srp6a.to_bigint(srp6a.pad(value, 129)) == value


# ---- RFC 5054 vectors ----------------------------------------------------

def test_group_modulus_and_generator():
    assert G1024.modulus.bit_length() == 1024
    assert G1024.generator == 2
    assert G1024.pad_bytes == 128


def test_multiplier_k_matches_rfc():
    assert G1024.multiplier == K


def test_digest_of_generator_uses_the_minimal_encoding():
    # g = 2 encodes as one byte, so H(g) hashes b"\x02", not a padded form.
    assert G1024.hash_generator == hashlib.sha1(b"\x02").digest()


def test_digest_of_modulus_is_full_width():
    assert G1024.hash_modulus == hashlib.sha1(srp6a.to_bytes(G1024.modulus)).digest()


def test_hash_xor_width_matches_the_digest():
    assert len(G1024.hash_xor) == len(G1024.digest(b""))


def test_hash_xor_round_trips():
    assert bytes(x ^ y for x, y in zip(G1024.hash_xor, G1024.hash_generator)) \
        == G1024.hash_modulus


def test_password_hash_x_matches_rfc():
    assert srp6a.password_hash(G1024, IDENT, PASSWORD, SALT) == X


def test_password_hash_uses_the_colon_separator():
    # The RFC's x only matches when the identifier and password are joined with ":".
    assert srp6a.password_hash(G1024, IDENT, PASSWORD, SALT) == srp6a.to_bigint(
        srp6a.sha1(SALT, srp6a.sha1(b"alice:password123")))


def test_password_verifier_v_matches_rfc():
    assert srp6a.password_verifier(G1024, IDENT, PASSWORD, SALT) == V


def test_server_public_key_b_matches_rfc():
    server = _server()
    assert server.public_key == srp6a.to_bigint(B)
    assert server.salt == SALT
    assert server.verifier == V


def test_client_public_key_a_matches_rfc():
    assert _client().public_key == srp6a.to_bigint(A)


def test_client_u_matches_rfc():
    assert _client().u == U


def test_client_session_key_is_the_hash_of_the_rfc_premaster():
    assert _client().session_key == hashlib.sha1(PREMASTER).digest()


def test_client_proof_matches_the_rfc_formula():
    """M_A rebuilt from the RFC's own formula, not from our code path."""
    client = _client()
    expected = srp6a.sha1(
        G1024.hash_xor + G1024.digest(IDENT.encode("utf-8"))
        + SALT + A + B + client.session_key)
    assert client.client_proof == expected


def test_server_and_client_derive_the_same_session_key():
    result = _server().verify(A, _client().client_proof)
    assert result.session_key == _client().session_key


# ---- M_A / M_B acceptance and rejection ----------------------------------

def test_server_accepts_the_client_proof():
    result = _server().verify(A, _client().client_proof)
    assert result.ok
    assert result.session_key == _client().session_key
    assert result.server_proof is not None


def test_client_accepts_the_server_proof():
    result = _server().verify(A, _client().client_proof)
    assert _client().verify_server_proof(result.server_proof)


def test_client_rejects_a_tampered_server_proof():
    result = _server().verify(A, _client().client_proof)
    proof = result.server_proof
    tampered = bytes([proof[0] ^ 0x01]) + proof[1:]
    assert not _client().verify_server_proof(tampered)


def test_server_rejects_a_wrong_password():
    impostor = _client(password="wrongpass")
    assert not _server().verify(impostor.public_key_bytes,
                                impostor.client_proof).ok


def test_server_rejects_a_tampered_client_proof():
    proof = _client().client_proof
    tampered = bytes([proof[0] ^ 0x01]) + proof[1:]
    assert not _server().verify(A, tampered).ok


def test_server_rejects_a_zero_public_key():
    assert not _server().verify(b"\x00" * 128, _client().client_proof).ok


def test_server_rejects_a_mislengthed_proof():
    assert not _server().verify(A, b"\x00").ok


def test_failed_result_carries_no_material():
    result = _server().verify(b"\x00" * 128, _client().client_proof)
    assert not result.ok
    assert result.session_key is None
    assert result.server_proof is None


def test_result_repr_distinguishes_outcomes():
    failed = _server().verify(b"\x00" * 128, _client().client_proof)
    passed = _server().verify(A, _client().client_proof)
    assert repr(failed) == "Result(failed)"
    assert repr(passed).startswith("Result(ok")
    assert passed != failed


# ---- CarPlay's group -----------------------------------------------------

def test_carplay_group_parameters():
    assert G3072.modulus.bit_length() == 3072
    assert G3072.generator == 5
    assert G3072.pad_bytes == 384
    assert G3072.salt_bytes == 16
    assert G3072.private_bytes == 32


def test_carplay_modulus_is_the_rfc5054_prime():
    assert G3072.modulus == srp6a.RFC_5054_3072
    # Not a plausible-looking lookalike of the 1024-bit prime.
    assert G3072.modulus != srp6a.RFC_5054_1024


def test_carplay_digest_is_sha512():
    assert len(G3072.digest(b"")) == 64
    assert len(G3072.hash_xor) == 64


def test_carplay_round_trip_agrees():
    server = srp6a.Srp6aSession(G3072, SETUP_USERNAME, SETUP_CODE)
    client = srp6a.ClientSession(G3072, SETUP_USERNAME, SETUP_CODE,
                                 server.salt, server.public_key_bytes)
    result = server.verify(client.public_key_bytes, client.client_proof)
    assert result.ok
    assert result.session_key == client.session_key
    assert len(result.session_key) == 64
    assert len(result.server_proof) == 64
    assert client.verify_server_proof(result.server_proof)


def test_carplay_wires_padded_384_byte_keys_and_a_16_byte_salt():
    server = srp6a.Srp6aSession(G3072, SETUP_USERNAME, SETUP_CODE)
    client = srp6a.ClientSession(G3072, SETUP_USERNAME, SETUP_CODE,
                                 server.salt, server.public_key_bytes)
    assert len(server.public_key_bytes) == 384
    assert len(client.public_key_bytes) == 384
    assert len(server.salt) == 16


def test_carplay_rejects_a_wrong_setup_code():
    server = srp6a.Srp6aSession(G3072, SETUP_USERNAME, SETUP_CODE)
    impostor = srp6a.ClientSession(G3072, SETUP_USERNAME, "0000",
                                   server.salt, server.public_key_bytes)
    assert not server.verify(impostor.public_key_bytes,
                             impostor.client_proof).ok


def test_carplay_rejects_a_wrong_identifier():
    server = srp6a.Srp6aSession(G3072, SETUP_USERNAME, SETUP_CODE)
    impostor = srp6a.ClientSession(G3072, "Other-User", SETUP_CODE,
                                   server.salt, server.public_key_bytes)
    assert not server.verify(impostor.public_key_bytes,
                             impostor.client_proof).ok


def test_carplay_accepts_a_fresh_client_each_time():
    server = srp6a.Srp6aSession(G3072, SETUP_USERNAME, SETUP_CODE)
    for _ in range(3):
        client = srp6a.ClientSession(G3072, SETUP_USERNAME, SETUP_CODE,
                                     server.salt, server.public_key_bytes)
        result = server.verify(client.public_key_bytes, client.client_proof)
        assert result.ok
        assert result.session_key == client.session_key


# ---- input validation ----------------------------------------------------

def test_salt_must_be_the_group_width():
    with pytest.raises(ValueError):
        srp6a.Srp6aSession(G1024, IDENT, PASSWORD, salt=b"\x00" * 4)


def test_zero_server_private_exponent_is_rejected():
    with pytest.raises(ValueError):
        srp6a.Srp6aSession(G1024, IDENT, PASSWORD, salt=SALT,
                          private_exponent=0)


def test_zero_client_private_exponent_is_rejected():
    with pytest.raises(ValueError):
        srp6a.ClientSession(G1024, IDENT, PASSWORD, SALT, B,
                            private_exponent=0)


def test_zero_client_b_is_rejected():
    with pytest.raises(ValueError):
        srp6a.ClientSession(G1024, IDENT, PASSWORD, SALT, b"\x00" * 128)


def test_unknown_group_name_is_rejected():
    with pytest.raises(ValueError):
        srp6a.get_group("nope")


def test_identifier_accepts_bytes():
    server = srp6a.Srp6aSession(G1024, b"alice", PASSWORD, salt=SALT)
    assert server.identifier == b"alice"


def test_identifier_rejects_numbers():
    with pytest.raises(TypeError):
        srp6a.Srp6aSession(G1024, 42, PASSWORD, salt=SALT)


def test_get_group_names_are_known():
    assert srp6a.get_group("rfc5054-3072-sha512").generator == 5
    assert srp6a.get_group("rfc5054-1024-sha1").generator == 2


def test_groups_are_fresh_objects():
    assert srp6a.get_group("rfc5054-1024-sha1") is not \
        srp6a.get_group("rfc5054-1024-sha1")


def test_group_repr_names_the_width_and_digest():
    text = repr(G3072)
    assert "3072" in text
    assert "sha512" in text
