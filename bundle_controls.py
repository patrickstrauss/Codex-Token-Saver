"""A small view of requested settings and observed component readiness."""
import json
import math
from datetime import datetime
from pathlib import Path

from bundle_preferences import EXTENSIONS, preference_status, set_preference
from bundle_activity import snapshot as activity_snapshot
from desktop_proxy_control import _latest_timestamp, _json

LABELS = {
    'rtk': 'RTK command filtering',
    'headroom_local': 'Headroom local output',
    'headroom_requests': 'Headroom request compression',
    'serena': 'Serena symbol navigation',
    'playwright_cli': 'Playwright CLI browser automation',
    'ast_grep': 'ast-grep structural code search',
    'laya_router': 'Laya bundle tool routing',
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
    def __init__(self, root, *, proxy=None, integrations=None, opencodex=None, ocx_control=None):
        self.root = Path(root).resolve()
        if proxy is None:
            from desktop_proxy_control import DesktopProxyControl
            proxy = DesktopProxyControl(self.root)
        if integrations is None:
            from bundle_integrations import BundleIntegrations
            integrations = BundleIntegrations(self.root)
        self.proxy, self.integrations = proxy, integrations
        if opencodex is None:
            from opencodex_integration import discovery_status
            opencodex = discovery_status
        self.opencodex = opencodex
        self.ocx_control = ocx_control

    def _managed_opencodex(self):
        try:
            return _json(self.root / 'proxy/settings.json').get('mode') == 'opencodex'
        except (OSError, ValueError, UnicodeError):
            return (self.root / 'proxy/opencodex-receipt.json').is_file()

    def _extension(self):
        if self.ocx_control is None:
            from opencodex_control import OpenCodexControl
            self.ocx_control = OpenCodexControl(self.root)
        return self.ocx_control


    def status(self, observations=None):
        observations = observations or {}
        new_activity = activity_snapshot(self.root)
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
                   'reason': '', 'last_use': None, 'last_error': None, 'restart_required': False,
                   'activity_source': 'legacy_mixed',
                   'last_verified_call': new_activity['last_verified_calls'].get(name)}
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
                if self._managed_opencodex() or (opencodex.get('routing_matches') is True
                                                and opencodex.get('control_protocol') == 1):
                    try:
                        extension = self._extension().status()
                        requested = extension.get('requested_enabled') is True
                        effective = extension.get('effective_enabled') is True
                        reload = extension.get('needs_reload') is True
                        row.update(available=opencodex.get('control_protocol') == 1,
                            requested_enabled=requested, effective_enabled=effective,
                            state='ready' if effective else 'needs_restart' if reload else 'bypassed' if requested else 'off',
                            restart_required=reload, last_error=None, last_use=None,
                            reason='Experimental OpenCodex transform integration.' if effective else extension.get('reason', ''),
                            outcomes=extension.get('outcomes', {}), mode='opencodex')
                    except Exception:
                        row.update(available=False, effective_enabled=False, state='error',
                                   reason='OpenCodex integration status could not be verified.')
            elif name in ('playwright_cli', 'ast_grep'):
                from cli_tools import status as cli_status
                data = cli_status(self.root, name)
                row.update(data)
                row['reason'] = (('Browser automation; Electron renderers require an available CDP connection. '
                                  'Off blocks new commands; detach external apps before switching Off.')
                                 if name == 'playwright_cli' else
                                 'Structural search, lint and explicit rewrites. Off blocks new commands.')
                row['reason'] += ' Version ' + (data.get('version') or 'not installed') + '. Updated with bundle releases. Activity counts are not token savings.'
            elif name == 'laya_router':
                from bundle_router import status as router_status
                row.update(router_status(self.root))
                row['reason'] = 'Laya is the main entry point for all explicit bundle requests when On. Typed MCP and CLI operations use validated routes without classification; free-form bundle_query uses the classifier and its confidence gate. Automatic compression and command hooks continue independently. Configured status does not verify a live task connection. No token savings are inferred.'
                row['reason'] += ' Version ' + (row.get('version') or 'not installed') + '.'
                if row.get('last_sequence'):
                    row['reason'] += ' Last sequence: ' + ' → '.join(row['last_sequence']) + '.'
                integration = integrations.get(name, {})
                if requested and not (integration.get('configured') and integration.get('managed')):
                    row.update(state='needs_restart', reason='The bundle entry tool needs registration or reload.')
                elif requested:
                    row.update(state='configured', effective_enabled=None)
            elif name == 'serena':
                integration = integrations.get(name, {})
                row['available'] = integration.get('installed') is True
                row['restart_required'] = integration.get('restart_required') is True
                row['last_use'] = activity.get('last_activity_at')
                row['diagnostics'] = serena_diagnostics(activity)
                row['activity'] = {key: value for key in ('completed', 'failed', 'blocked')
                                   if type(value := activity.get(key)) is int and value >= 0}
                if activity.get('last_outcome') == 'failed':
                    row['last_error'] = row['diagnostics'].get('last_failure', 'The last Serena lookup failed. Exact source tools remain available.')
                row['reason'] = 'Read-only symbol tools; activate a project explicitly. Reload Codex to discover newly configured tools.'
                if requested and (not integration.get('configured') or not integration.get('managed')):
                    row.update(state='needs_restart', reason='The bundle MCP entry is not configured or is unmanaged. Review configuration before enabling it.')
                elif requested:
                    # Configuration and history cannot verify a task's live MCP connection.
                    row.update(state='configured', effective_enabled=None,
                               reason='Read-only tools are configured; loading in each Codex task is unverified. Reload Codex to discover newly configured tools. Recorded calls are historical activity.')
            if name != 'headroom_requests':
                row_error = preferences.get('extension_error') if name in EXTENSIONS else settings_error
                if row_error:
                    row.update(state='error', last_error=row_error, reason='Component preferences are unreadable; filtering is bypassed.')
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
        severe = (any(row['state'] in ('error', 'unavailable') for row in selected) or bool(settings_error or preferences.get('extension_error'))
                  or any(row['requested_enabled'] is None for row in rows))
        degraded = any(row['state'] in ('bypassed', 'needs_restart') for row in selected)
        return {'components': rows, 'overall_health': 'error' if severe else 'stale' if degraded else 'ok',
                'selected_count': len(selected), 'preferences_error': settings_error,
                'unverified_count': sum(row['effective_enabled'] is None for row in selected),
                'opencodex': opencodex, 'new_activity': new_activity,
                'native_compaction_retained': True}

    def set_enabled(self, component, enabled):
        if component not in LABELS or type(enabled) is not bool:
            raise ValueError('Choose a listed component and a boolean value.')
        if component == 'headroom_requests':
            if self._managed_opencodex():
                return self._extension().set_enabled(enabled)
            if not enabled:
                if self.opencodex().get('routing_matches') is True:
                    return self._extension().set_enabled(False)
            if enabled:
                try:
                    opencodex = self.opencodex()
                except Exception as exc:
                    raise RuntimeError('OpenCodex status could not be verified; no route changed.') from exc
                if opencodex.get('routing_matches') is True:
                    if opencodex.get('control_protocol') == 1 and opencodex.get('transform_protocol') == 1:
                        return self._extension().set_enabled(True)
                    raise RuntimeError('OpenCodex integration is not qualified for enablement. Local tools remain available.')
            return self.proxy.set_enabled(enabled)
        if enabled:
            row = next(row for row in self.status()['components'] if row['id'] == component)
            if not row['available']:
                raise RuntimeError('This component has not been installed and validated.')
        if component in ('serena', 'laya_router'):
            return self.integrations.set_enabled(component, enabled)
        if component in ('playwright_cli', 'ast_grep'):
            from cli_tools import set_enabled
            return set_enabled(self.root, component, enabled, getattr(self.integrations, 'home', None))
        set_preference(self.root, component, enabled)
        return {'component': component, 'enabled': enabled}
