"""Retained optional runtimes are confined, validated and reversible."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bundle_updates as updates
from component_runtime import runtime_path


class OptionalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.versions = patch.object(updates.BundleUpdater, '_current_versions', return_value={
            'rtk': '0.49.0', 'headroom': '0.40.0', 'serena': '1.7.0', 'laya': '0.3.22'})
        self.versions.start()
        self.addCleanup(self.versions.stop)
        self.manager = updates.BundleUpdater(self.root)

    def executable(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'MZfixture')
        return path

    def staging_runner(self, component, version, commands, fail=None, locked=None, frozen=None):
        self.executable('tools/uv.exe')
        self.executable('headroom/.venv/Scripts/python.exe')
        build = self.root / 'packaging/requirements-build.txt'
        build.parent.mkdir(exist_ok=True)
        build.write_text('setuptools==84.0.0 --hash=sha256:' + 'a' * 64 + '\n')
        package = {'serena': 'serena-agent', 'laya': 'laya'}[component]
        def run(arguments, *args, **kwargs):
            commands.append(arguments)
            operation = arguments[4] if 'pip' in arguments else ('venv' if 'venv' in arguments else 'probe')
            if operation == 'install' and str(build) in arguments:
                operation = 'build'
            if operation == fail:
                raise updates.UpdateError('fixture ' + operation + ' failed')
            if operation == 'venv':
                python = Path(arguments[-1]) / 'Scripts/python.exe'
                python.parent.mkdir(parents=True)
                python.write_bytes(b'MZcandidate')
            elif operation == 'compile':
                Path(arguments[arguments.index('--output-file') + 1]).write_text(
                    locked if locked is not None else package + '==' + version + ' \\\n    --hash=sha256:' + 'b' * 64 + '\n')
            elif operation == 'freeze':
                return frozen if frozen is not None else package + '==' + version + '\n'
            return ''
        return run

    def test_retired_libraries_are_removed_from_persisted_offers_and_plans(self):
        state = self.manager._read_state()
        state['components'].append({'id': 'langmem', 'current': '0.0.30'})
        state['plans'] = {'langmem': {'version': '0.0.31'}, 'llama_cpp': {'version': 'b11461'}}
        self.manager._write_state(state)
        self.assertEqual([row['id'] for row in self.manager.status()['components']], ['headroom', 'rtk', 'serena', 'laya'])
        self.assertEqual(self.manager._read_state()['plans'], {})
        for retired in ('langmem', 'llama_cpp'):
            with self.assertRaises(ValueError):
                self.manager.start('install', retired)

    def test_runtime_selector_rejects_escape_and_preserves_default(self):
        for component in ('serena', 'laya'):
            with self.subTest(component=component):
                expected = self.executable(component + '/.venv/Scripts/python.exe')
                self.assertEqual(runtime_path(self.root, component), expected)
                (self.root / component / 'runtime.json').write_text(json.dumps({
                    'schema_version': 1, 'version': '1.8.0', 'python_path': '../outside.exe'}))
                with self.assertRaises(ValueError):
                    runtime_path(self.root, component)

    def test_official_checks_only_use_retained_python_packages(self):
        def metadata(url, limit):
            return b'{"info":{"version":"0.4.0"}}' if url == updates.OPTIONAL_PYPI['laya'] else b'{"info":{"version":"1.8.0"}}'
        with patch.object(updates, 'fetch_bytes', side_effect=metadata):
            self.assertEqual(self.manager._check_serena()['version'], '1.8.0')
            self.assertEqual(self.manager._check_laya()['version'], '0.4.0')
        self.assertTrue(self.manager._can_install('laya', '0.4.0'))
        self.assertFalse(self.manager._can_install('laya', '0.4.0rc1'))

    def test_failed_candidate_validation_does_not_change_selection(self):
        path = self.executable('laya/runtimes/0.4.0-test/Scripts/python.exe')
        descriptor = {'schema_version': 1, 'version': '0.4.0', 'python_path': path.relative_to(self.root).as_posix()}
        with patch.object(self.manager, '_stage_optional_python', return_value=descriptor), \
             patch.object(self.manager, '_validate_optional', side_effect=updates.UpdateError('probe failed')):
            with self.assertRaises(updates.UpdateError):
                self.manager._install_optional('laya', {'version': '0.4.0'})
        self.assertFalse((self.root / 'laya/runtime.json').exists())

    def test_activation_and_validated_rollback_preserve_previous_runtime(self):
        for component, package, old_version, new_version in (
                ('serena', 'serena-agent', '1.7.0', '1.8.0'), ('laya', 'laya', '0.3.22', '0.4.0')):
            with self.subTest(component=component):
                old = self.executable(component + '/.venv/Scripts/python.exe')
                metadata = old.parent.parent / ('Lib/site-packages/' + package.replace('-', '_') + '-' + old_version + '.dist-info/METADATA')
                metadata.parent.mkdir(parents=True)
                metadata.write_text('Name: ' + package + '\nVersion: ' + old_version + '\n')
                new = self.executable(component + '/runtimes/' + new_version + '-test/Scripts/python.exe')
                descriptor = {'schema_version': 1, 'version': new_version, 'python_path': new.relative_to(self.root).as_posix()}
                if component == 'laya':
                    (self.root / 'packaging').mkdir(exist_ok=True)
                    (self.root / 'packaging/laya-model.json').write_text('{"revision":"fixture"}')
                    legacy_ready = self.root / 'laya/ready.json'
                    legacy_ready.write_text('{"version":"0.3.22","revision":"fixture","inference_verified":true}')
                    legacy_bytes = legacy_ready.read_bytes()
                self.manager._activate_optional(component, descriptor)
                self.assertEqual(runtime_path(self.root, component), new)
                with patch.object(self.manager, '_validate_optional') as validator:
                    self.manager._rollback_optional(component)
                    self.assertEqual(validator.call_args.args[0], component)
                self.assertEqual(runtime_path(self.root, component), old)
                if component == 'laya':
                    self.assertEqual(legacy_ready.read_bytes(), legacy_bytes)
                    self.assertEqual(json.loads((new.parent.parent / 'bundle-ready.json').read_text())['version'], new_version)
                    self.assertEqual(json.loads((old.parent.parent / 'bundle-ready.json').read_text())['version'], old_version)

    def test_laya_validation_requires_real_offline_inference(self):
        path = self.executable('laya/runtimes/0.4.0-test/Scripts/python.exe')
        descriptor = {'schema_version': 1, 'version': '0.4.0', 'python_path': path.relative_to(self.root).as_posix()}
        for decision in ({'route': 'symbols', 'confidence': .9, 'truncated': False},
                         {'route': 'symbols', 'confidence': .1, 'truncated': False},
                         {'route': 'symbols', 'confidence': .9, 'truncated': True},
                         {'route': 'file_read', 'confidence': .9, 'truncated': False}):
            with self.subTest(decision=decision), patch.object(self.manager, '_run', side_effect=['0.4.0\n', json.dumps(decision)]) as runner:
                if decision['route'] == 'symbols' and decision['confidence'] >= .55 and not decision['truncated']:
                    self.manager._validate_optional('laya', descriptor)
                    self.assertIn('--probe', runner.call_args.args[0])
                    self.assertEqual(runner.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1')
                else:
                    with self.assertRaises(updates.UpdateError):
                        self.manager._validate_optional('laya', descriptor)

    def test_optional_staging_installs_candidate_hash_lock_with_only_serena_source_exception(self):
        for component, version, package in (('serena', '1.7.0', 'serena-agent'), ('laya', '0.4.0', 'laya')):
            with self.subTest(component=component):
                commands = []
                with patch.object(self.manager, '_run', side_effect=self.staging_runner(component, version, commands)):
                    descriptor = self.manager._stage_optional_python(component, {'version': version})
                python = self.root / descriptor['python_path']
                target = python.parent.parent
                self.assertTrue(any('compile' in command for command in commands))
                compile_command = next(command for command in commands if 'compile' in command)
                self.assertIn('--generate-hashes', compile_command)
                self.assertEqual(Path(compile_command[5]), target / 'requirements.in')
                inputs = (target / 'requirements.in').read_text().splitlines()
                self.assertEqual(inputs, [package + '==' + version, 'transformers<5'] if component == 'laya' else [package + '==' + version])
                lock = Path(compile_command[compile_command.index('--output-file') + 1])
                self.assertEqual(lock, target / 'requirements.txt')
                install = [command for command in commands if 'install' in command][-1]
                self.assertIn('--require-hashes', install)
                self.assertEqual(Path(install[install.index('-r') + 1]), lock)
                self.assertNotIn(package + '==' + version, install)
                for command in commands[1:]:
                    self.assertEqual(Path(command[command.index('--python') + 1]), python)
                    self.assertIn('--no-config', command)
                    self.assertIn('--no-python-downloads', command)
                for command in (compile_command, *[c for c in commands if 'install' in c]):
                    self.assertEqual(command[command.index('--index-url') + 1], 'https://pypi.org/simple')
                    self.assertNotIn('--extra-index-url', command)
                    self.assertEqual(command[command.index('--only-binary') + 1], ':all:')
                if component == 'serena':
                    build = commands[1]
                    self.assertIn('--require-hashes', build)
                    self.assertEqual(Path(build[build.index('-r') + 1]), self.root / 'packaging/requirements-build.txt')
                    self.assertLess(commands.index(build), commands.index(compile_command))
                    for command in (compile_command, install):
                        self.assertIn('--no-build-isolation', command)
                        self.assertEqual(command[command.index('--no-binary') + 1], 'proxy-tools')
                else:
                    for command in (compile_command, install):
                        self.assertNotIn('--no-binary', command)
                        self.assertNotIn('--no-build-isolation', command)
                receipt = json.loads((target / 'update-receipt.json').read_text())
                self.assertEqual(receipt['lock_sha256'], hashlib.sha256(lock.read_bytes()).hexdigest())
                self.assertFalse((self.root / component / 'runtime.json').exists())

    def test_optional_resolution_install_and_build_failures_preserve_loaded_runtime_selection(self):
        for component, version in (('serena', '1.7.0'), ('laya', '0.4.0')):
            for failure in ('compile', 'install', *(['build'] if component == 'serena' else [])):
                with self.subTest(component=component, failure=failure):
                    selected = self.executable(component + '/.venv/Scripts/python.exe')
                    manifest = self.root / component / 'runtime.json'
                    manifest.write_text(json.dumps({'schema_version': 1, 'version': version,
                                                    'python_path': selected.relative_to(self.root).as_posix()}))
                    original = manifest.read_bytes()
                    commands = []
                    with patch.object(self.manager, '_run', side_effect=self.staging_runner(component, version, commands, fail=failure)), \
                         patch.object(self.manager, '_validate_optional', side_effect=AssertionError('validation after failed stage')):
                        with self.assertRaisesRegex(updates.UpdateError, failure + ' failed'):
                            self.manager._install_optional(component, {'version': version})
                    self.assertEqual(manifest.read_bytes(), original)
                    self.assertEqual(selected.read_bytes(), b'MZfixture')
                    self.assertFalse(any('check' in command or 'freeze' in command for command in commands))
                    if failure == 'compile':
                        self.assertFalse(any('install' in command and 'requirements-build.txt' not in command[-1] for command in commands))

    def test_optional_lock_direct_sources_are_rejected_before_dependency_install(self):
        for locked in ('laya @ https://bad.invalid/laya.whl\n', '-e ../local-package\n'):
            with self.subTest(locked=locked):
                commands = []
                with patch.object(self.manager, '_run', side_effect=self.staging_runner('laya', '0.4.0', commands, locked=locked)):
                    with self.assertRaises(updates.UpdateError):
                        self.manager._install_optional('laya', {'version': '0.4.0'})
                self.assertFalse(any('install' in command for command in commands))
                self.assertFalse((self.root / 'laya/runtime.json').exists())

    def test_optional_freeze_direct_sources_still_block_activation(self):
        commands = []
        with patch.object(self.manager, '_run', side_effect=self.staging_runner(
                'laya', '0.4.0', commands, frozen='dependency @ https://bad.invalid/package.whl\n')):
            with self.assertRaises(updates.UpdateError):
                self.manager._install_optional('laya', {'version': '0.4.0'})
        self.assertFalse((self.root / 'laya/runtime.json').exists())

    def test_current_optional_core_can_refresh_compatible_dependencies(self):
        self.assertTrue(self.manager._can_install('serena', '1.7.0'))
        self.assertTrue(self.manager._can_install('laya', '0.3.22'))

    def test_updated_managed_python_is_preferred_without_global_discovery(self):
        baseline = self.executable('headroom/.venv/Scripts/python.exe')
        (self.root / 'packaging').mkdir()
        pins = self.root / 'packaging/dependencies.json'
        pins.write_text('{"python":"3.13.16"}')
        self.assertEqual(self.manager._baseline_python(), baseline)
        managed = self.executable('tools/python/cpython-3.13.16-windows-x86_64-none/python.exe')
        self.assertEqual(self.manager._baseline_python(), managed)
        pins.write_text('{"python":"../escape"}')
        self.assertEqual(self.manager._baseline_python(), baseline)


if __name__ == '__main__':
    unittest.main()
