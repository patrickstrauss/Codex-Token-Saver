"""Bounded housekeeping for owned update artifacts, never user data or shared caches.

CLI previews by default. Apply uses the same lock as updates/disable, protects
selected and rollback runtimes, and refuses runtime deletion if an older Python
worker could still have imported an earlier selection. File byte counts are
logical sizes: hardlinks mean they are not promises of recovered disk space.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
import time

DAY = 86400
RUNTIME_FAMILIES = {'updates/runtimes': 'headroom', 'serena/runtimes': 'serena', 'laya/runtimes': 'laya'}
MANIFESTS = ('updates/active.json', 'serena/runtime.json', 'laya/runtime.json', 'updates/rtk.json', 'updates/rtk-pending.json')


def _linked(path):
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except AttributeError:
        return path.is_symlink()
    except FileNotFoundError:
        return False


def confined(root, relative):
    if not isinstance(relative, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', relative):
        raise ValueError('Unsafe housekeeping path.')
    if any(p in ('.', '..') for p in relative.split('/')):
        raise ValueError('Unsafe housekeeping path.')
    path = root / relative
    for part in (path, *path.parents):
        if _linked(part):
            raise ValueError('Linked housekeeping paths are preserved.')
    path.resolve().relative_to(root.resolve())
    return path


def _record(root, relative):
    path = confined(root, relative)
    if not path.exists():
        return {}
    with path.open('rb') as stream:
        data = stream.read(65537)
    value = json.loads(data.decode('utf-8-sig'))
    if len(data) > 65536 or not isinstance(value, dict):
        raise ValueError('Invalid runtime metadata; housekeeping skipped.')
    return value


def _selection(root):
    protected, changed = set(), 0
    for relative in MANIFESTS:
        record = _record(root, relative)
        path = root / relative
        if path.exists():
            changed = max(changed, path.stat().st_mtime)
        if not record:
            continue
        schema = record.get('schema_version' if relative.startswith(('serena/', 'laya/')) else 'schema')
        if schema != 1:
            raise ValueError('Unknown runtime metadata; housekeeping skipped.')
        if relative == 'updates/active.json':
            entries = [record.get('headroom'), record.get('headroom_previous')]
            if isinstance(record.get('headroom'), dict):
                entries.append(record['headroom'].get('previous'))
            field = 'runtime'
        else:
            entries = [record, record.get('previous')]
            field = 'python_path' if relative.startswith(('serena/', 'laya/')) else 'path'
        for entry in entries:
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ValueError('Invalid rollback metadata; housekeeping skipped.')
            name = entry.get(field)
            if name is None:
                if field == 'python_path' or (field == 'runtime' and (field not in entry or not isinstance(entry.get('version'), str))):
                    raise ValueError('Incomplete runtime selection.')
                continue  # Baseline runtimes are never candidates.
            path = confined(root, name)
            if field == 'python_path':
                if path.name != 'python.exe' or path.parent.name != 'Scripts':
                    raise ValueError('Invalid Python runtime selection.')
                path = path.parent.parent
            protected.add(path.relative_to(root).as_posix().casefold())
    return protected, changed


def running_workers(root):
    """Only aggregate runtime paths/start times leave CIM; no command lines logged."""
    if os.name != 'nt':
        raise RuntimeError('Running-worker inspection is unavailable.')
    import base64
    escaped = str(root).replace("'", "''")
    script = r"""
$ErrorActionPreference='Stop'
$root='ROOT_VALUE'
$pattern=[regex]::Escape($root)+'[\\/](?:(?:updates|serena|laya)[\\/]runtimes[\\/][A-Za-z0-9.-]+|updates[\\/]verification-bundle-[0-9]{8})'
$items=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
    $text=[string]$_.ExecutablePath+' '+[string]$_.CommandLine
    if ($_.ProcessId -ne CLEANER_PID -and $text -notmatch '[\\/]dashboard[\\/]app\.py(?:"|\s|$)' -and $text.IndexOf($root,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        if (-not $_.CreationDate) { throw 'Missing worker start time' }
        [pscustomobject]@{started=([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds()/1000.0;refs=@([regex]::Matches($text,$pattern,'IgnoreCase') | ForEach-Object { $_.Value.Substring($root.Length+1).Replace('\','/') })}
    }
})
ConvertTo-Json -InputObject $items -Compress -Depth 4
""".replace('ROOT_VALUE', escaped).replace('CLEANER_PID', str(os.getpid()))
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    exe = Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, timeout=25, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    workers = json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(workers, list) or any(not isinstance(w, dict) or not isinstance(w.get('started'), (float, int))
                                          or not isinstance(w.get('refs'), list) for w in workers):
        raise RuntimeError('Invalid worker inspection.')
    return workers


def _tree_size(path):
    total = 0
    for folder, dirs, files in os.walk(path):
        for name in dirs + files:
            item = Path(folder) / name
            if _linked(item):
                raise ValueError('Linked artifact preserved.')
        for name in files:
            total += (Path(folder) / name).stat().st_size
    return total


def _candidates(root, protected, changed, workers, legacy_tests, clock, fresh=()):
    live = {name.casefold() for worker in workers for name in worker['refs']}
    # Baseline MCP launchers can import a selected runtime without its path on
    # their command line. Older workers therefore protect ALL old runtimes.
    old_worker = any(worker['started'] <= changed for worker in workers)
    candidates = []
    for parent, component in RUNTIME_FAMILIES.items():
        directory = confined(root, parent)
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if not re.fullmatch(component + r'-[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{32}', path.name):
                continue
            relative = path.relative_to(root).as_posix()
            if old_worker and relative not in fresh:
                continue
            if relative.casefold() in protected or relative.casefold() in live:
                continue
            path = confined(root, relative)
            if path.is_dir() and (relative in fresh or clock - path.stat().st_mtime >= DAY):
                candidates.append((relative, 'obsolete_runtime'))
    validation = confined(root, 'updates/validation')
    if validation.exists() and not old_worker:
        for path in validation.iterdir():
            if re.fullmatch('[a-f0-9]{32}', path.name) and clock - path.stat().st_mtime >= DAY:
                candidates.append((path.relative_to(root).as_posix(), 'old_validation'))
    # Historical one-off verification bundles are opt-in, not ordinary startup cleanup.
    if legacy_tests and not old_worker:
        for path in confined(root, 'updates').glob('verification-bundle-*'):
            relative = path.relative_to(root).as_posix()
            if (re.fullmatch(r'verification-bundle-[0-9]{8}', path.name)
                    and relative.casefold() not in live and clock - path.stat().st_mtime >= DAY
                    and (path / 'bundle_updates.py').is_file() and (path / 'headroom/.venv/pyvenv.cfg').is_file()):
                candidates.append((relative, 'legacy_test_fixture'))
    return candidates, old_worker


def _prune_caches(root):
    results = []
    uv = confined(root, 'tools/uv.exe')
    for relative in ('updates/cache', 'downloads/uv-cache'):
        cache = confined(root, relative)
        if not cache.is_dir():
            continue
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('UV_', 'PIP_'))}
        env.update(UV_NO_CONFIG='1', UV_LOCK_TIMEOUT='1', UV_PYTHON_DOWNLOADS='never')
        try:
            result = subprocess.run([str(uv), '--no-config', 'cache', 'prune', '--ci', '--cache-dir', str(cache)],
                                    env=env, capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            results.append({'path': relative, 'status': 'pruned' if result.returncode == 0 else 'deferred'})
        except (OSError, subprocess.SubprocessError):
            results.append({'path': relative, 'status': 'deferred'})
    return results


def cleanup(root, *, apply=False, automatic=False, legacy_tests=False, lock_held=False, fresh_candidates=()):
    root = Path(root).absolute()
    report = {'schema': 1, 'at': datetime.now(timezone.utc).isoformat(), 'applied': apply,
              'artifacts': [], 'caches': [], 'errors': [], 'logical_bytes_removed': 0}
    try:
        for marker in ('packaging/dependencies.json', 'headroom/.venv/pyvenv.cfg', 'tools/uv.exe'):
            if not confined(root, marker).is_file():
                return dict(report, skipped='Not an installed managed bundle.')
        if automatic:
            previous = _record(root, 'updates/storage-cleanup.json')
            if previous.get('completed_at', 0) > time.time() - DAY:
                return dict(report, skipped='Housekeeping already completed today.')
        if not lock_held:
            from desktop_proxy_control import routing_lock
            with routing_lock(confined(root, 'updates/operation.lock')):
                return cleanup(root, apply=apply, automatic=automatic, legacy_tests=legacy_tests,
                               lock_held=True, fresh_candidates=fresh_candidates)
        protected, changed = _selection(root)
        workers = running_workers(root)
        candidates, old_worker = _candidates(root, protected, changed, workers, legacy_tests, time.time(), fresh_candidates)
        report['older_workers_preserved'] = old_worker
        for relative, reason in candidates:
            try:
                path = confined(root, relative)
                size = _tree_size(path)
                if apply:
                    # Recheck both selections and process state immediately before removal.
                    current, latest = _selection(root)
                    allowed, _ = _candidates(root, current, latest, running_workers(root), legacy_tests, time.time(), fresh_candidates)
                    if (relative, reason) not in allowed:
                        continue
                    confined(root, relative)
                    _tree_size(path)
                    shutil.rmtree(path)
                    report['logical_bytes_removed'] += size
                report['artifacts'].append({'path': relative, 'reason': reason, 'logical_bytes': size})
            except (OSError, ValueError):
                report['errors'].append({'path': relative, 'message': 'Artifact preserved or cleanup deferred.'})
        if apply:
            # Use uv's own locked cache API; never rmtree cache internals or touch
            # the user's shared uv/Hugging Face caches or running uv tool environments.
            report['caches'] = _prune_caches(root)
            report['completed_at'] = time.time()
            from desktop_proxy_control import atomic_write
            atomic_write(confined(root, 'updates/storage-cleanup.json'), (json.dumps(report, indent=2) + '\n').encode())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report['skipped'] = type(error).__name__ + ': housekeeping deferred; active files preserved.'
    return report


def start_housekeeping(root):
    """One lightweight dashboard thread; no extra Python process or hot-path work."""
    def worker():
        while True:
            cleanup(root, apply=True, automatic=True)
            time.sleep(DAY)
    thread = threading.Thread(target=worker, name='storage-housekeeping', daemon=True)
    thread.start()
    return thread


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Remove only unreferenced owned update artifacts and prune private caches.')
    parser.add_argument('--legacy-tests', action='store_true', help='Also include obsolete, verified one-off test bundles in updates/.')
    args = parser.parse_args()
    print(json.dumps(cleanup(args.root, apply=args.apply, legacy_tests=args.legacy_tests)))
