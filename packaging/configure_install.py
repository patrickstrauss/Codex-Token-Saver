"""Register bundle tools and an untrusted hook transactionally; preserve settings."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib
import tomlkit


def receipt_bytes(before, fields, timestamp, backup):
    """Keep the original receipt, including its timestamp, on an unchanged rerun."""
    try:
        previous = json.loads(before)
    except (ValueError, UnicodeError):
        previous = None
    if isinstance(previous, dict) and {k: v for k, v in previous.items()
                                      if k not in ('timestamp', 'backup')} == fields:
        return before
    return (json.dumps(fields | {'timestamp': timestamp, 'backup': str(backup)}, indent=2) + '\n').encode()


def configure(root, config_home):
    sys.path.insert(0, str(root))
    from install_desktop_mcp import SERVER, merge_config, replace_checked
    from install_command_hook import hook_group, merge_hooks
    root.mkdir(parents=True, exist_ok=True)
    config_home.mkdir(parents=True, exist_ok=True)
    config, agents, hooks = (config_home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
    desktop_receipt, hook_receipt = (root / name for name in ('desktop-integration.json', 'automatic-headroom.json'))
    paths = (config, agents, hooks, desktop_receipt, hook_receipt)
    existed = {p: p.exists() for p in paths}
    before = {p: p.read_bytes() if existed[p] else b'' for p in paths}
    settings = tomllib.loads(before[config].decode('utf-8-sig'))
    hook_disabled = settings.get('features', {}).get('hooks') is False
    desired_hooks = before[hooks]
    if not hook_disabled:
        desired_hooks = merge_hooks(before[hooks].decode('utf-8-sig') if existed[hooks] else '{}', root).encode()
        if before[hooks].startswith(b'\xef\xbb\xbf'):
            desired_hooks = b'\xef\xbb\xbf' + desired_hooks
    source = before[config].decode('utf-8-sig')
    merged = merge_config(source, root)  # Also rejects a server owned by another install.
    if settings.get('mcp_servers', {}).get(SERVER, {}).get('enabled') is False:
        document = tomlkit.parse(merged)
        document['mcp_servers'][SERVER]['enabled'] = False
        merged = tomlkit.dumps(document)
        if tomllib.loads(merged) == settings:
            merged = source
    desired_config = merged.encode()
    if before[config].startswith(b'\xef\xbb\xbf'):
        desired_config = b'\xef\xbb\xbf' + desired_config
    guidance = before[agents]
    from cli_tools import guidance as cli_guidance, runtime_status
    from bundle_preferences import load_preferences
    if runtime_status(root)['available']:
        preferences = load_preferences(root)
        for component in ('playwright_cli', 'ast_grep'):
            guidance = cli_guidance(guidance, root, component, preferences[component])
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
    now = datetime.now(timezone.utc)
    backup = root / 'backups' / ('team-install-' + now.strftime('%Y%m%dT%H%M%S%fZ'))
    installed = tomllib.loads(merged)
    enabled = installed['mcp_servers'][SERVER]['enabled'] is True
    activation = ('Hooks were explicitly disabled; settings preserved.' if hook_disabled else
                  'Review and trust the command hook in Codex Settings > Hooks > Reload hooks > User.')
    desktop_fields = {
        'configured': enabled, 'registered': True, 'enabled': enabled, 'server': SERVER,
        'transport': 'stdio', 'required': False, 'scope': 'large local file reads',
        'config': str(config), 'model': installed.get('model'),
        'reasoning': installed.get('model_reasoning_effort'), 'provider': installed.get('model_provider', 'openai'),
        'global_proxy_route_added': False, 'loading_in_codex_verified': False,
        'restart_existing_desktop_session_to_load_tools': enabled,
    }
    hook_fields = {
        'configured': not hook_disabled, 'hook': 'headroom_commands', 'path': str(hooks),
        'sha256': hashlib.sha256(desired_hooks).hexdigest(), 'activation': activation,
        'trust_granted_by_installer': False, 'global_proxy_route_added': False,
        'scope': 'Single literal native Windows git status/diff/log and rg calls use RTK when enabled and on PATH; explicit supported executable calls can use Headroom; complex and exact commands remain unchanged',
    }
    changes = [(config, desired_config), (agents, guidance), (hooks, desired_hooks),
               (desktop_receipt, receipt_bytes(before[desktop_receipt], desktop_fields, now.isoformat(), backup)),
               (hook_receipt, receipt_bytes(before[hook_receipt], hook_fields, now.isoformat(), backup))]
    changes = [(p, value) for p, value in changes if value != before[p]]

    def verify_registration():
        # Receipts describe verified registration, never runtime loading or user trust.
        if config.read_bytes() != desired_config or (hooks.read_bytes() if hooks.exists() else b'') != desired_hooks:
            raise RuntimeError('Codex configuration changed concurrently; receipt was not verified.')
        actual = tomllib.loads(config.read_text(encoding='utf-8-sig'))
        if actual['mcp_servers'][SERVER] != installed['mcp_servers'][SERVER]:
            raise RuntimeError('Headroom server registration could not be verified.')
        if not hook_disabled and hook_group(root) not in json.loads(hooks.read_bytes())['hooks']['PreToolUse']:
            raise RuntimeError('Command hook registration could not be verified.')

    if changes:
        backup.mkdir(parents=True)
        for path, _ in changes:
            (backup / path.name).write_bytes(before[path])
    committed, created = [], []
    try:
        for path, value in changes:
            if path in (desktop_receipt, hook_receipt):
                verify_registration()
            if not existed[path]:
                with path.open('xb'):
                    pass
                created.append(path)
            replace_checked(path, before[path], value)
            committed.append((path, value))
        verify_registration()
    except BaseException as error:
        rollback_error = None
        for path, value in reversed(committed):
            # A concurrent writer is never overwritten during rollback.
            try:
                replace_checked(path, value, before[path])
            except BaseException as failure:
                rollback_error = failure
        for path in created:
            if path.exists() and path.read_bytes() == b'':
                path.unlink()
        if rollback_error is not None:
            raise rollback_error from error
        raise
    return {'registered': True, 'connection_preserved': True, 'backup': str(backup) if changes else None,
            'command_hook_registered': not hook_disabled, 'hook_trust_granted': False,
            'hook_activation': activation}


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    print(json.dumps(configure(root, home)))
