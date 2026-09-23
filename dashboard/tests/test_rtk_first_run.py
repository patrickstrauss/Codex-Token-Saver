"""Fresh bundle paths and missing history must not impersonate a broken RTK."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

import app


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'RTK_DB_PATH', str(tmp_path / 'bundle/data/rtk/history.db'))
    monkeypatch.setattr(app, '_last_good', {})
    monkeypatch.setattr(app, '_last_collect_success', {})
    monkeypatch.setattr(app, 'collect_headroom', lambda: {'active': False, 'records_readable': False})
    monkeypatch.setattr(app, 'collect_desktop_headroom', lambda: {})


@pytest.mark.parametrize('overrides', [False, True])
def test_rtk_paths_use_bundle_defaults_and_preserve_explicit_environment(tmp_path, overrides):
    dashboard = Path(app.__file__).resolve().parent
    environment = {k: v for k, v in os.environ.items() if k not in ('RTK_DB_PATH', 'RTK_BIN')}
    environment['PYTHONPATH'] = os.pathsep.join([str(dashboard), str(dashboard.parent)])
    if overrides:
        environment.update(RTK_DB_PATH=str(tmp_path / 'custom history.db'), RTK_BIN=str(tmp_path / 'custom.exe'))
    code = """from unittest.mock import patch
import json
with patch('threading.Thread.start'), patch('dotenv.load_dotenv'):
    import app
print(json.dumps([app.RTK_DB_PATH, app.RTK_BIN]))
"""
    result = subprocess.run([sys.executable, '-c', code], env=environment,
                            capture_output=True, text=True, timeout=20, check=True)
    actual = json.loads(result.stdout)
    expected = ([environment['RTK_DB_PATH'], environment['RTK_BIN']] if overrides else
                [str(dashboard.parent / 'data/rtk/history.db'), str(dashboard.parent / 'bin/rtk.exe')])
    assert actual == expected


def test_fresh_missing_history_is_empty_ready_and_creates_nothing():
    database = Path(app.RTK_DB_PATH)
    for _ in range(2):
        result = app.collect_all()['rtk']
        assert result['health'] == 'ok'
        assert result['data_status'] == 'not_started'
        assert result['history_exists'] is False
        assert result['records_readable'] is True
        assert result['recent_use'] is False
        assert result['last_recorded_at'] is None
        assert result['total_commands'] == result['total_saved'] == 0
        assert result['history'] == []
        assert all(window['total_commands'] == window['total_saved'] == 0
                   for window in result['windows'].values())
    assert not database.parent.exists()


@pytest.mark.parametrize('contents', [b'not a database', b''])
def test_existing_invalid_history_stays_error_without_inventing_zero_savings(contents):
    database = Path(app.RTK_DB_PATH)
    database.parent.mkdir(parents=True)
    database.write_bytes(contents)
    result = app.collect_all()['rtk']
    assert result['health'] == 'error'
    assert result['records_readable'] is False
    assert result['total_saved'] is None
    assert database.read_bytes() == contents


def test_permission_error_is_not_treated_as_a_missing_history(monkeypatch):
    database = Path(app.RTK_DB_PATH)
    original = Path.stat

    def denied(path, *args, **kwargs):
        if path == database:
            raise PermissionError('fixture access denied')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', denied)
    result = app.collect_all()['rtk']
    assert result['health'] == 'error'
    assert result['records_readable'] is False


@pytest.mark.parametrize('failure', ['deleted', 'corrupt'])
def test_lost_previous_history_retains_saved_metrics_as_stale(failure):
    database = Path(app.RTK_DB_PATH)
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE commands (id INTEGER, timestamp TEXT, original_cmd TEXT, '
                           'saved_tokens INTEGER, savings_pct REAL, exec_time_ms INTEGER, '
                           'input_tokens INTEGER, output_tokens INTEGER)')
        connection.execute('INSERT INTO commands VALUES (1, ?, ?, 50, 50, 10, 100, 50)',
                           ('2026-09-20T00:00:00Z', 'git status'))
    connection.close()
    assert app.collect_all()['rtk']['total_saved'] == 50
    if failure == 'deleted':
        database.unlink()
    else:
        database.write_bytes(b'corrupted fixture')
    result = app.collect_all()['rtk']
    assert result['health'] == 'stale'
    assert result['data_status'] == 'historical'
    assert result['records_readable'] is False
    assert result['total_saved'] == 50
    assert result['total_commands'] == 1
