"""Offline proxy records must never imply current Codex desktop compression."""
import importlib
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

with patch('threading.Thread.start'):
    app = importlib.import_module('app')


@pytest.fixture(autouse=True)
def isolated_collectors(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'HEADROOM_SAVINGS_PATH', tmp_path / 'proxy_savings.json', raising=False)
    monkeypatch.setattr(app, 'HEADROOM_EVENTS_PATH', tmp_path / 'savings_events.jsonl', raising=False)
    monkeypatch.setattr(app, '_headroom_disk_cache', {}, raising=False)
    monkeypatch.setattr(app, '_last_good', {})
    monkeypatch.setattr(app, '_last_collect_success', {})
    monkeypatch.setattr(app, '_load_weekly_cache', lambda: {})
    monkeypatch.setattr(app, 'collect_rtk', lambda: {'active': True, 'total_saved': 100, 'history': []})
    monkeypatch.setattr(app, 'urlopen', lambda *args, **kw: (_ for _ in ()).throw(URLError('offline')))


def test_optional_proxy_offline_does_not_fail_dashboard():
    data = app.collect_all()
    assert data['overall_health'] == 'ok'
    assert data['headroom']['active'] is False
    assert data['headroom']['optional'] is True
    assert data['headroom']['health'] == 'inactive'
    assert data['headroom']['data_status'] == 'unavailable'
    assert data['headroom']['total_saved'] is None


def test_persisted_lifetime_is_readonly_historical_data():
    app.HEADROOM_SAVINGS_PATH.write_text(json.dumps({
        'schema_version': 5,
        'lifetime': {'requests': 3, 'tokens_saved': 234, 'compression_savings_usd': 0.000702},
        'lifetime_metrics': {'persistence': {'last_saved_at': '2026-09-13T05:50:47+00:00'}},
    }), encoding='utf-8')
    before = app.HEADROOM_SAVINGS_PATH.read_bytes()
    data = app.collect_all()
    hr = data['headroom']
    assert hr['active'] is False
    assert hr['total_saved'] == 234
    assert hr['lifetime_requests'] == 3
    assert hr['data_status'] == 'historical'
    assert hr['source'] == 'proxy_savings.json'
    assert hr['last_recorded_at'] == '2026-09-13T05:50:47+00:00'
    assert 'historical' in hr['measurement'].lower()
    assert app.HEADROOM_SAVINGS_PATH.read_bytes() == before


def test_durable_events_fallback_counts_saved_only_and_tolerates_partial_tail():
    app.HEADROOM_EVENTS_PATH.write_text(
        json.dumps({'v': 1, 'ts': '2026-09-13T05:50:47+00:00', 'before': 10404, 'after': 10170, 'saved': 234, 'source': 'proxy'})
        + '\n' + json.dumps({'v': 1, 'ts': '2026-09-13T05:51:47+00:00', 'before': 50, 'after': 50, 'saved': 0, 'source': 'proxy'})
        + '\n{"unfinished":', encoding='utf-8')
    before = app.HEADROOM_EVENTS_PATH.read_bytes()
    hr = app.collect_headroom()
    assert hr['total_saved'] == 234
    assert hr['lifetime_requests'] == 2
    assert hr['source'] == 'savings_events.jsonl'
    assert hr['data_status'] == 'historical'
    assert hr['last_recorded_at'] == '2026-09-13T05:51:47+00:00'
    assert app.HEADROOM_EVENTS_PATH.read_bytes() == before


def test_corrupt_persisted_data_is_unavailable_not_zero_savings():
    app.HEADROOM_SAVINGS_PATH.write_text('{broken', encoding='utf-8')
    assert app.collect_headroom()['data_status'] == 'unavailable'


def test_recent_rtk_failure_is_stale_immediately_not_active(monkeypatch):
    app.collect_all()
    monkeypatch.setattr(app, 'collect_rtk', lambda: None)
    data = app.collect_all()
    assert data['rtk']['active'] is False
    assert data['rtk']['health'] == 'stale'
    assert data['rtk']['data_status'] == 'historical'
    assert data['rtk']['total_saved'] == 100
    assert data['overall_health'] == 'stale'


def test_rtk_never_read_reports_error(monkeypatch):
    monkeypatch.setattr(app, 'collect_rtk', lambda: None)
    data = app.collect_all()
    assert data['rtk']['health'] == 'error'
    assert data['overall_health'] == 'error'


def test_no_combined_savings_in_json_or_metrics():
    data = app.collect_all()
    assert data['combined_saved'] is None
    assert data['combined_saved_usd'] is None
    metrics = app._render_metrics(data)
    assert 'ctd_combined_saved_tokens' not in metrics
    assert 'ctd_combined_saved_usd' not in metrics
    assert ' None' not in metrics


def test_health_has_identity_without_collecting(monkeypatch):
    monkeypatch.setattr(app, 'collect_all', lambda: (_ for _ in ()).throw(AssertionError('health must stay independent')))
    data = app.app.test_client().get('/health').get_json()
    assert data == {'status': 'ok', 'service': 'codex-token-saver-dashboard'}
