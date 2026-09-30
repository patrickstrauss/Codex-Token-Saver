"""New records must remain bounded, attributable and free of operation contents."""
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

TASK = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'


@pytest.fixture
def activity():
    assert importlib.util.find_spec('bundle_activity'), 'The new activity ledger is missing'
    return importlib.import_module('bundle_activity')


def test_persists_only_fixed_metadata_and_never_guesses_task(tmp_path, activity):
    secret = 'https://private.invalid/customer?q=secret'
    assert activity.record(tmp_path, 'serena', 'failed', task_id=secret, error_code=secret)
    assert not activity.record(tmp_path, secret, 'completed')
    assert not activity.record(tmp_path, 'serena', secret)
    assert not activity.record(tmp_path, 'serena', 'completed', kind=secret)
    event = activity.snapshot(tmp_path)['recent'][0]
    assert set(event) == {'id', 'timestamp', 'component', 'outcome', 'task_id', 'kind', 'error_code'}
    assert event['task_id'] is None and event['error_code'] == 'other'
    assert all(secret.encode() not in file.read_bytes() for file in tmp_path.rglob('*') if file.is_file())


def test_groups_new_records_without_backfilling_legacy_counts(tmp_path, activity):
    (tmp_path / 'serena').mkdir()
    (tmp_path / 'serena/activity.json').write_text('{"completed":900}')
    assert activity.snapshot(tmp_path)['total'] == 0
    activity.record(tmp_path, 'serena', 'completed', task_id=TASK.upper())
    activity.record(tmp_path, 'serena', 'failed', task_id=TASK, kind='diagnostic', error_code='timeout')
    activity.record(tmp_path, 'ast_grep', 'completed', kind='informational')
    activity.record(tmp_path, 'playwright_cli', 'blocked', error_code='disabled')
    data = activity.snapshot(tmp_path)
    assert data['groups'] == {'all': 4, 'tasks': 1, 'diagnostic': 1, 'informational': 1, 'unknown': 1}
    assert activity.snapshot(tmp_path, group='tasks')['total'] == 1
    assert activity.snapshot(tmp_path, task_id=TASK)['total'] == 2
    assert activity.snapshot(tmp_path, group='unknown')['recent'][0]['task_id'] is None
    assert data['failure_categories'] == {'timeout': 1, 'disabled': 1}
    assert data['legacy_counters'] == 'mixed_unattributed'
    assert 'saved_tokens' not in data


def test_concurrent_writers_and_retention_keep_newest_records(tmp_path, activity, monkeypatch):
    monkeypatch.setattr(activity, 'MAX_EVENTS', 20)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: activity.record(tmp_path, 'serena', 'completed'), range(45)))
    assert all(results)
    data = activity.snapshot(tmp_path, limit=5)
    assert data['total'] == 20 and len(data['recent']) == 5
    ids = [event['id'] for event in data['recent']]
    assert ids == sorted(ids, reverse=True)
    assert data['recent_window_only'] is True


def test_unavailable_storage_is_best_effort_and_reads_create_nothing(tmp_path, activity):
    assert activity.snapshot(tmp_path)['data_status'] == 'not_started'
    assert list(tmp_path.iterdir()) == []
    (tmp_path / 'activity').write_text('blocked directory')
    assert activity.record(tmp_path, 'serena', 'completed') is False
    assert activity.snapshot(tmp_path)['data_status'] == 'unavailable'


@pytest.mark.parametrize('filters', [{'group': 'private'}, {'task_id': '../private'}, {'limit': 0}, {'limit': 201}])
def test_invalid_filters_do_not_silently_return_all_activity(tmp_path, activity, filters):
    with pytest.raises(ValueError):
        activity.snapshot(tmp_path, **filters)


def test_task_titles_are_read_only_id_queries_not_history(tmp_path, activity):
    home = tmp_path / 'codex'
    home.mkdir()
    database = home / 'state_5.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE threads (id TEXT, title TEXT, rollout_path TEXT)')
        connection.executemany('INSERT INTO threads VALUES (?, ?, ?)', [
            (TASK, '<img src=x> Requested title', '/unreadable/history'),
            ('b6e593dc-4bd7-40f6-8250-ae9d8990efe4', 'Unrelated private title', '/private')])
    before = database.read_bytes()
    assert activity.task_titles([TASK, '../invalid'], codex_home=home) == {TASK: '<img src=x> Requested title'}
    assert database.read_bytes() == before


@pytest.mark.parametrize('code', ['connection_refused', 'invalid_endpoint', 'ambiguous_selector',
    'timeout', 'command_failed', 'router_unavailable', 'runtime_missing', 'route_failed',
    'invalid_operation', 'router_off', 'classifier_unavailable', 'invalid_decision',
    'route_rejected', 'retrieval_recovery', 'tool_failed'])
def test_fixed_cli_router_failure_categories_are_preserved(tmp_path, activity, code):
    activity.record(tmp_path, 'laya_router', 'failed', error_code=code)
    assert activity.snapshot(tmp_path)['failure_categories'] == {code: 1}
