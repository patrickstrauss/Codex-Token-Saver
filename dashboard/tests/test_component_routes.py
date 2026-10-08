"""Only explicit local requests may change component state or start inference."""
import pytest
from flask import Flask
from update_routes import register_update_routes


class FakeControls:
    def __init__(self):
        self.calls = []

    def status(self, observations=None):
        return {'components': [{'id': 'rtk', 'requested_enabled': True, 'state': 'ready'}],
                'overall_health': 'ok'}

    def set_enabled(self, name, enabled):
        self.calls.append((name, enabled))
        return self.status()




@pytest.fixture
def api(tmp_path):
    from component_routes import register_component_routes
    app = Flask(__name__)
    security = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    controls = FakeControls()
    register_component_routes(app, tmp_path, security, lambda _: controls)
    return app.test_client(), security.csrf_token, controls


def post(api, path, payload, **headers):
    return api[0].post(path, base_url='http://127.0.0.1:8095', json=payload, headers={
        'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': api[1], **headers})


def test_reading_components_never_enables(api):
    for path in ('/api/components',):
        response = api[0].get(path, base_url='http://127.0.0.1:8095')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
    assert not api[2].calls


@pytest.mark.parametrize('headers', [{'Origin': ''}, {'Origin': 'http://evil.test'},
    {'X-Codex-Update-Token': ''}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_site_requests_cannot_toggle(api, headers):
    assert post(api, '/api/components', {'component': 'rtk', 'enabled': False}, **headers).status_code == 403
    assert not api[2].calls


@pytest.mark.parametrize('payload', [None, [], {}, {'component': 'rtk', 'enabled': 1},
    {'component': 'all', 'enabled': False}, {'component': 'rtk', 'enabled': False, 'path': 'private'}])
def test_component_body_has_fixed_names_and_real_boolean(api, payload):
    assert post(api, '/api/components', payload).status_code == 400
    assert not api[2].calls


def test_each_toggle_is_applied_once(api):
    for name in ('rtk', 'headroom_local', 'headroom_requests', 'serena', 'playwright_cli', 'ast_grep', 'laya_router'):
        assert post(api, '/api/components', {'component': name, 'enabled': False}).status_code == 200
    assert len(api[2].calls) == 7


def test_disable_dialog_is_launched_once_and_does_not_toggle_components(api, monkeypatch):
    import component_routes
    calls = []
    class Process:
        finished = False
        def poll(self):
            return 0 if self.finished else None
    process = Process()
    monkeypatch.setattr(component_routes, '_launch_disable', lambda root: calls.append(root) or process, raising=False)
    first = post(api, '/api/bundle/disable', {'action': 'open'})
    assert first.status_code == 202 and first.json == {'opened': True, 'already_open': False}
    assert first.headers['Cache-Control'] == 'no-store'
    assert post(api, '/api/bundle/disable', {'action': 'open'}).json['already_open'] is True
    assert len(calls) == 1 and not api[2].calls
    process.finished = True
    assert post(api, '/api/bundle/disable', {'action': 'open'}).status_code == 202
    assert len(calls) == 2


def test_disable_dialog_rejects_remote_untrusted_and_arbitrary_launches(api, monkeypatch):
    import component_routes
    monkeypatch.setattr(component_routes, '_launch_disable', lambda root: pytest.fail('Untrusted launch'), raising=False)
    for headers in ({'Origin': ''}, {'Origin': 'http://evil.test'}, {'X-Codex-Update-Token': ''}, {'Sec-Fetch-Site': 'cross-site'}):
        assert post(api, '/api/bundle/disable', {'action': 'open'}, **headers).status_code == 403
    for payload in ({}, {'action': 'disable'}, {'action': 'open', 'path': 'elsewhere'}, None):
        assert post(api, '/api/bundle/disable', payload).status_code == 400
    assert post(api, '/api/bundle/disable?path=elsewhere', {'action': 'open'}).status_code == 400
    assert api[0].get('/api/bundle/disable', base_url='http://127.0.0.1:8095').status_code == 405


def test_disable_dialog_launch_failure_does_not_claim_app_is_disabled(api, monkeypatch):
    import component_routes
    def unavailable(root):
        raise OSError('private local path')
    monkeypatch.setattr(component_routes, '_launch_disable', unavailable, raising=False)
    response = post(api, '/api/bundle/disable', {'action': 'open'})
    assert response.status_code == 503
    assert 'Disable-Token-Saver.cmd' in response.json['error']
    assert 'private local path' not in response.json['error']
    assert not api[2].calls


def test_disable_launcher_uses_only_fixed_script_and_interactive_mode(tmp_path, monkeypatch):
    import component_routes
    script = tmp_path / 'Disable-Token-Saver.ps1'
    script.write_text('# fixture, never executed')
    calls = []
    monkeypatch.setattr(component_routes.sys, 'platform', 'win32')
    monkeypatch.setattr(component_routes.subprocess, 'Popen', lambda args, **kwargs: calls.append((args, kwargs)))
    component_routes._launch_disable(tmp_path)
    args, options = calls[0]
    assert args[-3:] == ['-File', str(script.resolve()), '-Interactive']
    assert '-STA' in args and '-NoProfile' in args
    assert options.get('shell', False) is False
    assert options['stdin'] == component_routes.subprocess.DEVNULL
    assert options['creationflags'] == getattr(component_routes.subprocess, 'CREATE_NO_WINDOW', 0)
    script.unlink()
    with pytest.raises(RuntimeError):
        component_routes._launch_disable(tmp_path)
    assert len(calls) == 1


def test_mcp_configuration_change_returns_one_time_reload_hint(api, monkeypatch):
    monkeypatch.setattr(api[2], 'set_enabled', lambda component, enabled: {'restart_required': True})
    response = post(api, '/api/components', {'component': 'serena', 'enabled': True})
    assert response.json['change'] == {'component': 'serena', 'enabled': True, 'restart_required': True}
    # No persistent claim that a restart remains outstanding after later reloads.
    assert 'change' not in api[0].get('/api/components', base_url='http://127.0.0.1:8095').json
