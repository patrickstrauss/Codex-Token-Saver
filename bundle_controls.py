"""A small view of requested settings and observed component readiness."""
import json
import math
from datetime import datetime
from pathlib import Path

from bundle_preferences import preference_status, set_preference
from desktop_proxy_control import _latest_timestamp

LABELS = {
    'rtk': 'RTK command filtering',
    'headroom_local': 'Headroom local output',
    'headroom_requests': 'Headroom request compression',
    'serena': 'Serena symbol navigation',
    'local_summaries': 'LangMem local summaries',
    'llama_cpp': 'llama.cpp local inference',
}


def serena_diagnostics(activity):
    """Expose only bounded timings and fixed diagnostic categories, never upstream text."""
    result = {}
    elapsed = activity.get('last_elapsed_ms')
    try:
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
            result['last_elapsed_ms'] = round(elapsed, 1)
    except OverflowError:
        pass
    tool = activity.get('last_tool')
    if tool in ('activate_project', 'get_symbols_overview', 'find_symbol', 'find_referencing_symbols'):
        result['last_tool'] = tool
    failure = activity.get('last_failure')
    messages = {'missing_path': 'Requested path was not found. Check the active checkout and relative path.',
                'no_project': 'No project selected. Activate the intended checkout.',
                'timeout': 'Lookup timed out. Use native source tools for this query.',
                'upstream_error': 'Lookup failed. Use native source tools for this query.'}
    if isinstance(failure, dict) and isinstance(failure.get('kind'), str) and failure['kind'] in messages:
        result['last_failure'] = messages[failure['kind']]
        at = failure.get('at')
        if isinstance(at, str) and len(at) <= 64:
            try:
                stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
                if stamp.tzinfo is not None:
                    result['last_failure_at'] = stamp.isoformat()
            except ValueError:
                pass
    return result


class BundleControls:
    def __init__(self, root, *, proxy=None, integrations=None, summaries=None, opencodex=None):
        self.root = Path(root).resolve()
        if proxy is None:
            from desktop_proxy_control import DesktopProxyControl
            proxy = DesktopProxyControl(self.root)
        if integrations is None:
            from bundle_integrations import BundleIntegrations
            integrations = BundleIntegrations(self.root)
        self.proxy, self.integrations, self.summaries = proxy, integrations, summaries
        if opencodex is None:
            from opencodex_integration import discovery_status
            opencodex = discovery_status
        self.opencodex = opencodex

    def _summary_status(self):
        if self.summaries is None:
            from local_summaries import LocalSummaries
            self.summaries = LocalSummaries(self.root)
        return self.summaries.status()

    def status(self, observations=None):
        observations = observations or {}
        preferences = preference_status(self.root)
        values, settings_error = preferences['values'], preferences.get('error')
        try:
            opencodex = self.opencodex()
        except Exception:
            opencodex = {'reason': 'OpenCodex status could not be verified.'}
        try:
            proxy = self.proxy.status()
        except Exception:
            proxy = {'last_error': 'Request connection status could not be read.', 'enabled': None}
        try:
            integrations = self.integrations.status()
        except Exception:
            integrations = {}
        try:
            summaries = self._summary_status()
        except Exception:
            summaries = {'available': False, 'runtime_available': False, 'running': False}
        activity = {}
        try:
            with (self.root / 'serena/activity.json').open('r', encoding='utf-8') as stream:
                activity = json.loads(stream.read(16385))
            if not isinstance(activity, dict):
                activity = {}
        except (OSError, ValueError):
            pass

        rows = []
        for name, label in LABELS.items():
            requested = (proxy.get('enabled') is True or proxy.get('route_enabled') is True
                         if name == 'headroom_requests' else values[name])
            row = {'id': name, 'label': label, 'requested_enabled': requested,
                   'effective_enabled': False, 'available': False, 'state': 'off',
                   'reason': '', 'last_use': None, 'last_error': None, 'restart_required': False}
            if name == 'rtk':
                data = observations.get('rtk', {})
                row['available'] = all((self.root / file).is_file() for file in ('bin/rtk.exe', 'tools/rtk.exe'))
                row['last_use'] = data.get('last_recorded_at')
                row['reason'] = ('Used recently.' if data.get('recent_use') else
                                 'No commands recorded yet.' if data.get('data_status') == 'not_started' else
                                 'No recent use recorded.')
                row['reason'] += ' With the trusted command hook, eligible Git and rg commands use RTK automatically. Other supported commands require explicit RTK use.'
                row['last_error'] = 'RTK records could not be read; activity is unknown.' if data.get('health') in ('stale', 'error') else None
            elif name == 'headroom_local':
                data = observations.get('desktop_headroom', {})
                row['available'] = all((self.root / file).is_file() for file in ('desktop_headroom.py', 'headroom/.venv/Scripts/python.exe'))
                row['last_use'] = _latest_timestamp(data.get('last_command_check'), data.get('last_recorded_at'))
                row['reason'] = 'Checks eligible local file and command output. Original-content retrieval stays available when Off.'
                if data.get('data_status') == 'unavailable':
                    row['last_error'] = 'Local output records could not be read; activity is unknown.'
            elif name == 'headroom_requests':
                row['available'] = proxy.get('installed') is True and proxy.get('validated') is True
                row['last_use'] = proxy.get('savings', {}).get('last_recorded_at')
                row['last_error'] = proxy.get('last_error')
                row['restart_required'] = proxy.get('restart_required') is True
                row['reason'] = 'Uses the managed connection. Already-open connections may retain their prior route until Codex restarts.'
                if not requested and not row['available']:
                    row['reason'] = 'Run Setup-Request-Compression.cmd from the latest deployment package to download and validate the local request compressor, then enable it here.'
                if requested:
                    if not proxy.get('ready'):
                        row['state'] = 'error'
                        row['reason'] = 'The selected local request connection is unavailable.'
                    elif not proxy.get('route_enabled'):
                        row['state'] = 'bypassed'
                        row['reason'] = 'Compression is prepared, but Codex is using its normal connection.'
                    elif not proxy.get('backend_ready') or proxy.get('enabled') is not True:
                        row['state'] = 'bypassed'
                        row['reason'] = 'Compression is unavailable or paused. New eligible connections pass through directly.'
                    else:
                        row['state'] = 'in_use' if (proxy.get('requests', {}).get('active') or 0) > 0 else 'ready'
                        row['effective_enabled'] = True
                if proxy.get('enabled') is None:
                    row.update(state='error', requested_enabled=None, reason='The requested routing state is unknown.')
                if opencodex.get('routing_matches') is True:
                    row.update(available=False, effective_enabled=False, state='unavailable',
                               reason='Unavailable: OpenCodex integration required. Local tools remain available.')
            elif name in ('serena', 'local_summaries'):
                integration = integrations.get(name, {})
                row['available'] = integration.get('installed') is True
                row['restart_required'] = integration.get('restart_required') is True
                if name == 'serena':
                    row['last_use'] = activity.get('last_activity_at')
                    row['diagnostics'] = serena_diagnostics(activity)
                    row['activity'] = {key: value for key in ('completed', 'failed', 'blocked')
                                       if type(value := activity.get(key)) is int and value >= 0}
                    if activity.get('last_outcome') == 'failed':
                        row['last_error'] = row['diagnostics'].get('last_failure', 'The last Serena lookup failed. Exact source tools remain available.')
                    row['reason'] = 'Read-only symbol tools; activate a project explicitly. Reload Codex to discover newly configured tools.'
                else:
                    row['available'] = row['available'] and summaries.get('available') is True
                    row['last_use'] = summaries.get('last_recorded_at')
                    row['last_error'] = summaries.get('last_error')
                    row['reason'] = 'Experimental, on demand. Native Codex compaction remains enabled; summaries do not replace chat history.'
                    if requested and not values['llama_cpp']:
                        row.update(state='bypassed', reason='llama.cpp is Off. Turn it On before requesting a local summary.')
                    elif requested and summaries.get('running'):
                        row['state'] = 'in_use'
                if requested and row['state'] == 'off' and (not integration.get('configured') or not integration.get('managed')):
                    row.update(state='needs_restart', reason='The bundle MCP entry is not configured or is unmanaged. Review configuration before enabling it.')
                elif name == 'serena' and requested:
                    # A TOML entry and historical calls cannot identify which tasks
                    # currently have a live MCP connection. Do not invent a handshake.
                    row.update(state='configured', effective_enabled=None,
                               reason='Read-only tools are configured; loading in each Codex task is unverified. Reload Codex to discover newly configured tools. Recorded calls are historical activity.')
            else:
                row['available'] = summaries.get('runtime_available') is True
                row['last_use'] = summaries.get('last_recorded_at')
                row['reason'] = 'Loads the configured local model only for an explicit summary job, then unloads it. Off blocks new jobs.'
                if requested and summaries.get('running'):
                    row['state'] = 'in_use'
            if name != 'headroom_requests':
                if settings_error:
                    row.update(state='error', last_error=settings_error, reason='Component preferences are unreadable; filtering is bypassed.')
                elif requested:
                    if not row['available']:
                        row.update(state='unavailable', reason='Required runtime or configuration is missing. Install and validate it before enabling.')
                    elif row['state'] in ('off', 'in_use'):
                        row['state'] = 'in_use' if row['state'] == 'in_use' else 'ready'
                        row['effective_enabled'] = True
                else:
                    row['state'] = 'off'
                    if not row['available']:
                        row['reason'] = 'Not installed or not validated. ' + row['reason']
            if requested and row['last_error'] and row['state'] == 'ready':
                row['state'] = 'error'
            rows.append(row)
        selected = [row for row in rows if row['requested_enabled']]
        severe = (any(row['state'] in ('error', 'unavailable') for row in selected) or bool(settings_error)
                  or any(row['requested_enabled'] is None for row in rows))
        degraded = any(row['state'] in ('bypassed', 'needs_restart') for row in selected)
        return {'components': rows, 'overall_health': 'error' if severe else 'stale' if degraded else 'ok',
                'selected_count': len(selected), 'preferences_error': settings_error,
                'unverified_count': sum(row['effective_enabled'] is None for row in selected),
                'opencodex': opencodex,
                'native_compaction_retained': True}

    def set_enabled(self, component, enabled):
        if component not in LABELS or type(enabled) is not bool:
            raise ValueError('Choose a listed component and a boolean value.')
        if component == 'headroom_requests':
            if enabled:
                try:
                    opencodex = self.opencodex()
                except Exception as exc:
                    raise RuntimeError('OpenCodex status could not be verified; no route changed.') from exc
                if opencodex.get('routing_matches') is True:
                    raise RuntimeError('OpenCodex integration is not qualified for enablement. Local tools remain available.')
            return self.proxy.set_enabled(enabled)
        if enabled:
            row = next(row for row in self.status()['components'] if row['id'] == component)
            if not row['available']:
                raise RuntimeError('This component has not been installed and validated.')
        if component in ('serena', 'local_summaries'):
            return self.integrations.set_enabled(component, enabled)
        set_preference(self.root, component, enabled)
        return {'component': component, 'enabled': enabled}
