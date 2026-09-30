"""Disposable browser fixture: real activity APIs; no live services or user data."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ui_fixture import create_app, dashboard, FIXTURE_TASK
from bundle_activity import record


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='bundle-activity-ui-') as directory:
        root = Path(directory)
        # Isolate metadata resolution as well as the ledger.
        os.environ['CODEX_HOME'] = str(root / 'codex')
        (root / 'codex').mkdir()
        with closing(sqlite3.connect(root / 'codex/state_5.sqlite')) as connection, connection:
            connection.execute('CREATE TABLE threads (id TEXT, title TEXT)')
            connection.execute('INSERT INTO threads VALUES (?, ?)', (FIXTURE_TASK, 'Browser fixture <img src=x>'))
        record(root, 'serena', 'completed', task_id=FIXTURE_TASK)
        record(root, 'playwright_cli', 'failed', task_id=FIXTURE_TASK, error_code='connection_refused')
        record(root, 'ast_grep', 'completed', kind='informational')
        record(root, 'laya_router', 'completed', kind='diagnostic')
        record(root, 'serena', 'blocked', error_code='disabled')
        audit = root / 'hook-events.jsonl'
        audit.write_text('\n'.join(json.dumps(event) for event in [
            {'outcome': 'rewritten', 'task_id': FIXTURE_TASK},
            {'outcome': 'skipped', 'task_id': FIXTURE_TASK, 'reason': 'complex_syntax'},
            {'outcome': 'skipped', 'reason': 'disabled'},
        ]), encoding='utf-8')
        dashboard.HEADROOM_HOOK_EVENTS_PATH = audit
        dashboard.AUTOMATIC_HEADROOM_PATH = root / 'none'
        create_app(activity_root=root, hook_activity=dashboard.collect_headroom_automation, port=18896).run(
            host='127.0.0.1', port=18896, debug=False, use_reloader=False)
