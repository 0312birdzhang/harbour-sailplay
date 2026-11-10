#!/usr/bin/env python3
"""Apply the native Mconnect lifecycle integration with source identity guards."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SDK_REPO = HERE.parents[2]


def target_path(root, relative):
    target = root / relative
    target.resolve().relative_to(root)
    if target.is_symlink():
        raise RuntimeError('Integration target is a symlink ' + relative)
    return target


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def contents(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError('Integration target must be a file ' + str(path))
    return path.read_bytes()


def write_atomic(path, data, created_directories):
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir()
        created_directories.append(directory)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, name = tempfile.mkstemp(prefix='.sailplay-sdk-', dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        temporary.chmod(mode)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def apply(checkout, check=False):
    checkout = checkout.resolve(strict=True)
    manifest = json.loads((HERE / 'baseline.json').read_text(encoding='utf-8'))
    snapshots = {}
    expected_after = {}
    original, patched = True, True
    for record in manifest['files']:
        target = target_path(checkout, record['path'])
        current = contents(target)
        original = original and digest(current) == record['before_sha256']
        patched = patched and digest(current) == record['after_sha256']
        snapshots[target] = current
        expected_after[target] = record['after_sha256']
    if not original and not patched:
        raise RuntimeError('Native source differs from the integration baseline or complete applied state')
    overlay = {}
    for record in manifest['sdk_files']:
        source = target_path(SDK_REPO, record['source'])
        value = source.read_bytes()
        if digest(value) != record['sha256']:
            raise RuntimeError('SDK source differs from the integration manifest ' + record['source'])
        target = target_path(checkout, record['path'])
        current = contents(target)
        if current is not None and digest(current) != record['sha256']:
            raise RuntimeError('Existing SDK overlay differs ' + record['path'])
        snapshots[target] = current
        expected_after[target] = record['sha256']
        overlay[target] = value
    patch = (HERE / 'lifecycle.patch').read_bytes()
    if digest(patch) != manifest['patch_sha256']:
        raise RuntimeError('Lifecycle patch differs from the integration manifest')
    native = {}
    if original:
        # Validate exact patch bytes outside the checkout's line-ending and attribute rules.
        with tempfile.TemporaryDirectory(prefix='sailplay-mconnect-patch-') as staging_name:
            staging = Path(staging_name).resolve()
            for record in manifest['files']:
                source = target_path(checkout, record['path'])
                if snapshots[source] is not None:
                    target = target_path(staging, record['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(snapshots[source])
            command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
                       '-c', 'core.attributesFile=' + os.devnull, 'apply']
            subprocess.run(command + ['--check', '-'], input=patch, cwd=str(staging), check=True)
            if not check:
                subprocess.run(command + ['-'], input=patch, cwd=str(staging), check=True)
                for record in manifest['files']:
                    value = contents(target_path(staging, record['path']))
                    if digest(value) != record['after_sha256']:
                        raise RuntimeError('Prepared patch file differs ' + record['path'])
                    native[target_path(checkout, record['path'])] = value
    if check:
        return {'source': 'applied' if patched else 'baseline', 'checked_files': len(snapshots)}
    for target, previous in snapshots.items():
        if contents(target) != previous:
            raise RuntimeError('Integration target changed during verification ' + str(target))
    created_directories = []
    written_targets = []
    try:
        for target, value in list(native.items()) + list(overlay.items()):
            if contents(target) != snapshots[target]:
                raise RuntimeError('Integration target changed during application ' + str(target))
            if contents(target) != value:
                write_atomic(target, value, created_directories)
                written_targets.append(target)
        for target, expected in expected_after.items():
            if digest(contents(target)) != expected:
                raise RuntimeError('Applied file differs ' + str(target))
    except Exception:
        for target in reversed(written_targets):
            previous = snapshots[target]
            if digest(contents(target)) == expected_after[target]:
                if previous is None:
                    target.unlink()
                else:
                    write_atomic(target, previous, created_directories)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return {'source': 'applied', 'verified_files': len(expected_after)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path, help='Native flutter-sailfishos checkout matching the release 51 baseline')
    parser.add_argument('--check', action='store_true', help='Validate source and SDK identity')
    arguments = parser.parse_args()
    print(json.dumps(apply(arguments.checkout, arguments.check)))
