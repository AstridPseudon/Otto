#!/usr/bin/env python3
"""Optional file-mode snapshot helper. Proves file identity, never review or authority."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROLES = {'candidate', 'authority', 'evidence', 'observation'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('invalid relative path')
    p = Path(value)
    if p.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('path must be a normalized relative file path')
    return p


def selected_file(root, name):
    p = root
    for component in relative(name).parts:
        p = p / component
        if p.is_symlink():
            raise ValueError('symlink input is not supported: ' + name)
    if not p.is_file():
        raise ValueError('missing regular input: ' + name)
    return p


def validate_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('explicit nonempty inputs list required')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('input must be an object')
        name = row.get('path')
        relative(name)
        if name in seen:
            raise ValueError('duplicate input: ' + name)
        seen.add(name)
        value = row.get('sha256')
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('expected lowercase SHA-256 required: ' + name)
        if row.get('role') not in ROLES:
            raise ValueError('input role required: ' + name)
    return rows


def verify(packet):
    packet = packet.resolve(strict=True)
    manifest = json.loads(selected_file(packet, 'manifest.json').read_text())
    if manifest.get('version') != 1 or manifest.get('snapshot_root') != 'payload':
        raise ValueError('invalid snapshot root or manifest version')
    payload = packet / 'payload'
    if payload.is_symlink() or not payload.is_dir():
        raise ValueError('snapshot root must be the payload directory')
    rows = validate_rows(manifest.get('inputs'))
    expected = set()
    for row in rows:
        p = selected_file(payload, row['path'])
        data = p.read_bytes()
        if type(row.get('bytes')) is not int or len(data) != row['bytes'] or digest(data) != row['sha256']:
            raise ValueError('snapshot identity mismatch: ' + row['path'])
        expected.add(row['path'])
    actual = set()
    for p in payload.rglob('*'):
        if p.is_symlink():
            raise ValueError('unexpected symlink in payload')
        if p.is_file():
            actual.add(p.relative_to(payload).as_posix())
    if actual != expected:
        raise ValueError('unbound or missing payload files')
    return {'ok': True, 'files': len(rows), 'meaning': 'snapshot identity only'}


def assemble(source_root, selection, output):
    source_root = source_root.resolve(strict=True)
    rows = validate_rows(json.loads(selection.read_text()).get('inputs'))
    # Validate the full selection before creating any output; never discover extra inputs.
    for row in rows:
        if digest(selected_file(source_root, row['path']).read_bytes()) != row['sha256']:
            raise ValueError('stale selected input: ' + row['path'])
    output.mkdir(parents=False, exist_ok=False)  # refuses even an empty existing packet
    payload = output / 'payload'
    payload.mkdir()
    copied = []
    for row in rows:
        data = selected_file(source_root, row['path']).read_bytes()
        if digest(data) != row['sha256']:
            raise ValueError('input changed during assembly: ' + row['path'])
        target = payload / relative(row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(data)
        target.chmod(0o400)
        copied.append({**row, 'bytes': len(data)})
    for row in rows:
        if digest(selected_file(source_root, row['path']).read_bytes()) != row['sha256']:
            raise ValueError('input changed before completion: ' + row['path'])
    manifest = {'version': 1, 'snapshot_root': 'payload',
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'meaning': 'immutable observation of selected bytes; no execution authority or review verdict',
                'inputs': copied}
    # Written last. Interrupted/incomplete packets without a valid manifest cannot verify.
    with (output / 'manifest.json').open('x') as f:
        json.dump(manifest, f, indent=2)
        f.write('\n')
    (output / 'manifest.json').chmod(0o400)
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('assemble')
    build.add_argument('--source-root', type=Path, required=True)
    build.add_argument('--selection', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('--packet', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (assemble(args.source_root, args.selection, args.output)
                  if args.command == 'assemble' else verify(args.packet))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
