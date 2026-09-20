import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import desktop_proxy_control as module
except ImportError:
    module = None


class DesktopProxyControlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Desktop routing controller is missing')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.state = self.root / 'proxy'
        self.state.mkdir()
        self.config_home = self.root / 'codex-fixture'
        self.config_home.mkdir()
        self.config_file = self.config_home / 'config.toml'
        self.original = b'# Keep\r\nmodel="gpt-6-astra"\r\nmodel_reasoning_effort="ultra"\r\n[features]\r\nhooks=true\r\n'
        self.config_file.write_bytes(self.original)
        self.settings = self.state / 'settings.json'
        self.settings.write_text(json.dumps({'installed': True, 'enabled': False, 'upstream_mode': 'auto', 'custom': 9}))
        for name in module.CRITICAL_FILES:
            (self.root / name).write_text('fixture: ' + name)
        self.validate()
        self.control = module.DesktopProxyControl(self.root, config_home=self.config_home)
        self.gateway = {'service': 'codex-token-saver-proxy', 'status': 'ok', 'ready': True,
                        'backend_ready': True, 'requests': {'optimized': 3, 'direct': 1, 'failed': 0, 'active': 1}}
        self.backend = {'tokens': {'input': 300, 'output': 20, 'proxy_compression_saved': 40, 'saved': 999999},
                        'requests': {'total': 2}}
        self.control._fetch = Mock(side_effect=lambda url: self.backend if ':8789/' in url else self.gateway)

    def validate(self, age=0, overrides=None):
        value = {'passed': True, 'timestamp': (datetime.now(timezone.utc) - timedelta(days=age)).isoformat(),
                 'source_hashes': {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in module.CRITICAL_FILES}}
        value.update(overrides or {})
        (self.state / 'validation.json').write_text(json.dumps(value))

    def test_enable_and_pause_preserve_model_effort_comments_and_concurrent_edits(self):
        enabled = self.control.set_enabled(True)
        self.assertTrue(enabled['enabled'])
        self.assertTrue(enabled['route_enabled'])
        self.assertTrue(enabled['restart_required'])
        data = tomllib.loads(self.config_file.read_text())
        self.assertEqual(data['model'], 'gpt-6-astra')
        self.assertEqual(data['model_reasoning_effort'], 'ultra')
        self.assertNotIn('model_provider', data)
        self.assertTrue(self.config_file.read_bytes().endswith(self.original))
        later = b'\r\n[mcp_servers.user]\r\ncommand="keep"\r\n'
        self.config_file.write_bytes(self.config_file.read_bytes() + later)
        paused = self.control.set_enabled(False)
        self.assertFalse(paused['enabled'])
        self.assertFalse(paused['route_enabled'])
        self.assertEqual(self.config_file.read_bytes(), self.original + later)
        self.assertEqual(json.loads(self.settings.read_text())['custom'], 9)
        backups = list((self.state / 'backups').glob('config-*.toml'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_readonly_status_uses_only_independent_counters_and_creates_no_files(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        value = self.control.status()
        self.assertEqual(value['savings']['saved_tokens'], 40)
        self.assertEqual(value['savings']['requests'], 2)
        self.assertEqual(value['savings']['input_tokens'], 300)
        self.assertEqual(value['mode'], 'paused')
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_persisted_lifetime_takes_precedence_without_adding_session_or_cache(self):
        self.backend['persistent_savings'] = {'lifetime': {'tokens_saved': 123, 'requests': 7, 'total_input_tokens': 900},
            'recent_history': [{'timestamp': '2026-09-13T00:00:00Z', 'total_tokens_saved': 123}]}
        value = self.control.status()['savings']
        self.assertEqual(value['saved_tokens'], 123)
        self.assertEqual(value['input_tokens'], 900)
        self.assertEqual(value['requests'], 7)
        self.assertIsNone(value['output_tokens'])  # no mixing lifetime inputs with process-only output
        self.assertEqual(value['last_recorded_at'], '2026-09-13T00:00:00Z')

    def test_empty_backend_stats_are_unavailable_not_zero(self):
        self.backend = {}
        value = self.control.status()['savings']
        self.assertFalse(value['available'])
        self.assertIsNone(value['saved_tokens'])

    def test_offline_history_reads_only_the_dedicated_request_backend(self):
        self.control._fetch.side_effect = OSError('offline')
        old = self.root / 'headroom' / 'state'
        old.mkdir(parents=True)
        (old / 'proxy_savings.json').write_text(json.dumps({'lifetime': {'tokens_saved': 99999}}))
        self.assertFalse(self.control.status()['savings']['available'])
        new = self.state / 'backend-state'
        new.mkdir()
        (new / 'proxy_savings.json').write_text(json.dumps({'lifetime': {'tokens_saved': 77, 'requests': 3}}))
        value = self.control.status()['savings']
        self.assertTrue(value['historical'])
        self.assertEqual(value['saved_tokens'], 77)

    def test_status_exposes_no_raw_upstream_config_headers_or_request_logs(self):
        self.backend.update(config={'token': 'secret-fixture'}, request_logs=[{'body': 'private request'}])
        text = json.dumps(self.control.status())
        self.assertNotIn('secret-fixture', text)
        self.assertNotIn('private request', text)

    def test_another_routing_operation_prevents_mutation(self):
        with module.routing_lock(self.state / 'routing.lock'):
            with self.assertRaises(RuntimeError):
                self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_missing_or_wrong_service_does_not_claim_ready(self):
        self.gateway['service'] = 'unrelated'
        self.assertFalse(self.control.status()['ready'])
        with patch.object(module, 'WARMUP_SECONDS', .02), self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_missing_and_tampered_validation_block_enable(self):
        for mode in ('missing', 'tampered', 'future', 'partial'):
            self.validate()
            if mode == 'missing': (self.state / 'validation.json').unlink()
            if mode == 'tampered': (self.root / module.CRITICAL_FILES[0]).write_text('changed')
            if mode == 'future': self.validate(age=-1)
            if mode == 'partial': self.validate(overrides={'source_hashes': {}})
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                self.control.set_enabled(True)
            self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_changed_exact_retrieval_guard_invalidates_validation(self):
        helper = self.root / 'exact_retrieval.py'
        if not helper.exists():
            helper.write_text('# initial exact-retrieval guard\n')
        self.validate()
        self.assertTrue(self.control.validation())
        helper.write_text('# changed exact-retrieval guard\n')
        self.assertFalse(self.control.validation())

    def test_aged_validation_remains_valid_for_unchanged_tested_sources(self):
        self.validate(age=365)
        self.assertTrue(self.control.validation())
        self.assertTrue(self.control.set_enabled(True)['route_enabled'])

    def test_foreign_provider_url_and_profiles_are_never_overridden(self):
        configs = [b'model_provider="company"\n', b'openai_base_url="https://example.test"\n',
            b'openai_base_url="http://127.0.0.1:8788/v1"\n',
            b'[model_providers.openai]\nbase_url="https://example.test"\n',
            b'profile="work"\n[profiles.work]\nmodel_provider="company"\n',
            b'[profiles.work]\nopenai_base_url="https://example.test"\n']
        for raw in configs:
            self.config_file.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.control.set_enabled(True)
            self.assertEqual(self.config_file.read_bytes(), raw)
        self.config_file.write_bytes(b'profile="work"\n')
        (self.config_home / 'work.config.toml').write_text('model_provider="company"\n')
        with self.assertRaises(ValueError): self.control.set_enabled(True)

    def test_pause_works_without_validation_or_live_services(self):
        self.control.set_enabled(True)
        (self.state / 'validation.json').unlink()
        self.control._fetch.side_effect = OSError('offline')
        self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), self.original)
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])

    def test_pause_never_removes_user_replacement_endpoint(self):
        self.control.set_enabled(True)
        raw = self.config_file.read_bytes().replace(module.LOCAL_URL.encode(), b'https://user.example/v1')
        self.config_file.write_bytes(raw)
        self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), raw)

    def test_no_receipt_means_no_ownership_even_for_matching_endpoint(self):
        raw = b'openai_base_url="http://127.0.0.1:8788/v1"\n' + self.original
        self.config_file.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'is paused'): self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), raw)
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])

    def test_metadata_write_failure_never_enables_codex_route(self):
        real = module.atomic_write
        def fail(path, data):
            if Path(path).resolve() == self.settings.resolve(): raise OSError('disk failure')
            return real(path, data)
        with patch.object(module, 'atomic_write', side_effect=fail), self.assertRaises(OSError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_config_write_failure_preserves_config_and_restores_disabled_setting(self):
        with patch.object(self.control, '_replace_config', side_effect=OSError('disk failure')), self.assertRaises(OSError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])

    def test_concurrent_edit_before_replace_is_preserved(self):
        real = self.control._replace_config
        changed = self.original + b'# User edit\r\n'
        def race(before, after):
            self.config_file.write_bytes(changed)
            return real(before, after)
        with patch.object(self.control, '_replace_config', side_effect=race), self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), changed)

    def test_repeat_enable_does_not_replace_original_receipt_or_write_config(self):
        self.control.set_enabled(True)
        before = self.config_file.read_bytes()
        receipt = (self.state / 'route-receipt.json').read_bytes()
        self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), before)
        self.assertEqual((self.state / 'route-receipt.json').read_bytes(), receipt)
        self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_bom_multiline_strings_and_quoted_unrelated_keys_survive(self):
        original = b'\xef\xbb\xbfdescription="""\nopenai_base_url="inside text"\n"""\n["other"]\nopenai_base_url="keep"\n'
        self.config_file.write_bytes(original)
        self.control.set_enabled(True)
        self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_concurrent_settings_edit_during_health_check_is_not_overwritten(self):
        real = self.control.status
        changed = {'installed': True, 'enabled': False, 'upstream_mode': 'api', 'custom': 42}
        def concurrent_edit():
            self.settings.write_text(json.dumps(changed))
            return real()
        with patch.object(self.control, 'status', side_effect=concurrent_edit), self.assertRaisesRegex(RuntimeError, 'concurrently'):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)
        self.assertEqual(json.loads(self.settings.read_text()), changed)

    def test_validation_invalidated_during_status_blocks_enable(self):
        real = self.control.status
        def changed_validation():
            value = real()
            value['validated'] = False
            return value
        with patch.object(self.control, 'status', side_effect=changed_validation), self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])

    def test_source_change_after_metadata_write_blocks_config_commit_and_restores_pause(self):
        real = module.atomic_write
        def changed_source(path, data):
            real(path, data)
            if Path(path).resolve() == self.settings.resolve() and json.loads(data)['enabled']:
                (self.root / module.CRITICAL_FILES[0]).write_text('concurrently changed')
        with patch.object(module, 'atomic_write', side_effect=changed_source), self.assertRaises(RuntimeError):
            self.control.set_enabled(True)
        self.assertEqual(self.config_file.read_bytes(), self.original)
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])

    def test_pause_disables_optimization_when_config_or_receipt_is_corrupt(self):
        for corrupt in ('config', 'receipt'):
            self.validate()
            self.config_file.write_bytes(self.original)
            self.control.set_enabled(True)
            target = self.config_file if corrupt == 'config' else self.state / 'route-receipt.json'
            target.write_text('invalid {')
            saved_config = self.config_file.read_bytes()
            with self.subTest(corrupt=corrupt), self.assertRaisesRegex(RuntimeError, 'is paused'):
                self.control.set_enabled(False)
            self.assertFalse(json.loads(self.settings.read_text())['enabled'])
            self.assertEqual(self.config_file.read_bytes(), saved_config)
            if corrupt == 'receipt':
                target.unlink()

    def test_pause_config_write_failure_still_disables_optimization(self):
        self.control.set_enabled(True)
        before = self.config_file.read_bytes()
        with patch.object(self.control, '_replace_config', side_effect=OSError('private detail')), self.assertRaisesRegex(RuntimeError, 'is paused') as error:
            self.control.set_enabled(False)
        self.assertNotIn('private detail', str(error.exception))
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])
        self.assertEqual(self.config_file.read_bytes(), before)

    def test_unhealthy_backend_stats_are_not_claimed_as_live_savings(self):
        self.gateway['backend_ready'] = False
        value = self.control.status()
        self.assertFalse(value['backend_ready'])
        self.assertFalse(value['savings']['available'])

    def test_unicode_separator_inside_comment_is_preserved_on_pause(self):
        original = '# comment\u2028openai_base_url="comment text"\nmodel="gpt-6-astra"\n'.encode('utf-8')
        self.config_file.write_bytes(original)
        self.control.set_enabled(True)
        self.control.set_enabled(False)
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_enable_after_paused_boot_requests_supervisor_warmup_before_routing(self):
        observations = []
        def warming_service(url):
            enabled = json.loads(self.settings.read_text())['enabled']
            if not observations or observations[-1] != enabled:
                observations.append(enabled)
                self.assertEqual(self.config_file.read_bytes(), self.original)
            value = dict(self.gateway, backend_ready=enabled)
            return self.backend if ':8789/' in url else value
        self.control._fetch.side_effect = warming_service
        result = self.control.set_enabled(True)
        self.assertEqual(observations, [False, True])
        self.assertTrue(result['route_enabled'])
        self.assertTrue(result['backend_ready'])

    def test_failed_warmup_restores_pause_without_changing_codex_configuration(self):
        self.gateway['backend_ready'] = False
        writes = []
        real = module.atomic_write
        def record_settings(path, data):
            if Path(path).resolve() == self.settings.resolve():
                writes.append(json.loads(data)['enabled'])
            return real(path, data)
        with patch.object(module, 'WARMUP_SECONDS', .02, create=True), patch.object(module, 'atomic_write', side_effect=record_settings), self.assertRaisesRegex(RuntimeError, 'warm'):
            self.control.set_enabled(True)
        self.assertEqual(writes, [True, False])
        self.assertFalse(json.loads(self.settings.read_text())['enabled'])
        self.assertEqual(self.config_file.read_bytes(), self.original)

    def test_concurrent_settings_change_during_warmup_is_preserved(self):
        self.gateway['backend_ready'] = False
        real = self.control.status
        changed = {'installed': True, 'enabled': False, 'custom': 'concurrent user edit'}
        def changed_during_warmup():
            if json.loads(self.settings.read_text())['enabled']:
                self.settings.write_text(json.dumps(changed))
            return real()
        with patch.object(self.control, 'status', side_effect=changed_during_warmup), self.assertRaisesRegex(RuntimeError, 'concurrently'):
            self.control.set_enabled(True)
        self.assertEqual(json.loads(self.settings.read_text()), changed)
        self.assertEqual(self.config_file.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
