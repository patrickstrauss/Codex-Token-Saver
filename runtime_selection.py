"""Select a validated local Headroom environment before third-party imports.

The desktop continues launching its original Python executable. A fresh worker
can use a staged environment's packages; an already running process stays pinned.
This module never writes Codex configuration or activates an update manifest.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import threading

ROOT = Path(__file__).resolve().parent
_lock = threading.RLock()
_pinned = None
_dll_handles = []
_BOOTSTRAP_MODULES = {'_virtualenv', 'pywin32_bootstrap', 'pywin32_system32'}


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def _text(path: Path, boundary: Path, limit: int = 65536) -> str:
    if not _inside(path, boundary):
        raise ValueError('Runtime marker escapes its managed directory')
    with path.open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Runtime marker is too large')
    return data.decode('utf-8-sig')


def _python_version(runtime: Path):
    text = _text(runtime / 'pyvenv.cfg', runtime)
    values = dict(line.partition('=')[::2] for line in text.splitlines() if '=' in line)
    values = {key.strip(): value.strip() for key, value in values.items()}
    if values.get('include-system-site-packages', 'false').lower() != 'false':
        raise ValueError('Runtime must isolate its packages')
    match = re.match(r'^(\d+)\.(\d+)(?:\.|\s|$)', values.get('version_info', values.get('version', '')))
    if match is None:
        raise ValueError('Runtime Python version is unavailable')
    return tuple(map(int, match.groups()))


def _version(runtime: Path):
    site = runtime / 'Lib/site-packages'
    matches = []
    for path in site.glob('headroom*.dist-info/METADATA'):
        fields = {}
        for line in _text(path, runtime).splitlines():
            key, separator, value = line.partition(':')
            if separator and key in ('Name', 'Version'):
                fields[key] = value.strip()
        name = fields.get('Name', '').lower().replace('_', '-')
        if name == 'headroom-ai':
            matches.append(fields.get('Version'))
    if len(matches) != 1 or not isinstance(matches[0], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.!+_-]{0,79}', matches[0]):
        raise ValueError('Headroom distribution metadata is missing or inconsistent')
    return matches[0]


def _descriptor(root: Path, runtime: Path, source: str, expected_python, expected_version=None):
    site = runtime / 'Lib/site-packages'
    if not runtime.is_dir() or not site.is_dir() or not _inside(site, runtime):
        raise ValueError('Runtime packages are missing or outside the environment')
    if _python_version(runtime) != tuple(expected_python):
        raise ValueError('Runtime Python version is incompatible')
    for name in ('headroom', 'mcp', 'tomlkit'):
        marker = site / name / '__init__.py'
        if not marker.is_file() or not _inside(marker, runtime):
            raise ValueError('Required runtime packages are missing or outside the environment')
    version = _version(runtime)
    if expected_version is not None and version != expected_version:
        raise ValueError('Headroom version does not match the manifest')
    return {'source': source, 'runtime': str(runtime.resolve()), 'site_packages': str(site.resolve()),
            'version': version, 'diagnostic': None}


def _baseline(root: Path, diagnostic=None):
    runtime = root / 'headroom/.venv'
    try:
        version = _version(runtime)
    except (OSError, ValueError, UnicodeError, RuntimeError):
        version = None
    return {'source': 'baseline', 'runtime': str(runtime.resolve()),
            'site_packages': str((runtime / 'Lib/site-packages').resolve()),
            'version': version, 'diagnostic': diagnostic}


def _entry(root: Path, entry, expected_python):
    if not isinstance(entry, dict) or not isinstance(entry.get('runtime'), str) or not isinstance(entry.get('version'), str):
        raise ValueError('Active Headroom entry is invalid')
    value = entry['runtime']
    if '\\' in value or PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
        raise ValueError('Runtime path must be relative to the bundle')
    parts = PurePosixPath(value).parts
    if len(parts) != 3 or parts[:2] != ('updates', 'runtimes') or any(part in ('.', '..') for part in parts):
        raise ValueError('Runtime path is outside the managed runtime directory')
    managed = root / 'updates/runtimes'
    runtime = root.joinpath(*parts).resolve()
    if not _inside(managed, root) or not _inside(runtime, managed) or runtime == managed.resolve():
        raise ValueError('Runtime resolves outside the managed runtime directory')
    return _descriptor(root, runtime, 'active', expected_python, entry['version'])


def selected_runtime(bundle_root=ROOT, *, prefix=None, python_version=None, candidate=None):
    """Read-only descriptor for UI/updater checks; no imports or path changes.

    ``candidate`` is an internal validation entry with the same confined relative
    path/version shape as the manifest. It never activates or writes that entry.
    """
    root = Path(bundle_root).resolve()
    try:
        expected_python = tuple(python_version) if python_version is not None else _python_version(root / 'headroom/.venv')
    except (OSError, ValueError, UnicodeError, RuntimeError):
        expected_python = (3, 13)
    managed = root / 'updates/runtimes'
    current_prefix = Path(sys.prefix if prefix is None else prefix).resolve()
    # The updater starts staged interpreters to validate their own packages. An
    # older active manifest must not replace that interpreter's environment.
    if current_prefix != managed.resolve() and _inside(managed, root) and _inside(current_prefix, managed):
        try:
            return _descriptor(root, current_prefix, 'candidate', expected_python)
        except (OSError, ValueError, UnicodeError, RuntimeError):
            return {'source': 'candidate', 'runtime': str(current_prefix),
                    'site_packages': str(current_prefix / 'Lib/site-packages'),
                    'version': None, 'diagnostic': 'Candidate runtime is incomplete or incompatible'}
    try:
        if candidate is not None:
            if isinstance(candidate, dict) and candidate.get('runtime', ...) is None:
                if not isinstance(candidate.get('version'), str):
                    raise ValueError('Baseline validation entry has no Headroom version')
                return _descriptor(root, root / 'headroom/.venv', 'baseline', expected_python, candidate['version'])
            return _entry(root, candidate, expected_python)
        manifest_path = root / 'updates/active.json'
        if not manifest_path.exists():
            return _baseline(root)
        if not _inside(manifest_path, root):
            raise ValueError('Active runtime manifest resolves outside the bundle')
        manifest = json.loads(_text(manifest_path, root / 'updates'))
        if not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1:
            raise ValueError('Active runtime manifest has an unsupported schema')
        entry = manifest.get('headroom')
        return _baseline(root) if entry is None else _entry(root, entry, expected_python)
    except (OSError, ValueError, UnicodeError, RuntimeError) as error:
        # Diagnostics describe the failed check, never arbitrary manifest data.
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else 'Active runtime manifest or package files are unavailable or invalid'
        return _baseline(root, message)


def _loaded_runtime_packages(baseline: Path, selected: Path):
    for name, module in tuple(sys.modules.items()):
        if name in _BOOTSTRAP_MODULES:
            continue
        locations = []
        file = getattr(module, '__file__', None)
        if isinstance(file, str):
            locations.append(file)
        locations.extend(str(path) for path in getattr(module, '__path__', ()) if isinstance(path, (str, Path)))
        for location in locations:
            path = Path(location)
            if _inside(path, baseline) and not _inside(path, selected):
                return True
    return False


def _package_paths(site: Path):
    """Process only existing, confined directory entries from .pth files."""
    paths = [site]
    for path in sorted(site.glob('*.pth')):
        for line in _text(path, site).splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(('import ', 'import\t')):
                continue
            if PureWindowsPath(line).is_absolute() or PurePosixPath(line).is_absolute():
                continue
            local = (site / line.replace('\\', '/')).resolve()
            if _inside(local, site) and local.is_dir() and local not in paths:
                paths.append(local)
    return paths


def activate_headroom_runtime(bundle_root=ROOT, *, candidate=None):
    """Pin package selection once per process, before MCP/Headroom imports."""
    global _pinned
    with _lock:
        if _pinned is not None:
            return dict(_pinned)
        root = Path(bundle_root).resolve()
        selection = selected_runtime(root, python_version=sys.version_info[:2], candidate=candidate)
        if selection['source'] == 'active':
            baseline = (root / 'headroom/.venv/Lib/site-packages').resolve()
            selected = Path(selection['site_packages'])
            if _loaded_runtime_packages(baseline, selected):
                selection = _baseline(root, 'Headroom packages were already imported; this process keeps its original runtime')
            else:
                old_paths = list(sys.path)
                shims = {name: sys.modules[name] for name in ('pywin32_bootstrap', 'pywin32_system32') if name in sys.modules}
                handles = []
                try:
                    paths = _package_paths(selected)
                    baseline_indices = [i for i, path in enumerate(old_paths) if path and _inside(Path(path), baseline)]
                    insertion = baseline_indices[0] if baseline_indices else next((i for i, path in enumerate(old_paths) if 'site-packages' in path), len(old_paths))
                    kept = [path for path in old_paths if not (path and (_inside(Path(path), baseline) or _inside(Path(path), selected)))]
                    insertion = min(insertion, len(kept))
                    # Keep project modules and stdlib ahead of third-party paths.
                    kept[insertion:insertion] = [str(path) for path in paths]
                    if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
                        dll_paths = [selected, selected / 'pywin32_system32']
                        dll_paths.extend(path for path in selected.iterdir() if path.name.endswith('.libs'))
                        for path in dll_paths:
                            if path.is_dir() and _inside(path, selected):
                                handles.append(os.add_dll_directory(str(path)))
                    sys.path[:] = kept
                    # These startup shims contain no SDK objects or extension
                    # modules. Reload namespace lookup from the selected paths.
                    for name in ('pywin32_bootstrap', 'pywin32_system32'):
                        sys.modules.pop(name, None)
                    importlib.invalidate_caches()
                    _dll_handles.extend(handles)
                except (OSError, ValueError, UnicodeError, RuntimeError):
                    sys.path[:] = old_paths
                    for name in ('pywin32_bootstrap', 'pywin32_system32'):
                        sys.modules.pop(name, None)
                    sys.modules.update(shims)
                    for handle in handles:
                        try:
                            handle.close()
                        except OSError:
                            pass
                    selection = _baseline(root, 'Selected runtime package paths could not be initialized; using baseline')
        _pinned = dict(selection)
        if selection['diagnostic']:
            print('[Headroom runtime] ' + selection['diagnostic'], file=sys.stderr)
        return dict(selection)
