"""Focused tests for the Windows/Codex adapter; all fixtures are isolated."""
import importlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

with patch('threading.Thread.start'):
    app = importlib.import_module('app')


def test_rtk_weighted_ratio_and_readonly_database(tmp_path, monkeypatch):
    database = tmp_path / 'history.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE commands (id INTEGER, timestamp TEXT, original_cmd TEXT, saved_tokens INTEGER, savings_pct REAL, exec_time_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER)')
        conn.executemany('INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
            (1, '2026-09-13T00:00:00Z', 'git status', 90, 90, 10, 100, 10),
            (2, '2026-09-13T00:01:00Z', 'git diff', 100, 10, 20, 1000, 900),
        ])
    monkeypatch.setattr(app, 'RTK_DB_PATH', str(database))
    before = database.read_bytes()
    data = app.collect_rtk()
    assert data['total_saved'] == 190
    assert data['total_input'] == 1100
    assert data['avg_savings_pct'] == 17.3  # 190 / 1100, not mean(90, 10)
    assert database.read_bytes() == before


def test_headroom_current_schema_and_separate_metrics(monkeypatch):
    class Reply:
        def __init__(self, value):
            self.value = value

        def read(self):
            return json.dumps(self.value).encode()

    stats = {
        'tokens': {'proxy_compression_saved': 200, 'saved': 900, 'proxy_savings_percent': 20, 'savings_percent': 90},
        'persistent_savings': {'lifetime': {'tokens_saved': 300, 'requests': 3}},
        'requests': {'total': 2},
    }
    monkeypatch.setattr(app, 'urlopen', lambda url, **kw: Reply({'version': '0.37.0'} if url.endswith('/health') else stats))
    data = app.collect_headroom()
    assert data['session_saved'] == 200
    assert data['total_saved'] == 300
    assert data['avg_savings_pct'] == 20
    assert data['requests_total'] == 2


def test_disabled_credentials_do_not_touch_disk():
    with patch('builtins.open', side_effect=AssertionError('No credential reads permitted')):
        assert app._read_oauth_token() is None
        assert app.collect_claude_usage() is None


def test_combined_counter_is_not_reported(monkeypatch):
    monkeypatch.setattr(app, 'collect_rtk', lambda: {'active': True, 'total_saved': 100, 'history': []})
    monkeypatch.setattr(app, 'collect_headroom', lambda: {'active': True, 'total_saved': 200, 'history': []})
    monkeypatch.setattr(app, '_load_weekly_cache', lambda: {})
    result = app.collect_all()
    assert result['combined_saved'] is None
    assert result['combined_saved_usd'] is None
    assert result['rtk']['total_saved'] == 100
    assert result['headroom']['total_saved'] == 200
    assert result['overall_health'] == 'ok'


def test_codex_page_and_loopback_config():
    assert app.HOST == '127.0.0.1'
    with app.app.test_client() as client:
        response = client.get('/', base_url=f'http://127.0.0.1:{app.PORT}')
    assert response.status_code == 200
    assert b'<title>Codex Token Saver</title>' in response.data
    assert b'LOCAL COMPRESSION ACTIVITY' in response.data
    assert b'These separate counters may overlap' in response.data
