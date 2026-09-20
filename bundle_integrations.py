"""Own just the bundle's two optional Codex MCP entries."""
import json
import os
from pathlib import Path
import re
import tomllib
from datetime import datetime, timezone

from desktop_proxy_control import atomic_write, routing_lock
from bundle_preferences import load_preferences, set_preference

TOOLS = {
    'serena': ['activate_project', 'get_symbols_overview', 'find_symbol', 'find_referencing_symbols'],
    'local_summaries': ['list_local_summary_tasks', 'refresh_local_summary', 'get_local_summary'],
}


def _read(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return b''
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('The configuration is too large to manage safely.')
    return data


class BundleIntegrations:
    def __init__(self, root, config_home=None):
        self.root = Path(root).resolve()
        self.home = Path(config_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.config = self.home / 'config.toml'

    def _paths(self, component):
        if component not in TOOLS:
            raise ValueError('Unknown bundle integration.')
        directory = 'serena' if component == 'serena' else 'local-compaction'
        script = 'serena_mcp.py' if component == 'serena' else 'local_summary_mcp.py'
        return (self.root / 'headroom/.venv/Scripts/python.exe', self.root / script,
                self.root / directory / '.venv/Scripts/python.exe')

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
            updated = pattern.sub(lambda _: self._block(component) if enabled else '', text)
            if enabled and not matches:
                updated += self._block(component)
            tomllib.loads(updated.lstrip('\ufeff'))
            after = updated.encode('utf-8')
            previous_enabled = load_preferences(self.root)[component]
            if after != before:
                if _read(self.config) != before:
                    raise ValueError('Codex configuration changed during this operation. Try again.')
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                atomic_write(self.root / 'integrations/backups' / f'config-{stamp}.toml', before)
            # Disabling reaches loaded wrappers before removing future MCP configuration.
            # A failed write rolls back this component while preserving unrelated settings.
            set_preference(self.root, component, enabled)
            try:
                if after != before:
                    if _read(self.config) != before:
                        raise ValueError('Codex configuration changed during this operation. Try again.')
                    atomic_write(self.config, after)
            except Exception:
                set_preference(self.root, component, previous_enabled)
                raise
        return {'component': component, 'enabled': enabled, 'restart_required': True}
