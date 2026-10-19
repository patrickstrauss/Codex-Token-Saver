import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from scripts.benchmark_codex_e2e import child_environment, failure_category, main, parse_events, profile_text, study_manifest, summarize
from scripts.benchmark_e2e_fixtures import cases, grade
from scripts.publish_codex_e2e import render
from scripts.benchmark_stack import full_configuration, hook_counts


class EndToEndBenchmarkTests(unittest.TestCase):
    def test_default_plan_makes_no_model_call_and_has_balanced_frozen_workloads(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'plan.json'
            with patch('sys.argv', ['benchmark', '--output', str(output)]), \
                 patch('scripts.benchmark_codex_e2e.run', side_effect=AssertionError('No opt-in')):
                self.assertEqual(main(), 0)
            data = json.loads(output.read_text())
            self.assertEqual(data['model_calls'], 0)
            self.assertEqual(len(data['cases']), 5)
            for case in data['cases']:
                self.assertEqual(set(case['order']), {'native', 'bundle'})
            self.assertEqual(data, study_manifest(20261019))

    def test_native_profile_has_no_mcp_proxy_or_hooks(self):
        data = tomllib.loads(profile_text('gpt-6.1-sol', 'native', Path('C:/Example/Bundle'), Path('C:/Example/State')))
        self.assertEqual(data['model_provider'], 'openai')
        self.assertNotIn('mcp_servers', data)
        self.assertNotIn('hooks', data)
        self.assertNotIn('openai_base_url', data)

    def test_treatment_only_adds_actual_required_bundle_servers(self):
        data = tomllib.loads(profile_text('gpt-6.1-sol', 'bundle', Path('C:/Example/Bundle'), Path('C:/Example/State')))
        self.assertEqual(len(data['mcp_servers']), 3)
        for value in data['mcp_servers'].values():
            self.assertTrue(value['required'])
            self.assertEqual(value['env']['CTS_ACTIVITY_KIND'], 'diagnostic')
            self.assertIn('no-credentials', value['env']['CODEX_HOME'])
        self.assertNotIn('openai_base_url', data)

    def test_child_cannot_inherit_provider_overrides_or_internal_gateway_markers(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'private-placeholder', 'OPENAI_BASE_URL': 'private-placeholder',
                                     'CODEX_THREAD_ID': 'foreign', 'CTS_LAYA_INTERNAL': '1'}):
            env = child_environment(Path('profile'), Path('state'))
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('OPENAI_BASE_URL', env)
        self.assertNotIn('CODEX_THREAD_ID', env)
        self.assertNotIn('CTS_LAYA_INTERNAL', env)

    def test_usage_and_failures_are_recorded_without_tool_arguments_or_payloads(self):
        events = [
            {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'headroom_desktop',
                'tool': 'headroom_read_file', 'arguments': {'private': 'DO_NOT_PUBLISH'},
                'result': {'isError': True, 'content': 'DO_NOT_PUBLISH'}}},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'exit_code': 1, 'command': 'DO_NOT_PUBLISH'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 10}},
        ]
        parsed = parse_events('\n'.join(json.dumps(event) for event in events))
        self.assertEqual(parsed['usage']['cached_input_tokens'], 80)
        self.assertTrue(parsed['bundle_calls'][0]['failed'])
        self.assertEqual(parsed['command_failures'], 1)
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(parsed))

    def test_missing_invalid_and_impossible_cache_usage_are_not_fabricated(self):
        for usage in ({}, {'input_tokens': True, 'output_tokens': 1},
                      {'input_tokens': 10, 'cached_input_tokens': 11, 'output_tokens': 1}):
            data = parse_events(json.dumps({'type': 'turn.completed', 'usage': usage}))
            self.assertIsNone(data['usage'])

    def test_quality_rejects_correct_answer_if_fixture_was_changed(self):
        case = cases()[0]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content in case['files'].items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            self.assertTrue(grade(case, root, case['expected'])['passed'])
            (root / 'logs/worker.log').write_text('changed')
            self.assertFalse(grade(case, root, case['expected'])['passed'])

    def test_hidden_oracle_rejects_original_and_accepts_valid_code(self):
        case = cases()[3]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content in case['files'].items():
                (root / name).write_text(content, encoding='utf-8')
            self.assertFalse(grade(case, root, {'summary': 'fixed'})['passed'])
            (root / 'retries.py').write_text('''import math
def retry_delay(attempt, base=1, cap=30):
    if type(attempt) is not int or attempt < 1: raise ValueError()
    for value in (base,cap):
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0: raise ValueError()
    if base == 0 or cap == 0: return 0
    return min(cap,base * 2**(attempt-1))
''', encoding='utf-8')
            self.assertTrue(grade(case, root, {'summary': 'fixed'})['passed'])
            (root / 'test_retries.py').write_text('# deleted tests')
            self.assertFalse(grade(case, root, {'summary': 'fixed'})['passed'])

    def test_negative_results_and_partial_usage_remain_visible(self):
        rows = [{'arm': arm, 'passed': arm == 'native', 'wall_seconds': 1,
                 'usage': {'input_tokens': 100 if arm == 'native' else 150, 'cached_input_tokens': 0, 'output_tokens': 10},
                 'bundle_calls': []} for _ in range(5) for arm in ('native', 'bundle')]
        summary = summarize(rows)
        self.assertEqual(summary['input_reduction_percent'], -50)
        self.assertEqual(summary['arms']['bundle']['passed'], 0)
        rows[0]['usage'] = None
        self.assertIsNone(summarize(rows)['input_reduction_percent'])

    def test_failure_diagnostics_are_allowlisted_categories(self):
        self.assertEqual(failure_category('401 private token=DO_NOT_PUBLISH'), 'authentication')
        self.assertEqual(failure_category('private unrelated diagnostic'), 'unclassified')

    def test_full_plan_freezes_automatic_paths_and_clear_symbol_answer_format(self):
        data = study_manifest(20261019, 'full')
        self.assertEqual(data['configuration'], 'full')
        self.assertNotIn('automatic request proxy', data['excluded'])
        self.assertIn('unqualified function names', data['cases'][1]['prompt'])

    def test_full_configuration_refuses_an_unready_backend_without_starting_services(self):
        with patch('scripts.benchmark_stack.get_json', return_value={'ready': False}), \
             patch('scripts.benchmark_stack.subprocess.Popen') as spawn:
            with self.assertRaises(ValueError), full_configuration(Path('unused'), Path('unused'), Path('unused'), {}):
                pass
            spawn.assert_not_called()

    def test_hook_observations_exclude_other_chats_and_detect_truncated_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'headroom/desktop-state/hook-events.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'task_id': 'unrelated', 'outcome': 'rewritten'}) + '\n')
            offset = path.stat().st_size
            with path.open('a') as stream:
                for task, outcome in [('mine','rewritten'), ('mine','skipped'), ('unrelated','rewritten')]:
                    stream.write(json.dumps({'task_id': task, 'outcome': outcome}) + '\n')
            stdout = json.dumps({'type': 'thread.started', 'thread_id': 'mine'})
            result = hook_counts(root, offset, stdout)
            self.assertEqual(result['events'], {'rewritten': 1, 'skipped': 1})
            self.assertNotIn('mine', json.dumps(result))
            self.assertFalse(hook_counts(root, path.stat().st_size + 1, stdout)['coverage_complete'])

    def test_report_refuses_incomplete_and_duplicate_pairs(self):
        row = {'case': 'log-diagnosis', 'arm': 'native'}
        for rows in ([row], [row] * 10):
            with self.assertRaises(ValueError):
                render({'samples': rows}, 'results.json', 'manifest.json')

    def test_report_keeps_negative_results_and_failed_quality_visible(self):
        rows = [{'case': case['id'], 'arm': arm, 'passed': arm == 'native',
                 'quality': {'answer_correct': arm == 'native'}, 'wall_seconds': 1,
                 'usage': {'input_tokens': 100 if arm == 'native' else 150,
                           'cached_input_tokens': 20, 'output_tokens': 10},
                 'bundle_calls': []} for case in cases() for arm in ('native', 'bundle')]
        report = {'samples': rows, 'summary': summarize(rows), 'complete': True,
                  'started_at': '2026-10-19', 'daily_profile_unchanged': True,
                  'metadata': {'configured_model': 'test', 'reasoning_effort': 'low', 'codex_version': 'test',
                               'os_version': 'test', 'architecture': 'x64',
                               'sandbox_mode': 'workspace-write', 'bundle_versions': {'headroom': 'test'}}}
        text = render(report, 'results.json', 'manifest.json')
        self.assertIn('-50.00%', text)
        self.assertIn('failed checks: answer_correct', text)
        self.assertIn('VM tests remain paused', text)
        report['summary']['arms']['bundle']['passed'] = 5
        with self.assertRaises(ValueError):
            render(report, 'results.json', 'manifest.json')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows chart renderer')
    def test_chart_renders_png_from_recorded_attempts_without_extra_packages(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'chart.png'
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(root / 'scripts/Plot-CodexBenchmark.ps1'), '-InputJson',
                str(root / 'docs/benchmarks/coding-windows.json'), '-OutputPng', str(output)],
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(output.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows chart renderer')
    def test_chart_refuses_incomplete_data_and_fabricated_summary_before_writing(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / 'docs/benchmarks/coding-windows.json').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'report.json', Path(folder) / 'chart.png'
            for kind in ('duplicate_pair', 'missing_usage', 'fake_summary'):
                data = json.loads(original)
                if kind == 'duplicate_pair':
                    data['samples'][0] = data['samples'][1]
                elif kind == 'missing_usage':
                    data['samples'][0]['usage'] = None
                else:
                    data['summary']['arms']['bundle']['input_tokens'] = 1
                source.write_text(json.dumps(data), encoding='utf-8')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(root / 'scripts/Plot-CodexBenchmark.ps1'), '-InputJson', str(source), '-OutputPng', str(output)],
                    capture_output=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, kind)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
