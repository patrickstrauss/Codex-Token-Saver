"""Register bundle tools and an untrusted hook transactionally; preserve settings."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib


def configure(root, config_home):
    sys.path.insert(0, str(root))
    from install_desktop_mcp import merge_config, replace_checked
    from install_command_hook import merge_hooks
    config_home.mkdir(parents=True, exist_ok=True)
    config, agents, hooks = (config_home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
    existed = {p: p.exists() for p in (config, agents, hooks)}
    before = {p: p.read_bytes() if existed[p] else b'' for p in (config, agents, hooks)}
    hook_disabled = tomllib.loads(before[config].decode('utf-8-sig')).get('features', {}).get('hooks') is False
    desired_hooks = before[hooks]
    if not hook_disabled:
        desired_hooks = merge_hooks(before[hooks].decode('utf-8-sig') if existed[hooks] else '{}', root).encode()
        if before[hooks].startswith(b'\xef\xbb\xbf'):
            desired_hooks = b'\xef\xbb\xbf' + desired_hooks
    desired_config = merge_config(before[config].decode('utf-8-sig'), root).encode()
    if before[config].startswith(b'\xef\xbb\xbf'):
        desired_config = b'\xef\xbb\xbf' + desired_config
    guidance = before[agents]
    additions = {
        'HEADROOM DESKTOP': 'Prefer headroom_read_file for large local JSON, CSV and logs. Retrieve exact content with headroom_retrieve or compress=false before edits or precise claims. Use native reads if unavailable. Preserve the managed connection, selected model, reasoning and authentication; use the bundle controls for routing changes.',
        'CODEX TOKEN SAVER': 'For supported external commands, prefer `rtk git status/diff/log`, `rtk rg`, and supported test/build commands. Keep PowerShell cmdlets, scripts and pipelines native. Use original output for exact evidence. If rtk is not on PATH, use `& "$env:USERPROFILE\\CodexTokenSaver\\bin\\rtk.exe"`. Preserve the selected Codex model, reasoning and authentication.',
    }
    for name, text in additions.items():
        start, end = f'<!-- BEGIN {name} -->'.encode(), f'<!-- END {name} -->'.encode()
        if guidance.count(start) != guidance.count(end) or guidance.count(start) > 1:
            raise ValueError('Managed guidance markers are damaged; nothing changed.')
        if start not in guidance:
            guidance += b'\n\n' + start + b'\n' + text.encode() + b'\n' + end + b'\n'
    changes = [(config, desired_config), (agents, guidance), (hooks, desired_hooks)]
    changes = [(p, value) for p, value in changes if value != before[p]]
    backup = root / 'backups' / ('team-install-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    if changes:
        backup.mkdir(parents=True)
        for path, _ in changes:
            (backup / path.name).write_bytes(before[path])
    committed, created = [], []
    try:
        for path, value in changes:
            if not existed[path]:
                with path.open('xb'):
                    pass
                created.append(path)
            replace_checked(path, before[path], value)
            committed.append((path, value))
    except BaseException:
        for path, value in reversed(committed):
            # A concurrent writer is never overwritten during rollback.
            replace_checked(path, value, before[path])
        for path in created:
            if path.exists() and path.read_bytes() == b'':
                path.unlink()
        raise
    return {'registered': True, 'connection_preserved': True, 'backup': str(backup) if changes else None,
            'command_hook_registered': not hook_disabled, 'hook_trust_granted': False,
            'hook_activation': ('Hooks were explicitly disabled; settings preserved.' if hook_disabled else
                                'Review and trust the command hook in Codex Settings > Hooks > Reload hooks > User.')}


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    print(json.dumps(configure(root, home)))
