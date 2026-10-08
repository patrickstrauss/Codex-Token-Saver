"""Confined runtime selectors shared by optional tools and their updater."""
import json
from pathlib import Path
import re

COMPONENTS = {
    'serena': ('serena/runtime.json', 'serena/.venv/Scripts/python.exe', 'serena-agent'),
    'laya': ('laya/runtime.json', 'laya/.venv/Scripts/python.exe', 'laya'),
}


def runtime_manifest(root, component):
    return Path(root) / COMPONENTS[component][0]


def _package_version(python, package):
    prefix = package.replace('-', '_')
    for metadata in (python.parent.parent / 'Lib/site-packages').glob(prefix + '-*.dist-info/METADATA'):
        with metadata.open(encoding='utf-8') as stream:
            text = stream.read(65536)
        name = re.search(r'(?m)^Name: (.+)$', text)
        version = re.search(r'(?m)^Version: (.+)$', text)
        if name and version and name[1].strip().lower().replace('_', '-') == package:
            return version[1].strip()
    return None


def component_descriptor(root, component):
    root = Path(root).resolve()
    manifest = runtime_manifest(root, component)
    field = 'python_path'
    try:
        with manifest.open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError('Runtime selection is too large.')
        record = json.loads(raw.decode('utf-8-sig'))
        if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
                or record['schema_version'] != 1):
            raise ValueError('Invalid runtime selection.')
        descriptor = {key: record.get(key) for key in ('schema_version', 'version', field)}
    except FileNotFoundError:
        relative = COMPONENTS[component][1]
        path = root / relative
        package = COMPONENTS[component][2]
        version = _package_version(path, package) if path.is_file() else None
        descriptor = {'schema_version': 1, 'version': version, field: relative}
    _confined_path(root, component, descriptor)
    return descriptor


def _confined_path(root, component, descriptor):
    field = 'python_path'
    relative = descriptor.get(field)
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or Path(relative).drive:
        raise ValueError('Runtime path must be bundle-relative.')
    path = (root / relative).resolve()
    base = root / Path(COMPONENTS[component][0]).parent
    if not path.is_relative_to(base) or path.suffix.lower() != '.exe':
        raise ValueError('Runtime path is outside its managed component directory.')
    return path


def runtime_path(root, component, descriptor=None):
    root = Path(root).resolve()
    path = _confined_path(root, component, descriptor or component_descriptor(root, component))
    if not path.is_file():
        raise FileNotFoundError('The selected component runtime is missing.')
    return path
