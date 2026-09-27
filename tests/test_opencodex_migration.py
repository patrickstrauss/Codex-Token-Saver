from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import json
from desktop_proxy_control import DesktopProxyControl

from opencodex_migration import Migration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'; self.home.mkdir()
        self.config = self.home / 'config.toml'
        self.config.write_text('model="chosen"\nmodel_reasoning_effort="ultra"\nopenai_base_url="http://127.0.0.1:8788/v1"\n')
        (self.home / 'auth.json').write_bytes(b'private')
        self.native = Mock()
        self.native.set_enabled.side_effect = lambda enabled: self.config.write_text('model="chosen"\nmodel_reasoning_effort="ultra"\n')
        self.control = Mock()
        self.control.bridge.read.return_value = {'value': None}
        self.control.discovery.return_value = {'ready': True, 'routing_matches': True, 'transform_protocol': 1, 'control_protocol': 1}
        self.control.set_enabled.return_value = {'phase': 'warming', 'requested_enabled': True}
        self.migration = Migration(self.root, self.home, native=self.native, control=self.control)

    def test_handoff_uses_owned_pause_then_extension(self):
        self.migration.prepare()
        self.native.set_enabled.assert_called_once_with(False)
        self.config.write_text(self.config.read_text() + 'openai_base_url="http://127.0.0.1:10100/v1"\n')
        self.assertEqual(self.migration.connect()['phase'], 'warming')
        self.control.set_enabled.assert_called_once_with(True)

    def test_changed_model_blocks_enable(self):
        self.migration.prepare()
        self.config.write_text('model="different"\nmodel_reasoning_effort="ultra"\n')
        with self.assertRaisesRegex(RuntimeError, 'settings'):
            self.migration.connect()
        self.control.set_enabled.assert_not_called()

    def test_changed_auth_blocks_enable_without_restoring_it(self):
        self.migration.prepare()
        (self.home / 'auth.json').write_bytes(b'new credentials')
        with self.assertRaisesRegex(RuntimeError, 'settings'):
            self.migration.connect()
        self.assertEqual((self.home / 'auth.json').read_bytes(), b'new credentials')

    def test_unsupported_binary_does_not_pause_native(self):
        self.control.bridge.read.side_effect = RuntimeError('unsupported')
        with self.assertRaises(RuntimeError):
            self.migration.prepare()
        self.native.set_enabled.assert_not_called()

    def test_resume_does_not_pause_opencodex_route(self):
        self.migration.prepare(); self.migration.prepare()
        self.native.set_enabled.assert_called_once_with(False)

    def test_wrong_route_does_not_enable(self):
        self.migration.prepare()
        self.control.discovery.return_value['routing_matches'] = False
        with self.assertRaisesRegex(RuntimeError, 'route'):
            self.migration.connect()
        self.control.set_enabled.assert_not_called()

    def test_actual_native_receipt_restores_only_its_owned_route(self):
        state = self.root / 'proxy'; state.mkdir()
        (state / 'settings.json').write_text(json.dumps({'installed': True, 'enabled': True, 'custom': 42}))
        (state / 'route-receipt.json').write_text(json.dumps({'schema': 1,
            'url': 'http://127.0.0.1:8788/v1', 'config': str(self.config.resolve()), 'previous_present': False}))
        native = DesktopProxyControl(self.root, config_home=self.home)
        native._fetch = Mock(return_value={})
        self.migration.native = native
        self.migration.prepare()
        self.assertNotIn('openai_base_url', self.config.read_text())
        self.assertEqual(json.loads((state / 'settings.json').read_text())['custom'], 42)
        self.assertFalse(json.loads((state / 'settings.json').read_text())['enabled'])

    def test_normal_model_changes_after_completed_handoff_are_allowed(self):
        self.migration.prepare(); self.migration.connect()
        self.config.write_text('model="later user choice"\nmodel_reasoning_effort="high"\n')
        self.migration.prepare(); self.migration.connect()
        self.assertIn('later user choice', self.config.read_text())

    def test_settings_race_during_activation_pauses_compression(self):
        self.migration.prepare()
        def update(enabled):
            if enabled:
                self.config.write_text('model="concurrent choice"\n')
            return {'phase': 'complete'}
        self.control.set_enabled.side_effect = update
        with self.assertRaisesRegex(RuntimeError, 'settings'):
            self.migration.connect()
        self.assertEqual(self.control.set_enabled.call_args.args, (False,))


if __name__ == '__main__':
    unittest.main()
