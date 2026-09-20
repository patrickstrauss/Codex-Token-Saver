"""Register bundle file tools transactionally; preserve unrelated Codex settings."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


def configure(root, config_home):
    sys.path.insert(0, str(root))
    from install_desktop_mcp import merge_config, replace_checked
    config_home.mkdir(parents=True, exist_ok=True)
    config, agents = config_home / 'config.toml', config_home / 'AGENTS.md'
    existed = {p: p.exists() for p in (config, agents)}
    before = {p: p.read_bytes() if existed[p] else b'' for p in (config, agents)}
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
    changes = [(config, desired_config), (agents, guidance)]
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
    return {'registered': True, 'connection_preserved': True, 'backup': str(backup) if changes else None}


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    print(json.dumps(configure(root, home)))
