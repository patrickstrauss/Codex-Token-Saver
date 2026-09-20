import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import local_summaries as module
except ModuleNotFoundError:
    module = None

TASK = '01a09946-380f-72f1-ab4a-29bb5da7b861'
OTHER = '01a09b37-059e-7043-ad8d-820a2b9ad62c'


class LocalSummariesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'bundle'
        self.home = Path(self.tmp.name) / 'codex'
        self.root.mkdir()
        self.folder = self.home / 'sessions/2026/09/14'
        self.folder.mkdir(parents=True)

    def controller(self):
        if module is None:
            self.skipTest('Missing implementation is reported by the feature test.')
        return module.LocalSummaries(self.root, self.home)

    def rollout(self, items=(), task=TASK, tail=b''):
        p = self.folder / f'rollout-2026-09-14T01-00-00-{task}.jsonl'
        rows = [{'type': 'session_meta', 'payload': {'id': task, 'cwd': 'C:/work/project'}}]
        rows.extend({'type': 'response_item', 'payload': x} for x in items)
        p.write_bytes(b''.join(json.dumps(x, ensure_ascii=False).encode() + b'\n' for x in rows) + tail)
        return p

    def ready(self):
        runtime = self.root / 'local-compaction/.venv/Scripts'
        runtime.mkdir(parents=True)
        (runtime / 'python.exe').write_text('fixture')
        (self.root / 'local-compaction/model.json').write_text('{}')
        (self.root / 'local_summary_engine.py').write_text('# fixture')

    def fake_engine(self, request, task_id, job_id):
        covered = request.get('previous_summary', {}).get('summarized_message_ids', [])
        ids = covered + [x['id'] for x in request['messages']]
        return {'status': 'summarized', 'summary': 'Local summary.',
                'running_summary': {'summary': 'Local summary.', 'summarized_message_ids': ids,
                                    'last_summarized_message_id': ids[-1] if ids else None},
                'input_tokens': 100, 'output_tokens': 20, 'token_reduction_estimate': 80,
                'original_preserved': True}

    def test_feature_exists(self):
        self.assertIsNotNone(module, 'Local summaries controller is missing.')

    def test_lists_only_explicit_valid_local_task_metadata(self):
        c = self.controller()
        self.rollout()
        self.assertEqual(c.list_tasks(), [{'task_id': TASK, 'project': 'project',
            'updated_at': c.list_tasks()[0]['updated_at'], 'bytes': c.list_tasks()[0]['bytes'],
            'has_summary': False}])
        self.assertFalse(c.status()['available'])

    def test_invalid_and_unknown_task_ids_are_not_inferred(self):
        c = self.controller()
        self.rollout()
        for value in ('latest', '../sessions', '', None, 'http://localhost/'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.get_summary(value)
        with self.assertRaises(LookupError):
            c.start(OTHER)

    def test_parser_retains_visible_text_and_complete_tool_pairs_only(self):
        c = self.controller()
        p = self.rollout([
            {'type': 'message', 'role': 'system', 'content': [{'text': 'PRIVATE SYSTEM'}]},
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Hello ไทย'}]},
            {'type': 'reasoning', 'encrypted_content': 'PRIVATE ENCRYPTED'},
            {'type': 'message', 'role': 'assistant', 'phase': 'analysis', 'content': [{'text': 'PRIVATE THINKING'}]},
            {'type': 'function_call', 'call_id': 'call1', 'name': 'read_file', 'arguments': '{"path":"a.txt","api_key":"secret"}'},
            {'type': 'function_call_output', 'call_id': 'call1', 'output': 'line one\r\nline two'},
            {'type': 'custom_tool_call', 'call_id': 'unfinished', 'name': 'exec', 'input': 'pending'},
        ])
        result = c._read_rollout(p, TASK)
        self.assertEqual(len(result['messages']), 2)
        text = json.dumps(result['messages'], ensure_ascii=False)
        self.assertIn('Hello ไทย', text)
        self.assertIn('line one', text)
        self.assertIn('read_file', text)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('secret', text)
        self.assertEqual(result['incomplete_tool_pairs'], 1)

    def test_partial_tail_is_ignored_without_modifying_source(self):
        c = self.controller()
        p = self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'Complete'}]}], tail=b'{"type":')
        before = p.read_bytes()
        result = c._read_rollout(p, TASK)
        self.assertEqual(len(result['messages']), 1)
        self.assertTrue(result['source_incomplete'])
        self.assertEqual(p.read_bytes(), before)

    def test_oversized_and_invalid_lines_are_reported(self):
        c = self.controller()
        p = self.rollout(tail=b'{bad}\n' + b'x' * 200 + b'\n')
        with patch.object(module, 'MAX_LINE_BYTES', 100):
            result = c._read_rollout(p, TASK)
        self.assertTrue(result['source_truncated'])
        self.assertGreater(result['skipped_lines'], 0)

    def test_long_messages_have_stable_labeled_parts(self):
        c = self.controller()
        p = self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'x' * 30000}]}])
        result = c._read_rollout(p, TASK)['messages']
        self.assertGreater(len(result), 1)
        self.assertTrue(all(len(x['content']) <= module.MAX_SEGMENT_CHARS + 100 for x in result))
        self.assertEqual(result, c._read_rollout(p, TASK)['messages'])

    def test_start_is_serialized_between_independent_controllers(self):
        c = self.controller()
        self.ready()
        self.rollout()
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(self.controller().status()['job']['task_id'], TASK)
        with self.assertRaisesRegex(RuntimeError, 'running|active'):
            self.controller().start(TASK)

    def test_worker_saves_incremental_summary_and_preserves_rollout(self):
        c = self.controller()
        self.ready()
        p = self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        before = p.read_bytes()
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', side_effect=self.fake_engine):
            c._run_job(TASK, job['job_id'])
        value = c.get_summary(TASK)
        self.assertEqual(value['summary'], 'Local summary.')
        self.assertEqual(value['coverage']['pending_messages'], 0)
        self.assertTrue(value['native_compaction_retained'])
        self.assertEqual(p.read_bytes(), before)
        self.assertNotIn('tokens_saved', json.dumps(value))

    def test_append_uses_previous_summary_and_changed_prefix_resets_it(self):
        c = self.controller()
        self.ready()
        one = {'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}
        two = {'type': 'message', 'role': 'assistant', 'content': [{'text': 'Second'}]}
        for items, expected_previous in [([one], False), ([one, two], True), ([two], False)]:
            self.rollout(items)
            with patch.object(c, '_launch_worker', return_value=1234):
                job = c.start(TASK)
            requests = []
            def engine(request, *args):
                requests.append(request)
                return self.fake_engine(request, *args)
            with patch.object(c, '_engine', side_effect=engine):
                c._run_job(TASK, job['job_id'])
            self.assertEqual('previous_summary' in requests[0], expected_previous)

    def test_partial_engine_result_does_not_claim_complete_coverage(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]},
                      {'type': 'message', 'role': 'assistant', 'content': [{'text': 'Second'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        def engine(request, *args):
            result = self.fake_engine({**request, 'messages': request['messages'][:1]}, *args)
            result['status'] = 'partial'
            return result
        with patch.object(c, '_engine', side_effect=engine):
            c._run_job(TASK, job['job_id'])
        result = c.get_summary(TASK)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage']['pending_messages'], 1)

    def test_cancellation_is_explicit_and_does_not_touch_other_task(self):
        c = self.controller()
        self.ready()
        self.rollout()
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with self.assertRaises(LookupError):
            c.cancel(OTHER)
        c.cancel(TASK)
        with patch.object(c, '_engine') as engine:
            c._run_job(TASK, job['job_id'])
        engine.assert_not_called()
        self.assertEqual(c.status()['job']['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
