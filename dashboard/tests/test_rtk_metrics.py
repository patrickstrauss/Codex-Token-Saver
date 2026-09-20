import sqlite3
from datetime import datetime, timezone

import pytest


def test_recent_windows_do_not_hide_lifetime_outliers_or_claim_activity():
    from rtk_metrics import window_metrics
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE commands(timestamp TEXT,saved_tokens INTEGER,input_tokens INTEGER,output_tokens INTEGER,exec_time_ms INTEGER)')
    conn.executemany('INSERT INTO commands VALUES(?,?,?,?,?)', [
        ('2026-09-01T00:00:00Z', 999900, 1000000, 100, 500),
        ('2026-09-18T00:00:00Z', 60, 100, 40, 500),
        ('2026-09-20T01:00:00Z', 10, 20, 10, 500),
        ('2026-09-20T02:00:00Z', 0, 10, 10, 500),
    ])
    metrics = window_metrics(conn, datetime(2026, 9, 20, 12, tzinfo=timezone.utc))
    assert metrics['today']['total_saved'] == 10
    assert metrics['today']['optimized_commands'] == 1
    assert metrics['today']['total_commands'] == 2
    assert metrics['seven_days']['total_saved'] == 70
    assert metrics['lifetime']['total_saved'] == 999970
    assert metrics['lifetime']['largest_saved_share_pct'] > 99
    assert metrics['last_recorded_at'] == '2026-09-20T02:00:00Z'
    assert not metrics['recent_use']
    assert metrics['collected_at'] == '2026-09-20T12:00:00+00:00'


def test_empty_records_are_readable_but_not_active():
    from rtk_metrics import window_metrics
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE commands(timestamp TEXT,saved_tokens INTEGER,input_tokens INTEGER,output_tokens INTEGER,exec_time_ms INTEGER)')
    result = window_metrics(conn, datetime.now(timezone.utc))
    assert result['today']['total_saved'] == 0
    assert result['last_recorded_at'] is None and result['recent_use'] is False


def test_timezone_offsets_use_the_same_instant():
    from rtk_metrics import window_metrics
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE commands(timestamp TEXT,saved_tokens INTEGER,input_tokens INTEGER,output_tokens INTEGER,exec_time_ms INTEGER)')
    conn.execute('INSERT INTO commands VALUES(?,?,?,?,?)', ('2026-09-20T19:00:00+07:00', 10, 20, 10, 1))
    result = window_metrics(conn, datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc))
    assert result['recent_use'] is True
    assert result['today']['total_saved'] == 10
