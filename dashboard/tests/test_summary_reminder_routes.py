"""Reminder preferences share the dashboard's local request boundary."""
import pytest
from flask import Flask
from update_routes import register_update_routes


class Reminders:
    def __init__(self):
        self.calls = []
        self.enabled, self.threshold = True, 70

    def status(self):
        return {'enabled': self.enabled, 'threshold_percent': self.threshold,
                'tasks': [], 'error': None}

    def configure(self, enabled, threshold_percent):
        self.calls.append((enabled, threshold_percent))
        self.enabled, self.threshold = enabled, threshold_percent
        return self.status()


@pytest.fixture
def api(tmp_path):
    from summary_reminder_routes import register_summary_reminder_routes
    app = Flask(__name__)
    guard = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    service, constructed = Reminders(), []
    def factory(root):
        constructed.append(root)
        return service
    register_summary_reminder_routes(app, tmp_path, guard, factory)
    return app.test_client(), guard.csrf_token, service, constructed


def post(api, payload, **headers):
    return api[0].post('/api/summary-reminders', base_url='http://127.0.0.1:8095', json=payload,
                       headers={'Origin': 'http://127.0.0.1:8095',
                                'X-Codex-Update-Token': api[1], **headers})


def test_read_never_changes_preferences_and_returns_no_store(api):
    response = api[0].get('/api/summary-reminders', base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    assert response.json == api[2].status()
    assert response.headers['Cache-Control'] == 'no-store'
    assert api[2].calls == []


@pytest.mark.parametrize('headers', [{'Origin': ''}, {'Origin': 'http://evil.test'},
    {'X-Codex-Update-Token': ''}, {'Sec-Fetch-Site': 'cross-site'}, {'Host': 'evil.test:8095'}])
def test_invalid_request_boundary_cannot_construct_service(api, headers):
    assert post(api, {'enabled': True, 'threshold_percent': 70}, **headers).status_code == 403
    assert api[3] == []


@pytest.mark.parametrize('payload', [None, [], {}, {'enabled': True},
    {'enabled': 1, 'threshold_percent': 70}, {'enabled': True, 'threshold_percent': True},
    {'enabled': True, 'threshold_percent': 70.0}, {'enabled': True, 'threshold_percent': '70'},
    {'enabled': True, 'threshold_percent': 19}, {'enabled': True, 'threshold_percent': 96},
    {'enabled': True, 'threshold_percent': 70, 'task_id': 'private'}])
def test_body_is_fixed_boolean_and_integer_range(api, payload):
    assert post(api, payload).status_code == 400
    assert api[3] == []


@pytest.mark.parametrize('threshold', [20, 70, 95])
def test_explicit_configuration_is_applied_once(api, threshold):
    response = post(api, {'enabled': False, 'threshold_percent': threshold})
    assert response.status_code == 200
    assert response.json['threshold_percent'] == threshold
    assert response.json['enabled'] is False
    assert api[2].calls == [(False, threshold)]
    assert response.headers['Cache-Control'] == 'no-store'


def test_unknown_queries_bad_host_and_oversized_body_are_rejected(api):
    assert api[0].get('/api/summary-reminders?path=private', base_url='http://127.0.0.1:8095').status_code == 400
    assert api[0].get('/api/summary-reminders', base_url='http://evil.test:8095').status_code == 403
    assert post(api, {'enabled': True, 'threshold_percent': '7' * 3000}).status_code == 400
    assert api[3] == []


def test_backend_failure_does_not_expose_exception(api, monkeypatch):
    def fail():
        raise OSError('private path and transcript content')
    monkeypatch.setattr(api[2], 'status', fail)
    response = api[0].get('/api/summary-reminders', base_url='http://127.0.0.1:8095')
    assert response.status_code == 503
    assert 'private' not in response.text
