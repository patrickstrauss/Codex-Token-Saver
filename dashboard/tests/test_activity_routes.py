import importlib
import json

import pytest
from flask import Flask
from component_routes import register_component_routes
from update_routes import register_update_routes

TASK = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'


def test_activity_api_is_guarded_and_filters_only_new_records(tmp_path, monkeypatch):
    app = Flask(__name__)
    security = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    register_component_routes(app, tmp_path, security)
    client = app.test_client()
    url = 'http://localhost:8095'
    response = client.get('/api/activity', base_url=url)
    assert response.status_code == 200
    activity = importlib.import_module('bundle_activity')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'absent'))
    activity.record(tmp_path, 'serena', 'failed', task_id=TASK, error_code='timeout')
    activity.record(tmp_path, 'ast_grep', 'completed')
    data = client.get('/api/activity?task_id=' + TASK, base_url=url).json
    assert data['total'] == 1 and data['recent'][0]['task_id'] == TASK
    assert data['failure_categories'] == {'timeout': 1}
    assert data['legacy_counters'] == 'mixed_unattributed'
    assert 'savings' not in data
    assert response.headers['Cache-Control'] == 'no-store'
    for query in ('task_id=bad', 'group=bad', 'limit=999', 'group=all&group=tasks', 'path=secret'):
        assert client.get('/api/activity?' + query, base_url=url).status_code == 400
    assert client.get('/api/activity', base_url='http://evil.test:8095').status_code == 403
    assert client.get('/api/activity', base_url=url, headers={'Origin': 'https://evil.test'}).status_code == 403


def test_hook_task_filter_preserves_unknown_and_global_coverage(tmp_path, monkeypatch):
    import app
    audit = tmp_path / 'events.jsonl'
    audit.write_text('\n'.join(json.dumps(event) for event in [
        {'outcome': 'rewritten', 'task_id': TASK},
        {'outcome': 'skipped', 'task_id': TASK, 'reason': 'complex_syntax'},
        {'outcome': 'skipped', 'reason': 'unsupported_command'},
        {'outcome': 'skipped', 'task_id': 'bad', 'reason': 'secret raw error'},
    ]))
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'none')
    assert app.collect_headroom_automation()['observed'] == 4
    data = app.collect_headroom_automation(task_id=TASK)
    assert data['observed'] == 2 and data['rewritten'] == 1
    assert data['skip_reasons'] == {'complex_syntax': 1}
    assert app.collect_headroom_automation(unknown_task=True)['observed'] == 2
    assert data['task_ids'] == [TASK]


def test_hook_only_tasks_are_selectable_by_title_in_activity_api(tmp_path, monkeypatch):
    import sqlite3
    home = tmp_path / 'codex'
    home.mkdir()
    monkeypatch.setenv('CODEX_HOME', str(home))
    with sqlite3.connect(home / 'state_5.sqlite') as connection:
        connection.execute('CREATE TABLE threads (id TEXT, title TEXT)')
        connection.execute('INSERT INTO threads VALUES (?, ?)', (TASK, 'Hook only task'))
    app = Flask(__name__)
    security = register_update_routes(app, tmp_path, 8095, {}, lambda _: None)
    register_component_routes(app, tmp_path, security, hook_activity=lambda **_: {'task_ids': [TASK], 'observed': 1})
    data = app.test_client().get('/api/activity', base_url='http://localhost:8095').json
    assert data['tasks'] == [{'task_id': TASK, 'title': 'Hook only task', 'count': 0, 'last_activity_at': None}]
    assert data['total'] == 0


def test_hook_metadata_exposes_fixed_rtk_reasons_and_no_raw_timestamp(tmp_path, monkeypatch):
    import app
    audit = tmp_path / 'events.jsonl'
    audit.write_text('\n'.join(json.dumps({'outcome': 'skipped', 'reason': reason,
        'timestamp': 'https://private.invalid/raw-error'}) for reason in ('missing_rtk', 'rtk_path_unavailable')))
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'none')
    data = app.collect_headroom_automation()
    assert data['skip_reasons'] == {'missing_rtk': 1, 'rtk_path_unavailable': 1}
    assert data['last_observed_at'] is None


def test_standalone_dashboard_activity_does_not_depend_on_prior_component_load(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    source = Path(__file__).resolve().parents[2]
    shutil.copy2(source / 'bundle_activity.py', tmp_path / 'bundle_activity.py')
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from flask import Flask
from component_routes import register_component_routes
from update_routes import register_update_routes
app = Flask(__name__)
security = register_update_routes(app, sys.argv[2], 8095, {}, lambda _: None)
register_component_routes(app, sys.argv[2], security)
response = app.test_client().get('/api/activity', base_url='http://localhost:8095')
assert response.status_code == 200, response.json
assert response.json['total'] == 0
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(source / 'dashboard'), str(tmp_path)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
