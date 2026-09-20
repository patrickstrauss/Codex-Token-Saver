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
        from bundle_preferences import set_preference
        set_preference(self.root, 'local_summaries', True)
        set_preference(self.root, 'llama_cpp', True)
        runtime = self.root / 'local-compaction/.venv/Scripts'
        runtime.mkdir(parents=True)
        (runtime / 'python.exe').write_text('fixture')
        model = self.root / 'fixture.gguf'
        model.touch()
        binary = self.root / 'local-compaction/llama-b10809/llama-server.exe'
        binary.parent.mkdir()
        binary.touch()
        (self.root / 'local-compaction/model.json').write_text(json.dumps({'model_path': str(model)}))
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

    def test_disabled_dependency_prevents_a_job_but_preserves_saved_reads(self):
        from bundle_preferences import set_preference
        c = self.controller()
        self.ready()
        self.rollout()
        set_preference(self.root, 'llama_cpp', False)
        with self.assertRaisesRegex(RuntimeError, 'Enable'):
            c.start(TASK)
        self.assertEqual(c.get_summary(TASK)['status'], 'not_started')

    def test_missing_model_is_reported_before_any_worker_launch(self):
        c = self.controller()
        self.ready()
        self.rollout()
        (self.root / 'fixture.gguf').unlink()
        self.assertFalse(c.status()['runtime_available'])
        with self.assertRaises(RuntimeError):
            c.start(TASK)

    def test_lists_only_explicit_valid_local_task_metadata(self):
        c = self.controller()
        self.rollout()
        self.assertEqual(c.list_tasks(), [{'task_id': TASK, 'project': 'project',
            'updated_at': c.list_tasks()[0]['updated_at'], 'bytes': c.list_tasks()[0]['bytes'],
            'has_summary': False}])
        self.assertFalse(c.status()['available'])

    def test_lookup_resolves_an_old_task_without_reading_its_conversation(self):
        c = self.controller()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'PRIVATE TRANSCRIPT'}]}])
        with patch.object(c, 'list_tasks', return_value=[]), patch.object(c, '_read_rollout', side_effect=AssertionError('must not read text')):
            value = c.lookup_task(TASK)
        self.assertEqual(value['task_id'], TASK)
        self.assertEqual(value['project'], 'project')
        self.assertNotIn('PRIVATE TRANSCRIPT', json.dumps(value))
        with self.assertRaises(FileNotFoundError):
            c.lookup_task(OTHER)
        with self.assertRaises(ValueError):
            c.lookup_task('../sessions')

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

    def test_refresh_drains_partial_engine_results_until_snapshot_is_covered(self):
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
        self.assertEqual(result['status'], 'summarized')
        self.assertEqual(result['coverage']['pending_messages'], 0)
        self.assertEqual(c.status()['job']['batches_completed'], 2)

    def test_cancel_between_batches_keeps_checkpoint_and_refresh_resumes(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]},
                      {'type': 'message', 'role': 'assistant', 'content': [{'text': 'Second'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        calls = []
        def engine(request, *args):
            calls.append(request)
            if len(calls) == 2:
                c.cancel(TASK)
            return self.fake_engine({**request, 'messages': request['messages'][:1]}, *args)
        with patch.object(c, '_engine', side_effect=engine):
            c._run_job(TASK, job['job_id'])
        self.assertEqual(c.status()['job']['status'], 'cancelled')
        self.assertEqual(c.get_summary(TASK)['coverage']['summarized_messages'], 1)
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', side_effect=self.fake_engine):
            c._run_job(TASK, job['job_id'])
        self.assertEqual(c.get_summary(TASK)['coverage']['pending_messages'], 0)

    def test_no_progress_fails_instead_of_spinning_forever(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', return_value={'status': 'unchanged', 'summary': 'old',
                'running_summary': {'summary': 'old', 'summarized_message_ids': []}}) as engine:
            c._run_job(TASK, job['job_id'])
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(c.status()['job']['status'], 'failed')
        self.assertFalse(c._saved_path(TASK).exists())

    def test_timeout_retries_only_pending_content_in_a_smaller_batch(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': f'part {i}'}]} for i in range(4)])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        requests = []
        def engine(request, *args):
            requests.append(json.loads(json.dumps(request)))
            if len(requests) == 1:
                return {'status': 'failed', 'error_code': 'model_timeout', 'error_stage': 'model', 'retryable': True}
            return self.fake_engine(request, *args)
        with patch.object(c, '_engine', side_effect=engine), patch.object(c, '_close_engine') as close:
            c._run_job(TASK, job['job_id'])
        self.assertEqual([len(r['messages']) for r in requests], [4, 2, 2])
        self.assertEqual(close.call_count, 2)
        self.assertEqual(c.status()['job']['recoveries'], 1)
        self.assertEqual(c.get_summary(TASK)['coverage']['pending_messages'], 0)

    def test_repeated_timeout_stops_with_actionable_error_and_preserved_checkpoint(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', return_value={'status': 'failed', 'error_code': 'model_timeout',
                'error_type': 'APITimeoutError', 'retryable': True}) as engine:
            c._run_job(TASK, job['job_id'])
        self.assertEqual(engine.call_count, 2)
        self.assertEqual(c.status()['job']['error_code'], 'model_timeout')
        self.assertEqual(c.status()['job']['error_type'], 'APITimeoutError')
        self.assertIn('timed out', c.status()['job']['error'])
        self.assertFalse(c._saved_path(TASK).exists())

    def test_cancel_during_retry_cleanup_does_not_restart_model(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', return_value={'status': 'failed', 'error_code': 'model_timeout'}) as engine, \
             patch.object(c, '_close_engine', side_effect=lambda: c.cancel(TASK)):
            c._run_job(TASK, job['job_id'])
        engine.assert_called_once()
        self.assertEqual(c.status()['job']['status'], 'cancelled')
        self.assertFalse(c._saved_path(TASK).exists())

    def test_engine_process_is_reused_then_closed(self):
        import sys
        c = self.controller()
        self.ready()
        self.rollout()
        (self.root / 'local_summary_engine.py').write_text(
            'import json, sys, os\n'
            'for line in sys.stdin:\n'
            ' print(json.dumps({"pid":os.getpid(),"echo":json.loads(line)}),flush=True)\n')
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        self.addCleanup(lambda: getattr(c, '_close_engine', lambda: None)())
        with patch.object(c, '_runtime', return_value=Path(sys.executable)):
            one = c._engine({'n': 1}, TASK, job['job_id'])
            two = c._engine({'n': 2}, TASK, job['job_id'])
        self.assertEqual(one['pid'], two['pid'])
        self.assertEqual(two['echo'], {'n': 2})
        process = c._engine_process
        c._close_engine()
        self.assertIsNotNone(process.poll())

    def test_cleanup_still_runs_if_final_status_write_fails(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        update = c._update_job
        def fail_unloading(*args, **kwargs):
            if kwargs.get('phase') == 'unloading':
                raise OSError('fixture state write failed')
            return update(*args, **kwargs)
        with patch.object(c, '_engine', side_effect=self.fake_engine), \
             patch.object(c, '_update_job', side_effect=fail_unloading), \
             patch.object(c, '_close_engine') as close:
            with self.assertRaises(OSError):
                c._run_job(TASK, job['job_id'])
        close.assert_called_once()

    def test_large_checkpoint_roundtrip_and_oversized_write_preserves_previous(self):
        c = self.controller()
        path = c._saved_path(TASK)
        ids = [f'{i:064x}' for i in range(16000)]
        value = {'covered_ids': ids, 'running_summary': {'summary': 'fixture',
            'summarized_message_ids': ids, 'last_summarized_message_id': ids[-1]}}
        module._write(path, value)
        self.assertEqual(module._read(path), value)
        before = path.read_bytes()
        with patch.object(module, 'MAX_STATE_BYTES', 100), self.assertRaises(ValueError):
            module._write(path, value)
        self.assertEqual(path.read_bytes(), before)

    def test_checkpoint_publication_tolerates_a_brief_status_reader(self):
        import threading
        c = self.controller()
        path = c._saved_path(TASK)
        module._write(path, {'n': 0})
        reader = path.open('rb')
        release = threading.Timer(.08, reader.close)
        release.start()
        try:
            module._write(path, {'n': 1})
        finally:
            release.join()
            reader.close()
        self.assertEqual(module._read(path), {'n': 1})

    def test_old_summary_is_stale_and_explicit_refresh_rebuilds_evidence(self):
        c = self.controller()
        self.ready()
        p = self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'First'}]}])
        ids = [m['id'] for m in c._read_rollout(p, TASK)['messages']]
        module._write(c._saved_path(TASK), {'summary': 'old', 'covered_ids': ids,
                     'running_summary': {'summary': 'old', 'summarized_message_ids': ids}})
        self.assertEqual(c.get_summary(TASK)['status'], 'stale')
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', side_effect=self.fake_engine) as engine:
            c._run_job(TASK, job['job_id'])
        self.assertNotIn('previous_summary', engine.call_args.args[0])
        self.assertEqual(c.get_summary(TASK)['status'], 'summarized')

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

    def test_incomplete_source_is_never_reported_fully_summarized(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'Complete item'}]}],
                     tail=b'{bad}\n' + b'{"incomplete":')
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        with patch.object(c, '_engine', side_effect=self.fake_engine):
            c._run_job(TASK, job['job_id'])
        result = c.get_summary(TASK)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['coverage']['source_truncated'])
        self.assertTrue(result['coverage']['source_incomplete'])
        self.assertEqual(c.status()['job']['status'], 'partial')

    def test_cancel_before_final_publication_preserves_previous_summary(self):
        c = self.controller()
        self.ready()
        self.rollout([{'type': 'message', 'role': 'user', 'content': [{'text': 'New item'}]}])
        with patch.object(c, '_launch_worker', return_value=1234):
            job = c.start(TASK)
        original_path = c._saved_path
        lookups = []
        def publication_path(task):
            lookups.append(task)
            # First lookup reads the prior artifact; second resolves the publication target.
            # Cancel arriving between the model result check and its commit must win.
            if len(lookups) == 2:
                c.cancel(TASK)
            return original_path(task)
        with patch.object(c, '_engine', side_effect=self.fake_engine), \
             patch.object(c, '_saved_path', side_effect=publication_path):
            c._run_job(TASK, job['job_id'])
        self.assertFalse(original_path(TASK).exists())
        self.assertEqual(c.status()['job']['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
