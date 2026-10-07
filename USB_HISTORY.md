# harbour-sailplay

CarPlay media-device protocol stack for SailfishOS. Implements the byte-level
wire codecs the tablet needs to present itself as an iPhone to a real CarPlay
head unit.

Protocol reference: [`../CARPLAY_MD_SPEC.md`](../CARPLAY_MD_SPEC.md).

**Wireless phone-role development resumed 2026-10-07:** see [WIRELESS.md](WIRELESS.md)
for the RFCOMM/iAP2 probe, current device evidence and outstanding media work.
The USB status below applies only to the earlier USBMUX attempt.

> **Status: shelved — USBMUX is unreachable on the target device**
>
> **CarPlay-over-USB was abandoned 2026-09-24.** All protocol work below is
> complete and tested, but it has no transport. The head unit needs a USBMUX
> interface (`EF/02/01` + 2 bulk endpoints) and the target tablet cannot produce
> one — three separate blockers, all verified on-device:
>
> 1. **FunctionFS is broken.** `mkdir functions/ffs.X` returns success but yields
>    0 attributes and no `/dev/usb` node. `f_fs.c` in the running kernel has no
>    configfs glue at all (no `ct_attrs`, no `config_item_type`); the configfs
>    registration is a stripped stub. `/proc/config.gz` claims `USB_F_FS=y` but
>    that is not what was built.
> 2. **No kernel module can be built.** No `flex`/`bison`/`python2`, no
>    `Module.symvers`, no `include/config`, `make olddefconfig` fails on a pruned
>    tree, and `CONFIG_MODVERSIONS=y` would reject any out-of-tree `.ko`.
> 3. **No stock gadget function can present `EF/02/01`.** `rndis` is the only one
>    with writable class/subclass/protocol, but those feed only the IAD and are
>    immediately overwritten, and its bulk endpoints sit on an interface whose
>    class is hardcoded `0x0A` and never rewritten.
>
> Full evidence and re-check procedure: [`../CARPLAY_MD_SPEC.md` §12](../CARPLAY_MD_SPEC.md).
>
> The delivered product is **CarLife-over-AOA** (`harbour-sailife`), which is
> car-verified. This repo is retained for protocol reuse only.

## Scope

The original stack consists of byte-level codecs. Wireless development adds a
BlueZ diagnostic executable and pinned-accessory verification using system
OpenSSL. See WIRELESS.md for the current implementation and actual device proof.
Codec layers, bottom up:

| module           | layer                                        |
| ---------------- | -------------------------------------------- |
| `types.py`       | CSM scalar codecs (all big-endian)           |
| `wire.py`        | CSM framing, parameters, streaming framer    |
| `body.py`        | schema-aware body builder and reader         |
| `endpoints.py`   | declared endpoint catalog + builders         |
| `usbmux.py`      | USBMUX v2 frames + minimal TCP subset        |
| `ntb16.py`       | NTB16/NCM transfer-block codec               |
| `iap2link.py`    | incremental iAP2 link framing and checksums    |
| `wireless.py`    | phone Wi-Fi request and credential parsing     |
| `accessoryauth.py` | pinned P256 challenge verification via libcrypto |
| `crypto.py`      | ChaCha20-Poly1305, HKDF-SHA512, CarPlay nonces |
| `controlcipher.py` | control-channel frame encryption/decryption  |
| `pubkey.py`      | X25519 key agreement + Ed25519 signatures    |
| `tlv8.py`        | TLV8 codec for the pairing messages          |
 | `pairverify.py`  | Pair-Verify identity exchange, control keys  |
 | `srp6a.py`       | generic SRP-6a (RFC 5054 groups, SHA-1/SHA-512) |
 | `pairsetup.py`   | Pair-Setup exchange, code entry, key storage  |
 | `pairings.py`    | persisted peer -> long-term key store         |

 Not yet implemented (hard walls, see the spec): the Apple device certificate
 (`0xaa11`/`0xaa13`), the USB composite NCM gadget, and the CarPlay app
 protocol. The screen and audio streams reuse the same primitives but are not
 yet wired up.

## Usage

```python
from carplay_proto import body, endpoints

frame = (endpoints.builder(endpoints.CARPLAY_AVAILABILITY, validate=True)
         .group(0, lambda b: b.u8(0, 1).string(1, "usb"))
         .group(1, lambda b: b.u8(0, 0))
         .group(2, lambda b: b.u8(0, 1))
         .build())

wire_bytes = frame.encoded()          # 0x4040 | u16 length | u16 msg | body
```

```python
from carplay_proto.wire import Framer

framer = Framer()
for frame in framer.offer(chunk):      # tolerates arbitrary chunking
    reader = body.BodyReader.of(frame)
```

`endpoints.raw_builder(message_id)` is for opaque endpoints with no declared
schema.

```python
from carplay_proto import controlcipher, crypto

shared = x25519_shared_secret   # produced by the pairing half
read_key = crypto.hkdf_sha512(shared, b"Events-Salt",
                             b"Events-Read-Encryption-Key")
write_key = crypto.hkdf_sha512(shared, b"Events-Salt",
                               b"Events-Write-Encryption-Key")

cipher = controlcipher.ControlCipher(read_key, write_key)
wire = cipher.encrypt(frame.encoded())

plain, rest = cipher.decrypt(wire + next_read)
```

Each frame is `[u16 ciphertext length][ciphertext][16-byte Poly1305 tag]`.
The length is the associated data, payloads over `0x4000` bytes split into
several frames, and each direction counts its own 64-bit nonce. `rest` is
fed back into the next `decrypt` so frames split across reads still line up.

The events channel derives each key from the label matching its direction. The
**control** channel is the reverse, and which way round it goes depends on the
role: each peer reads with the key the other writes. `pairverify` handles it,
so this channel only ever receives already-derived keys.

### Pair-Verify

```python
from carplay_proto import controlcipher, pairverify, pubkey

controller = pairverify.PairVerify(
    pairverify.ROLE_CONTROLLER, "iPhone",
    pubkey.ed25519_generate().secret,
    accessory_long_term_public_key)    # from the Pair-Setup store

m2 = <the /pair-verify reply>          # head unit's m2
m3 = controller.handle(m2)             # verifies, answers with m3

keys = controller.control_keys         # .read_key / .write_key
cipher = controlcipher.ControlCipher(keys.read_key, keys.write_key)
```

`controller.begin()` builds m1; `PairVerify(ROLE_ACCESSORY, ...).handle(m1)`
answers with m2. The controller sets `is_verified` and `control_keys` when it
processes m2, before it sends m3; the head unit's m4 is an acknowledgement
that `handle` accepts with `None`. A message that cannot be accepted returns
the TLV8 error reply (state plus error code `2`) instead of raising, so a
misbehaving peer never kills the session.

### Pair-Setup

```python
from carplay_proto import pairsetup, pairings, pubkey

store = pairings.PairingStore()
identity = pubkey.ed25519_generate()
accessory_seed = pubkey.ed25519_generate().secret

controller = pairsetup.PairSetup(
    pairsetup.ROLE_CONTROLLER, "iPhone", identity.secret, store)
accessory = pairsetup.PairSetup(
    pairsetup.ROLE_ACCESSORY, "HU", accessory_seed, store)

m2 = accessory.handle(controller.begin())   # B, salt
m4 = accessory.handle(controller.handle(m2))  # m3 -> m4
controller.handle(m4)
m6 = accessory.handle(controller.m5())      # encrypted identity + signature
controller.handle(m6)

assert controller.is_paired
peer_key = store.get("HU")                  # feed this into PairVerify
```

```python
from carplay_proto import pairverify

controller = pairverify.PairVerify(
    pairverify.ROLE_CONTROLLER, "iPhone", identity.secret, peer_key)
```

`PairSetup` implements both roles, so two peers complete the exchange in one
process. m1 and m3 carry plain TLV8; m5 and m6 are sealed with the SRP session
key, so the identifier, method and long-term key never travel in the clear.
Each peer signs `signKey || ownId || ownLTPK` under the sign key derived for
its own role, and checks the peer's under the peer's role key: the key set is
derived from the same session key, so no side needs to send its sign key. The
controller stores the accessory's key by the accessory's identifier, which is
exactly what `PairVerify` needs to check the head unit's m2 signature.

`pairings.PairingStore` keeps identifier -> 32-byte key in memory and can
persist through an optional `on_save` callback; `to_json()`/`from_json()`
round-trip it as hex for the on-disk form.

## Build and test

Python 3.6+, no third-party runtime dependency. Tests use pytest.

```sh
pip3 install pytest
PYTHONPATH=. python3 -m pytest
```

The suite cross-checks the codecs against the golden vectors in the
`xcertplay` reference implementation, including the exact CarPlay
`0x4301` start-session body. `tests/test_crypto.py` carries RFC 8439
known-answer vectors for every primitive, `tests/test_pubkey.py` carries
RFC 7748 (X25519, sections 5.2 and 6.1) and RFC 8032 (Ed25519, section 7.1)
ones, and `tests/test_srp6a.py` carries the RFC 5054 appendix B vectors
(the 1024-bit group, generator 2, `I="alice"`, `P="password123"`). Note the
SRP test vectors live in RFC 5054, not RFC 5055, which is SCVP.
`tests/test_crypto_reference.py` and `tests/test_pubkey_reference.py`
compare against the `cryptography` package and skip where it is absent, which
is the tablet, which has neither `chacha20_poly1305` in its stdlib nor
`hashlib.hkdf`.

Apple's `rpm/libap-lib.so` already exports `chacha20_poly1305_encrypt_all_96x32`,
`poly1305_*`, `NetTransportChaCha20Poly1305Configure` and
`AirPlay_DeriveAESKeySHA512`. It is deliberately not linked: the project stays
dependency-free, and a stripped closed-source binary is not an API to build on.

## License

GPL-3.0-or-later, matching `harbour-sailife`.
