"""Checked source-only upgrade. Runtime data and client configuration are never payloads."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


def digest(path):
    if not Path(path).exists():
        return None
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_source_path(value):
    path = PurePosixPath(value)
    if (not isinstance(value, str) or '\\' in value or ':' in value or path.is_absolute()
            or not path.parts or any(part in ('..', '.', '') for part in value.split('/'))):
        raise ValueError('Invalid payload path')
    if len(path.parts) == 1:
        allowed = path.suffix in ('.py', '.ps1', '.cmd', '.ico', '.md') or value in ('ocx.exe', 'team-install-source.json')
    else:
        allowed = path.parts[0] in ('bin', 'native', 'scripts', 'packaging', 'docs', 'dashboard', 'serena', 'gui')
        allowed = allowed and not any(part.startswith('.') or part in ('node_modules', '__pycache__') for part in path.parts)
        allowed = allowed and (value == 'dashboard/LICENSE' or path.suffix in ('.py', '.ps1', '.cmd', '.exe', '.cs', '.html', '.yml', '.json', '.txt', '.md', '.patch', '.css', '.js', '.svg', '.png', '.ico', '.woff2'))
    if not allowed:
        raise ValueError('Payload contains runtime state or an unsupported source file')
    return str(path)


def checked(root, relative):
    root = Path(root).absolute()
    result = root / safe_source_path(relative)
    # Check every ancestor before resolving; resolution would hide junctions.
    for part in (result, *result.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Linked source or destination is not upgradeable')
    result.resolve().relative_to(root.resolve())
    if result.exists() and not result.is_file():
        raise ValueError('Source destination is not a file')
    return result


def replace(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.cts-upgrade-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(plan):
    replace(Path(plan['backup']) / 'journal.json', json.dumps(plan, indent=2).encode())


@contextmanager
def locked(plan):
    path = Path(plan['backup']) / 'operation.lock'
    # OS-owned locks release on a crash. Keep the lock inode so contenders cannot
    # obtain different locks by deleting/recreating it between transactions.
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def prepare(groups, backup):
    """Record hashes and original bytes before any destination writes."""
    entries, seen = [], set()
    for source, destination, files in groups:
        for item in files:
            relative = safe_source_path(item['path'])
            src, dst = checked(source, relative), checked(destination, relative)
            if str(dst).casefold() in seen:
                raise ValueError('Duplicate destination')
            seen.add(str(dst).casefold())
            if not re.fullmatch('[a-f0-9]{64}', item['sha256']) or digest(src) != item['sha256']:
                raise RuntimeError('Payload changed or failed its checksum')
            before = digest(dst)
            if before != item['sha256']:
                entries.append({'source_root': str(Path(source).absolute()), 'root': str(Path(destination).absolute()),
                    'path': relative, 'before': before, 'after': item['sha256']})
    backup = Path(backup).absolute()
    for part in (backup, *backup.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Linked backup directory')
    backup.mkdir(parents=True, exist_ok=False)
    plan = {'schema': 1, 'backup': str(backup), 'phase': 'prepared', 'files': entries}
    for index, item in enumerate(entries):
        dst = checked(item['root'], item['path'])
        if digest(dst) != item['before']:
            raise RuntimeError('Installed source changed during preparation')
        if item['before'] is not None:
            data = dst.read_bytes()
            if hashlib.sha256(data).hexdigest() != item['before']:
                raise RuntimeError('Installed source changed during backup')
            replace(backup / f'{index}.original', data)
    save(plan)
    return plan


def _rollback(plan):
    # Preflight every rollback first. Never clobber an edit made after the upgrade.
    for index, item in enumerate(plan['files']):
        dst = checked(item['root'], item['path'])
        if digest(dst) not in (item['before'], item['after']):
            raise RuntimeError('Installed source changed; automatic rollback refused')
        if item['before'] is not None and digest(Path(plan['backup']) / f'{index}.original') != item['before']:
            raise RuntimeError('Original backup failed its checksum')
    for index in reversed(range(len(plan['files']))):
        item = plan['files'][index]
        dst = checked(item['root'], item['path'])
        current = digest(dst)
        if current == item['before']:
            continue
        if current != item['after']:
            raise RuntimeError('Installed source changed during rollback')
        if item['before'] is None:
            dst.unlink()  # Only the exact individually recorded new file, never a tree.
        else:
            data = (Path(plan['backup']) / f'{index}.original').read_bytes()
            if hashlib.sha256(data).hexdigest() != item['before']:
                raise RuntimeError('Original backup changed during rollback')
            replace(dst, data)
    plan['phase'] = 'rolled_back'; save(plan)


def rollback(plan):
    with locked(plan):
        _rollback(plan)


def apply(plan):
    with locked(plan):
        if plan['phase'] != 'prepared':
            raise RuntimeError('Upgrade plan is not prepared')
        for item in plan['files']:
            if (digest(checked(item['root'], item['path'])) != item['before']
                    or digest(checked(item['source_root'], item['path'])) != item['after']):
                raise RuntimeError('Source or destination changed since preparation')
        plan['phase'] = 'applying'; save(plan)
        try:
            for item in plan['files']:
                dst = checked(item['root'], item['path'])
                data = checked(item['source_root'], item['path']).read_bytes()
                if digest(dst) != item['before'] or hashlib.sha256(data).hexdigest() != item['after']:
                    raise RuntimeError('Source or destination changed during upgrade')
                replace(dst, data)
            if any(digest(checked(item['root'], item['path'])) != item['after'] for item in plan['files']):
                raise RuntimeError('Installed source changed before verification')
            plan['phase'] = 'complete'; save(plan)
        except BaseException:
            _rollback(plan)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('upgrade', 'rollback'))
    parser.add_argument('--package', type=Path)
    parser.add_argument('--opencodex-package', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--opencodex', type=Path)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'rollback':
        plan = json.loads((args.backup / 'journal.json').read_text())
        if Path(plan['backup']).resolve() != args.backup.resolve() or plan['schema'] != 1:
            raise ValueError('Backup identity mismatch')
        rollback(plan)
    else:
        if any(value is None for value in (args.package, args.opencodex_package, args.bundle, args.opencodex)):
            parser.error('Upgrade requires both packages and both destinations')
        manifest = json.loads((args.package / 'package-manifest.json').read_text(encoding='utf-8-sig'))
        ocx = json.loads((args.opencodex_package / 'package-manifest.json').read_text(encoding='utf-8-sig'))
        # Prepare the installer identity as another rollback-protected source file.
        with tempfile.TemporaryDirectory(prefix='cts-upgrade-marker-') as temporary:
            marker = Path(temporary) / 'team-install-source.json'
            marker.write_text(json.dumps({'version': manifest['version'], 'package_sha256': digest(args.package / 'package-manifest.json')}))
            groups = [(args.package / 'payload', args.bundle, manifest['files']),
                (args.opencodex_package, args.opencodex, ocx['files']),
                (Path(temporary), args.bundle, [{'path': marker.name, 'sha256': digest(marker)}])]
            plan = prepare(groups, args.backup)
            print(f"Backed up {len(plan['files'])} source files to {args.backup}", flush=True)
            apply(plan)
    print(json.dumps({'phase': plan['phase'], 'backup': plan['backup']}))


if __name__ == '__main__':
    main()
