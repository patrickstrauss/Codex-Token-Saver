"""Install one optional command rewrite hook; never grant hook trust."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tomllib

from install_desktop_mcp import replace_checked


def hook_group(root):
    script = Path(root) / 'Headroom-PreToolUse.ps1'
    command = f'powershell.exe -NoProfile -NonInteractive -File "{script}"'
    return {'matcher': '^Bash$', 'hooks': [{'type': 'command', 'command': command,
        'timeout': 5, 'statusMessage': 'Checking automatic Headroom command compression'}]}


def merge_hooks(source, root):
    document = json.loads(source)
    if not isinstance(document, dict):
        raise ValueError('Existing hooks file must be an object')
    hooks = document.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Existing hooks configuration is invalid')
    groups = hooks.setdefault('PreToolUse', [])
    if not isinstance(groups, list):
        raise ValueError('Existing PreToolUse configuration is invalid')
    desired = hook_group(root)
    if desired not in groups:
        # Never replace another hook or silently reset its reviewed definition.
        for group in groups:
            for handler in group.get('hooks', []):
                if 'Headroom-PreToolUse.ps1' in handler.get('command', ''):
                    raise ValueError('An existing Headroom hook differs; review it before changing registration')
        groups.append(desired)
    return json.dumps(document, indent=2, ensure_ascii=False) + '\n'


def main():
    root = Path(__file__).resolve().parent
    for name in ('Headroom-PreToolUse.ps1', 'bin/headroom-run.exe', 'headroom_run.py', 'command_compression.py'):
        if not (root / name).is_file():
            raise RuntimeError('Installation incomplete: ' + name)
    codex_dir = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    config = codex_dir / 'config.toml'
    config_before = config.read_bytes()
    settings = tomllib.loads(config_before.decode('utf-8-sig'))
    if settings.get('features', {}).get('hooks') is False:
        raise RuntimeError('Hooks are explicitly disabled; no settings changed')
    target = codex_dir / 'hooks.json'
    original = target.read_bytes() if target.exists() else None
    content = merge_hooks(original.decode('utf-8-sig') if original else '{}', root).encode('utf-8')
    backup = root / 'backups' / ('automatic-headroom-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    (backup / 'config.toml').write_bytes(config_before)
    if original is not None:
        (backup / 'hooks.json').write_bytes(original)
        if original != content:
            replace_checked(target, original, content)
    else:
        with target.open('xb') as stream:
            stream.write(content)
    if config.read_bytes() != config_before:
        raise RuntimeError('Codex config changed concurrently; inspect before continuing')
    receipt = {'configured': True, 'hook': 'headroom_commands',
        'timestamp': datetime.now(timezone.utc).isoformat(), 'path': str(target),
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'backup': str(backup),
        'activation': 'Requires user review in Codex Settings > Hooks > Reload hooks > User > Trust',
        'trust_granted_by_installer': False, 'codex_config_unchanged': True,
        'global_proxy_route_added': False,
        'scope': 'Supported explicit Windows native command calls; complex or ambiguous commands remain unchanged'}
    (root / 'automatic-headroom.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
