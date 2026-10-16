"""Read-only client setup exports behind the dashboard's local security boundary."""
import sys
from pathlib import Path
from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


def register_client_routes(app, root, security):
    root = Path(root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from harness_clients import CLIENTS, export_config, registrations, codex_enabled

    def respond(data):
        response = jsonify(data)
        response.headers['Cache-Control'] = 'no-store'
        return response

    def clients():
        denied = security.guard()
        if denied is not None:
            return denied
        if request.query_string:
            return security.error('Client setup does not accept query parameters.', 400)
        try:
            return respond({'clients': [dict(id=k, label=v[0]) for k, v in CLIENTS.items()],
                            'registrations': registrations(root), 'codex_integration': codex_enabled(root)})
        except (OSError, ValueError, KeyError):
            return security.error('Client ownership data is unavailable; keep it for recovery.', 409)

    def export():
        denied = security.guard(mutation=True)
        if denied is not None:
            return denied
        request.max_content_length = 1024
        try:
            if request.query_string or not request.is_json:
                raise ValueError()
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) != {'client'} or payload['client'] not in CLIENTS:
                raise ValueError()
            return respond({'config': export_config(root, payload['client']),
                            'script': str(root / 'Connect-Harness.ps1')})
        except (ValueError, TypeError, BadRequest, RequestEntityTooLarge):
            return security.error('Choose a listed MCP client with an installed bundle runtime.', 400)
        except OSError:
            return security.error('Bundle runtime is unavailable.', 503)

    app.add_url_rule('/api/clients', 'coding_clients', clients, methods=['GET'])
    app.add_url_rule('/api/clients/export', 'export_client_config', export, methods=['POST'])
