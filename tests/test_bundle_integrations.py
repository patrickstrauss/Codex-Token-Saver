import tempfile
import unittest
from pathlib import Path
import tomllib
from unittest.mock import patch

from bundle_integrations import BundleIntegrations


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.config = self.home / 'config.toml'
        self.original = b'model = "selected-model"\nmodel_reasoning_effort = "ultra"\nopenai_base_url = "http://127.0.0.1:8788/v1"\n\n[mcp_servers.existing]\ncommand = "existing.exe"\n'
        self.config.write_bytes(self.original)
        for name in ('headroom/.venv/Scripts/python.exe', 'serena_mcp.py', 'local_summary_mcp.py',
                     'serena/.venv/Scripts/python.exe', 'local-compaction/.venv/Scripts/python.exe'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        self.control = BundleIntegrations(self.root, config_home=self.home)

    def test_enable_owns_only_its_mcp_table_and_is_idempotent(self):
        self.control.set_enabled('serena', True)
        first = self.config.read_bytes()
        self.control.set_enabled('serena', True)
        self.assertEqual(first, self.config.read_bytes())
        config = tomllib.loads(first.decode())
        self.assertEqual(config['model'], 'selected-model')
        self.assertEqual(config['model_reasoning_effort'], 'ultra')
        self.assertEqual(config['openai_base_url'], 'http://127.0.0.1:8788/v1')
        self.assertEqual(config['mcp_servers']['existing'], {'command': 'existing.exe'})
        self.assertFalse(config['mcp_servers']['bundle_serena']['required'])
        self.assertEqual(len(config['mcp_servers']['bundle_serena']['enabled_tools']), 4)

    def test_toggle_changes_live_preference_and_reenabling_keeps_table_order(self):
        from bundle_preferences import load_preferences
        self.control.set_enabled('serena', True)
        self.control.set_enabled('local_summaries', True)
        before = self.config.read_bytes()
        self.control.set_enabled('serena', True)
        self.assertEqual(before, self.config.read_bytes())
        self.assertTrue(load_preferences(self.root)['serena'])
        self.assertTrue(self.control.status()['serena']['requested_enabled'])
        self.control.set_enabled('serena', False)
        self.assertFalse(load_preferences(self.root)['serena'])

    def test_concurrent_codex_config_change_is_preserved_and_preference_rolled_back(self):
        from bundle_preferences import set_preference, load_preferences
        concurrent = self.original + b'\n# external change\n'
        def changed(root, name, enabled):
            result = set_preference(root, name, enabled)
            if enabled:
                self.config.write_bytes(concurrent)
            return result
        with patch('bundle_integrations.set_preference', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.control.set_enabled('serena', True)
        self.assertEqual(self.config.read_bytes(), concurrent)
        self.assertFalse(load_preferences(self.root)['serena'])

    def test_disable_restores_original_and_preserves_other_bundle_component(self):
        self.control.set_enabled('serena', True)
        self.control.set_enabled('local_summaries', True)
        self.control.set_enabled('serena', False)
        config = tomllib.loads(self.config.read_text())
        self.assertNotIn('bundle_serena', config['mcp_servers'])
        self.assertIn('bundle_local_summaries', config['mcp_servers'])
        self.control.set_enabled('local_summaries', False)
        self.assertEqual(self.original, self.config.read_bytes())

    def test_unmanaged_table_and_malformed_config_are_never_overwritten(self):
        for extra in (b'\n[mcp_servers.bundle_serena]\ncommand="custom"\n', b'\ninvalid = ['):
            before = self.original + extra
            self.config.write_bytes(before)
            with self.assertRaises(ValueError):
                self.control.set_enabled('serena', True)
            self.assertEqual(before, self.config.read_bytes())

    def test_missing_runtime_and_invalid_arguments_do_not_change_config(self):
        (self.root / 'serena/.venv/Scripts/python.exe').unlink()
        for component, enabled in (('serena', True), ('../bad', True), ('serena', 'yes')):
            with self.assertRaises(ValueError):
                self.control.set_enabled(component, enabled)
        self.assertEqual(self.original, self.config.read_bytes())

    def test_status_does_not_change_files_or_start_a_model(self):
        before = set(self.root.rglob('*'))
        result = self.control.status()
        self.assertFalse(result['serena']['configured'])
        self.assertFalse(result['local_summaries']['configured'])
        self.assertEqual(before, set(self.root.rglob('*')))
        self.assertEqual(self.original, self.config.read_bytes())


if __name__ == '__main__':
    unittest.main()
