"""Bounded metadata for new operations only; never contents, arguments or savings.

record() is best effort and returns a bool. Unknown task IDs become null; unknown
error codes become 'other'. Invalid components/outcomes/kinds are not recorded.
Diagnostic/informational groups are separate from attributed/unknown operations.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
from uuid import UUID

MAX_EVENTS = 2000
COMPONENTS = frozenset(('rtk', 'headroom_local', 'headroom_requests', 'headroom_hook',
    'headroom_commands', 'serena', 'playwright_cli',
    'ast_grep', 'laya_router'))
OUTCOMES = ('completed', 'failed', 'blocked', 'bypassed')
KINDS = ('operation', 'informational', 'diagnostic')
GROUPS = ('all', 'tasks', 'diagnostic', 'informational', 'unknown')
ERROR_CODES = frozenset(('disabled', 'invalid_preferences', 'missing_runtime',
    'missing_executable', 'missing_path', 'no_project', 'timeout', 'upstream_error',
    'invalid_input', 'unsupported_command', 'unsupported_event', 'complex_syntax',
    'ambiguous_shell', 'dynamic_input', 'exact_opt_out', 'already_wrapped',
    'oversized_input', 'parse_error', 'nonzero_exit', 'execution_failed',
    'runtime_error', 'unavailable', 'cancelled', 'no_route', 'other', 'connection_refused',
    'invalid_endpoint', 'ambiguous_selector', 'command_failed', 'router_unavailable',
    'runtime_missing', 'route_failed', 'invalid_operation', 'router_off',
    'classifier_unavailable', 'invalid_decision', 'route_rejected', 'retrieval_recovery', 'tool_failed'))


def valid_task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _category(value, choices):
    return isinstance(value, str) and value in choices


def record(root, component, outcome, *, task_id=None, kind='operation', error_code=None):
    if not (_category(component, COMPONENTS) and _category(outcome, OUTCOMES) and _category(kind, KINDS)):
        return False
    code = None if error_code is None else error_code if _category(error_code, ERROR_CODES) else 'other'
    try:
        path = Path(root) / 'activity/events.sqlite3'
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=2)) as connection, connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, component TEXT NOT NULL,
                outcome TEXT NOT NULL, task_id TEXT, kind TEXT NOT NULL, error_code TEXT)''')
            connection.execute('INSERT INTO events (timestamp, component, outcome, task_id, kind, error_code) VALUES (?, ?, ?, ?, ?, ?)',
                (datetime.now(timezone.utc).isoformat(), component, outcome, valid_task_id(task_id), kind, code))
            connection.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)', (MAX_EVENTS,))
        return True
    except (OSError, sqlite3.Error):
        return False


def _group(event):
    return event['kind'] if event['kind'] != 'operation' else 'tasks' if event['task_id'] else 'unknown'


def snapshot(root, *, group='all', task_id=None, limit=50):
    """Read a retained-window snapshot. Task filters never touch legacy totals."""
    if not _category(group, GROUPS) or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Invalid activity filter')
    if task_id is not None:
        task_id = valid_task_id(task_id)
        if task_id is None:
            raise ValueError('Invalid task ID')
    events, data_status = [], 'not_started'
    path = Path(root) / 'activity/events.sqlite3'
    try:
        if path.parent.exists() and not path.parent.is_dir():
            raise OSError()
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute('SELECT id, timestamp, component, outcome, task_id, kind, error_code FROM events ORDER BY id DESC LIMIT ?', (MAX_EVENTS,))
                for row in rows:
                    event = dict(row)
                    if not (_category(event['component'], COMPONENTS) and _category(event['outcome'], OUTCOMES)
                            and _category(event['kind'], KINDS)):
                        continue
                    stamp = datetime.fromisoformat(event['timestamp'])
                    if stamp.tzinfo is None:
                        continue
                    event['timestamp'] = stamp.isoformat()
                    event['task_id'] = valid_task_id(event['task_id'])
                    if event['error_code'] is not None and not _category(event['error_code'], ERROR_CODES):
                        event['error_code'] = 'other'
                    events.append(event)
            data_status = 'recorded' if events else 'not_started'
    except (OSError, sqlite3.Error, ValueError, TypeError):
        events, data_status = [], 'unavailable'
    groups = {name: 0 for name in GROUPS}
    tasks = {}
    for event in events:
        groups['all'] += 1
        groups[_group(event)] += 1
        if event['task_id']:
            task = tasks.setdefault(event['task_id'], {'task_id': event['task_id'], 'count': 0, 'last_activity_at': event['timestamp']})
            task['count'] += 1
    selected = [event for event in events if (group == 'all' or _group(event) == group)
                and (task_id is None or event['task_id'] == task_id)]
    outcomes = Counter(event['outcome'] for event in selected)
    verified = {}
    for event in selected:
        if event['kind'] == 'operation' and event['outcome'] == 'completed':
            verified.setdefault(event['component'], event['timestamp'])
    return {'schema_version': 1, 'data_status': data_status, 'recent_window_only': True,
            'retention_limit': MAX_EVENTS, 'legacy_counters': 'mixed_unattributed',
            'group': group, 'task_id': task_id, 'groups': groups, 'tasks': list(tasks.values()),
            'total': len(selected), 'outcomes': {key: outcomes[key] for key in OUTCOMES},
            'last_verified_calls': verified,
            'components': dict(Counter(event['component'] for event in selected)),
            'failure_categories': dict(Counter(event['error_code'] or 'other' for event in selected if event['outcome'] in ('failed', 'blocked'))),
            'bypass_reasons': dict(Counter(event['error_code'] or 'other' for event in selected if event['outcome'] == 'bypassed')),
            'recent': selected[:limit]}


def status(root, **filters):
    return snapshot(root, **filters)


def task_titles(task_ids, *, codex_home=None):
    """Resolve only requested IDs using read-only SQLite; never read rollouts."""
    ids = list(dict.fromkeys(value for item in task_ids if (value := valid_task_id(item))))[:MAX_EVENTS]
    if not ids:
        return {}
    home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    titles = {}
    try:
        databases = sorted(home.glob('state_*.sqlite'), reverse=True)[:4]
        for path in databases:
            try:
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.1)) as connection:
                    for offset in range(0, len(ids), 400):
                        batch = ids[offset:offset + 400]
                        query = 'SELECT id, substr(title, 1, 200) FROM threads WHERE id IN (' + ','.join('?' for _ in batch) + ')'
                        for task_id, title in connection.execute(query, batch):
                            if isinstance(title, str) and title.strip():
                                titles.setdefault(task_id, title)
            except sqlite3.Error:
                continue
    except OSError:
        pass
    return titles
