"""Handoff transactions use disposable state and the real routing controllers."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_proxy_control import DesktopProxyControl, LOCAL_URL, _encode, _read
from native_migration import Migration
from opencodex_control import OpenCodexControl, fingerprint


class Bridge:
    value = None

    def read(self):
        return {'protocol': 1, 'value': self.value, 'fingerprint': fingerprint(self.value)}

    def write(self, expected, value):
        if fingerprint(self.value) != expected:
            raise RuntimeError('Concurrent extension edit')
        self.value = value
        return self.read()


class NativeMigrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.state = self.root / 'proxy'
        self.config = self.home / 'config.toml'
        self.endpoint = 'http://127.0.0.1:18888/v1'
        self.keep = (b'# keep\r\nmodel="gpt-6.1-sol"\r\nmodel_reasoning_effort="ultra"\r\n'
                     b'[profiles.work]\r\nmodel="gpt-6.1-sol"\r\nmodel_reasoning_effort="ultra"\r\n'
                     b'[features]\r\nhooks=true\r\n')
        self.config.write_bytes(self.original())
        (self.home / 'auth.json').write_bytes(b'{"fixture":"auth"}\n')
        self.bridge = Bridge()
        info = {'ready': True, 'routing_matches': True, 'endpoint': self.endpoint,
                'transform_protocol': 1, 'control_protocol': 1, 'config_home': str(self.root / 'ocx')}
        self.control = OpenCodexControl(self.root, config_home=self.home, bridge=self.bridge,
            discovery=lambda: dict(info, extension_enabled=bool(self.bridge.value and self.bridge.value['enabled'])),
            backend=lambda: {'ready': True, 'enabled': True, 'mode': 'transform-only', 'protocol': 1})
        self.control.set_enabled(True)
        self.native = DesktopProxyControl(self.root, config_home=self.home)
        self.native.validation = lambda: True
        self.native._fetch = lambda url: {'service': 'codex-token-saver-proxy', 'status': 'ok',
            'ready': True, 'backend_ready': True} if ':8788/' in url else {}
        self.migration = Migration(self.root, self.home, native=self.native, control=self.control)
        self.env = patch.dict(os.environ, {key: '' for key in
            ('OPENAI_BASE_URL', 'OPENAI_API_BASE', 'AZURE_OPENAI_ENDPOINT', 'CODEX_OSS_BASE_URL')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def original(self, realtime=None):
        route = b'openai_base_url="http://127.0.0.1:18888/v1"\r\n'
        catalog = ('model_catalog_json=' + json.dumps(str(self.home / 'opencodex-catalog.json')) + '\r\n').encode()
        ws = b'' if realtime is None else ('experimental_realtime_ws_base_url=' + json.dumps(realtime) + '\r\n').encode()
        return b'\xef\xbb\xbf' + route + catalog + ws + self.keep

    def test_prepare_and_connect_preserve_exact_settings_auth_and_backup(self):
        original = self.config.read_bytes()
        auth = (self.home / 'auth.json').read_bytes()
        receipt = self.migration.prepare()
        self.assertEqual(receipt['phase'], 'prepared')
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf' + self.keep)
        self.assertEqual(Path(receipt['backup']).read_bytes(), original)
        self.assertFalse(self.bridge.value['enabled'])
        result = self.migration.connect()
        self.assertEqual(result['phase'], 'complete')
        self.assertTrue(result['enabled'])
        self.assertIn(LOCAL_URL.encode(), self.config.read_bytes())
        self.assertTrue(self.config.read_bytes().endswith(self.keep))
        self.assertEqual((self.home / 'auth.json').read_bytes(), auth)
        self.assertEqual(self.migration.connect()['phase'], 'complete')

    def test_removes_only_owned_root_realtime_override(self):
        self.config.write_bytes(self.original('ws://127.0.0.1:18888/v1'))
        self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf' + self.keep)

    def test_foreign_realtime_overrides_are_rejected_without_config_changes(self):
        for value in ('ws://127.0.0.1:18889/v1', 'http://127.0.0.1:18889/v1', 'wss://example.org/v1', ''):
            with self.subTest(value=value):
                before = self.original(value)
                self.config.write_bytes(before)
                with self.assertRaisesRegex(ValueError, 'realtime'):
                    self.migration.prepare()
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse(self.migration.receipt.exists())

    def test_removes_owned_http_realtime_override_from_actual_ocx_shape(self):
        self.config.write_bytes(self.original(self.endpoint))
        receipt = self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf' + self.keep)
        self.assertEqual(Path(receipt['backup']).read_bytes(), self.original(self.endpoint))

    def test_profile_realtime_override_is_rejected(self):
        before = self.original() + b'[profiles.other]\nexperimental_realtime_ws_base_url="ws://127.0.0.1:18888/v1"\n'
        self.config.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'realtime'):
            self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), before)

    def test_expected_pause_settings_rewrite_is_accepted(self):
        pause = self.control.set_enabled
        def rewriting(enabled):
            result = pause(enabled)
            settings = json.loads((self.state / 'settings.json').read_bytes())
            settings.update(installed=True, enabled=False, mode='opencodex')
            (self.state / 'settings.json').write_bytes(_encode(settings))
            return result
        # Alternate controller versions normalize request settings on pause.
        (self.state / 'settings.json').write_bytes(b'{"installed":true,"enabled":true,"mode":"opencodex","custom":7}')
        self.control.set_enabled = rewriting
        self.migration.prepare()
        settings = json.loads((self.state / 'settings.json').read_bytes())
        self.assertEqual(settings, {'installed': True, 'enabled': False, 'mode': 'native', 'custom': 7})

    def test_concurrent_settings_edit_during_pause_is_preserved(self):
        pause = self.control.set_enabled
        foreign = b'{"installed":true,"enabled":false,"mode":"opencodex","foreign":99}'
        def racing(enabled):
            result = pause(enabled)
            (self.state / 'settings.json').write_bytes(foreign)
            return result
        self.control.set_enabled = racing
        before = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'concurrently'):
            self.migration.prepare()
        self.assertEqual((self.state / 'settings.json').read_bytes(), foreign)
        self.assertEqual(self.config.read_bytes(), before)

    def test_concurrent_config_edit_during_pause_is_preserved(self):
        pause = self.control.set_enabled
        foreign = self.config.read_bytes() + b'# external edit\n'
        def racing(enabled):
            result = pause(enabled)
            self.config.write_bytes(foreign)
            return result
        self.control.set_enabled = racing
        with self.assertRaisesRegex(RuntimeError, 'concurrently'):
            self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), foreign)

    def test_prepare_resumes_after_lost_pause_reply(self):
        pause = self.control.set_enabled
        def lost(enabled):
            pause(enabled)
            raise RuntimeError('reply lost')
        self.control.set_enabled = lost
        with self.assertRaisesRegex(RuntimeError, 'reply lost'):
            self.migration.prepare()
        self.control.set_enabled = pause
        self.assertEqual(self.migration.prepare()['phase'], 'prepared')

    def test_prepare_resumes_after_final_receipt_write_is_lost(self):
        save = self.migration._save
        def lost(receipt):
            if receipt['phase'] == 'prepared':
                raise RuntimeError('receipt lost')
            save(receipt)
        self.migration._save = lost
        with self.assertRaisesRegex(RuntimeError, 'receipt lost'):
            self.migration.prepare()
        self.migration._save = save
        self.assertEqual(self.migration.prepare()['phase'], 'prepared')

    def test_connect_resumes_after_final_receipt_write_is_lost(self):
        self.migration.prepare()
        save = self.migration._save
        def lost(receipt):
            if receipt['phase'] == 'complete':
                raise RuntimeError('receipt lost')
            save(receipt)
        self.migration._save = lost
        with self.assertRaisesRegex(RuntimeError, 'receipt lost'):
            self.migration.connect()
        self.migration._save = save
        self.assertEqual(self.migration.connect()['phase'], 'complete')

    def test_corrupt_backup_rejects_connect_without_config_change(self):
        receipt = self.migration.prepare()
        Path(receipt['backup']).write_bytes(b'corrupt')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'backup'):
            self.migration.connect()
        self.assertEqual(self.config.read_bytes(), before)

    def test_prepare_without_installed_extension_needs_no_shim(self):
        self.control.receipt_file.unlink()
        self.bridge.value = None
        self.control.discovery = lambda: {'ready': True, 'routing_matches': True,
            'endpoint': self.endpoint, 'extension_enabled': None,
            'transform_protocol': None, 'control_protocol': None}
        self.assertEqual(self.migration.prepare()['phase'], 'prepared')
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf' + self.keep)

    def test_unowned_extension_is_rejected(self):
        self.control.receipt_file.unlink()
        before = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'owned'):
            self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), before)

    def test_connect_resumes_after_owned_activation_is_paused_on_failure(self):
        self.migration.prepare()
        activate = self.native.set_enabled
        def not_ready(enabled):
            result = activate(enabled)
            return dict(result, backend_ready=False) if enabled else result
        self.native.set_enabled = not_ready
        with self.assertRaisesRegex(RuntimeError, 'ready'):
            self.migration.connect()
        self.native.set_enabled = activate
        self.assertEqual(self.migration.connect()['phase'], 'complete')

    def test_config_cas_rejects_last_moment_external_edit(self):
        replace = self.native._replace_config
        foreign = self.config.read_bytes() + b'# CAS race\n'
        def racing(before, after):
            self.config.write_bytes(foreign)
            replace(before, after)
        self.native._replace_config = racing
        with self.assertRaisesRegex(RuntimeError, 'concurrently'):
            self.migration.prepare()
        self.assertEqual(self.config.read_bytes(), foreign)

    def test_selected_external_profile_is_preserved_and_races_rejected(self):
        before = self.original().replace(b'# keep\r\n', b'profile="external"\r\n# keep\r\n')
        self.config.write_bytes(before)
        profile = self.home / 'external.config.toml'
        profile.write_bytes(b'# external profile\r\nmodel="gpt-6.1-sol"\r\nmodel_reasoning_effort="ultra"\r\n')
        raw = profile.read_bytes()
        self.migration.prepare()
        self.assertEqual(profile.read_bytes(), raw)
        profile.write_bytes(raw + b'# concurrent\n')
        with self.assertRaisesRegex(RuntimeError, 'changed concurrently'):
            self.migration.connect()
        self.assertEqual(profile.read_bytes(), raw + b'# concurrent\n')

    def test_prepared_config_settings_and_auth_edits_are_preserved(self):
        self.migration.prepare()
        for path in (self.config, self.state / 'settings.json', self.home / 'auth.json'):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                foreign = before + b' '
                path.write_bytes(foreign)
                with self.assertRaisesRegex(RuntimeError, 'changed concurrently'):
                    self.migration.connect()
                self.assertEqual(path.read_bytes(), foreign)
                path.write_bytes(before)
