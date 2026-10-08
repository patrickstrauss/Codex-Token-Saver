"""Own the retained optional Codex MCP entries."""
import json
import os
from pathlib import Path
import re
import tomllib
import tomlkit
from datetime import datetime, timezone

from desktop_proxy_control import atomic_write, routing_lock
from bundle_preferences import load_preferences, set_preference

TOOLS = {
    'serena': ['activate_project', 'get_symbols_overview', 'find_symbol', 'find_referencing_symbols'],
    'laya_router': ['bundle_query'],
}

SERENA_GUIDANCE = (
    b'\n<!-- BEGIN CODEX TOKEN SAVER SERENA -->\n'
    b'For relevant coding navigation, use the enabled bundle Serena tools implicitly without a per-task setup prompt. '
    b'Activate the current checkout with activate_project using its absolute path; reactivate when switching checkouts. '
    b'Prefer get_symbols_overview, find_symbol and find_referencing_symbols before reading whole code files. '
    b'Use Serena for named definitions/references; for call shapes or syntax patterns prefer Laya bundle_query with ast-grep pattern + language. '
    b'Before editing or making exact claims, fetch original bodies with find_symbol(include_body=true) or native file reads. '
    b'When Serena is off, unavailable, unsupported or unhelpful, continue with native tools; skip irrelevant calls. '
    b'Respect the bundle toggle and do not enable it automatically. Serena guides tool selection; it does not intercept all reads.\n'
    b'<!-- END CODEX TOKEN SAVER SERENA -->\n'
)


def _serena_guidance(before, enabled):
    start = b'<!-- BEGIN CODEX TOKEN SAVER SERENA -->'
    end = b'<!-- END CODEX TOKEN SAVER SERENA -->'
    pattern = re.compile(b'\r?\n' + re.escape(start) + b'\r?\n.*?\r?\n' + re.escape(end) + b'\r?\n', re.S)
    matches = list(pattern.finditer(before))
    if len(matches) > 1 or before.count(start) != len(matches) or before.count(end) != len(matches):
        raise ValueError('Managed Serena guidance markers are damaged; settings were left unchanged.')
    if matches:
        return pattern.sub(lambda _: SERENA_GUIDANCE if enabled else b'', before)
    return before + SERENA_GUIDANCE if enabled else before


def laya_guidance(before, enabled):
    start, end = (f'<!-- {kind} CODEX TOKEN SAVER LAYA -->'.encode() for kind in ('BEGIN', 'END'))
    pattern = re.compile(rb'\r?\n' + re.escape(start) + rb'\r?\n.*?' + re.escape(end) + rb'\r?\n', re.S)
    matches = list(pattern.finditer(before))
    if len(matches) > 1 or before.count(start) != len(matches) or before.count(end) != len(matches):
        raise ValueError('Managed Laya guidance markers are damaged; nothing changed.')
    text = (b'All explicit Codex Token Saver work goes through Laya. Prefer bundle_laya_router.bundle_query with a short intent, '
            b'absolute project, and the arguments needed for a file read, symbol lookup, structural search, Git report, or browser snapshot. '
            b'For call shapes, nested expressions or repeated code structure, prefer a structural search before broad text scans: '
            b'provide pattern and language (for example JavaScript ipcMain.handle($$$ARGS), Python subprocess.run($$$ARGS)). '
            b'Laya routes explicit patterns without model startup and returns exact match text with locations; use max_matches and next_offset/offset for pages. '
            b'Use rg for literal text and Serena for named definitions/references; do not run duplicate searches just to exercise a tool. '
            b'Direct bundle MCP/CLI compatibility entry points also consult Laya before executing. '
            b'If a decision is ambiguous, narrow the request; do not bypass the gateway by invoking bundled runtime paths. '
            b'For exact source or edits set exact=true. Include caller_task_id only when the current chat UUID is known; otherwise omit it. '
            b'Automatic Headroom request compression and RTK command hooks retain their fast paths. '
            b'Codex model/provider routing and non-bundle tools are unchanged. Respect all component toggles; never enable them automatically.\n')
    block = b'\n' + start + b'\n' + text + end + b'\n' if enabled else b''
    return pattern.sub(lambda _: block, before) if matches else before + block


def _read(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return b''
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('The configuration is too large to manage safely.')
    return data


def remove_retired_config(before, root):
    """Remove only the obsolete MCP table belonging to this bundle installation."""
    source = (before or b'').decode('utf-8-sig')
    parsed = tomllib.loads(source)
    entry = parsed.get('mcp_servers', {}).get('bundle_local_summaries')
    owned = {'command': str(Path(root) / 'headroom/.venv/Scripts/python.exe'),
             'args': [str(Path(root) / 'local_summary_mcp.py')]}
    if not isinstance(entry, dict) or any(entry.get(key) != value for key, value in owned.items()):
        return before
    document = tomlkit.parse(source)
    del document['mcp_servers']['bundle_local_summaries']
    output = tomlkit.dumps(document)
    output = re.sub(r'(?m)^# (?:BEGIN|END) CODEX TOKEN SAVER LOCAL_SUMMARIES\r?\n', '', output)
    tomllib.loads(output)
    if '\r\n' in source and '\n' not in source.replace('\r\n', ''):
        output = output.replace('\r\n', '\n').replace('\n', '\r\n')
    return (b'\xef\xbb\xbf' if (before or b'').startswith(b'\xef\xbb\xbf') else b'') + output.encode('utf-8')


class BundleIntegrations:
    def __init__(self, root, config_home=None):
        self.root = Path(root).resolve()
        self.home = Path(config_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.config = self.home / 'config.toml'

    def remove_retired_tools(self):
        """Explicit upgrade cleanup; status reads stay read-only."""
        with routing_lock(self.root / 'proxy/routing.lock'):
            before = _read(self.config)
            after = remove_retired_config(before, self.root)
            if after == before:
                return {'removed': False, 'restart_required': False}
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            atomic_write(self.root / 'integrations/backups' / f'config-{stamp}.toml', before)
            if _read(self.config) != before:
                raise ValueError('Codex configuration changed during cleanup; retry the upgrade.')
            try:
                atomic_write(self.config, after)
            except Exception:
                if _read(self.config) == after:
                    atomic_write(self.config, before)
                raise
        return {'removed': True, 'restart_required': True}

    def _paths(self, component):
        if component not in TOOLS:
            raise ValueError('Unknown bundle integration.')
        script = {'serena': 'serena_mcp.py', 'laya_router': 'bundle_router_mcp.py'}[component]
        from component_runtime import component_descriptor
        descriptor = component_descriptor(self.root, 'laya' if component == 'laya_router' else component)
        return (self.root / 'headroom/.venv/Scripts/python.exe', self.root / script,
                self.root / descriptor['python_path'])

    @staticmethod
    def _pattern(component):
        label = component.upper()
        return re.compile(r'\r?\n# BEGIN CODEX TOKEN SAVER ' + label + r'\r?\n.*?\r?\n# END CODEX TOKEN SAVER ' + label + r'\r?\n', re.S)

    def _block(self, component):
        python, script, _ = self._paths(component)
        label = component.upper()
        return (f'\n# BEGIN CODEX TOKEN SAVER {label}\n[mcp_servers.bundle_{component}]\n'
                f'command = {json.dumps(str(python))}\nargs = {json.dumps([str(script)])}\n'
                'required = false\nstartup_timeout_sec = 90\ntool_timeout_sec = 120\n'
                f'enabled_tools = {json.dumps(TOOLS[component])}\n'
                f'# END CODEX TOKEN SAVER {label}\n')

    def status(self):
        raw = _read(self.config)
        parsed = tomllib.loads(raw.decode('utf-8-sig'))
        text = raw.decode('utf-8')
        preferences = load_preferences(self.root)
        result = {}
        for name in TOOLS:
            entry = parsed.get('mcp_servers', {}).get('bundle_' + name)
            result[name] = {
                'requested_enabled': preferences[name],
                'installed': all(path.is_file() for path in self._paths(name)),
                'configured': isinstance(entry, dict) and entry.get('enabled', True) is not False,
                'managed': bool(self._pattern(name).search(text)),
                'tools': TOOLS[name],
            }
            if name == 'serena':
                try:
                    activity = json.loads(_read(self.root / 'serena/activity.json'))
                    result[name]['last_use'] = activity.get('last_activity_at')
                except (ValueError, OSError, AttributeError):
                    result[name]['last_use'] = None
        return result

    def set_enabled(self, component, enabled):
        self._paths(component)
        if type(enabled) is not bool:
            raise ValueError('enabled must be true or false.')
        if enabled and not all(path.is_file() for path in self._paths(component)):
            raise ValueError('Install and validate this integration before enabling it.')
        with routing_lock(self.root / 'proxy/routing.lock'):
            before = _read(self.config)
            text = before.decode('utf-8')
            parsed = tomllib.loads(before.decode('utf-8-sig'))
            pattern = self._pattern(component)
            matches = list(pattern.finditer(text))
            label = component.upper()
            if len(matches) > 1 or text.count('# BEGIN CODEX TOKEN SAVER ' + label) != len(matches):
                raise ValueError('Managed integration markers are damaged; configuration was left unchanged.')
            if 'bundle_' + component in parsed.get('mcp_servers', {}) and not matches:
                raise ValueError('An unmanaged MCP entry uses this name; configuration was left unchanged.')
            entry = parsed.get('mcp_servers', {}).get('bundle_' + component, {})
            if matches and 'enabled' in entry:
                # Codex can append this field after our end comment; it still belongs to our table.
                document = tomlkit.parse(text.lstrip('\ufeff'))
                del document['mcp_servers']['bundle_' + component]['enabled']
                text = ('\ufeff' if text.startswith('\ufeff') else '') + tomlkit.dumps(document)
            updated = pattern.sub(lambda _: self._block(component) if enabled else '', text)
            if enabled and not matches:
                updated += self._block(component)
            tomllib.loads(updated.lstrip('\ufeff'))
            after = updated.encode('utf-8')
            previous_enabled = load_preferences(self.root)[component]
            changes = [(self.config, before, after, self.config.exists())]
            if component == 'serena':
                agents = self.home / 'AGENTS.md'
                original = _read(agents)
                changes.append((agents, original, _serena_guidance(original, enabled), agents.exists()))
            if component == 'laya_router':
                if enabled:
                    from bundle_router import status as router_status
                    if not router_status(self.root)['available']:
                        raise RuntimeError('Install and validate Laya before enabling its entry tool.')
                agents = self.home / 'AGENTS.md'
                original = _read(agents)
                changes.append((agents, original, laya_guidance(original, enabled), agents.exists()))
            changes = [item for item in changes if item[1] != item[2]]
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            for path, original, updated, existed in changes:
                if _read(path) != original or path.exists() != existed:
                    raise ValueError('Codex configuration or guidance changed during this operation. Try again.')
                atomic_write(self.root / 'integrations/backups' / f'{path.stem}-{stamp}{path.suffix}', original)
            # Disabling reaches loaded wrappers before removing future MCP configuration.
            # A failed write rolls back this component while preserving unrelated settings.
            attempted = []
            try:
                set_preference(self.root, component, enabled)
                for change in changes:
                    path, original, updated, existed = change
                    if _read(path) != original or path.exists() != existed:
                        raise ValueError('Codex configuration or guidance changed during this operation. Try again.')
                    attempted.append(change)
                    atomic_write(path, updated)
            except Exception:
                try:
                    for path, original, updated, existed in reversed(attempted):
                        # Never overwrite a concurrent external edit during rollback.
                        if _read(path) == updated:
                            if existed:
                                atomic_write(path, original)
                            else:
                                path.unlink(missing_ok=True)
                finally:
                    set_preference(self.root, component, previous_enabled)
                raise
        return {'component': component, 'enabled': enabled, 'restart_required': True}
