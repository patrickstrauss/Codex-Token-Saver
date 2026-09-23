"""Setup transaction tests: no real downloads, services, startup, or API calls."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('request_setup', ROOT / 'scripts/setup_request_compression.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@contextmanager
def unlocked(path):
    yield True


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'proxy').mkdir()
        (self.root / 'proxy_runtime.py').write_text('test source', encoding='utf-8')
        self.config = self.root / 'config.toml'
        self.config.write_bytes(b'model="user-model"\nmodel_reasoning_effort="high"\n')
        self.auth = self.root / 'auth.json'
        self.auth.write_bytes(b'original authentication is never read by setup')
        self.settings = self.root / 'proxy/settings.json'
        self.validation = self.root / 'proxy/validation.json'
        self.status = {'enabled': False, 'route_enabled': False, 'installed': False,
                       'validated': False, 'ready': False, 'supervisor': {'live': False}}
        self.control = SimpleNamespace(config_file=self.config, settings_file=self.settings,
                                       status=Mock(side_effect=lambda: dict(self.status)))

        def atomic(path, data):
            path.write_bytes(data)

        self.api = SimpleNamespace(control=self.control, critical=('proxy_runtime.py',),
                                   atomic=Mock(side_effect=atomic), lock=unlocked, lifetime=unlocked,
                                   validate_runtime=Mock(return_value={'ok': True, 'request_invariants_preserved': True,
                                       'exact_retrieval_protected': True, 'compress_user_messages': False,
                                       'compress_system_messages': False, 'output_shaper': False,
                                       'effort_router': False, 'model_router': False, 'log_requests': False}),
                                   validate_model=Mock(return_value={'ok': True, 'model_ready': True,
                                       'exact_original_recovered': True, 'small_saving_recovered': True}),
                                   runtime={'runtime': 'test runtime'}, cleanup=Mock(return_value={'stopped': True}))
        self.process = Mock()
        self.mocks = {}
        for name, value in [('run_worker', None), ('start_supervisor', self.process),
                            ('wait_ready', {'ready': True, 'validated': True, 'supervisor': {'live': True}}),
                            ('install_startup', {'success': True}), ('check_ports', None)]:
            patcher = patch.object(setup, name, return_value=value)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def run_setup(self):
        return setup.setup(self.root, self.api)

    def assert_preserved(self):
        self.assertEqual(self.config.read_bytes(), b'model="user-model"\nmodel_reasoning_effort="high"\n')
        self.assertEqual(self.auth.read_bytes(), b'original authentication is never read by setup')

    def test_fresh_setup_validates_then_installs_paused_without_changing_codex(self):
        result = self.run_setup()
        self.assertTrue(result['ok'])
        self.assertFalse(result['enabled'])
        self.assertFalse(result['route_changed'])
        self.assertEqual(json.loads(self.settings.read_bytes()), {'installed': True, 'enabled': False})
        proof = json.loads(self.validation.read_bytes())
        self.assertEqual(proof['source_hashes'], setup.source_hashes(self.root, self.api.critical))
        self.assertTrue(proof['isolated_backend_verified'])
        self.assertFalse(proof['full_windows_reboot_tested'])
        self.assert_preserved()
        self.api.cleanup.assert_not_called()
        self.mocks['install_startup'].assert_called_once_with(self.root)
        self.assertEqual([call.args[1] for call in self.mocks['run_worker'].call_args_list],
                         ['--prefetch-worker', '--probe-worker'])
        for function in (self.api.validate_runtime, self.api.validate_model):
            state = function.call_args.args[1]
            self.assertFalse(state.exists())
            self.assertFalse(state.is_relative_to(self.root))

    def test_runtime_invariant_failure_does_not_install(self):
        self.api.validate_runtime.return_value['request_invariants_preserved'] = False
        with self.assertRaisesRegex(RuntimeError, 'exact retrieval validation failed'):
            self.run_setup()
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.validation.exists())
        self.mocks['start_supervisor'].assert_not_called()
        self.mocks['install_startup'].assert_not_called()
        self.assert_preserved()

    def test_model_exact_retrieval_failure_does_not_install(self):
        self.api.validate_model.return_value['small_saving_recovered'] = False
        with self.assertRaises(RuntimeError):
            self.run_setup()
        self.api.atomic.assert_not_called()

    def test_runtime_steering_or_logging_is_rejected(self):
        for key in ('compress_user_messages', 'compress_system_messages', 'output_shaper',
                    'effort_router', 'model_router', 'log_requests'):
            with self.subTest(key=key):
                self.api.validate_runtime.return_value[key] = True
                with self.assertRaises(RuntimeError):
                    self.run_setup()
                self.api.validate_runtime.return_value[key] = False
        self.api.atomic.assert_not_called()

    def test_isolated_backend_failure_does_not_install(self):
        self.mocks['run_worker'].side_effect = [None, RuntimeError('isolated probe failed')]
        with self.assertRaisesRegex(RuntimeError, 'isolated probe failed'):
            self.run_setup()
        self.api.atomic.assert_not_called()

    def test_failure_restores_prior_state_and_only_cleans_created_process(self):
        settings = b'{"installed": false, "enabled": false, "user_choice": 42}\n'
        validation = b'{"passed": false, "old": true}\n'
        self.settings.write_bytes(settings)
        self.validation.write_bytes(validation)
        self.mocks['install_startup'].side_effect = RuntimeError('startup rejected')
        with self.assertRaisesRegex(RuntimeError, 'startup rejected'):
            self.run_setup()
        self.assertEqual(self.settings.read_bytes(), settings)
        self.assertEqual(self.validation.read_bytes(), validation)
        self.api.cleanup.assert_called_once_with(self.process)
        self.assert_preserved()

    def test_fresh_failure_removes_only_own_new_metadata(self):
        self.mocks['wait_ready'].side_effect = RuntimeError('not ready')
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            self.run_setup()
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.validation.exists())
        self.api.cleanup.assert_called_once_with(self.process)

    def test_metadata_rollback_error_does_not_skip_process_cleanup(self):
        old = b'{"installed": false}'
        self.settings.write_bytes(old)

        def write(path, data):
            if data == old:
                raise OSError('test rollback failure')
            path.write_bytes(data)

        self.api.atomic.side_effect = write
        self.mocks['wait_ready'].side_effect = RuntimeError('not ready')
        with self.assertRaisesRegex(RuntimeError, 'Could not restore settings.json'):
            self.run_setup()
        self.api.cleanup.assert_called_once_with(self.process)

    def test_failure_preserves_concurrent_setting_edits(self):
        concurrent = b'{"installed": true, "enabled": false, "changed_elsewhere": true}'

        def fail(*args):
            self.settings.write_bytes(concurrent)
            raise RuntimeError('concurrent change')

        self.mocks['wait_ready'].side_effect = fail
        with self.assertRaises(RuntimeError):
            self.run_setup()
        self.assertEqual(self.settings.read_bytes(), concurrent)
        self.assertFalse(self.validation.exists())

    def test_existing_live_supervisor_is_not_replaced_or_stopped_on_failure(self):
        self.status['supervisor'] = {'live': True}
        self.mocks['install_startup'].side_effect = RuntimeError('startup rejected')
        with self.assertRaises(RuntimeError):
            self.run_setup()
        self.mocks['start_supervisor'].assert_not_called()
        self.mocks['check_ports'].assert_not_called()
        self.api.cleanup.assert_not_called()

    def test_enabled_validated_installation_is_a_noop_even_if_backend_is_temporarily_unready(self):
        self.status.update(enabled=True, validated=True, route_enabled=True)
        result = self.run_setup()
        self.assertTrue(result['already_configured'])
        self.assertTrue(result['enabled'])
        self.mocks['run_worker'].assert_not_called()
        self.api.atomic.assert_not_called()

    def test_enabled_unvalidated_installation_is_preserved(self):
        self.status['enabled'] = True
        with self.assertRaisesRegex(RuntimeError, 'was preserved'):
            self.run_setup()
        self.api.atomic.assert_not_called()

    def test_invalid_setting_types_are_preserved(self):
        before = b'{"installed": true, "enabled": "true"}'
        self.settings.write_bytes(before)
        with self.assertRaisesRegex(RuntimeError, 'settings changed or are invalid'):
            self.run_setup()
        self.assertEqual(self.settings.read_bytes(), before)
        self.api.atomic.assert_not_called()

    def test_unowned_local_route_is_preserved(self):
        self.status['route_enabled'] = True
        with self.assertRaisesRegex(RuntimeError, 'Restore Direct'):
            self.run_setup()
        self.mocks['run_worker'].assert_not_called()

    def test_source_change_during_probe_is_not_validated(self):
        def change(*args):
            if args[1] == '--probe-worker':
                (self.root / 'proxy_runtime.py').write_text('changed', encoding='utf-8')

        self.mocks['run_worker'].side_effect = change
        with self.assertRaisesRegex(RuntimeError, 'sources or Codex settings changed'):
            self.run_setup()
        self.api.atomic.assert_not_called()

    def test_occupied_port_is_not_adopted(self):
        self.mocks['check_ports'].side_effect = RuntimeError('already in use')
        with self.assertRaisesRegex(RuntimeError, 'already in use'):
            self.run_setup()
        self.api.atomic.assert_not_called()
        self.mocks['start_supervisor'].assert_not_called()


class EntryPointTests(unittest.TestCase):
    def test_helper_cannot_leave_artifact_imports_ahead_of_installed_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'helper.py').write_text(
                'import sys\nsys.path.insert(0, "artifact-first")\nROOT = "artifact"\n', encoding='utf-8')
            before = setup.sys.path[:]
            installed = directory / 'installed'
            with patch.object(setup, 'SCRIPT', directory / 'setup.py'):
                module = setup.helper('helper.py', installed)
            self.assertEqual(setup.sys.path, before)
            self.assertEqual(module.ROOT, installed)

    def test_prefetch_rebinds_all_managed_paths_to_the_installed_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / 'CodexTokenSaver'
            module = SimpleNamespace(main=Mock(), ROOT=Path('artifact'), MODEL_CACHE=Path('artifact/models'))
            with patch.object(setup.Path, 'home', return_value=home), \
                    patch.object(setup, 'load_api', return_value=Mock()) as load, \
                    patch.object(setup, 'helper', return_value=module) as helper:
                setup.main(['--bundle-root', str(root), '--prefetch-worker'])
            load.assert_called_once_with(root.resolve())
            helper.assert_called_once_with('prefetch_proxy_model.py', root.resolve())
            self.assertEqual(module.MODEL_CACHE, root.resolve() / 'models/huggingface')
            module.main.assert_called_once_with()

    def test_probe_uses_selected_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / 'CodexTokenSaver'
            module = SimpleNamespace(main=Mock())
            with patch.object(setup.Path, 'home', return_value=home), \
                    patch.object(setup, 'load_api', return_value=SimpleNamespace(runtime={'runtime': 'selected runtime'})), \
                    patch.object(setup, 'helper', return_value=module), patch.object(setup.sys, 'argv', ['setup']):
                setup.main(['--bundle-root', str(root), '--probe-worker'])
                self.assertEqual(setup.sys.argv[1:], ['--runtime', 'selected runtime'])
            module.main.assert_called_once_with()

    def test_other_bundle_location_is_rejected_before_import_or_mutation(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup, 'load_api') as load:
            with self.assertRaisesRegex(ValueError, 'USERPROFILE'):
                setup.main(['--bundle-root', temporary])
            load.assert_not_called()

    def test_worker_timeout_closes_its_owned_job(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('test worker', 2)
        close = Mock()
        with patch.object(setup.subprocess, 'Popen', return_value=process), \
                patch('local_summary_engine._windows_job', return_value=close):
            with self.assertRaises(subprocess.TimeoutExpired):
                setup.run_worker(ROOT, '--probe-worker', 2)
        close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
