"""Local usage-metadata reminders. Never starts inference or changes a transcript."""
from datetime import datetime, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

from bundle_preferences import load_preferences
from desktop_proxy_control import atomic_write, routing_lock
from local_summaries import LocalSummaries, TASK_ID

TAIL_BYTES = 512 * 1024
MAX_TASKS = 64
_CACHE = {}


def _read(path, default):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else 0
    except (AttributeError, ValueError, TypeError, OverflowError):
        return 0


def _usage(path):
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _CACHE:
        return _CACHE[key]
    with path.open('rb') as stream:
        first = stream.readline(64 * 1024)
        try:
            meta = json.loads(first).get('payload', {})
        except (ValueError, AttributeError):
            return None
        if not isinstance(meta, dict):
            return None
        task_id = meta.get('id')
        if (not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id)
                or isinstance(meta.get('source'), dict)):
            return None  # Do not notify for delegated/background agent tasks.
        stream.seek(max(0, stat.st_size - TAIL_BYTES))
        lines = stream.read(TAIL_BYTES).splitlines(keepends=True)
    result = None
    for line in reversed(lines):
        if not line.endswith(b'\n') or b'"token_count"' not in line:
            continue
        try:
            event = json.loads(line)
            payload = event.get('payload', {})
            if event.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                continue
            info = payload.get('info') or {}
            used = (info.get('last_token_usage') or {}).get('input_tokens')
            window = info.get('model_context_window')
            # Cache hits are already included in input_tokens. Cumulative
            # total_token_usage is not the current context size.
            if type(used) is not int or used < 0 or type(window) is not int or window <= 0:
                continue
            if not _timestamp(event.get('timestamp')):
                continue
            result = {'task_id': task_id, 'title': Path(meta.get('cwd') or '').name or task_id[:8],
                      'input_tokens': used, 'context_window': window,
                      'context_percent': round(100 * used / window, 1),
                      'last_updated': event['timestamp']}
            break
        except (ValueError, AttributeError, TypeError):
            continue
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = result
    return result


class SummaryReminders:
    def __init__(self, root, codex_home=None):
        self.root = Path(root).resolve()
        self.home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.settings = self.root / 'settings/summary-reminders.json'
        self.state = self.root / 'local-compaction/state/reminders.json'

    def _settings(self):
        defaults = {'enabled': True, 'threshold_percent': 70}
        if not self.settings.exists():
            return defaults, None
        value = _read(self.settings, {})
        if (value.get('schema') != 1 or type(value.get('enabled')) is not bool
                or type(value.get('threshold_percent')) is not int
                or not 20 <= value['threshold_percent'] <= 95):
            return {'enabled': False, 'threshold_percent': 70}, 'Reminder settings are invalid; notifications are paused.'
        return {key: value[key] for key in defaults}, None

    def configure(self, enabled, threshold_percent):
        if type(enabled) is not bool or type(threshold_percent) is not int or not 20 <= threshold_percent <= 95:
            raise ValueError('Choose On or Off and a whole-number threshold from 20 to 95 percent.')
        with routing_lock(self.settings.with_suffix('.lock')):
            atomic_write(self.settings, json.dumps({'schema': 1, 'enabled': enabled,
                                                   'threshold_percent': threshold_percent}).encode())
        return self.status()

    def _titles(self, rows):
        """Optional read-only title lookup; never select messages or content."""
        if not rows:
            return
        files = sorted(self.home.glob('state_*.sqlite'), reverse=True)
        for path in files[:1]:
            try:
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as connection:
                    ids = [row['task_id'] for row in rows]
                    query = 'SELECT id, title, archived FROM threads WHERE id IN (' + ','.join('?' for _ in ids) + ')'
                    metadata = {task_id: (title, archived) for task_id, title, archived in connection.execute(query, ids)}
                for row in rows:
                    title, archived = metadata.get(row['task_id'], (None, False))
                    if isinstance(title, str) and title.strip():
                        row['title'] = ' '.join(title.split())[:160]
                    row['archived'] = bool(archived)
            except (OSError, sqlite3.Error):
                pass

    def status(self):
        settings, error = self._settings()
        prefs = load_preferences(self.root)
        rows = []
        try:
            files = LocalSummaries(self.root, self.home)._files()
            recent = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_TASKS]
            for path in recent:
                try:
                    usage = _usage(path)
                    if not usage or time.time() - _timestamp(usage['last_updated']) > 86400:
                        continue
                    row = dict(usage)
                    summary = _read(self.root / 'local-compaction/state' / row['task_id'] / 'summary.json', {})
                    summarized_at = _timestamp(summary.get('updated_at'))
                    row['needs_summary'] = (row['context_percent'] >= settings['threshold_percent']
                                            and summarized_at < _timestamp(row['last_updated']))
                    rows.append(row)
                except OSError:
                    continue
            self._titles(rows)
            rows = [row for row in rows if not row.get('archived')]
        except OSError:
            error = 'Local task usage metadata is currently unavailable.'
        active = settings['enabled'] and prefs['local_summaries'] and prefs['llama_cpp']
        return {**settings, 'active': active, 'tasks': rows, 'error': error,
                'reason': None if active or not settings['enabled'] else 'Enable LangMem and llama.cpp to receive summary reminders.',
                'measurement': 'Latest reported input tokens, including cache hits, divided by the reported context window.'}

    def poll(self):
        """Queue at most one tray reminder per threshold crossing; no inference."""
        status = self.status()
        if not status['active'] or status['error']:
            return {'notification': None}
        with routing_lock(self.state.with_suffix('.lock')):
            now = time.time()
            state = _read(self.state, {})
            stored = state.get('attempts', {})
            if not isinstance(stored, dict):
                stored = {}
            attempts = {key: value for key, value in stored.items()
                        if isinstance(value, dict) and type(value.get('at')) in (int, float)
                        and now - value['at'] < 30 * 86400}
            eligible = []
            for row in status['tasks']:
                task_id = row['task_id']
                if row['context_percent'] < status['threshold_percent']:
                    attempts.pop(task_id, None)  # Native compaction/new context rearms the reminder.
                prior = attempts.get(task_id, {})
                if (row['needs_summary'] and 0 <= now - _timestamp(row['last_updated']) < 900
                        and (not prior or prior.get('threshold') != status['threshold_percent'])):
                    eligible.append(row)
            notification = max(eligible, key=lambda row: row['context_percent'], default=None)
            if notification:
                attempts[notification['task_id']] = {'at': now, 'threshold': status['threshold_percent']}
            atomic_write(self.state, json.dumps({'attempts': attempts}).encode())
        return {'notification': notification}


if __name__ == '__main__':
    try:
        print(json.dumps(SummaryReminders(Path(__file__).resolve().parent).poll()))
    except Exception:
        # A reminder failure must never interrupt the tray or a Codex task.
        print(json.dumps({'notification': None, 'error': 'Summary reminder check unavailable.'}))
