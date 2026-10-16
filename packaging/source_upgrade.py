"""Transactional source updates. Runtime updates remain separately validated operations."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import os


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(root, name):
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', name)
            or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('Unsafe manifest path')
    for part in name.split('/'):
        if part.endswith('.') or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise ValueError('Unsafe Windows filename')
    path = root.joinpath(*PurePosixPath(name).parts)
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Linked installation paths are unsupported')
        if item == root:
            break
    path.resolve().relative_to(root.resolve())
    return path


def manifest(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('schema_version') != 1 or not value.get('files'):
        raise ValueError('Invalid manifest')
    files = {}
    for entry in value['files']:
        name, checksum = entry['path'], entry['sha256']
        checked_path(path.parent, name)
        if name.casefold() in {n.casefold() for n in files} or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('Duplicate path or invalid checksum')
        files[name] = checksum
    return value, files


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def upgrade(root, package, *, plan=False, validate=None):
    root, package = Path(root).absolute(), Path(package).absolute()
    receipt = checked_path(root, 'packaging/installed-manifest.json')
    if not receipt.is_file():
        raise ValueError('This older/source installation has no ownership manifest. Use the migration guide; nothing was replaced.')
    old, owned = manifest(receipt)
    new, incoming = manifest(package / 'package-manifest.json')
    payload = package / 'payload'
    contents = {}
    for name, checksum in incoming.items():
        data = checked_path(payload, name).read_bytes()
        if digest(data) != checksum:
            raise ValueError('Package checksum mismatch: ' + name)
        contents[name] = data
    for name, checksum in owned.items():
        if digest(checked_path(root, name).read_bytes()) != checksum:
            raise ValueError('Installed source changed; preserved: ' + name)
    for name in incoming.keys() - owned.keys():
        if checked_path(root, name).exists():
            raise ValueError('Unowned destination file; preserved: ' + name)
    # An app source update must not claim to have upgraded an existing runtime.
    for name in owned.keys() | incoming.keys():
        if name.startswith('packaging/') and (name.endswith('.txt') or name.endswith('.json')):
            if owned.get(name) != incoming.get(name):
                raise ValueError('Runtime pins changed. Use the clean reinstall procedure: ' + name)
    changed = {n for n in owned.keys() | incoming.keys() if owned.get(n) != incoming.get(n)}
    if plan:
        return {'plan': True, 'from': old['version'], 'to': new['version'], 'changed_files': sorted(changed)}
    marker = checked_path(root, 'team-install-source.json')
    targets = {checked_path(root, n): contents.get(n) for n in changed}
    targets[receipt] = (package / 'package-manifest.json').read_bytes()
    targets[marker] = (json.dumps({'version': new['version'], 'package_sha256':
                                   digest(targets[receipt])}) + '\n').encode()
    result_path = checked_path(root, 'team-install-result.json')
    if result_path.exists():
        result_value = json.loads(result_path.read_text(encoding='utf-8-sig'))
        result_value.update(version=new['version'], source_sha256=digest(targets[receipt]))
        targets[result_path] = (json.dumps(result_value, indent=2) + '\n').encode()
    before = {p: p.read_bytes() if p.exists() else None for p in targets}
    backup = checked_path(root, 'backups/app-upgrade-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    for path, data in before.items():
        if data is not None:
            destination = backup / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    (backup / 'transaction.json').write_text(json.dumps({str(p.relative_to(root)): data is not None
                                                         for p, data in before.items()}, indent=2))
    applied = []
    try:
        for path, data in targets.items():
            if (path.read_bytes() if path.exists() else None) != before[path]:
                raise RuntimeError('Concurrent modification; stopped: ' + path.name)
            if data is None:
                path.unlink()
            else:
                atomic_write(path, data)
            applied.append(path)
        if validate:
            validate(root)
    except Exception:
        for path in reversed(applied):
            current = path.read_bytes() if path.exists() else None
            if current != targets[path]:
                raise RuntimeError('Concurrent edit during rollback; keep backup: ' + str(backup))
            if before[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, before[path])
        raise
    return {'updated': True, 'version': new['version'], 'backup': str(backup), 'changed_files': len(changed)}


def validate_runtime(root):
    subprocess.run([str(root / 'headroom/.venv/Scripts/python.exe'),
                    str(root / 'packaging/verify_install.py'), str(root)],
                   check=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    # Same byte-range lock as library updates and disable operations.
    import sys
    sys.path.insert(0, str(args.root))
    from desktop_proxy_control import routing_lock
    with routing_lock(args.root / 'updates/operation.lock'):
        print(json.dumps(upgrade(args.root, args.package, plan=args.plan, validate=validate_runtime)))
