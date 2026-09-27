import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from opencodex_control import OpenCodexControl, fingerprint
except ImportError:
    OpenCodexControl = None


class Bridge:
    def __init__(self):
        self.value = None
        self.calls = []
        self.interrupt = False

    def read(self):
        return {'protocol': 1, 'value': self.value, 'fingerprint': fingerprint(self.value)}

    def write(self, expected, value):
        if fingerprint(self.value) != expected:
            raise RuntimeError('Concurrent extension edit')
        self.calls.append(value)
        self.value = value
        if self.interrupt:
            self.interrupt = False
            raise RuntimeError('Response lost after write')
        return self.read()


class OpenCodexControlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(OpenCodexControl, 'OpenCodex controller is missing')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.config = self.home / 'config.toml'
        self.original = b'# preserve\nmodel="chosen"\nmodel_reasoning_effort="high"\n'
        self.config.write_bytes(self.original)
        self.bridge = Bridge()
        self.info = {'ready': True, 'routing_matches': True, 'transform_protocol': 1,
                     'control_protocol': 1, 'config_home': str(self.root / 'ocx'),
                     'extension_enabled': False}
        self.backend = {'ready': True, 'enabled': True, 'mode': 'transform-only', 'protocol': 1}
        self.control = OpenCodexControl(self.root, config_home=self.home, bridge=self.bridge,
            discovery=lambda: dict(self.info, extension_enabled=bool(self.bridge.value and self.bridge.value['enabled'])),
            backend=lambda: self.backend)

    def test_enable_pause_disconnect_preserve_route_and_selected_settings(self):
        self.assertTrue(self.control.set_enabled(True)['requested_enabled'])
        self.assertTrue(self.bridge.value['enabled'])
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.control.set_enabled(False)['requested_enabled'])
        self.assertFalse(self.bridge.value['enabled'])
        self.assertEqual(self.config.read_bytes(), self.original)
        self.control.disconnect()
        self.assertIsNone(self.bridge.value)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_missing_capability_never_writes_settings_or_extension(self):
        self.info['control_protocol'] = None
        with self.assertRaisesRegex(RuntimeError, 'OpenCodex'):
            self.control.set_enabled(True)
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse((self.root / 'proxy/settings.json').exists())

    def test_native_worker_warmup_never_enables_extension_early(self):
        self.backend = {'ready': True, 'mode': 'native', 'protocol': None}
        result = self.control.set_enabled(True)
        self.assertFalse(result['effective_enabled'])
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse(json.loads((self.root / 'proxy/opencodex-policy.json').read_text())['enabled'])
        self.backend = {'ready': True, 'enabled': True, 'mode': 'transform-only', 'protocol': 1}
        self.assertTrue(self.control.set_enabled(True)['effective_enabled'])

    def test_external_extension_edit_is_preserved(self):
        self.control.set_enabled(True)
        external = dict(self.bridge.value, tokenFile=str(self.root / 'someone-else'))
        self.bridge.value = external
        with self.assertRaisesRegex(RuntimeError, 'changed|owned'):
            self.control.disconnect()
        self.assertEqual(self.bridge.value, external)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_lost_reply_is_recoverable_without_another_write(self):
        self.bridge.interrupt = True
        with self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.assertFalse(json.loads((self.root / 'proxy/opencodex-policy.json').read_text())['enabled'])
        self.assertTrue(self.control.set_enabled(True)['effective_enabled'])
        self.assertEqual(len(self.bridge.calls), 1)

    def test_foreign_existing_extension_is_not_adopted(self):
        self.bridge.value = {'protocol': 1, 'enabled': True, 'endpoint': 'http://127.0.0.1:8789',
                             'tokenFile': str(self.root / 'foreign')}
        with self.assertRaisesRegex(RuntimeError, 'owned'):
            self.control.set_enabled(True)
        self.assertEqual(self.bridge.calls, [])

    def test_offline_pause_still_disables_local_compression(self):
        self.control.set_enabled(True)
        self.bridge.read = lambda: (_ for _ in ()).throw(RuntimeError('offline'))
        with self.assertRaises(RuntimeError):
            self.control.set_enabled(False)
        policy = json.loads((self.root / 'proxy/opencodex-policy.json').read_text())
        self.assertFalse(policy['enabled'])

    def test_offline_pause_cancels_pending_activation(self):
        self.backend = {}
        self.control.set_enabled(True)
        self.info['ready'] = False
        with self.assertRaises(RuntimeError):
            self.control.set_enabled(False)
        receipt = json.loads(self.control.receipt_file.read_text())
        self.assertFalse(receipt['requested_enabled'])

    def test_offline_disconnect_cancels_pending_activation(self):
        self.backend = {}
        self.control.set_enabled(True)
        self.info['ready'] = False
        with self.assertRaises(RuntimeError):
            self.control.disconnect()
        receipt = json.loads(self.control.receipt_file.read_text())
        self.assertFalse(receipt['requested_enabled'])

    def test_lost_reply_reconciles_ownership_before_another_cold_start(self):
        self.bridge.interrupt = True
        with self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.backend = {}
        self.control.set_enabled(True)
        self.backend = {'ready': True, 'enabled': True, 'mode': 'transform-only', 'protocol': 1}
        self.assertTrue(self.control.set_enabled(True)['effective_enabled'])
        self.assertEqual(len(self.bridge.calls), 1)

    def test_fingerprint_matches_wire_canonical_shape(self):
        self.assertEqual(fingerprint(None), hashlib.sha256(b'null').hexdigest())

    def test_legacy_pause_delegates_without_taking_native_route(self):
        from desktop_proxy_control import DesktopProxyControl
        from unittest.mock import patch
        self.control.set_enabled(True)
        legacy = DesktopProxyControl(self.root, config_home=self.home)
        with patch('opencodex_control.OpenCodexControl', return_value=self.control):
            legacy.set_enabled(False)
        self.assertFalse(self.bridge.value['enabled'])
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_legacy_offline_pause_with_damaged_settings_cancels_warmup(self):
        from desktop_proxy_control import DesktopProxyControl
        from unittest.mock import patch
        self.backend = {}
        self.control.set_enabled(True)
        self.control.settings_file.write_text('broken')
        self.info['ready'] = False
        with patch('opencodex_control.OpenCodexControl', return_value=self.control):
            with self.assertRaises(RuntimeError):
                DesktopProxyControl(self.root, config_home=self.home).set_enabled(False)
        self.assertFalse(json.loads(self.control.policy_file.read_text())['enabled'])
        self.assertFalse(json.loads(self.control.receipt_file.read_text())['requested_enabled'])

    def test_external_removal_is_not_silently_readopted(self):
        self.control.set_enabled(True)
        self.bridge.value = None
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.control.set_enabled(True)
        self.assertIsNone(self.bridge.value)

    def test_corrupt_ownership_fingerprint_refuses_changes(self):
        self.control.set_enabled(True)
        receipt = json.loads(self.control.receipt_file.read_text())
        receipt['owned_fingerprint'] = 'broken'
        self.control.receipt_file.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(RuntimeError, 'receipt'):
            self.control.set_enabled(False)


if __name__ == '__main__':
    unittest.main()
