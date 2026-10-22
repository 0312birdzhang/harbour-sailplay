# Accessory certificate compatibility

## Honda report and limits

The report describes an iAP2 `0xaa01` certificate of 908 bytes followed by
`only P256 accessory certificates are supported`. The original Honda
certificate and signature capture have not been provided. No matching Honda
certificate exists among the local/phone captures inspected on 2026-10-22.
The Honda key type and an actual Honda authentication round trip remain
unverified. Certificate/container size alone does not identify its public key.

The old exception occurred **after** OpenSSL had parsed the CMS/PKCS#7
container, found one certificate, and extracted/serialized its public key.
It was a rejection by our SPKI encoding policy, not evidence that OpenSSL
failed to parse the certificate. The previous check accepted only 91 bytes
with the prefix for a named-curve, uncompressed P-256 point.

There are at least two distinct compatibility problems:

| Public key | Example SPKI length | Old result | Compatibility profile |
| --- | ---: | --- | --- |
| P-256, named/uncompressed | 91 | accepted | ECDSA, 32-byte SHA-256 digest |
| P-256, compressed point | 59 | incorrectly rejected | same ECDSA profile |
| P-256, explicit parameters | 335 | incorrectly rejected | same ECDSA profile |
| RSA-1024 | 162 | rejected | legacy RSA PKCS#1 v1.5, 20-byte SHA-1 digest |
| Other EC curves/key types | varies | rejected | remain rejected with a specific error |

Lengths above describe generated test keys, not the missing Honda sample.

## Research evidence

- [Apple Platform Security: verifying accessories](https://support.apple.com/en-ca/guide/security/sec70a4f377d/web)
  describes certificate/challenge authentication and the older RSA-1024
  authentication IC in the MFi-SAP path. It does not identify this Honda's key.
- The supplied `DiPlay-Legacy-Android` source,
  `shared/src/main/java/com/shilapi/xcertplay/airplay/MfiSapAuthSetup.kt`, selects
  SHA-1 for protocol major 2 and SHA-256 otherwise. Its local P-256 signer uses
  `NONEwithECDSA`: the challenge is already a digest and must not be hashed
  again. These are accessory-side references; they are not a Honda trace.
- [OpenSSL EVP_PKEY_verify](https://docs.openssl.org/3.0/man3/EVP_PKEY_verify/)
  documents digest verification and explicit RSA PKCS#1 padding selection.

The X.509 certificate's **issuer signature algorithm** is a different field
from its **subject public key** and the challenge signature algorithm. Do not
select the challenge format from `signatureAlgorithm` or certificate size.

## Implementation in 0.1.1-48

`carplay_proto/accessoryauth.py` now inspects OpenSSL key types, key sizes and
actual EC domain parameters. It accepts equivalent P-256 encodings without
comparing a DER prefix. `EC_GROUP_cmp` also prevents accepting secp256k1 merely
because it has 256-bit keys. OpenSSL 1.1/3 exported API names are supported.

The legacy RSA profile is `rsa-pkcs1v15-sha1`: a random 20-byte challenge is
treated as an already-computed digest, with PKCS#1 v1.5 verification and a
signature exactly as long as the modulus. The current bounded implementation
accepts 1024..4096-bit RSA keys; 1024/2048-bit examples were tested. This is a
legacy interoperability path, not a recommendation for new cryptosystems.
P-256 retains its existing 32-byte challenge and raw/DER ECDSA verification.

There is no algorithm guessing after verification fails, no signature bypass,
and no replacement of an existing certificate pin. A newly paired device's
pin is still saved only after it proves possession of the certificate's key.
This remains key-possession/observed-certificate pinning, **not Apple CA-chain
validation**. Ambiguous multi-certificate containers and trailing data fail
closed. An explicitly exported offline pin remains an operator action.

Persistent Bluetooth logs now record the selected algorithm, key size,
SPKI length, challenge length and signature-response length. Public certificates
continue to be saved before authentication, including on failure.

For offline inspection on the phone (root may be needed to read the file):

```sh
python3 /opt/sailplay/scripts/inspect-accessory-certificate.py \
  /var/lib/sailplay/accessories/dev_74_D7_CA_65_F7_1B.der
```

This reports public metadata without network operations, private keys or pin
writes. Missing Honda data is not fabricated or replaced by another identity.

## Validation

The focused certificate, wireless-probe, iAP2 and Bluetooth-adapter run passed
52 tests. Release 0.1.1-48 was installed on the phone; rpm verification was
clean and the installed authentication module matched the tested source hash.
The five public proof vectors were repeated against the installed module.

- Generated RSA-1024/RSA-2048 and named/compressed/explicit P-256 cases passed
  on Linux and on the phone's system OpenSSL. Tests include rejected altered
  signatures, replay, algorithm/key mismatch, double hashing, wrong RSA padding,
  changed certificates and trailing bytes; failed first-use proof leaves no pin.
- Socket-pair iAP2 tests exercise the real wireless probe: RSA/P-256 challenges
  have the correct length, `0xaa05` and Wi-Fi requests follow verified proof
  only, and invalid signatures end the session without pinning.
- All five previously captured phone certificates and the existing saved
  P-256 pins loaded through the new implementation. No stored pins were changed.
- These checks establish parser/verifier and protocol-test compatibility.
  They do **not** establish successful connection to the reported Honda.
