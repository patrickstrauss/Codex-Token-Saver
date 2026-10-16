"""Isolated installed-source upgrade and integration removal qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def qualify(root, package, home):
    sys.path[:0] = [str(root), str(root / 'packaging')]
    from source_upgrade import upgrade, validate_runtime
    from disable_bundle import disable
    from unregister_install import unregister
    protected = {p: p.read_bytes() for p in home.iterdir() if p.is_file()}
    marker = (root / 'team-install-source.json').read_bytes()
    old_readme = (root / 'README.md').read_bytes()
    candidate = root.parent / 'upgrade-candidate'
    shutil.copytree(package, candidate)
    readme = candidate / 'payload/README.md'
    readme.write_bytes(old_readme + b'\nSynthetic source upgrade qualification.\n')
    manifest_path = candidate / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    manifest['version'] += '-qualification'
    for entry in manifest['files']:
        if entry['path'] == 'README.md':
            entry['sha256'] = hashlib.sha256(readme.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    assert upgrade(root, candidate, plan=True)['changed_files'] == ['README.md']

    def fail(_):
        raise RuntimeError('injected validation failure')

    try:
        upgrade(root, candidate, validate=fail)
    except RuntimeError as error:
        assert str(error) == 'injected validation failure'
    else:
        raise AssertionError('An invalid source update succeeded')
    assert (root / 'README.md').read_bytes() == old_readme
    assert (root / 'team-install-source.json').read_bytes() == marker
    assert upgrade(root, candidate, validate=validate_runtime)['updated']
    assert (root / 'README.md').read_bytes() == readme.read_bytes()
    assert all(p.read_bytes() == b for p, b in protected.items()), 'Upgrade changed Codex settings'
    assert disable(root, home)['integrations_disabled']
    unregister(root, home)
    import tomllib
    config = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8-sig'))
    assert config['model'] == 'preserve-this-model'
    assert config['openai_base_url'] == 'https://existing.example/v1'
    assert not any(n in config.get('mcp_servers', {}) for n in ('headroom_desktop', 'bundle_serena', 'bundle_laya_router'))
    assert (home / 'auth.json').read_bytes() == protected[home / 'auth.json']
    assert 'Preserve these personal instructions.' in (home / 'AGENTS.md').read_text()
    (root.parent / 'lifecycle-result.json').write_text(json.dumps({
        'passed': True, 'source_upgrade': True, 'validation_rollback': True,
        'owned_integrations_removed': True, 'auth_and_model_preserved': True}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'package', 'codex-home'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    expected = os.environ.get('CODEX_HOME')
    if not expected or Path(expected).resolve() != args.codex_home.resolve():
        raise RuntimeError('An explicit isolated CODEX_HOME is required')
    qualify(args.root.resolve(), args.package.resolve(), args.codex_home.resolve())
