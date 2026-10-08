"""Upgrade boundaries preserve retained state while retired entry points disappear."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.mark.parametrize('path', ['/api/local-summaries', '/api/local-summaries/lookup', '/api/summary-reminders'])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_retired_dashboard_endpoints_are_absent(path, method):
    import app
    response = app.app.test_client().open(path, method=method, base_url='http://127.0.0.1:8095')
    assert response.status_code == 404


def test_legacy_preferences_keep_retained_choices_and_saved_data(tmp_path):
    from bundle_preferences import preference_status, set_preference
    settings = tmp_path / 'settings/components.json'
    settings.parent.mkdir()
    original = json.dumps({'schema_version': 1, 'components': {
        'rtk': False, 'headroom_local': True, 'serena': True,
        'local_summaries': True, 'llama_cpp': True}}).encode()
    settings.write_bytes(original)
    summary = tmp_path / 'saved-summary.json'
    summary.write_bytes(b'private saved summary')
    model = tmp_path / 'model.gguf'
    model.write_bytes(b'private saved model')
    status = preference_status(tmp_path)
    assert status['error'] is None
    assert status['values']['rtk'] is False and status['values']['serena'] is True
    assert not {'local_summaries', 'llama_cpp'} & status['values'].keys()
    assert settings.read_bytes() == original
    set_preference(tmp_path, 'rtk', True)
    assert json.loads(settings.read_bytes())['components'] == {'rtk': True, 'headroom_local': True, 'serena': True}
    for key in ('local_summaries', 'llama_cpp'):
        with pytest.raises(ValueError):
            set_preference(tmp_path, key, True)
    assert summary.read_bytes() == b'private saved summary' and model.read_bytes() == b'private saved model'


@pytest.mark.parametrize('fields', [{'task_id': '11111111-1111-4111-8111-111111111111'}, {'summary_action': 'start'}, {}])
def test_laya_rejects_summary_requests_before_execution(tmp_path, fields):
    import bundle_router
    from bundle_preferences import set_preference
    set_preference(tmp_path, 'laya_router', True)
    request = {'intent': 'read saved summary', 'project': str(tmp_path), **fields}
    def prediction(root, intent, eligible):
        assert 'summary' not in eligible
        return {'route': 'summary', 'confidence': .99, 'delivery': 'exact'}
    with patch.object(bundle_router, 'execute', side_effect=AssertionError('retired backend executed')):
        with pytest.raises(ValueError):
            bundle_router.query(tmp_path, request, predictor=prediction)


def test_old_summary_tools_cannot_use_internal_authorization(tmp_path):
    import laya_dispatch
    for operation in ('list_local_summary_tasks', 'get_local_summary', 'refresh_local_summary'):
        with laya_dispatch.routed_call(tmp_path, 'local_summaries'):
            with pytest.raises(laya_dispatch.AuthorizationError):
                laya_dispatch.authorize_explicit(tmp_path, 'local_summaries', operation)


def test_retired_activity_is_not_offered_or_recorded(tmp_path):
    import bundle_activity
    for component in ('local_summaries', 'llama_cpp'):
        assert bundle_activity.record(tmp_path, component, 'completed') is False
    assert bundle_activity.snapshot(tmp_path)['recent'] == []


def test_owned_obsolete_mcp_entry_is_removed_without_changing_unrelated_config(tmp_path):
    import tomllib
    from bundle_integrations import BundleIntegrations
    home = tmp_path / 'codex'
    home.mkdir()
    config = home / 'config.toml'
    source = ('model="saved-provider-model"\nmodel_provider="custom"\n'
        '[model_providers.custom]\nbase_url="https://provider.invalid/v1"\n'
        '[mcp_servers.external]\ncommand="external.exe"\n'
        '# BEGIN CODEX TOKEN SAVER LOCAL_SUMMARIES\n[mcp_servers.bundle_local_summaries]\n'
        'command=' + json.dumps(str(tmp_path / 'headroom/.venv/Scripts/python.exe')) + '\n'
        'args=' + json.dumps([str(tmp_path / 'local_summary_mcp.py')]) + '\n'
        '# END CODEX TOKEN SAVER LOCAL_SUMMARIES\nenabled=false\n')
    config.write_text(source)
    control = BundleIntegrations(tmp_path, config_home=home)
    control.remove_retired_tools()
    parsed = tomllib.loads(config.read_text())
    assert 'bundle_local_summaries' not in parsed['mcp_servers']
    assert parsed['mcp_servers']['external'] == {'command': 'external.exe'}
    assert parsed['model'] == 'saved-provider-model' and parsed['model_provider'] == 'custom'
    assert parsed['model_providers']['custom']['base_url'] == 'https://provider.invalid/v1'
    first = config.read_bytes()
    control.remove_retired_tools()
    assert config.read_bytes() == first


def test_custom_mcp_entry_with_retired_name_is_preserved(tmp_path):
    from bundle_integrations import BundleIntegrations
    home = tmp_path / 'codex'
    home.mkdir()
    config = home / 'config.toml'
    original = b'[mcp_servers.bundle_local_summaries]\ncommand="unrelated.exe"\n'
    config.write_bytes(original)
    BundleIntegrations(tmp_path, config_home=home).remove_retired_tools()
    assert config.read_bytes() == original


def selected_laya(root):
    selected = root / 'laya/releases/0.4.0/Scripts/python.exe'
    selected.parent.mkdir(parents=True)
    selected.touch()
    (root / 'laya/runtime.json').write_text(json.dumps({'schema_version': 1, 'version': '0.4.0',
        'python_path': selected.relative_to(root).as_posix()}))
    return selected


def test_laya_worker_uses_selected_runtime(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import bundle_router
    from bundle_preferences import set_preference
    selected = selected_laya(tmp_path)
    set_preference(tmp_path, 'laya_router', True)
    monkeypatch.setattr(bundle_router, 'status', lambda root: {'available': True})
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=False)
    probe.connect_ex.return_value = 1
    monkeypatch.setattr(bundle_router.socket, 'socket', lambda: probe)
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(bundle_router.subprocess, 'Popen', launch)
    replies = iter([OSError('worker absent'), {'service': 'cts-laya-router'}, {'route': 'file_read'}])
    def request(*args, **kwargs):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(bundle_router, '_request', request)
    bundle_router.classify(tmp_path, 'fixture request', ['file_read'])
    assert launch.call_args.args[0][0] == str(selected)


def test_laya_live_status_matches_selected_version_and_validation_receipt(tmp_path):
    import bundle_router
    selected = selected_laya(tmp_path)
    (tmp_path / 'laya/model').mkdir()
    (tmp_path / 'laya/model/model.safetensors').touch()
    (tmp_path / 'bundle_router_mcp.py').touch()
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/laya-model.json').write_text(json.dumps({'revision': 'fixture'}))
    legacy = tmp_path / 'laya/ready.json'
    legacy.write_text(json.dumps({'version': '0.3.22', 'revision': 'fixture', 'inference_verified': True}))
    ready = selected.parent.parent / 'bundle-ready.json'
    ready.write_text(json.dumps({'version': '0.4.0', 'revision': 'fixture', 'inference_verified': True}))
    state = bundle_router.status(tmp_path)
    assert state['available'] is True and state['version'] == '0.4.0'
    ready.write_text(json.dumps({'version': '0.3.22', 'revision': 'fixture', 'inference_verified': True}))
    assert bundle_router.status(tmp_path)['available'] is False
    ready.unlink()
    legacy.write_text(json.dumps({'version': '0.4.0', 'revision': 'fixture', 'inference_verified': True}))
    assert bundle_router.status(tmp_path)['available'] is False


@pytest.mark.parametrize('action', ['install', 'rollback'])
@pytest.mark.parametrize('component', ['laya', 'langmem', 'llama_cpp'])
def test_update_boundary_accepts_laya_and_rejects_retired_libraries(tmp_path, action, component):
    from flask import Flask
    from update_routes import register_update_routes
    class Updater:
        def __init__(self):
            self.calls = []
        def start(self, action, component):
            self.calls.append((action, component))
            return {'busy': True}
    updater = Updater()
    app = Flask(__name__)
    routes = register_update_routes(app, tmp_path, 8095, {}, lambda _: updater)
    response = app.test_client().post('/api/updates', base_url='http://127.0.0.1:8095',
        json={'action': action, 'component': component},
        headers={'Origin': 'http://127.0.0.1:8095', 'X-Codex-Update-Token': routes.csrf_token})
    assert response.status_code == (202 if component == 'laya' else 400)
    assert updater.calls == ([(action, component)] if component == 'laya' else [])


def test_rendered_dashboard_has_retained_cards_and_no_summary_panel():
    import app
    response = app.app.test_client().get('/', base_url=f'http://127.0.0.1:{app.PORT}')
    assert response.status_code == 200
    for component in ('headroom', 'rtk', 'serena', 'laya'):
        assert f'id="update-{component}-current"' in response.text
    assert not any(value in response.text for value in ('LangMem', 'llama.cpp', 'local-summary-panel', 'summary-reminder'))


def test_disable_removes_owned_retired_registration_and_keeps_other_disabled_contracts(tmp_path):
    import tomllib
    from bundle_integrations import BundleIntegrations
    from disable_bundle import disable_config
    source = 'model="chosen"\n[mcp_servers.external]\ncommand="custom.exe"\n'
    source += '[mcp_servers.bundle_local_summaries]\ncommand=' + json.dumps(str(tmp_path / 'headroom/.venv/Scripts/python.exe'))
    source += '\nargs=' + json.dumps([str(tmp_path / 'local_summary_mcp.py')]) + '\n'
    integration = BundleIntegrations(tmp_path, config_home=tmp_path / 'codex')
    for component in ('serena', 'laya_router'):
        source += integration._block(component)
    disabled = disable_config(source.encode(), tmp_path)
    parsed = tomllib.loads(disabled.decode())
    assert parsed['model'] == 'chosen'
    assert parsed['mcp_servers']['external'] == {'command': 'custom.exe'}
    assert 'bundle_local_summaries' not in parsed['mcp_servers']
    assert all(parsed['mcp_servers'][name]['enabled'] is False for name in ('bundle_serena', 'bundle_laya_router'))
    assert disable_config(disabled, tmp_path) == disabled
