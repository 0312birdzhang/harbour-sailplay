#!/usr/bin/env python3
"""Inspect a public iAP2 CMS certificate; no network, private key or pin writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carplay_proto.accessoryauth import certificate_info

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('certificate', type=Path)
args = parser.parse_args()
try:
    print(json.dumps(certificate_info(args.certificate.read_bytes()), indent=2))
except (ValueError, OSError) as error:
    parser.exit(1, 'Accessory certificate inspection failed: {}\n'.format(error))
