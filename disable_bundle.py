"""Disable owned bundle integration; a normal Windows restart clears old workers."""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import tomllib

import tomlkit

from bundle_preferences import DEFAULTS
from desktop_proxy_control import DesktopProxyControl, LOCAL_URL, _encode, _with_route, _without_route, routing_lock
from install_command_hook import hook_group
from install_desktop_mcp import replace_checked, server_config


def assert_codex_closed():
    """Never stop Codex or edit its registrations while it is still running."""
    if os.name != 'nt':
        raise RuntimeError('This recovery command supports Windows only.')
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command',
                             '@(Get-Process -Name Codex -ErrorAction SilentlyContinue).Count'],
                            capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode or not result.stdout.strip().isdigit():
        raise RuntimeError('Could not confirm that Codex is closed; no integrations were changed.')
    if int(result.stdout.strip()):
        raise RuntimeError('Close Codex completely, then run Disable-Token-Saver.cmd again. It will not force Codex to close.')


def read(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) > 2 * 1024 * 1024:
        raise ValueError(f'{path.name} is too large to manage safely.')
    return data


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def references_root(value, root):
    if not isinstance(value, str):
        return False
    base = ntpath.normcase(ntpath.normpath(str(root)))
    candidate = (value.split('=', 1)[-1] if value.startswith('-') and '=' in value else value).strip(' "\'')
    normalized = ntpath.normcase(ntpath.normpath(candidate))
    if normalized == base or normalized.startswith(base + '\\'):
        return True
    # A shell argument can contain a quoted absolute path. Refuse conservatively
    # without parsing or executing the user's shell program.
    return re.search(re.escape(base) + r'''(?=[\\\s"']|$)''', value.replace('/', '\\').casefold()) is not None


def disable_config(before, root):
    source = (before or b'').decode('utf-8-sig')
    original = tomllib.loads(source)
    document = tomlkit.parse(source)
    expected = {'headroom_desktop': server_config(root)}
    for name, script in (('bundle_serena', 'serena_mcp.py'), ('bundle_local_summaries', 'local_summary_mcp.py')):
        expected[name] = {'command': str(root / 'headroom/.venv/Scripts/python.exe'), 'args': [str(root / script)]}
    for name, entry in original.get('mcp_servers', {}).items():
        if name in expected or not isinstance(entry, dict) or entry.get('enabled') is False:
            continue
        arguments = entry.get('args', [])
        values = [entry.get('command'), entry.get('cwd')] + (arguments if isinstance(arguments, list) else [arguments])
        if any(references_root(value, root) for value in values):
            raise ValueError(f'Additional MCP registration {name} references this bundle. Disable or review it manually before retrying; it was preserved.')
    changed = []
    for name, owned in expected.items():
        entry = original.get('mcp_servers', {}).get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict) or any(entry.get(key) != owned[key] for key in ('command', 'args')):
            raise ValueError(f'{name} is not owned by this installation; review its configuration before disabling.')
        if entry.get('enabled') is not False:
            document['mcp_servers'][name]['enabled'] = False
            changed.append(name)
    if not changed:
        return before
    output = tomlkit.dumps(document)
    if '\r\n' in source and '\n' not in source.replace('\r\n', ''):
        output = output.replace('\r\n', '\n').replace('\n', '\r\n')
    return (b'\xef\xbb\xbf' if (before or b'').startswith(b'\xef\xbb\xbf') else b'') + output.encode()


def disable_hooks(before, root):
    if before is None:
        return None
    document = json.loads(before.decode('utf-8-sig'))
    if not isinstance(document, dict) or not isinstance(document.get('hooks', {}), dict):
        raise ValueError('Hooks configuration is invalid; no integrations were changed.')
    groups = document.get('hooks', {}).get('PreToolUse', [])
    if not isinstance(groups, list):
        raise ValueError('PreToolUse hooks are invalid; no integrations were changed.')
    owned = hook_group(root)['hooks'][0]['command']
    updated, changed = [], False
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('hooks', []), list):
            raise ValueError('Hook group is invalid; no integrations were changed.')
        handlers = []
        for handler in group.get('hooks', []):
            if not isinstance(handler, dict):
                raise ValueError('Hook handler is invalid; no integrations were changed.')
            command = handler.get('command', '')
            if handler.get('type') == 'command' and command == owned:
                changed = True
            elif isinstance(command, str) and str(root / 'Headroom-PreToolUse.ps1').casefold() in command.casefold():
                raise ValueError('The owned Headroom hook has an unfamiliar command; review it before disabling.')
            else:
                handlers.append(handler)
        if handlers or not group.get('hooks'):
            updated.append(dict(group, hooks=handlers))
    if not changed:
        return before
    document['hooks']['PreToolUse'] = updated
    return (b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b'') + json_bytes(document)


def disable_guidance(before):
    if before is None:
        return None
    result = before
    for label in ('CODEX TOKEN SAVER', 'HEADROOM DESKTOP', 'HEADROOM COMMAND OUTPUT', 'CODEX TOKEN SAVER SERENA'):
        start, end = (f'<!-- {kind} {label} -->'.encode() for kind in ('BEGIN', 'END'))
        pattern = re.compile(re.escape(start) + rb'\r?\n.*?' + re.escape(end) + rb'(?:\r?\n|$)', re.S)
        matches = list(pattern.finditer(result))
        if len(matches) > 1 or result.count(start) != len(matches) or result.count(end) != len(matches):
            raise ValueError('Managed guidance markers are damaged; no integrations were changed.')
        result = pattern.sub(b'', result)
    return result


def planned_changes(root, config_home):
    config, hooks, agents = (config_home / name for name in ('config.toml', 'hooks.json', 'AGENTS.md'))
    changes = []
    for path, transform in ((config, lambda b: disable_config(b, root)),
                            (hooks, lambda b: disable_hooks(b, root)), (agents, disable_guidance)):
        before = read(path)
        after = transform(before)
        if before != after:
            changes.append((path, before, after))
    settings = root / 'proxy/settings.json'
    before = read(settings)
    value = json.loads((before or b'{}').decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Proxy settings are invalid; restore the direct connection first.')
    after = json_bytes(dict(value, installed=False, enabled=False))
    if value != json.loads(after):
        changes.append((settings, before, after))
    preferences = root / 'settings/components.json'
    before = read(preferences)
    after = json_bytes({'schema_version': 1, 'components': dict.fromkeys(DEFAULTS, False)})
    if before != after:
        changes.append((preferences, before, after))
    for name, fields in (('desktop-integration.json', {'configured': False, 'enabled': False}),
                         ('automatic-headroom.json', {'configured': False})):
        path = root / name
        before = read(path)
        value = json.loads((before or b'{}').decode('utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError(f'{name} is invalid; preserve it for inspection.')
        after = json_bytes(dict(value, **fields))
        if before != after:
            changes.append((path, before, after))
    return changes


def apply_changes(changes, backup):
    """Rollback only our writes, never a concurrent user's edit."""
    attempted = []
    for index, (path, before, _) in enumerate(changes):
        if read(path) != before:
            raise RuntimeError(f'{path.name} changed concurrently; retry recovery.')
        if before is not None:
            (backup / f'{index}-{path.name}').write_bytes(before)
    try:
        for path, before, after in changes:
            if read(path) != before:
                raise RuntimeError(f'{path.name} changed concurrently; retry recovery.')
            path.parent.mkdir(parents=True, exist_ok=True)
            if before is None:
                with path.open('xb'):
                    pass
            attempted.append((path, before, after))
            replace_checked(path, before or b'', after)
    except Exception as error:
        rollback_errors = []
        for path, before, after in reversed(attempted):
            try:
                current = read(path)
                if current == after or (before is None and current == b''):
                    if before is None:
                        path.unlink()
                    else:
                        replace_checked(path, current, before)
            except Exception:
                rollback_errors.append(path.name)
        if rollback_errors:
            raise RuntimeError('Integration rollback is incomplete for: ' + ', '.join(rollback_errors) + '. Keep the backup for recovery.') from error
        raise


def disable(root, config_home, *, plan=False, operation_lock_held=False):
    root, config_home = Path(root).resolve(), Path(config_home).resolve()
    assert_codex_closed()
    if not root.is_dir():
        raise ValueError('The installation folder is missing; follow the deleted-installation recovery guide.')
    lock = nullcontext() if plan or operation_lock_held else routing_lock(root / 'updates/operation.lock')
    with lock:
        return _disable_locked(root, config_home, plan=plan)


def _disable_locked(root, config_home, *, plan):
    changes = planned_changes(root, config_home)  # Validate every owned registration before any write.
    if plan:
        return {'plan': True, 'files_to_update': [str(path) for path, _, _ in changes], 'restart_windows_required': True}
    backup = root / 'backups' / ('disable-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    config, settings, receipt = config_home / 'config.toml', root / 'proxy/settings.json', root / 'proxy/route-receipt.json'
    expected = {path: read(path) for path in (config, settings, receipt, config_home / 'hooks.json', config_home / 'AGENTS.md',
                 root / 'settings/components.json', root / 'desktop-integration.json', root / 'automatic-headroom.json')}
    for path in (config, settings, receipt):
        before = read(path)
        if before is not None:
            (backup / ('before-route-' + path.name)).write_bytes(before)
    # Expect only the controller's documented route/pause changes. Edits to any
    # other field or file during pause must not be silently adopted.
    value = json.loads((expected[settings] or b'{}').decode('utf-8-sig'))
    value.update(installed=value.get('installed') is True, enabled=False)
    value.setdefault('upstream_mode', 'auto')
    expected[settings] = _encode(value)
    if tomllib.loads((expected[config] or b'').decode('utf-8-sig')).get('openai_base_url') == LOCAL_URL:
        route = json.loads((expected[receipt] or b'{}').decode('utf-8-sig'))
        expected[config] = _without_route(expected[config])
        if route.get('previous_present'):
            expected[config] = _with_route(expected[config], route.get('previous_value'))
        expected[receipt] = _encode(dict(route, restart_required=True))
    # A failed safe route restoration must leave runtime/startup available.
    # Pausing is intentionally retained if a later integration write fails.
    result = DesktopProxyControl(root, config_home=config_home).set_enabled(False)
    if result.get('route_enabled') or result.get('enabled'):
        raise RuntimeError('The owned endpoint could not be restored; services must remain available.')
    if any(read(path) != before for path, before in expected.items()):
        raise RuntimeError('Bundle or Codex configuration changed during route pause; integration changes were stopped. The pause remains in effect.')
    changes = planned_changes(root, config_home)
    apply_changes(changes, backup)
    return {'integrations_disabled': True, 'backup': str(backup), 'restart_windows_required': True,
            'processes_stopped': False,
            'message': 'Owned Codex integrations are disabled. Disable startup, then restart Windows to stop existing workers.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'CodexTokenSaver')
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex'))
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--operation-lock-held', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(json.dumps(disable(args.root, args.codex_home, plan=args.plan, operation_lock_held=args.operation_lock_held)))


if __name__ == '__main__':
    main()
