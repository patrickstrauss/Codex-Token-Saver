"""Desktop routing changes are explicit, local, and never replayed by the UI."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask

from update_routes import register_update_routes


def test_request_proxy_controls_are_available():
    assert importlib.util.find_spec('proxy_routes') is not None, 'Desktop proxy controls are missing'


class FakeControl:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.enabled = False

    def status(self):
        return {'installed': True, 'validated': True, 'enabled': self.enabled,
                'route_enabled': self.enabled, 'mode': 'optimized' if self.enabled else 'paused',
                'ready': True, 'backend_ready': True, 'restart_required': bool(self.calls),
                'requests': {'optimized': 2, 'direct': 1, 'failed': 0, 'active': 0},
                'backend_metrics': {'scope': 'backend_counters', 'active_reduction_pct': 60,
                                    'whole_reduction_pct': 2, 'collected_at': '2026-09-21T03:00:00Z'},
                'savings': {'available': True, 'saved_tokens': 321, 'estimated': True}}

    def set_enabled(self, enabled):
        self.calls.append(enabled)
        if self.failure:
            raise self.failure
        self.enabled = enabled
        return self.status()


@pytest.mark.parametrize('enabled', [True, False])
def test_opencodex_panel_uses_extension_control_and_marks_legacy_counters(tmp_path, enabled):
    from proxy_routes import RequestProxyView
    (tmp_path / 'proxy').mkdir()
    settings = tmp_path / 'proxy/settings.json'
    settings.write_text(json.dumps({'mode': 'opencodex', 'enabled': False}))
    native = FakeControl()
    class Extension:
        def __init__(self):
            self.calls = []
        def status(self):
            return {'managed': True, 'requested_enabled': enabled, 'effective_enabled': enabled,
                    'ready': True, 'needs_reload': False, 'reason': None if enabled else 'Paused.',
                    'outcomes': {'compressed': 3, 'unchanged': 1, 'bypassed': 2, 'error': 0}}
        def set_enabled(self, value):
            self.calls.append(value)
    extension = Extension()
    view = RequestProxyView(tmp_path, native, extension)
    status = view.status()
    assert status['mode'] == 'opencodex'
    assert status['enabled'] is enabled
    assert status['effective_enabled'] is enabled
    assert status['restart_required'] is False
    assert status['savings_history_only'] is True
    assert status['savings']['saved_tokens'] == 321
    assert status['backend_metrics'] == {}  # Never reuse native percentages for this mode.
    assert status['transform_outcomes']['compressed'] == 3
    view.set_enabled(not enabled)
    assert extension.calls == [not enabled] and not native.calls
    settings.write_text(json.dumps({'mode': 'native'}))
    view.set_enabled(True)
    assert native.calls == [True]  # Re-read mode after a handoff.


@pytest.fixture
def proxy_api(tmp_path):
    from proxy_routes import register_proxy_routes
    app = Flask(__name__)
    guard = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    control, constructed = FakeControl(), []
    def factory(root):
        constructed.append(root)
        return control
    register_proxy_routes(app, tmp_path, guard, factory)
    return app.test_client(), guard.csrf_token, control, constructed


def post(api, payload, **kwargs):
    client, token, _, _ = api
    headers = {'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': token}
    headers.update(kwargs.pop('headers', {}))
    return client.post('/api/request-proxy', base_url=kwargs.pop('base_url', 'http://127.0.0.1:8095'),
                       headers=headers, json=payload, **kwargs)


def test_status_is_read_only_and_reports_uncombined_proxy_savings(proxy_api):
    client, _, control, constructed = proxy_api
    assert not constructed
    response = client.get('/api/request-proxy', base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    assert response.json['savings']['saved_tokens'] == 321
    assert response.json['mode'] == 'paused'
    assert response.json['backend_metrics'] == control.status()['backend_metrics']
    assert response.headers['Cache-Control'] == 'no-store'
    assert not control.calls


@pytest.mark.parametrize('coverage', ['missing', 'complete', 'partial', 'corrupt'])
def test_recent_ledger_coverage_is_explicit_and_read_only(proxy_api, tmp_path, coverage):
    path = tmp_path / 'proxy/backend-state/savings_events.jsonl'
    event = json.dumps({'ts': (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
                        'before': 100, 'after': 40, 'saved': 60}) + '\n'
    if coverage != 'missing':
        path.parent.mkdir(parents=True)
        path.write_text({'complete': event, 'partial': event + '{broken\n',
                         'corrupt': '{broken\n'}[coverage], encoding='utf-8')
    original = path.read_bytes() if path.exists() else None
    response = proxy_api[0].get('/api/request-proxy', base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    recent = response.json['recent_savings']
    assert recent['scope'] == 'all_tasks'
    assert recent['available'] == (coverage in ('complete', 'partial'))
    assert recent['complete'] == (coverage == 'complete')
    if recent['available']:
        assert recent['windows']['fifteen_minutes']['requests'] == 1
        assert recent['windows']['fifteen_minutes']['saved_tokens'] == 60
    assert response.json['savings']['saved_tokens'] == 321  # Remains independent.
    assert (path.read_bytes() if path.exists() else None) == original
    assert not proxy_api[2].calls


@pytest.mark.parametrize('headers', [
    {'Origin': 'http://evil.test'}, {'Origin': ''}, {'X-Codex-Update-Token': 'stale'},
    {'X-Codex-Update-Token': ''}, {'Sec-Fetch-Site': 'cross-site'},
])
def test_cross_origin_and_invalid_tokens_cannot_enable_routing(proxy_api, headers):
    assert post(proxy_api, {'action': 'enable'}, headers=headers).status_code == 403
    assert not proxy_api[3]


@pytest.mark.parametrize('host', ['http://evil.test:8095', 'https://127.0.0.1:8095', 'http://localhost:8096'])
def test_unexpected_host_is_rejected_before_loading_controller(proxy_api, host):
    assert proxy_api[0].get('/api/request-proxy', base_url=host).status_code == 403
    assert not proxy_api[3]


@pytest.mark.parametrize('payload', [None, [], {}, {'action': []}, {'action': 'restart'},
    {'action': 'enable', 'upstream': 'https://evil.test'}, {'action': 'enable', 'enabled': True}])
def test_only_fixed_actions_without_extra_fields_are_accepted(proxy_api, payload):
    assert post(proxy_api, payload).status_code == 400
    assert not proxy_api[3]


def test_queries_and_large_or_malformed_bodies_are_rejected(proxy_api):
    client, token, _, constructed = proxy_api
    assert client.get('/api/request-proxy?action=enable', base_url='http://127.0.0.1:8095').status_code == 400
    assert post(proxy_api, {'action': 'x' * 3000}).status_code == 400
    headers = {'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': token}
    assert client.post('/api/request-proxy', base_url='http://127.0.0.1:8095', headers=headers,
                       data='{broken', content_type='application/json').status_code == 400
    assert not constructed


def test_each_explicit_action_is_applied_once_and_reports_restart_state(proxy_api):
    response = post(proxy_api, {'action': 'enable'})
    assert response.status_code == 200 and response.json['enabled']
    assert response.json['restart_required'] is True
    response = post(proxy_api, {'action': 'pause'})
    assert response.status_code == 200 and not response.json['enabled']
    assert proxy_api[2].calls == [True, False]


@pytest.mark.parametrize('error,code', [(ValueError('private value'), 400),
    (RuntimeError('private busy state'), 409), (OSError('private credentials'), 503)])
def test_failures_are_opaque_and_never_retried(proxy_api, error, code):
    proxy_api[2].failure = error
    response = post(proxy_api, {'action': 'enable'})
    assert response.status_code == code
    assert 'private' not in response.text
    assert proxy_api[2].calls == [True]


def test_page_contains_request_controls_before_library_updates():
    import app
    page = app.app.test_client().get('/', base_url=f'http://127.0.0.1:{app.PORT}').text
    assert 'id="request-proxy"' in page
    assert page.index('id="request-proxy"') < page.index('id="library-updates"')
    assert '/static/proxy.js' in page
    assert '__REQUEST_PROXY_PANEL__' not in page
    assert 'id="request-proxy-window"><option value="fifteen_minutes">Last 15 minutes</option>' in page
