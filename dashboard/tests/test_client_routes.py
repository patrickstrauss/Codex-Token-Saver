import json
from pathlib import Path
import sys

import pytest
from flask import Flask
from update_routes import register_update_routes
from client_routes import register_client_routes


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'bundle'
    python = root / 'headroom/.venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    (root / 'harness_mcp.py').touch()
    (root / 'desktop_mcp.py').touch()
    app = Flask(__name__)
    security = register_update_routes(app, root, 8095, {})
    register_client_routes(app, root, security)
    return app.test_client(), security, root


def test_export_is_read_only_and_supports_each_format(setup):
    client, security, root = setup
    headers = {'Origin':'http://127.0.0.1:8095', 'X-Codex-Update-Token':security.csrf_token}
    for name, section in (('claude-code','mcpServers'), ('gemini-cli','mcpServers'),
                          ('cursor','mcpServers'), ('opencode','mcp'), ('vscode','servers'), ('generic','mcpServers'),
                          ('kilo','mcp'), ('cline','mcpServers'), ('windsurf-cascade','mcpServers')):
        response = client.post('/api/clients/export', base_url='http://127.0.0.1:8095', headers=headers, json={'client':name})
        assert response.status_code == 200
        assert section in response.json['config']
        assert response.headers['Cache-Control'] == 'no-store'
    assert not (root / 'integrations/clients.json').exists()


def test_export_requires_origin_and_token(setup):
    client, security, _ = setup
    for headers in ({}, {'Origin':'https://evil.test', 'X-Codex-Update-Token':security.csrf_token},
                    {'Origin':'http://127.0.0.1:8095', 'X-Codex-Update-Token':'bad'}):
        assert client.post('/api/clients/export', base_url='http://127.0.0.1:8095', headers=headers,
                           json={'client':'cursor'}).status_code == 403
    assert client.get('/api/clients', base_url='http://evil.test:8095').status_code == 403


def test_reject_arbitrary_config_reads_and_invalid_payloads(setup):
    client, security, _ = setup
    headers = {'Origin':'http://127.0.0.1:8095', 'X-Codex-Update-Token':security.csrf_token}
    for body in ({'client':'cursor', 'path':'auth.json'}, {'client':[]}, {'client':'unknown'}, []):
        assert client.post('/api/clients/export', base_url='http://127.0.0.1:8095', headers=headers, json=body).status_code == 400
    assert client.get('/api/clients?path=auth.json', base_url='http://127.0.0.1:8095').status_code == 400


def test_list_reports_registration_not_liveness(setup):
    client, _, root = setup
    response = client.get('/api/clients', base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    assert response.json['registrations'] == []
    assert len(response.json['clients']) == 9


def test_standalone_toggles_never_call_codex_integrations(tmp_path, monkeypatch):
    from bundle_controls import BundleControls
    from bundle_preferences import load_preferences
    root = tmp_path / 'bundle'
    root.mkdir()
    (root / 'team-install-result.json').write_text('{"codex_integration":false}')
    class Forbidden:
        def status(self):
            raise AssertionError('Codex must not be inspected')
        def set_enabled(self, *args):
            raise AssertionError('Codex must not be configured')
    control = BundleControls(root, proxy=Forbidden(), integrations=Forbidden(), opencodex=lambda: (_ for _ in ()).throw(AssertionError()))
    control.set_enabled('serena', False)
    control.set_enabled('ast_grep', False)
    assert load_preferences(root)['serena'] is False
    with pytest.raises(ValueError, match='Codex only'):
        control.set_enabled('headroom_requests', True)
