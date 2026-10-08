"""Local updater endpoints must not accept browser cross-origin mutations."""
import pytest
from flask import Flask

from update_routes import register_update_routes


class FakeUpdater:
    def __init__(self):
        self.calls = []
        self.failure = None

    def status(self):
        return {'busy': False, 'stage': 'ready', 'message': 'Ready', 'error': None,
                'components': [{'id': 'rtk', 'current': '0.50.0'}]}

    def start(self, action, component=None):
        self.calls.append((action, component))
        if self.failure:
            raise self.failure
        return {**self.status(), 'busy': True, 'operation': action}


@pytest.fixture
def updater_api(tmp_path):
    flask_app = Flask(__name__)
    fake = FakeUpdater()
    constructed = []
    versions = {'rtk': '0.49.0'}
    def factory(root):
        constructed.append(root)
        return fake
    updates = register_update_routes(flask_app, tmp_path, 8095, versions, factory)
    return flask_app.test_client(), updates, fake, versions, constructed


def post(client, token, payload, **overrides):
    headers = {'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': token}
    headers.update(overrides.pop('headers', {}))
    return client.post('/api/updates', base_url=overrides.pop('base_url', 'http://127.0.0.1:8095'),
                       headers=headers, json=payload, **overrides)


def test_status_is_lazy_read_only_and_refreshes_cached_rtk_version(updater_api):
    client, updates, fake, versions, constructed = updater_api
    assert not constructed
    response = client.get('/api/updates', base_url='http://127.0.0.1:8095')
    assert response.status_code == 200
    assert response.json['stage'] == 'ready'
    assert response.headers['Cache-Control'] == 'no-store'
    assert len(constructed) == 1
    assert fake.calls == []
    assert versions['rtk'] == '0.50.0'


@pytest.mark.parametrize('base_url', ['http://evil.test:8095', 'http://127.0.0.1:8096', 'http://localhost', 'https://localhost:8095'])
def test_host_and_scheme_rejected_before_constructing_manager(updater_api, base_url):
    client, _, _, _, constructed = updater_api
    assert client.get('/api/updates', base_url=base_url).status_code == 403
    assert not constructed


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://evil.test'}, {'Origin': 'http://localhost:8095'}, {'Origin': ''},
    {'X-Codex-Update-Token': ''}, {'X-Codex-Update-Token': 'invalid'},
    {'Sec-Fetch-Site': 'cross-site'},
])
def test_cross_origin_or_missing_token_cannot_start_updates(updater_api, headers):
    client, updates, fake, _, constructed = updater_api
    assert post(client, updates.csrf_token, {'action': 'check'}, headers=headers).status_code == 403
    assert fake.calls == []
    assert not constructed


@pytest.mark.parametrize('payload', [None, [], {}, {'action': 'shell'}, {'action': 'check', 'component': 'rtk'},
    {'action': 'install'}, {'action': 'install', 'component': 'other'},
    {'action': 'install', 'component': 'rtk', 'version': '9.9.9'},
    {'action': 'check', 'url': 'https://evil.test'}, {'action': ['check']}])
def test_invalid_payload_never_reaches_manager(updater_api, payload):
    client, updates, fake, _, _ = updater_api
    assert post(client, updates.csrf_token, payload).status_code == 400
    assert fake.calls == []


def test_non_json_malformed_json_and_query_are_rejected(updater_api):
    client, updates, fake, _, _ = updater_api
    headers = {'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': updates.csrf_token}
    for kwargs in [{'data': 'action=check'}, {'data': '{broken', 'content_type': 'application/json'}]:
        assert client.post('/api/updates', base_url='http://127.0.0.1:8095', headers=headers, **kwargs).status_code == 400
    assert client.post('/api/updates?command=anything', base_url='http://127.0.0.1:8095', headers=headers,
                       json={'action': 'check'}).status_code == 400
    assert fake.calls == []


@pytest.mark.parametrize('action,component', [('check', None), ('install', 'headroom'), ('rollback', 'rtk'),
                                            ('install', 'serena'), ('install', 'laya'), ('rollback', 'laya')])
def test_fixed_actions_start_one_background_operation(updater_api, action, component):
    client, updates, fake, _, _ = updater_api
    payload = {'action': action}
    if component:
        payload['component'] = component
    response = post(client, updates.csrf_token, payload)
    assert response.status_code == 202
    assert response.json['busy'] is True
    assert fake.calls == [(action, component)]


def test_busy_and_unexpected_failure_return_safe_errors_without_retry(updater_api):
    client, updates, fake, _, _ = updater_api
    fake.failure = RuntimeError('private backend text')
    response = post(client, updates.csrf_token, {'action': 'check'})
    assert response.status_code == 409
    assert 'private' not in response.text
    fake.failure = OSError('secret path or traceback')
    response = post(client, updates.csrf_token, {'action': 'check'})
    assert response.status_code == 503
    assert 'secret' not in response.text
    assert len(fake.calls) == 2


def test_dashboard_page_token_is_local_only_and_no_store(updater_api):
    client, updates, _, _, constructed = updater_api
    client.application.add_url_rule('/', 'index', lambda: updates.page('<meta content="__BUNDLE_UPDATE_CSRF__">'))
    denied = client.get('/', base_url='http://evil.test:8095')
    assert denied.status_code == 403
    assert updates.csrf_token not in denied.text
    response = client.get('/', base_url='http://localhost:8095')
    assert response.status_code == 200
    assert updates.csrf_token in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert not constructed


def test_request_size_limit_and_get_query_do_not_construct_updater(updater_api):
    client, updates, _, _, constructed = updater_api
    response = post(client, updates.csrf_token, {'action': 'check', 'padding': 'x' * 3000})
    assert response.status_code == 400
    assert client.get('/api/updates?action=install', base_url='http://127.0.0.1:8095').status_code == 400
    assert not constructed
