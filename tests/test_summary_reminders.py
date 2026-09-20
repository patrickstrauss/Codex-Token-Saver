import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from bundle_preferences import set_preference
from summary_reminders import SummaryReminders

TASK = '01234567-1234-1234-1234-123456789abc'


class SummaryReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        (self.home / 'sessions').mkdir(parents=True)
        self.rollout = self.home / 'sessions' / f'rollout-{TASK}.jsonl'
        self.control = SummaryReminders(self.root, self.home)
        set_preference(self.root, 'local_summaries', True)
        set_preference(self.root, 'llama_cpp', True)
        self.reset()

    def reset(self, source='vscode'):
        self.rollout.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': TASK, 'cwd': '/projects/example', 'source': source}}) + '\n')

    def usage(self, used, window=1000, age=0):
        stamp = datetime.fromtimestamp(time.time()-age, timezone.utc).isoformat()
        payload = {'type': 'token_count', 'info': {'last_token_usage': {
            'input_tokens': used, 'cached_input_tokens': used, 'output_tokens': 500},
            'total_token_usage': {'input_tokens': 999999999}, 'model_context_window': window}}
        with self.rollout.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'timestamp': stamp, 'payload': payload}) + '\n')

    def test_uses_last_input_without_adding_cache_or_lifetime_totals(self):
        self.usage(600)
        row = self.control.status()['tasks'][0]
        self.assertEqual(row['context_percent'], 60)
        self.assertFalse(row['needs_summary'])
        self.assertIsNone(self.control.poll()['notification'])

    def test_crossing_alert_once_and_native_context_drop_rearms(self):
        self.usage(800)
        self.assertEqual(self.control.poll()['notification']['task_id'], TASK)
        self.assertIsNone(self.control.poll()['notification'])
        self.usage(900)
        self.assertIsNone(self.control.poll()['notification'], 'Growth must not nag while still above threshold')
        self.usage(100)
        self.assertIsNone(self.control.poll()['notification'])
        self.usage(750)
        self.assertIsNotNone(self.control.poll()['notification'])

    def test_disabled_reminders_or_model_preference_prevents_notification(self):
        self.usage(900)
        self.control.configure(False, 70)
        self.assertIsNone(self.control.poll()['notification'])
        self.control.configure(True, 70)
        set_preference(self.root, 'llama_cpp', False)
        self.assertFalse(self.control.status()['active'])
        self.assertIsNone(self.control.poll()['notification'])

    def test_stale_usage_can_be_displayed_but_does_not_interrupt_user(self):
        self.usage(900, age=3600)
        self.assertTrue(self.control.status()['tasks'][0]['needs_summary'])
        self.assertIsNone(self.control.poll()['notification'])

    def test_no_guessed_percentage_without_a_context_window(self):
        self.usage(999999, window=None)
        self.assertEqual(self.control.status()['tasks'], [])

    def test_subagents_and_archived_tasks_are_excluded(self):
        self.reset({'subagent': {'thread_spawn': {'parent_thread_id': TASK}}})
        self.usage(900)
        self.assertEqual(self.control.status()['tasks'], [])
        self.reset()
        self.usage(900)
        db = sqlite3.connect(self.home / 'state_5.sqlite')
        db.execute('create table threads(id text,title text,archived integer)')
        db.execute('insert into threads values(?,?,?)', (TASK, 'Archived task', 1))
        db.commit(); db.close()
        self.assertEqual(self.control.status()['tasks'], [])

    def test_saved_fresh_summary_suppresses_reminder_without_changing_source(self):
        self.usage(900, age=10)
        original = self.rollout.read_bytes()
        saved = self.root / 'local-compaction/state' / TASK / 'summary.json'
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps({'updated_at': datetime.now(timezone.utc).isoformat()}))
        with patch('local_summaries.LocalSummaries.start') as start:
            self.assertIsNone(self.control.poll()['notification'])
            start.assert_not_called()
        self.assertEqual(self.rollout.read_bytes(), original)

    def test_incomplete_final_event_is_not_treated_as_completed_usage(self):
        self.usage(400)
        with self.rollout.open('ab') as stream:
            stream.write(b'{"type":"event_msg","payload":{"type":"token_count"')
        self.assertEqual(self.control.status()['tasks'][0]['input_tokens'], 400)

    def test_settings_validation_and_malformed_file_pause(self):
        for enabled, threshold in ((1, 70), (True, True), (True, 19), (True, 96), (True, 70.5)):
            with self.assertRaises(ValueError):
                self.control.configure(enabled, threshold)
        self.control.settings.parent.mkdir(parents=True, exist_ok=True)
        self.control.settings.write_text('not json')
        self.assertFalse(self.control.status()['enabled'])
        self.assertIsNotNone(self.control.status()['error'])

    def test_malformed_attempt_map_is_recoverable(self):
        self.usage(900)
        self.control.state.parent.mkdir(parents=True)
        self.control.state.write_text('{"attempts":[]}')
        self.assertIsNotNone(self.control.poll()['notification'])

    def test_malformed_recent_session_does_not_hide_valid_tasks(self):
        self.usage(900)
        invalid = self.home / 'sessions/rollout-invalid.jsonl'
        for payload in (None, [], 1, 'bad'):
            invalid.write_text(json.dumps({'type': 'session_meta', 'payload': payload}) + '\n')
            self.assertEqual(self.control.status()['tasks'][0]['task_id'], TASK)


if __name__ == '__main__':
    unittest.main()
