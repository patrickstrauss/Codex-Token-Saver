import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.benchmark_codex_context import fixtures, main, parse_events


class CodexContextStudyTests(unittest.TestCase):
    def stream(self, answer=None, usage=None, tool=False, failed=False):
        events = []
        if tool:
            events.append({'type': 'item.completed', 'item': {'type': 'command_execution'}})
        events.append({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}})
        events.append({'type': 'turn.completed', 'usage': usage or {}})
        if failed:
            events.append({'type': 'turn.failed'})
        return '\n'.join(json.dumps(event) for event in events)

    def test_fixture_rubric_contains_one_unambiguous_error(self):
        cases = fixtures()
        self.assertEqual(len({case['id'] for case in cases}), 5)
        for case in cases:
            self.assertEqual(case['text'].count('ERROR'), 1)
            self.assertTrue(all(value in case['text'] for value in case['expected'].values()))

    def test_usage_is_reported_separately_from_answer_quality(self):
        expected = fixtures()[0]['expected']
        usage = {'input_tokens': 3000, 'cached_input_tokens': 2000, 'output_tokens': 50}
        result = parse_events(self.stream(expected, usage), expected)
        self.assertTrue(result['passed'])
        self.assertEqual(result['usage'], usage)
        wrong = parse_events(self.stream({'component': 'wrong'}, usage), expected)
        self.assertFalse(wrong['passed'])
        self.assertEqual(wrong['usage'], usage)

    def test_runtime_errors_and_tool_use_cannot_pass(self):
        expected = fixtures()[0]['expected']
        self.assertFalse(parse_events(self.stream(expected, tool=True), expected)['passed'])
        self.assertFalse(parse_events(self.stream(expected, failed=True), expected)['passed'])

    def test_missing_usage_and_malformed_events_are_not_invented(self):
        self.assertIsNone(parse_events('not-json', {})['usage'])
        result = parse_events(self.stream({}, {'input_tokens': True, 'output_tokens': -1}), {})
        self.assertIsNone(result['usage'])
        self.assertFalse(result['passed'])
        self.assertFalse(parse_events('[]\nnull\n' + self.stream({}), {})['passed'])

    def test_default_plan_never_reads_auth_or_runs_models(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'plan.json'
            with patch('sys.argv', ['study', '--output', str(output)]), \
                 patch('scripts.benchmark_codex_context.run_study', side_effect=AssertionError('Must opt in')):
                self.assertEqual(main(), 0)
            result = json.loads(output.read_text())
            self.assertTrue(result['plan_only'])
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual(result['max_cli_invocations'], 10)


if __name__ == '__main__':
    unittest.main()
