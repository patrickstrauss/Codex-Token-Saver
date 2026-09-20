import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bundle_preferences as preferences
from command_compression import CommandCompressor
from desktop_headroom import DesktopHeadroom


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_independent_updates_preserve_other_choices_and_missing_defaults(self):
        self.assertTrue(preferences.load_preferences(self.root)['rtk'])
        self.assertFalse(preferences.load_preferences(self.root)['serena'])
        preferences.set_preference(self.root, 'rtk', False)
        preferences.set_preference(self.root, 'serena', True)
        values = preferences.load_preferences(self.root)
        self.assertFalse(values['rtk'])
        self.assertTrue(values['headroom_local'])
        self.assertTrue(values['serena'])

    def test_bad_values_are_rejected_without_writing(self):
        for key, value in [('rtk', 1), ('rtk', 'false'), ('headroom_requests', True)]:
            with self.assertRaises(ValueError):
                preferences.set_preference(self.root, key, value)
        self.assertFalse((self.root / 'settings/components.json').exists())

    def test_corrupt_state_disables_compression_and_is_not_overwritten(self):
        path = self.root / 'settings/components.json'
        path.parent.mkdir()
        for data in ['{', '{"schema_version":true,"components":{}}',
                     '{"schema_version":1,"components":{"rtk":"false"}}']:
            path.write_text(data)
            status = preferences.preference_status(self.root)
            self.assertTrue(status['error'])
            self.assertFalse(any(status['values'].values()))
            with self.assertRaises(ValueError):
                preferences.set_preference(self.root, 'rtk', True)
            self.assertEqual(path.read_text(), data)

    def test_local_off_returns_file_and_command_bytes_without_tokenizer(self):
        preferences.set_preference(self.root, 'headroom_local', False)
        backend = DesktopHeadroom(self.root / 'state', bundle_root=self.root)
        data = 'ภาษาไทย\r\nlast line'
        source = self.root / 'sample.txt'
        source.write_bytes(data.encode())
        with patch.object(backend, '_count', side_effect=AssertionError('tokenizer called')):
            self.assertTrue(backend.read_file(str(source)).endswith(data))
            compressor = CommandCompressor(self.root / 'state', backend, bundle_root=self.root)
            raw = b'\x00\xff\r\n' * 1000
            result = compressor.process(raw, return_code=0)
            self.assertEqual(result.output, raw)
            self.assertEqual(result.status, 'disabled')
            self.assertIsNone(result.input_tokens)

    def test_toggle_is_read_on_each_file_operation_and_retrieval_stays_available(self):
        from types import SimpleNamespace
        class Cache:
            entries = {}
            def store(self, **kwargs):
                key = kwargs['explicit_hash']
                self.entries[key] = SimpleNamespace(original_content=kwargs['original'])
                return key
            def retrieve(self, key):
                return self.entries.get(key)
        cache = Cache()
        backend = DesktopHeadroom(self.root / 'state', compressor=lambda _: 'summary',
                                  token_counter=len, cache=cache, bundle_root=self.root)
        original = 'retain every original line\r\n' * 100
        source = self.root / 'sample.txt'
        source.write_bytes(original.encode())
        self.assertIn('Compressed overview', backend.read_file(str(source)))
        key = next(iter(cache.entries))
        preferences.set_preference(self.root, 'headroom_local', False)
        self.assertTrue(backend.read_file(str(source)).endswith(original))
        self.assertTrue(backend.retrieve(key).endswith(original))


if __name__ == '__main__':
    unittest.main()
