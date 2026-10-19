"""Audit a source release ZIP without extracting or executing its contents."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile


MAX_EXPANDED_BYTES = 64 * 1024 * 1024
ROOT_FILES = frozenset(('package-manifest.json', 'Install.cmd', 'Install.ps1',
    'Upgrade-App.cmd', 'Upgrade-App.ps1', 'Repair-Team-Setup.cmd',
    'Setup-Request-Compression.cmd', 'Disable-Token-Saver.cmd',
    'Uninstall-Token-Saver.cmd', 'Get-Token-Saver-Diagnostics.cmd'))
REQUIRED = frozenset(('README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md',
    'THIRD-PARTY-NOTICES.md', 'docs/INSTALL.md', 'docs/RELEASE-CHECKLIST.md'))
PRIVATE_PARTS = frozenset(('.git', '.scratch', '.venv', '__pycache__', 'node_modules',
    'sessions', 'backups', 'downloads', 'runtimes', 'models', 'desktop-state', 'backend-state'))
PRIVATE_NAMES = frozenset(('auth.json', 'config.toml', '.env', 'hooks.json',
    'activity.db', 'team-install-result.json', 'bundle-state.json', 'desktop-integration.json'))
LINK = re.compile(r'\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)')
PERSONAL_PATH = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s"\'<>]+)', re.I)
EXAMPLE_USERS = frozenset(('public', 'default', 'example', 'user', 'username', 'you', 'alice'))


def checked_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Invalid archive path')
    parts = PurePosixPath(value).parts
    if value.startswith('/') or '..' in parts or any(ord(c) < 32 for c in value):
        raise ValueError('Unsafe archive path')
    if str(PurePosixPath(value)) != value.rstrip('/'):
        raise ValueError('Non-canonical archive path')
    return value.rstrip('/')


def headings(text):
    anchors, counts = set(), {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        anchors.add(slug + ('-' + str(count) if count else ''))
        counts[slug] = count + 1
    anchors.update(re.findall(r'(?:id|name)=["\']([^"\']+)["\']', text))
    return anchors


def documentation_issues(payload):
    issues = []
    for name, raw in payload.items():
        if not name.endswith('.md'):
            continue
        text = raw.decode('utf-8-sig')
        text = re.sub(r'^```[^\n]*\n.*?^```\s*$', '', text, flags=re.M | re.S)
        for match in LINK.finditer(text):
            link = urlsplit(match[1].strip('<>'))
            if link.scheme or link.netloc:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(link.path))) if link.path else name
            if target not in payload:
                issues.append({'file': name, 'check': 'missing_document_link', 'target': target})
            elif link.fragment and target.endswith('.md') and unquote(link.fragment) not in headings(payload[target].decode('utf-8-sig')):
                issues.append({'file': name, 'check': 'missing_document_anchor', 'target': target})
    return issues


def audit(package):
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'package_sha256': None,
              'passed': False, 'issues': [], 'limitations': [
                  'Secret detection is a separate pinned Gitleaks scan.',
                  'Does not qualify Windows 11 desktop/reboot behavior or authenticated coding clients.']}
    issues = report['issues']
    try:
        if package.stat().st_size > MAX_EXPANDED_BYTES:
            raise ValueError('Release exceeds the source-package size budget')
        report['package_sha256'] = hashlib.sha256(package.read_bytes()).hexdigest()
        with ZipFile(package) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
                raise ValueError('Expanded release exceeds the source-package size budget')
            names, roots, files = set(), set(), {}
            for item in entries:
                name = checked_path(item.filename)
                if name.casefold() in names:
                    raise ValueError('Duplicate archive path')
                names.add(name.casefold())
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError('Linked or encrypted archive entry')
                parts = PurePosixPath(name).parts
                roots.add(parts[0])
                if not item.is_dir():
                    if len(parts) < 2:
                        raise ValueError('Files must be inside the package root')
                    relative = '/'.join(parts[1:])
                    files[relative] = archive.read(item)
            if len(roots) != 1:
                raise ValueError('Expected a single package root')
            manifest = json.loads(files['package-manifest.json'].decode('utf-8-sig'))
            if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), list):
                raise ValueError('Unsupported package manifest')
            version = manifest.get('version')
            if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,60}', version):
                raise ValueError('Invalid package version')
            if roots != {'Codex-Token-Saver-' + version + '-windows-x64'}:
                raise ValueError('Package root and manifest version differ')
            payload = {name[len('payload/'):]: raw for name, raw in files.items() if name.startswith('payload/')}
            expected = set()
            for row in manifest['files']:
                name = checked_path(row['path'])
                if name.casefold() in expected:
                    raise ValueError('Duplicate manifest path')
                expected.add(name.casefold())
                if name not in payload or hashlib.sha256(payload[name]).hexdigest() != row['sha256']:
                    issues.append({'file': name, 'check': 'payload_checksum'})
            if expected != {name.casefold() for name in payload}:
                issues.append({'check': 'manifest_payload_set'})
            if set(files) - {'payload/' + name for name in payload} != ROOT_FILES:
                issues.append({'check': 'outer_file_set'})
            for name in sorted(REQUIRED - payload.keys()):
                issues.append({'file': name, 'check': 'required_document'})
            for name, raw in files.items():
                parts = {part.casefold() for part in PurePosixPath(name).parts}
                leaf = PurePosixPath(name).name.casefold()
                suffix = PurePosixPath(name).suffix.casefold()
                if parts & PRIVATE_PARTS or leaf in PRIVATE_NAMES or suffix in ('.db', '.sqlite', '.log', '.pem', '.key', '.onnx', '.safetensors', '.gguf'):
                    issues.append({'file': name, 'check': 'private_or_runtime_file'})
                if suffix == '.exe' and not name.startswith('payload/bin/'):
                    issues.append({'file': name, 'check': 'unexpected_binary'})
                if suffix in ('.md', '.py', '.ps1', '.json', '.js', '.html', '.cmd', '.txt'):
                    for match in PERSONAL_PATH.finditer(raw.decode('utf-8', errors='replace')):
                        if match[1].casefold() not in EXAMPLE_USERS:
                            issues.append({'file': name, 'check': 'personal_windows_path'})
                            break
            issues.extend(documentation_issues(payload))
            report.update(version=version, file_count=len(files),
                          documentation_count=sum(name.endswith('.md') for name in payload),
                          expanded_bytes=sum(item.file_size for item in entries))
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, UnicodeError):
        # No corrupt file contents, personal paths or secret values in public evidence.
        issues.append({'check': 'invalid_package'})
    report['passed'] = not issues
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.package)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'issues': result['issues']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
