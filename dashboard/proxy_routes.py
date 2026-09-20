"""Explicit local desktop request routing controls, sharing the dashboard guard."""
import sys
import threading
from pathlib import Path

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


PANEL_HTML = '''
<section class="updates-panel" id="request-proxy" aria-labelledby="request-proxy-heading">
    <div class="updates-body">
        <h2 id="request-proxy-heading" style="font-size:16px;margin:0">Headroom request savings</h2>
        <p id="request-proxy-status" role="status">Checking desktop connection...</p>
        <div style="font-size:30px;color:#67c9ff;font-weight:bold" id="request-proxy-saved">Unavailable</div>
        <p class="updates-muted">Estimated input tokens avoided across model requests</p>
        <p id="request-proxy-counts" class="updates-muted"></p>
        <p id="request-proxy-routing" class="updates-muted"></p>
        <p id="request-proxy-backend" class="updates-muted"></p>
        <p id="request-proxy-recorded" class="updates-muted"></p>
        <div class="updates-actions">
            <button type="button" id="request-proxy-enable" disabled>Enable request compression</button>
            <button type="button" id="request-proxy-pause" disabled>Pause request compression</button>
        </div>
        <p id="request-proxy-error" class="updates-error" role="alert" hidden></p>
        <p id="request-proxy-restart" class="updates-restart" hidden></p>
        <p class="updates-muted">Request savings are measured separately from RTK and local file or command savings; the totals are not added together.</p>
    </div>
</section>
'''


def _make_control(root):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from desktop_proxy_control import DesktopProxyControl
    return DesktopProxyControl(root)


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
