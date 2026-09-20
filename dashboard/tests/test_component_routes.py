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


class FakeSummaries:
    def __init__(self):
        self.calls = []

    def status(self):
        return {'available': True, 'running': False, 'native_compaction_retained': True}

    def list_tasks(self):
        return [{'task_id': 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4', 'project': 'fixture'}]

    def start(self, task_id):
        self.calls.append(('start', task_id))
        return {'status': 'running'}

    def cancel(self, task_id):
        self.calls.append(('cancel', task_id))
        return {'status': 'cancelled'}

    def get_summary(self, task_id):
        return {'task_id': task_id, 'summary': 'Originals remain available.'}

    def lookup_task(self, task_id):
        return {'task_id': task_id, 'title': 'An older local task'}


@pytest.fixture
def api(tmp_path):
    from component_routes import register_component_routes
    app = Flask(__name__)
    security = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    controls, summaries = FakeControls(), FakeSummaries()
    register_component_routes(app, tmp_path, security, lambda _: controls, lambda _: summaries)
    return app.test_client(), security.csrf_token, controls, summaries


def post(api, path, payload, **headers):
    return api[0].post(path, base_url='http://127.0.0.1:8095', json=payload, headers={
        'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': api[1], **headers})


def test_reading_components_and_tasks_never_enables_or_starts(api):
    for path in ('/api/components', '/api/local-summaries'):
        response = api[0].get(path, base_url='http://127.0.0.1:8095')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
    assert not api[2].calls and not api[3].calls


@pytest.mark.parametrize('headers', [{'Origin': ''}, {'Origin': 'http://evil.test'},
    {'X-Codex-Update-Token': ''}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_site_requests_cannot_toggle_or_start_model(api, headers):
    assert post(api, '/api/components', {'component': 'rtk', 'enabled': False}, **headers).status_code == 403
    assert post(api, '/api/local-summaries', {'action': 'start', 'task_id': 'x'}, **headers).status_code == 403
    assert not api[2].calls and not api[3].calls


@pytest.mark.parametrize('payload', [None, [], {}, {'component': 'rtk', 'enabled': 1},
    {'component': 'all', 'enabled': False}, {'component': 'rtk', 'enabled': False, 'path': 'private'}])
def test_component_body_has_fixed_names_and_real_boolean(api, payload):
    assert post(api, '/api/components', payload).status_code == 400
    assert not api[2].calls


def test_each_toggle_is_applied_once(api):
    for name in ('rtk', 'headroom_local', 'headroom_requests', 'serena', 'local_summaries', 'llama_cpp'):
        assert post(api, '/api/components', {'component': name, 'enabled': False}).status_code == 200
    assert len(api[2].calls) == 6


def test_mcp_configuration_change_returns_one_time_reload_hint(api, monkeypatch):
    monkeypatch.setattr(api[2], 'set_enabled', lambda component, enabled: {'restart_required': True})
    response = post(api, '/api/components', {'component': 'serena', 'enabled': True})
    assert response.json['change'] == {'component': 'serena', 'enabled': True, 'restart_required': True}
    # No persistent claim that a restart remains outstanding after later reloads.
    assert 'change' not in api[0].get('/api/components', base_url='http://127.0.0.1:8095').json


def test_model_work_requires_explicit_uuid_and_action(api):
    for payload in ({'action': 'start', 'task_id': '../secrets'}, {'action': 'start'},
                    {'action': 'start', 'task_id': 'x' * 3000}, {'action': 'latest', 'task_id': []}):
        assert post(api, '/api/local-summaries', payload).status_code == 400
    task = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'
    assert post(api, '/api/local-summaries', {'action': 'start', 'task_id': task}).status_code == 202
    assert post(api, '/api/local-summaries', {'action': 'cancel', 'task_id': task}).status_code == 200
    assert api[3].calls == [('start', task), ('cancel', task)]


def test_summary_read_and_unknown_queries_are_guarded(api):
    task = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'
    assert api[0].get('/api/local-summaries?task_id=' + task, base_url='http://127.0.0.1:8095').json['summary']
    for path in ('/api/components?enabled=true', '/api/local-summaries?path=secrets'):
        assert api[0].get(path, base_url='http://127.0.0.1:8095').status_code == 400
    assert api[0].get('/api/local-summaries', base_url='http://evil.test:8095').status_code == 403


@pytest.mark.parametrize('reference', ['01a09946-380f-72f1-ab4a-29bb5da7b861',
    'codex://threads/01a09946-380f-72f1-ab4a-29bb5da7b861',
    ' 01A09946-380F-72F1-AB4A-29BB5DA7B861 '])
def test_lookup_finds_an_older_exact_task_without_inference(api, reference):
    response = api[0].get('/api/local-summaries/lookup', query_string={'task': reference}, base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    assert response.json['task']['task_id'] == '01a09946-380f-72f1-ab4a-29bb5da7b861'
    assert response.headers['Cache-Control'] == 'no-store'
    assert not api[3].calls and not api[2].calls


@pytest.mark.parametrize('query', [{}, {'task': ''}, {'task': '../private'}, {'task': 'https://example.com'},
    {'task': 'codex://threads/01a09946-380f-72f1-ab4a-29bb5da7b861?view=review'},
    {'task': 'codex://threads/01a09946-380f-72f1-ab4a-29bb5da7b861#more'},
    {'task': 'codex://threads/01a09946-380f-72f1-ab4a-29bb5da7b861/extra'},
    {'task': 'codex://threads@evil.test/01a09946-380f-72f1-ab4a-29bb5da7b861'},
    {'task': '01a09946-380f-72f1-ab4a-29bb5da7b861', 'url': 'https://example.com'},
    [('task', '01a09946-380f-72f1-ab4a-29bb5da7b861'), ('task', 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4')]])
def test_lookup_rejects_non_task_links_and_ambiguous_queries(api, query, monkeypatch):
    monkeypatch.setattr(api[3], 'lookup_task', lambda _: pytest.fail('Invalid reference reached the local reader'))
    response = api[0].get('/api/local-summaries/lookup', query_string=query, base_url='http://127.0.0.1:8095')
    assert response.status_code == 400
    assert not api[3].calls


def test_lookup_missing_task_and_wrong_task_have_clear_errors(api, monkeypatch):
    query = {'task': '01a09946-380f-72f1-ab4a-29bb5da7b861'}
    def missing(_):
        raise FileNotFoundError('private path is not returned')
    monkeypatch.setattr(api[3], 'lookup_task', missing)
    response = api[0].get('/api/local-summaries/lookup', query_string=query, base_url='http://127.0.0.1:8095')
    assert response.status_code == 404 and 'not found on this device' in response.json['error']
    assert 'private path' not in response.json['error']
    monkeypatch.setattr(api[3], 'lookup_task', lambda _: {'task_id': 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'})
    response = api[0].get('/api/local-summaries/lookup', query_string=query, base_url='http://127.0.0.1:8095')
    assert response.status_code == 503 and 'different task' in response.json['error']
    assert api[0].get('/api/local-summaries/lookup', query_string=query, base_url='http://evil.test:8095').status_code == 403
    assert api[0].get('/api/local-summaries/lookup', query_string=query, base_url='http://127.0.0.1:8095', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert api[0].post('/api/local-summaries/lookup', query_string=query, base_url='http://127.0.0.1:8095').status_code == 405
    assert not api[3].calls
