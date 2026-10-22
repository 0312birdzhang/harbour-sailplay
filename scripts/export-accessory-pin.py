#!/usr/bin/env python3
"""Offline public certificate -> explicitly pinned accessory verification key."""
import argparse
import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carplay_proto.accessoryauth import certificate_info, certificate_key

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('certificate')
parser.add_argument('output')
args = parser.parse_args()
certificate = Path(args.certificate).read_bytes()
try:
    info, encoded = certificate_info(certificate), certificate_key(certificate)
except (ValueError, OSError) as error:
    parser.error(str(error))
pin = {'algorithm': info['algorithm'],
       'certificate_sha256': info['certificate_sha256'],
       'public_key_der': base64.b64encode(encoded).decode('ascii')}
Path(args.output).write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
