"""Opt-in MCP adapters. Never change a client's models, hooks, auth or history."""
import argparse
from dataclasses import dataclass, field
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from desktop_proxy_control import atomic_write, routing_lock

CLIENTS = {
    'claude-code': ('Claude Code', 'mcpServers'),
    'gemini-cli': ('Gemini CLI', 'mcpServers'),
    'cursor': ('Cursor', 'mcpServers'),
    'opencode': ('OpenCode', 'mcp'),
    'vscode': ('VS Code', 'servers'),
    'cline': ('Cline CLI / IDE', 'mcpServers'),
    'kilo': ('Kilo Code', 'mcp'),
    'windsurf-cascade': ('Windsurf / Devin Cascade (legacy)', 'mcpServers'),
    'generic': ('Other MCP client', 'mcpServers'),
}
ARRAY_CLIENTS = frozenset(('opencode', 'kilo'))
SCRIPTS = {'headroom_local': ('headroom_desktop', 'desktop_mcp.py'),
           'serena': ('bundle_serena', 'serena_mcp.py'),
           'laya_router': ('bundle_laya_router', 'bundle_router_mcp.py')}
MAX_BYTES = 2 * 1024 * 1024


@dataclass
class Node:
    value: object
    start: int
    end: int
    members: dict = field(default_factory=dict)


class JsonDocument:
    """Parse JSONC and retain spans; patch only our server entries, not user text."""
    def __init__(self, text):
        self.text, self.pos = text, 0
        self.root = self.parse()
        self.space()
        if self.pos != len(text) or not isinstance(self.root.value, dict):
            raise ValueError('Expected one JSON/JSONC configuration object.')

    def space(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace() or (self.pos == 0 and self.text[0] == '\ufeff'):
                self.pos += 1
            elif self.text.startswith('//', self.pos):
                end = self.text.find('\n', self.pos)
                self.pos = len(self.text) if end < 0 else end
            elif self.text.startswith('/*', self.pos):
                end = self.text.find('*/', self.pos + 2)
                if end < 0:
                    raise ValueError('Unclosed JSONC comment.')
                self.pos = end + 2
            else:
                break

    def parse(self, depth=0):
        if depth > 64:
            raise ValueError('Configuration nesting is too deep.')
        self.space()
        start = self.pos
        if self.pos >= len(self.text):
            raise ValueError('Incomplete configuration.')
        opening = self.text[self.pos]
        if opening not in '{[':
            try:
                value, end = json.JSONDecoder(parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number.'))).raw_decode(self.text, self.pos)
            except (ValueError, RecursionError) as exc:
                raise ValueError('Invalid JSON/JSONC value.') from exc
            self.pos = end
            return Node(value, start, end)
        self.pos += 1
        values, members = ({} if opening == '{' else []), {}
        closing = '}' if opening == '{' else ']'
        while True:
            self.space()
            if self.pos >= len(self.text):
                raise ValueError('Unclosed configuration object.')
            if self.text[self.pos] == closing:
                self.pos += 1
                return Node(values, start, self.pos, members)
            member_start = self.pos
            if opening == '{':
                key = self.parse(depth + 1)
                if not isinstance(key.value, str) or key.value in values:
                    raise ValueError('Configuration keys must be unique strings.')
                self.space()
                if self.pos >= len(self.text) or self.text[self.pos] != ':':
                    raise ValueError('Missing configuration separator.')
                self.pos += 1
                child = self.parse(depth + 1)
                values[key.value] = child.value
            else:
                child = self.parse(depth + 1)
                values.append(child.value)
            self.space()
            comma = self.pos if self.pos < len(self.text) and self.text[self.pos] == ',' else None
            if opening == '{':
                members[key.value] = (member_start, child, comma)
            if comma is not None:
                self.pos += 1
            elif self.pos >= len(self.text) or self.text[self.pos] != closing:
                raise ValueError('Missing configuration comma.')


def patch_member(text, parent, name, value, *, remove=False):
    """One edit per parse avoids overlapping comma spans during removal."""
    members = parent.members
    if name in members:
        start, child, comma = members[name]
        if not remove:
            return text[:child.start] + json.dumps(value, ensure_ascii=False, indent=2) + text[child.end:]
        if comma is not None:
            return text[:start] + text[comma + 1:]
        keys = list(members)
        previous = members[keys[keys.index(name) - 1]][2] if keys.index(name) else None
        result = text[:start] + text[child.end:]
        return result[:previous] + result[previous + 1:] if previous is not None else result
    if remove:
        return text
    comma = ',' if members and next(reversed(members.values()))[2] is None else ''
    entry = json.dumps(name) + ': ' + json.dumps(value, ensure_ascii=False, indent=2)
    # Insert before closing brace; trailing comments and existing text remain intact.
    insertion = parent.end - 1
    if comma:
        last = next(reversed(members.values()))[1].end
        text = text[:last] + ',' + text[last:]
        insertion += 1
    return text[:insertion] + '\n' + entry + '\n' + text[insertion:]


def _checked(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Client configuration through links is unsupported.')
    if path.exists() and not path.is_file():
        raise ValueError('Client configuration must be a file.')
    return path.resolve()


def read(path):
    path = _checked(path)
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(data) > MAX_BYTES:
        raise ValueError('Client configuration is too large.')
    return data


def config_path(client, scope='user', project=None, config=None, home=None):
    if client not in CLIENTS or scope not in ('user', 'project'):
        raise ValueError('Choose a listed client and user or project scope.')
    if config:
        if not Path(config).is_absolute():
            raise ValueError('Use an absolute explicit MCP configuration path.')
        result = Path(config)
        if result.suffix.lower() not in ('.json', '.jsonc') or result.name.lower() in ('auth.json', 'credentials.json'):
            raise ValueError('Choose an MCP JSON/JSONC configuration, never credentials.')
        return _checked(result)
    if client in ('generic', 'windsurf-cascade') or (client == 'vscode' and scope == 'user') or (client == 'cline' and scope == 'project'):
        raise ValueError('Use an explicit MCP configuration path for this client/profile, or export its snippet.')
    if client == 'cline' and scope == 'user' and os.environ.get('CLINE_MCP_SETTINGS_PATH') and home is None:
        return config_path(client, config=os.environ['CLINE_MCP_SETTINGS_PATH'])
    if scope == 'project':
        if not project or not Path(project).is_absolute() or not Path(project).is_dir():
            raise ValueError('Select an existing absolute project directory.')
        base = Path(project)
        relative = {'claude-code': '.mcp.json', 'gemini-cli': '.gemini/settings.json',
                    'cursor': '.cursor/mcp.json', 'vscode': '.vscode/mcp.json',
                    'opencode': 'opencode.json', 'kilo': '.kilo/kilo.jsonc'}[client]
    else:
        base = Path(home or Path.home())
        relative = {'claude-code': '.claude.json', 'gemini-cli': '.gemini/settings.json',
                    'cursor': '.cursor/mcp.json', 'opencode': '.config/opencode/opencode.json',
                    'kilo': '.config/kilo/kilo.jsonc', 'cline': '.cline/data/settings/cline_mcp_settings.json'}[client]
    result = base / relative
    if client == 'kilo':
        options = [result, result.with_suffix('.json')]
        if scope == 'project':
            options += [base / 'kilo.json', base / 'kilo.jsonc']
        existing = [p for p in options if p.exists()]
        if len(existing) > 1:
            raise ValueError('Multiple Kilo configuration files exist; select the intended file with --config.')
        result = existing[0] if existing else result
    if client == 'opencode' and result.with_suffix('.jsonc').exists():
        if result.exists():
            raise ValueError('Both OpenCode JSON and JSONC files exist; choose one configuration manually.')
        result = result.with_suffix('.jsonc')
    return _checked(result)


def server_entries(root, client):
    root = Path(root).resolve()
    if client not in CLIENTS:
        raise ValueError('Unknown client.')
    python = root / 'headroom/.venv/Scripts/python.exe'
    if not python.is_file() or not (root / 'harness_mcp.py').is_file():
        raise ValueError('Repair the managed Headroom runtime and client launcher before connecting a client.')
    entries = {}
    for component, (name, script) in SCRIPTS.items():
        runtime = {'headroom_local': 'headroom', 'serena': 'serena', 'laya_router': 'laya'}[component]
        if not (root / runtime / '.venv/Scripts/python.exe').is_file():
            continue
        if not (root / script).is_file():
            raise ValueError('Repair the missing MCP server source before connecting a client.')
        args = ['-u', str(root / 'harness_mcp.py'), '--client', client, '--component', component]
        env = {'PYTHONUTF8': '1'}
        if client in ARRAY_CLIENTS:
            entry = {'type': 'local', 'command': [str(python), *args], 'environment': env, 'enabled': True}
        else:
            entry = {'command': str(python), 'args': args, 'env': env}
            if client in ('claude-code', 'cursor', 'vscode'):
                entry['type'] = 'stdio'
        entries[name] = entry
    if not entries:
        raise ValueError('Install the managed Headroom runtime before connecting a client.')
    return entries


def export_config(root, client):
    return {CLIENTS[client][1]: server_entries(root, client)}


def _state(root):
    data = read(Path(root) / 'integrations/clients.json')
    if data is None:
        return {'schema_version': 1, 'registrations': []}
    value = json.loads(data)
    if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('registrations'), list):
        raise ValueError('Client ownership receipt is damaged; preserve it for recovery.')
    keys = set()
    for record in value['registrations']:
        if (not isinstance(record, dict) or set(record) != {'key', 'client', 'scope', 'path', 'entries'}
                or not isinstance(record['client'], str) or record['client'] not in CLIENTS
                or not isinstance(record['scope'], str) or record['scope'] not in ('user', 'project')
                or not isinstance(record['path'], str) or not Path(record['path']).is_absolute()
                or not isinstance(record['key'], str) or record['key'] in keys
                or not isinstance(record['entries'], dict) or not record['entries']):
            raise ValueError('Client ownership receipt is damaged; preserve it for recovery.')
        canonical = str(_checked(record['path']))
        if record['key'] != (canonical.casefold() if os.name == 'nt' else canonical):
            raise ValueError('Client ownership path does not match its receipt.')
        config_path(record['client'], config=record['path'])
        for name, entry in record['entries'].items():
            component = next((k for k, v in SCRIPTS.items() if v[0] == name), None)
            command = [str(Path(root).resolve() / 'headroom/.venv/Scripts/python.exe'),
                       '-u', str(Path(root).resolve() / 'harness_mcp.py'), '--client', record['client'], '--component', component]
            if (component is None or not isinstance(entry, dict)
                    or (record['client'] not in ARRAY_CLIENTS and not isinstance(entry.get('args'), list))
                    or (entry.get('command') != command if record['client'] in ARRAY_CLIENTS
                        else [entry.get('command'), *entry.get('args', [])] != command)):
                raise ValueError('Client ownership entry does not belong to this installation.')
        keys.add(record['key'])
    return value


def codex_enabled(root):
    """Legacy installs remain Codex installs; standalone explicitly opts out."""
    data = read(Path(root) / 'team-install-result.json')
    if data is None:
        return True
    value = json.loads(data)
    if not isinstance(value, dict) or type(value.get('codex_integration', True)) is not bool:
        raise ValueError('Installation client mode is damaged; no client settings were changed.')
    return value.get('codex_integration', True)


def registrations(root):
    result = []
    for record in _state(root)['registrations']:
        try:
            raw = read(record['path'])
            values = JsonDocument(raw.decode('utf-8-sig')).root.value if raw is not None else {}
            current = values.get(CLIENTS[record['client']][1], {})
            configured = isinstance(current, dict) and all(current.get(k) == v for k, v in record['entries'].items())
        except (ValueError, OSError):
            configured = False
        result.append({'client': record['client'], 'scope': record['scope'], 'config': record['path'],
                       'servers': list(record['entries']), 'status': 'configured' if configured else 'changed_or_missing',
                       'live_verified': False})
    return result


def change(root, client, *, scope='user', project=None, config=None, remove=False, apply=False, home=None, _recorded=False):
    root = Path(root).resolve()
    if client not in CLIENTS or scope not in ('user', 'project'):
        raise ValueError('Unknown client or scope.')
    path = _checked(config) if _recorded else config_path(client, scope, project, config, home)
    with routing_lock(root / 'integrations/clients.lock') if apply else nullcontext():
        state = _state(root)
        original_state = read(root / 'integrations/clients.json')
        key = str(path).casefold() if os.name == 'nt' else str(path)
        record = next((r for r in state['registrations'] if r.get('key') == key), None)
        if _recorded and (not record or record['path'] != str(path)):
            raise ValueError('Client ownership receipt does not match this path.')
        if record and record['client'] != client:
            raise ValueError('This file is already managed with a different client format.')
        before = read(path)
        source = (before or b'{}').decode('utf-8-sig')
        document = JsonDocument(source)
        section = CLIENTS[client][1]
        container = document.root.members.get(section)
        if container and not isinstance(container[1].value, dict):
            raise ValueError('The MCP server section is not an object.')
        desired = record['entries'] if remove and record else {} if remove else server_entries(root, client)
        existing = container[1].value if container else {}
        owned = record['entries'] if record else {}
        for name in set(desired) | set(owned):
            if name in existing and (name not in owned or existing[name] != owned[name]):
                raise ValueError('A server entry was changed or belongs to someone else; nothing was overwritten.')
        after = source
        if not container and desired and not remove:
            after = patch_member(source, document.root, section, {})
        for name in dict.fromkeys([*owned, *desired]):
            tree = JsonDocument(after)
            parent = tree.root.members.get(section)
            if parent:
                after = patch_member(after, parent[1], name, desired.get(name), remove=remove or name not in desired)
        # Validate every unrelated setting, not just JSON syntax.
        expected = dict(document.root.value)
        section_value = dict(existing)
        for name in set(owned) | set(desired):
            if remove or name not in desired:
                section_value.pop(name, None)
            else:
                section_value[name] = desired[name]
        if container or (desired and not remove):
            expected[section] = section_value
        if JsonDocument(after).root.value != expected:
            raise RuntimeError('Unexpected client configuration change; nothing written.')
        encoded = (b'\xef\xbb\xbf' if before and before.startswith(b'\xef\xbb\xbf') else b'') + after.encode('utf-8')
        if before is None and remove:
            encoded = None
        elif before is not None and JsonDocument(source).root.value == JsonDocument(after).root.value:
            encoded = before  # An unchanged rerun preserves every original byte.
        replacement = {'key': key, 'client': client, 'scope': scope, 'path': str(path), 'entries': desired}
        state['registrations'] = [replacement if r.get('key') == key else r
                                  for r in state['registrations'] if not (remove and r.get('key') == key)]
        if not remove and record is None:
            state['registrations'].append(replacement)
        state_bytes = (json.dumps(state, indent=2) + '\n').encode()
        plan = {'client': client, 'scope': scope, 'config': str(path), 'action': 'disconnect' if remove else 'connect',
                'servers': list(desired), 'changed': encoded != before, 'applied': False,
                'live_verified': False, 'models_auth_history_changed': False,
                'notice': 'Reload this client to discover tools. Component switches remain unchanged. Request compression and hooks are not installed.'}
        if not apply:
            return plan
        if (encoded == before and state_bytes == original_state) or (remove and record is None):
            return plan | {'applied': True, 'backup': None}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root / 'integrations/backups' / ('client-' + stamp)
        backup.mkdir(parents=True)
        if before is not None:
            atomic_write(backup / 'config.before', before)
        atomic_write(backup / 'ownership.before.json', original_state or b'null')
        # Write-ahead receipt makes an interrupted commit reviewable, never silently adopted.
        atomic_write(backup / 'transaction.json', json.dumps({'path': str(path), 'before_exists': before is not None,
            'after_sha256': hashlib.sha256(encoded).hexdigest() if encoded is not None else None,
            'client': client, 'action': plan['action']}).encode())
        if read(path) != before or read(root / 'integrations/clients.json') != original_state:
            raise RuntimeError('Client configuration changed concurrently. Retry after reviewing it.')
        try:
            if encoded != before:
                atomic_write(path, encoded)
            if read(path) != encoded:
                raise RuntimeError('Client configuration changed during registration.')
            atomic_write(root / 'integrations/clients.json', state_bytes)
        except BaseException:
            if read(root / 'integrations/clients.json') == state_bytes:
                if original_state is None:
                    (root / 'integrations/clients.json').unlink(missing_ok=True)
                else:
                    atomic_write(root / 'integrations/clients.json', original_state)
            if read(path) == encoded and encoded != before:
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, before)
            raise
        return plan | {'applied': True, 'backup': str(backup)}


def disconnect_all(root, *, apply=False):
    results = []
    # Preflight every client before removing any registration.
    records = list(_state(root)['registrations'])
    for record in records:
        results.append(change(root, record['client'], scope=record['scope'],
            config=record['path'], remove=True, apply=False, _recorded=True))
    if apply:
        # Use the exact recorded path, with no default profile/environment discovery.
        results = [_disconnect_record(root, record) for record in records]
    return results


def _disconnect_record(root, record):
    # Preserve format and receipt identity while resolving the exact recorded path.
    return change(root, record['client'], scope=record['scope'],
                  config=record['path'], remove=True, apply=True, _recorded=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('list', 'export', 'connect', 'disconnect', 'disconnect-all'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--client', choices=CLIENTS)
    parser.add_argument('--scope', choices=('user', 'project'), default='user')
    parser.add_argument('--project', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--apply', action='store_true', help='Commit the reviewed connect/disconnect plan.')
    args = parser.parse_args()
    if args.action in ('export', 'connect', 'disconnect') and not args.client:
        parser.error('--client is required')
    try:
        if args.action == 'list':
            result = {'clients': [dict(id=k, label=v[0]) for k, v in CLIENTS.items()],
                      'registrations': registrations(args.root)}
        elif args.action == 'export':
            result = export_config(args.root, args.client)
        elif args.action == 'disconnect-all':
            result = disconnect_all(args.root, apply=args.apply)
        else:
            result = change(args.root, args.client, scope=args.scope, project=args.project,
                            config=args.config, remove=args.action == 'disconnect', apply=args.apply)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
