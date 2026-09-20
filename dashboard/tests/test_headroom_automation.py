import json
import sqlite3

import app


def test_command_savings_and_hook_observations_are_separate(tmp_path, monkeypatch):
    ledger = tmp_path / 'activity.db'
    receipt = tmp_path / 'automatic-headroom.json'
    audit = tmp_path / 'hook-events.jsonl'
    monkeypatch.setattr(app, 'DESKTOP_HEADROOM_DB_PATH', ledger)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', receipt, raising=False)
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit, raising=False)
    receipt.write_text(json.dumps({'configured': True, 'hook': 'headroom_commands'}))
    audit.write_text('\n'.join(json.dumps({'timestamp': '2026-09-13T14:00:00Z', 'outcome': outcome, 'reason': 'fixture'}) for outcome in ['rewritten','skipped']) + '\n')
    with sqlite3.connect(ledger) as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, input_tokens INTEGER, output_tokens INTEGER, saved_tokens INTEGER)')
        conn.execute("INSERT INTO events VALUES (1, '2026-09-13T14:00:00Z', 'command', 3000, 1000, 2000)")
    data = app.collect_desktop_headroom()
    assert data['total_saved'] == 2000
    assert data['gross_saved'] == 2000
    assert data['command_count'] == 1
    assert data['command_saved'] == 2000
    assert data['read_count'] == 0
    assert data['automation']['configured'] is True
    assert data['automation']['observed'] == 2
    assert data['automation']['rewritten'] == 1
    assert 'trusted' not in data['automation']


def test_registered_hook_without_activity_does_not_claim_running(tmp_path, monkeypatch):
    receipt = tmp_path / 'automatic-headroom.json'
    receipt.write_text('{"configured":true,"hook":"headroom_commands"}')
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', receipt, raising=False)
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', tmp_path / 'missing.jsonl', raising=False)
    data = app.collect_headroom_automation()
    assert data['configured'] is True
    assert data['observed'] == 0
    assert data['skipped'] == 0
    assert data['skip_reasons'] == {}
    assert data['top_skip_reasons'] == []
    assert data['data_status'] == 'empty'
    assert data['last_observed_at'] is None
    assert data['status'] == 'awaiting_first_event'


def test_small_command_is_observed_without_claiming_token_savings(tmp_path, monkeypatch):
    ledger = tmp_path / 'activity.db'
    monkeypatch.setattr(app, 'DESKTOP_HEADROOM_DB_PATH', ledger)
    with sqlite3.connect(ledger) as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, input_tokens INTEGER, output_tokens INTEGER, saved_tokens INTEGER)')
        conn.execute('CREATE TABLE command_attempts (id INTEGER PRIMARY KEY, ts TEXT, status TEXT)')
        conn.execute("INSERT INTO command_attempts VALUES (1, '2026-09-13T14:00:00Z', 'small_output')")
    data = app.collect_desktop_headroom()
    assert data['command_attempt_count'] == 1
    assert data['last_command_status'] == 'small_output'
    assert data['total_saved'] == 0


def test_new_output_check_without_savings_advances_activity_only(tmp_path, monkeypatch):
    ledger = tmp_path / 'activity.db'
    monkeypatch.setattr(app, 'DESKTOP_HEADROOM_DB_PATH', ledger)
    with sqlite3.connect(ledger) as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, input_tokens INTEGER, output_tokens INTEGER, saved_tokens INTEGER)')
        conn.execute("INSERT INTO events VALUES (1, '2026-09-13T14:00:00Z', 'command', 3000, 1000, 2000)")
        conn.execute('CREATE TABLE command_attempts (id INTEGER PRIMARY KEY, ts TEXT, status TEXT)')
        conn.execute("INSERT INTO command_attempts VALUES (1, '2026-09-13T14:00:00Z', 'compressed')")
    before = app.collect_desktop_headroom()
    with sqlite3.connect(ledger) as conn:
        conn.execute("INSERT INTO command_attempts VALUES (2, '2026-09-13T15:00:00Z', 'no_reduction')")
    database_bytes = ledger.read_bytes()
    after = app.collect_desktop_headroom()
    assert after['total_saved'] == before['total_saved'] == 2000
    assert after['last_recorded_at'] == before['last_recorded_at'] == '2026-09-13T14:00:00Z'
    assert after.get('last_command_check') == '2026-09-13T15:00:00Z'
    assert after['last_command_status'] == 'no_reduction'
    assert after.get('command_statuses') == {'compressed': 1, 'no_reduction': 1}
    assert ledger.read_bytes() == database_bytes


def test_output_check_summary_counts_unknown_status_without_echoing_it(tmp_path, monkeypatch):
    ledger = tmp_path / 'activity.db'
    monkeypatch.setattr(app, 'DESKTOP_HEADROOM_DB_PATH', ledger)
    statuses = ['compressed', 'small_output', 'no_reduction', 'command_failed',
                'compression_unavailable', 'exact_requested', 'size_limit',
                'binary_output', 'non_utf8', 'compression_timeout', 'streaming_timeout',
                'inherited_pipe', 'interactive_passthrough', 'arbitrary private text']
    with sqlite3.connect(ledger) as conn:
        conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, input_tokens INTEGER, output_tokens INTEGER, saved_tokens INTEGER)')
        conn.execute('CREATE TABLE command_attempts (id INTEGER PRIMARY KEY, ts TEXT, status TEXT)')
        conn.executemany('INSERT INTO command_attempts (ts, status) VALUES (?, ?)',
                         [('2026-09-13T15:00:00Z', status) for status in statuses])
    data = app.collect_desktop_headroom()
    assert data['last_command_status'] == 'other'
    assert sum(data['command_statuses'].values()) == data['command_attempt_count'] == 14
    for status in ['compression_timeout', 'streaming_timeout', 'inherited_pipe', 'interactive_passthrough']:
        assert data['command_statuses'].get(status) == 1
    assert data['command_statuses']['other'] == 1
    assert 'arbitrary private text' not in json.dumps(data)


def test_hook_coverage_counts_skips_without_treating_wrapping_as_savings(tmp_path, monkeypatch):
    audit = tmp_path / 'hook-events.jsonl'
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'missing.json')
    events = [
        {'outcome': 'skipped', 'reason': 'complex_syntax'},
        {'outcome': 'rewritten', 'reason': 'supported_external'},
        {'outcome': 'skipped', 'reason': 'ambiguous_shell'},
        {'outcome': 'skipped', 'reason': 'complex_syntax'},
        {'outcome': 'skipped', 'reason': 'dynamic_input'},
    ]
    audit.write_text('\n'.join(json.dumps(event) for event in events), encoding='utf-8')
    data = app.collect_headroom_automation()
    assert data['observed'] == 5
    assert data['rewritten'] == 1
    assert data['skipped'] == 4
    assert data['skip_reasons'] == {'complex_syntax': 2, 'ambiguous_shell': 1, 'dynamic_input': 1}
    assert data['top_skip_reasons'][0] == {
        'reason': 'complex_syntax', 'label': 'scripts, pipelines or unsupported syntax', 'count': 2}
    assert data['data_status'] == 'recorded'
    assert data['recent_window_only'] is True
    assert 'total_saved' not in data


def test_hook_coverage_ignores_broken_records_and_never_echoes_unknown_reason(tmp_path, monkeypatch):
    audit = tmp_path / 'hook-events.jsonl'
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'missing.json')
    audit.write_text('\n'.join([
        'null', '[]', '{broken',
        json.dumps({'outcome': 'unexpected', 'reason': 'complex_syntax'}),
        json.dumps({'outcome': 'skipped', 'reason': 'do not display arbitrary local content'}),
        json.dumps({'outcome': 'skipped', 'reason': ['not a reason enum']}),
    ]), encoding='utf-8')
    data = app.collect_headroom_automation()
    assert data['observed'] == data['skipped'] == 2
    assert data['rewritten'] == 0
    assert data['skip_reasons'] == {'other': 2}
    assert data['top_skip_reasons'] == [{'reason': 'other', 'label': 'other or unknown reason', 'count': 2}]


def test_unreadable_hook_log_is_unavailable_instead_of_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', tmp_path)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'missing.json')
    data = app.collect_headroom_automation()
    assert data['data_status'] == 'unavailable'
    assert data['observed'] is None
    assert data['rewritten'] is None
    assert data['skipped'] is None


def test_hook_coverage_counts_only_complete_records_in_bounded_tail(tmp_path, monkeypatch):
    audit = tmp_path / 'hook-events.jsonl'
    monkeypatch.setattr(app, 'HEADROOM_HOOK_EVENTS_PATH', audit)
    monkeypatch.setattr(app, 'AUTOMATIC_HEADROOM_PATH', tmp_path / 'missing.json')
    old_event = json.dumps({'outcome': 'skipped', 'reason': 'complex_syntax'}) + '\n'
    new_event = json.dumps({'outcome': 'rewritten', 'reason': 'supported_external'}) + '\n'
    audit.write_text(old_event + ('x' * (256 * 1024)) + '\n' + new_event, encoding='utf-8')
    data = app.collect_headroom_automation()
    assert data['observed'] == data['rewritten'] == 1
    assert data['skipped'] == 0
    assert data['recent_window_only'] is True
