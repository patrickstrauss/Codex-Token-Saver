"""Desktop file-read estimates stay distinct from proxy history and runtime status."""
import json
import sqlite3

import pytest

import app


@pytest.fixture(autouse=True)
def desktop_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'DESKTOP_HEADROOM_DB_PATH', tmp_path / 'activity.db', raising=False)
    monkeypatch.setattr(app, 'DESKTOP_INTEGRATION_PATH', tmp_path / 'desktop-integration.json', raising=False)


def create_events(rows=()):
    with sqlite3.connect(app.DESKTOP_HEADROOM_DB_PATH) as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, input_tokens INTEGER, output_tokens INTEGER, saved_tokens INTEGER)')
        conn.executemany('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)', rows)


def register():
    app.DESKTOP_INTEGRATION_PATH.write_text(json.dumps({'configured': True, 'server': 'headroom_desktop'}), encoding='utf-8')


def test_missing_history_is_empty_and_never_created():
    data = app.collect_desktop_headroom()
    assert data['configured'] is False
    assert data['data_status'] == 'empty'
    assert data['total_saved'] == 0
    assert data['last_recorded_at'] is None
    assert not app.DESKTOP_HEADROOM_DB_PATH.exists()


def test_receipt_confirms_configuration_only():
    register()
    data = app.collect_desktop_headroom()
    assert data['configured'] is True
    assert data['data_status'] == 'empty'
    assert 'active' not in data


@pytest.mark.parametrize('receipt', ['{broken', '{"configured":true,"server":"other"}', '{"configured":"true","server":"headroom_desktop"}'])
def test_invalid_receipt_does_not_claim_configuration(receipt):
    app.DESKTOP_INTEGRATION_PATH.write_text(receipt, encoding='utf-8')
    assert app.collect_desktop_headroom()['configured'] is False


def test_signed_net_deducts_retrieval_and_expansion_without_mutating_database():
    register()
    create_events([
        (1, '2026-09-13T05:50:00Z', 'read', 500, 200, 300),
        (2, '2026-09-13T05:51:00Z', 'read', 10, 30, -20),
        (3, '2026-09-13T05:52:00Z', 'retrieve', 0, 400, -400),
    ])
    before = app.DESKTOP_HEADROOM_DB_PATH.read_bytes()
    data = app.collect_desktop_headroom()
    assert data['data_status'] == 'recorded'
    assert data['total_saved'] == -120
    assert data['gross_saved'] == 300
    assert data['retrieval_tokens'] == 400
    assert data['read_count'] == 2
    assert data['retrieve_count'] == 1
    assert data['last_recorded_at'] == '2026-09-13T05:52:00Z'
    assert data['source'] == 'headroom/desktop-state/activity.db'
    assert app.DESKTOP_HEADROOM_DB_PATH.read_bytes() == before


def test_empty_database_is_zero_recorded_activity():
    create_events()
    assert app.collect_desktop_headroom()['data_status'] == 'empty'
    assert app.collect_desktop_headroom()['read_count'] == 0


def test_corrupt_database_does_not_show_zero_or_stale_success():
    register()
    app.DESKTOP_HEADROOM_DB_PATH.write_bytes(b'not a database')
    data = app.collect_desktop_headroom()
    assert data['configured'] is True
    assert data['data_status'] == 'unavailable'
    assert data['total_saved'] is None
    assert data['read_count'] is None


def test_desktop_history_is_a_separate_snapshot_object(monkeypatch):
    create_events([(1, '2026-09-13T05:50:00Z', 'read', 500, 200, 300)])
    monkeypatch.setattr(app, 'collect_rtk', lambda: {'active': True, 'total_saved': 100, 'history': []})
    monkeypatch.setattr(app, 'collect_headroom', lambda: {'active': False, 'total_saved': 234, 'history': []})
    data = app.collect_all()
    assert data['desktop_headroom']['total_saved'] == 300
    assert data['headroom']['total_saved'] == 234
    assert data['combined_saved'] is None
    assert 'Codex model requests when enabled below' in data['connection_note']
    assert 'local Headroom tools' in data['connection_note']
