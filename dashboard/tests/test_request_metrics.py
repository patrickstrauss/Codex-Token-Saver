import json
from datetime import datetime, timezone

from request_metrics import request_windows


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def event(ts, before=100, after=40):
    return json.dumps({'ts': ts, 'before': before, 'after': after, 'saved': before - after}) + '\n'


def test_recent_signed_savings_exclude_old_and_future_events(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text(event('2026-09-01T00:00:00Z', 100000, 1)
                    + event('2026-09-20T01:00:00Z')
                    + event('2026-09-20T18:59:00+07:00')
                    + event('2026-09-20T11:59:30Z', 10, 20)
                    + event('2026-09-21T00:00:00Z'), encoding='utf-8')
    result = request_windows(path, now=NOW)
    assert result['scope'] == 'all_tasks'
    recent = result['windows']['fifteen_minutes']
    assert recent['saved_tokens'] == 50 and recent['requests'] == 2
    assert recent['input_tokens'] == 110 and recent['reduction_pct'] == 45.5
    assert result['windows']['today']['saved_tokens'] == 110
    assert result['complete'] and result['available']


def test_missing_or_corrupt_records_are_not_reported_as_zero_savings(tmp_path):
    path = tmp_path / 'events.jsonl'
    assert request_windows(path, now=NOW)['available'] is False
    path.write_text('broken\n' + event('2026-09-20T11:59:00Z') + '{"ts":', encoding='utf-8')
    result = request_windows(path, now=NOW)
    assert result['available'] and not result['complete']
    assert result['invalid_records'] == 2
    assert result['windows']['fifteen_minutes']['saved_tokens'] == 60
    path.write_text('broken\n', encoding='utf-8')
    assert request_windows(path, now=NOW)['available'] is False


def test_bounded_tail_exposes_incomplete_coverage(tmp_path):
    path = tmp_path / 'events.jsonl'
    line = event('2026-09-20T11:59:00Z')
    path.write_text(line * 100, encoding='utf-8')
    result = request_windows(path, now=NOW, max_bytes=len(line.encode()) * 2 + 10)
    assert result['available'] and not result['complete']
    assert result['truncated']
    assert result['windows']['fifteen_minutes']['requests'] == 2


def test_invalid_counters_and_missing_timezone_do_not_inflate_savings(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text(''.join(json.dumps(e) + '\n' for e in [
        {'ts': '2026-09-20T11:59:00Z', 'before': True, 'after': 0, 'saved': 1},
        {'ts': '2026-09-20T11:59:00Z', 'before': 1, 'after': 0, 'saved': 999},
        {'ts': '2026-09-20T11:59:00', 'before': 1, 'after': 0, 'saved': 1},
        {'ts': '2026-09-20T11:59:00Z', 'before': -1, 'after': 0, 'saved': -1},
    ]), encoding='utf-8')
    result = request_windows(path, now=NOW)
    assert not result['available'] and result['invalid_records'] == 4


def test_empty_ledger_is_readable_and_has_no_activity(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_bytes(b'')
    result = request_windows(path, now=NOW)
    assert result['available'] and result['complete']
    assert result['windows']['today']['requests'] == 0
    assert result['windows']['today']['reduction_pct'] is None


def test_oversized_integer_does_not_break_the_status_endpoint(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text(event('2026-09-20T11:59:00Z', 1, 10**400), encoding='utf-8')
    result = request_windows(path, now=NOW)
    assert not result['available'] and not result['complete']
    assert result['invalid_records'] == 1
