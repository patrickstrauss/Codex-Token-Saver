import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import bundle_updates as updates
from component_runtime import component_descriptor, runtime_path


class OptionalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.versions = patch.object(updates.BundleUpdater, '_current_versions', return_value={
            'rtk': '0.49.0', 'headroom': '0.37.0', 'serena': '1.7.0',
            'langmem': '0.0.30', 'llama_cpp': 'b10809'})
        self.versions.start()
        self.addCleanup(self.versions.stop)
        self.manager = updates.BundleUpdater(self.root)

    def executable(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'MZfixture')
        return path

    def test_new_libraries_are_exposed_and_existing_status_is_migrated(self):
        state = self.manager._read_state()
        state['components'] = state['components'][:2]
        self.manager._write_state(state)
        ids = [x['id'] for x in self.manager.status()['components']]
        self.assertEqual(ids, ['headroom', 'rtk', 'serena', 'langmem', 'llama_cpp'])

    def test_runtime_selector_rejects_escape_and_preserves_default(self):
        expected = self.executable('local-compaction/.venv/Scripts/python.exe')
        self.assertEqual(runtime_path(self.root, 'langmem'), expected)
        (self.root / 'local-compaction/runtime.json').write_text(json.dumps({
            'schema_version': 1, 'version': '0.0.31', 'python_path': '../outside.exe'}))
        with self.assertRaises(ValueError):
            runtime_path(self.root, 'langmem')

    def test_official_llama_build_requires_matching_asset_and_digest(self):
        payload = [{'tag_name': 'b11060', 'prerelease': True, 'draft': False,
                    'assets': [{'name': 'llama-b11060-bin-win-vulkan-x64.zip',
                                'digest': 'sha256:' + 'a' * 64}]}]
        with patch.object(updates, 'fetch_bytes', return_value=json.dumps(payload).encode()):
            plan = self.manager._check_llama_cpp()
        self.assertEqual(plan['version'], 'b11060')
        payload[0]['assets'][0].pop('digest')
        with patch.object(updates, 'fetch_bytes', return_value=json.dumps(payload).encode()):
            with self.assertRaises(updates.UpdateError):
                self.manager._check_llama_cpp()

    def test_all_optional_official_checks_create_installable_version_plans(self):
        def metadata(url, limit):
            if url == updates.OPTIONAL_PYPI['serena']:
                return b'{"info":{"version":"1.8.0"}}'
            if url == updates.OPTIONAL_PYPI['langmem']:
                return b'{"info":{"version":"0.0.31"}}'
            raise AssertionError(url)
        with patch.object(updates, 'fetch_bytes', side_effect=metadata):
            self.assertEqual(self.manager._check_serena()['version'], '1.8.0')
            self.assertEqual(self.manager._check_langmem()['version'], '0.0.31')
        self.assertTrue(self.manager._can_install('llama_cpp', 'b11060'))
        self.assertFalse(self.manager._can_install('llama_cpp', 'b10000'))
        self.assertFalse(self.manager._can_install('langmem', '0.0.30rc1'))

    def test_failed_candidate_validation_does_not_change_selection(self):
        path = self.executable('serena/runtimes/1.8.0-test/Scripts/python.exe')
        descriptor = {'schema_version': 1, 'version': '1.8.0',
                      'python_path': path.relative_to(self.root).as_posix()}
        with patch.object(self.manager, '_stage_optional_python', return_value=descriptor), \
             patch.object(self.manager, '_validate_optional', side_effect=updates.UpdateError('probe failed')):
            with self.assertRaises(updates.UpdateError):
                self.manager._install_serena({'version': '1.8.0'})
        self.assertFalse((self.root / 'serena/runtime.json').exists())

    def test_activation_and_validated_rollback_preserve_previous_runtime(self):
        old = self.executable('local-compaction/.venv/Scripts/python.exe')
        metadata = old.parent.parent / 'Lib/site-packages/langmem-0.0.30.dist-info/METADATA'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('Name: langmem\nVersion: 0.0.30\n')
        new = self.executable('local-compaction/runtimes/langmem-0.0.31-test/Scripts/python.exe')
        descriptor = {'schema_version': 1, 'version': '0.0.31', 'python_path': new.relative_to(self.root).as_posix()}
        self.manager._activate_optional('langmem', descriptor)
        self.assertEqual(runtime_path(self.root, 'langmem'), new)
        with patch.object(self.manager, '_validate_optional') as validator:
            self.manager._rollback_langmem()
            self.assertEqual(validator.call_args.args[0], 'langmem')
        self.assertEqual(runtime_path(self.root, 'langmem'), old)

    def test_llama_archive_rejects_traversal_and_digest_mismatch(self):
        for name in ['../llama-server.exe', 'C:/llama-server.exe', 'link/../../llama-server.exe']:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, b'MZfixture')
            data = stream.getvalue()
            plan = {'version': 'b11060', 'sha256': hashlib.sha256(data).hexdigest()}
            with patch.object(updates, 'fetch_bytes', return_value=data):
                with self.assertRaises(updates.UpdateError):
                    self.manager._stage_llama(plan)
        with patch.object(updates, 'fetch_bytes', return_value=b'incorrect'):
            with self.assertRaises(updates.UpdateError):
                self.manager._stage_llama({'version': 'b11060', 'sha256': 'a' * 64})

    def test_llama_candidate_must_pass_real_model_smoke_before_selection(self):
        binary = self.executable('local-compaction/runtimes/llama-b11060-test/llama-server.exe')
        self.executable('local-compaction/.venv/Scripts/python.exe')
        (self.root / 'local-compaction/model.json').write_text('{"model_path":"existing.gguf"}')
        descriptor = {'version': 'b11060', 'binary_path': binary.relative_to(self.root).as_posix()}
        help_text = '--host --port --api-key --reasoning-budget --no-agent --no-webui --no-context-shift'
        with patch.object(self.manager, '_run', side_effect=['build 11060', help_text, '{"status":"failed"}']):
            with self.assertRaises(updates.UpdateError):
                self.manager._validate_optional('llama_cpp', descriptor)
        good = json.dumps({'status': 'summarized', 'model_unloaded': True, 'original_preserved': True,
                           'summary': 'NEVER_DELETE_BACKUPS; NATIVE_COMPACTION_ENABLED'})
        with patch.object(self.manager, '_run', side_effect=['build 11060', help_text, good]) as runner:
            self.manager._validate_optional('llama_cpp', descriptor)
            self.assertIn('--probe-candidate-llama', runner.call_args.args[0])
        self.assertFalse((self.root / 'local-compaction/llama-runtime.json').exists())

    def test_llama_archive_rejects_windows_device_names_and_normalized_aliases(self):
        for name in ('NUL', 'folder/CON.txt', 'LPT1.dll', 'file. ', 'folder./data'):
            with self.subTest(name=name):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    archive.writestr('llama-server.exe', b'MZfixture')
                    archive.writestr(name, b'data')
                data = stream.getvalue()
                with patch.object(updates, 'fetch_bytes', return_value=data):
                    with self.assertRaises(updates.UpdateError):
                        self.manager._stage_llama({'version': 'b11060', 'sha256': hashlib.sha256(data).hexdigest()})


if __name__ == '__main__':
    unittest.main()
