#!/usr/bin/env python3
"""Offline public certificate -> explicitly pinned P256 verification key."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from cryptography.hazmat.primitives.serialization import pkcs7, Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric import ec

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('certificate')
parser.add_argument('output')
args = parser.parse_args()
certificate = Path(args.certificate).read_bytes()
certificates = pkcs7.load_der_pkcs7_certificates(certificate)
if len(certificates) != 1:
    parser.error('expected exactly one accessory certificate')
key = certificates[0].public_key()
if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
    parser.error('only P256 accessory keys are supported')
pin = {'algorithm': 'ecdsa-p256-sha256',
       'certificate_sha256': hashlib.sha256(certificate).hexdigest(),
       'public_key_der': base64.b64encode(key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode('ascii')}
Path(args.output).write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
