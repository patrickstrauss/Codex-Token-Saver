"""Explicit local desktop request routing controls, sharing the dashboard guard."""
import sys
import json
import threading
from pathlib import Path

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from request_metrics import request_windows


PANEL_HTML = '''
<section class="updates-panel" id="request-proxy" aria-labelledby="request-proxy-heading">
  <div class="updates-body">
    <div class="request-heading">
      <div class="request-title"><span class="tool-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m13 2-9 12h7l-1 8 10-13h-8l1-7Z"/></svg></span><div><h2 id="request-proxy-heading">Headroom request savings</h2><p id="request-proxy-status" role="status">Checking desktop connection...</p></div></div>
      <span class="window-control" id="request-proxy-window">Last 24 hours</span>
    </div>
    <div class="request-metrics" aria-label="Compression effectiveness">
      <div class="request-total"><div id="request-proxy-saved">Unavailable</div><div class="metric-caption">Estimated input tokens avoided</div></div>
      <div class="rate-metric"><span class="rate-scope">Current backend counters</span><strong id="request-proxy-active-rate">Unavailable</strong><span>Of content submitted for compression</span></div>
      <div class="rate-metric"><span class="rate-scope">Current backend counters</span><strong id="request-proxy-whole-rate">Unavailable</strong><span>Of complete request input</span></div>
    </div>
    <p id="request-proxy-scope" class="updates-muted">Estimated input tokens avoided across all tasks; individual-task attribution is unavailable.</p>
    <div class="request-footer"><p id="request-proxy-recorded" class="updates-muted"></p><div class="updates-actions"><button type="button" id="request-proxy-enable" disabled>Enable request compression</button><button type="button" id="request-proxy-pause" disabled>Pause request compression</button></div></div>
    <p id="request-proxy-error" class="updates-error" role="alert" hidden></p>
    <p id="request-proxy-restart" class="updates-restart" hidden></p>
    <details class="metric-details"><summary>Coverage, connection &amp; measurement details</summary>
      <p id="request-proxy-window-detail" class="updates-muted"></p>
      <p id="request-proxy-coverage" class="updates-muted"></p>
      <p id="request-proxy-backend-scope" class="updates-muted"></p>
      <p id="request-proxy-rate-note" class="updates-muted">The first rate covers eligible content and tool schemas; the second includes protected history and uses compression savings only. These are token estimates, not measured Codex quota savings.</p>
      <p id="request-proxy-diagnostics" class="updates-muted"></p><p id="request-proxy-timing" class="updates-muted"></p>
      <p id="request-proxy-counts" class="updates-muted"></p><p id="request-proxy-routing" class="updates-muted"></p><p id="request-proxy-backend" class="updates-muted"></p>
      <p class="updates-muted">Request savings are measured separately from RTK and local file or command savings; the totals are not added together. These text estimates are not measured Codex quota savings. A connection can carry multiple model requests.</p>
    </details>
  </div>
</section>
'''


def _make_control(root):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from desktop_proxy_control import DesktopProxyControl
    from opencodex_control import OpenCodexControl
    return RequestProxyView(root, DesktopProxyControl(root), OpenCodexControl(root))


class RequestProxyView:
    """Select the owned control while retaining explicitly historical native savings."""
    def __init__(self, root, native, extension):
        self.root, self.native, self.extension = Path(root), native, extension

    def _opencodex(self):
        try:
            return json.loads((self.root / 'proxy/settings.json').read_text(encoding='utf-8-sig')).get('mode') == 'opencodex'
        except FileNotFoundError:
            return False

    def status(self):
        state = self.native.status()
        if self._opencodex():
            extension = self.extension.status()
            effective = extension.get('effective_enabled') is True
            state.update(mode='opencodex', enabled=extension.get('requested_enabled') is True,
                         effective_enabled=effective, route_enabled=effective,
                         validated=extension.get('managed') is True, ready=extension.get('ready') is True,
                         backend_ready=effective, restart_required=extension.get('needs_reload') is True,
                         last_error=extension.get('reason') if extension.get('requested_enabled') else None,
                         savings_history_only=True, backend_metrics={},
                         transform_outcomes=extension.get('outcomes', {}))
        return state

    def set_enabled(self, enabled):
        if self._opencodex():
            self.extension.set_enabled(enabled)
            return self.status()
        return self.native.set_enabled(enabled)


def register_proxy_routes(app, root, security, control_factory=None):
    """Reuse the page's Host/Origin/CSRF token; no reads change routing."""
    factory = control_factory or _make_control
    root = Path(root)
    control = None
    lock = threading.Lock()

    def manager():
        nonlocal control
        with lock:
            if control is None:
                control = factory(root)
            return control

    def handle():
        denied = security.guard(mutation=request.method == 'POST')
        if denied is not None:
            return denied
        if request.query_string:
            return security.error('Request compression controls do not accept query parameters.', 400)
        enabled = None
        if request.method == 'POST':
            try:
                request.max_content_length = 2048
                if not request.is_json:
                    raise ValueError()
                payload = request.get_json()
                if not isinstance(payload, dict) or set(payload) != {'action'}:
                    raise ValueError()
                action = payload['action']
                if action not in ('enable', 'pause'):
                    raise ValueError()
                enabled = action == 'enable'
            except (ValueError, BadRequest, RequestEntityTooLarge):
                return security.error('Choose Enable or Pause request compression.', 400)
        try:
            snapshot = manager().status() if enabled is None else manager().set_enabled(enabled)
            if snapshot.get('mode') == 'opencodex':
                recent = request_windows(root / 'proxy/transform-state/savings_events.jsonl')
                snapshot['native_savings'] = snapshot.get('savings', {})
                snapshot['recent_savings'] = recent
                snapshot['savings'] = dict(recent['windows']['last_24_hours'], available=recent['available'])
                snapshot['savings_history_only'] = False
            else:
                snapshot['recent_savings'] = request_windows(root / 'proxy/backend-state/savings_events.jsonl')
            response = jsonify(snapshot)
            response.headers['Cache-Control'] = 'no-store'
            return response
        except ValueError:
            return security.error('This routing change is not valid. Refresh the status.', 400)
        except RuntimeError:
            return security.error('Request compression is not ready for this change. Check the status and try again.', 409)
        except Exception:
            return security.error('Request compression status is unavailable. Check the status before trying again.', 503)

    app.add_url_rule('/api/request-proxy', 'request_proxy', handle, methods=['GET', 'POST'])
