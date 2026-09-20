import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_summaries as module


TASK = '01a09946-380f-72f1-ab4a-29bb5da7b861'


class SummaryReaderCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'rollout.jsonl'
        self.reader = module.LocalSummaries(self.temp.name, self.temp.name)

    def write(self, rows, tail=b''):
        metadata = {'type': 'session_meta', 'payload': {'id': TASK}}
        self.path.write_bytes(b''.join(json.dumps(row).encode() + b'\n'
            for row in [metadata, *rows]) + tail)

    def message(self, text, role='user', phase=None):
        return {'type': 'response_item', 'payload': {'type': 'message', 'role': role,
            'phase': phase, 'content': [{'type': 'input_text', 'text': text}]}}

    def read(self):
        return self.reader._read_rollout(self.path, TASK)

    def test_large_native_compaction_is_not_missing_transcript(self):
        self.write([self.message('before'), {'type': 'compacted', 'payload': {
            'replacement_history': 'x' * (module.MAX_LINE_BYTES + 100)}},
            self.message('after')])
        result = self.read()
        self.assertEqual([x['content'] for x in result['messages']], ['before', 'after'])
        self.assertFalse(result['source_truncated'])
        self.assertEqual(result['skipped_lines'], 0)

    def test_valid_oversized_message_keeps_all_text(self):
        text = 'visible ' * (module.MAX_LINE_BYTES // 8 + 100)
        self.write([self.message(text)])
        result = self.read()
        reconstructed = ''.join(x['content'].split('\n', 1)[1]
            for x in result['messages'])
        self.assertEqual(reconstructed, text)
        self.assertFalse(result['source_truncated'])

    def test_source_size_limit_does_not_drop_later_records(self):
        self.write([self.message(str(index)) for index in range(20)])
        with patch.object(module, 'MAX_SOURCE_BYTES', 300):
            result = self.read()
        self.assertEqual(len(result['messages']), 20)
        self.assertFalse(result['source_truncated'])

    def test_oversized_ignored_messages_keep_privacy_filter(self):
        private = 'PRIVATE' * (module.MAX_LINE_BYTES // 7 + 100)
        self.write([self.message(private, role='system'),
            self.message(private, role='developer'),
            self.message(private, role='assistant', phase='analysis'),
            self.message('visible')])
        result = self.read()
        self.assertEqual([x['content'] for x in result['messages']], ['visible'])
        self.assertFalse(result['source_truncated'])

    def test_invalid_record_and_partial_tail_report_distinct_coverage(self):
        self.write([self.message('visible')], b'{bad}\n{"unfinished":')
        before = self.path.read_bytes()
        result = self.read()
        self.assertEqual(len(result['messages']), 1)
        self.assertEqual(result['skipped_lines'], 1)
        self.assertTrue(result['source_truncated'])
        self.assertTrue(result['source_incomplete'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_message_ids_do_not_change(self):
        self.write([self.message('first'), self.message('second')])
        expected = self.read()['messages']
        self.write([self.message('first'), {'type': 'compacted', 'payload': {
            'replacement_history': 'x' * (module.MAX_LINE_BYTES + 100)}},
            self.message('second')])
        self.assertEqual(self.read()['messages'], expected)

    def test_exceptional_record_limit_is_explicit_and_scan_continues(self):
        self.write([self.message('x' * (16 * 1024 * 1024)), self.message('after')])
        result = self.read()
        self.assertEqual([x['content'] for x in result['messages']], ['after'])
        self.assertEqual(result['oversized_lines'], 1)
        self.assertEqual(result['malformed_lines'], 0)
        self.assertTrue(result['source_truncated'])

    def test_progress_callback_uses_snapshot_and_can_cancel(self):
        self.write([self.message('x' * 1200000)])
        initial_bytes = self.path.stat().st_size
        progress = []
        def append_once(scanned, total):
            progress.append((scanned, total))
            if len(progress) == 1:
                with self.path.open('ab') as stream:
                    stream.write(json.dumps(self.message('later')).encode() + b'\n')
        result = self.reader._read_rollout(self.path, TASK, on_progress=append_once)
        self.assertGreater(len(progress), 0)
        self.assertEqual(progress[-1], (initial_bytes, initial_bytes))
        self.assertFalse(any(x['content'] == 'later' for x in result['messages']))
        def cancel(*args):
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.reader._read_rollout(self.path, TASK, on_progress=cancel)


if __name__ == '__main__':
    unittest.main()
