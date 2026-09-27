import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'dashboard')]


class MetricsTests(unittest.TestCase):
    def test_replies_include_cached_and_zero_savings_without_private_text(self):
        from request_transform_metrics import record_transform
        from request_metrics import request_windows
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = {'entries': [{'id': 'one', 'text': 'private output' * 200}]}
            compressed = {'outcome': 'compressed', 'replacements': [{'id': 'one', 'replacement': 'short'}]}
            now = datetime.now(timezone.utc)
            for result in (compressed, compressed, {'outcome': 'unchanged', 'replacements': []},
                           {'outcome': 'bypassed', 'replacements': []}):
                self.assertTrue(record_transform(root, len, value, result, now=now))
            path = root / 'proxy/transform-state/savings_events.jsonl'
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(r['saved'] for r in rows), 2 * (len(value['entries'][0]['text']) - 5))
            self.assertNotIn('private output', path.read_text())
            self.assertNotIn('replacement', path.read_text())
            windows = request_windows(path, now=now, include_lifetime=True)['windows']
            self.assertEqual(windows['today'], windows['lifetime'])
            self.assertEqual(windows['today']['requests'], 4)
            self.assertEqual(windows['today']['input_tokens'], 4 * len(value['entries'][0]['text']))

    def test_invalid_and_failed_metering_do_not_break_compression(self):
        from request_transform_metrics import record_transform
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertFalse(record_transform(root, len, {}, {'outcome': 'error'}))
            def broken(_):
                raise RuntimeError('private failure')
            self.assertFalse(record_transform(root, broken, {'entries': [{'id': 'a', 'text': 'secret'}]},
                                              {'outcome': 'unchanged', 'replacements': []}))
            self.assertFalse((root / 'proxy/transform-state/savings_events.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
