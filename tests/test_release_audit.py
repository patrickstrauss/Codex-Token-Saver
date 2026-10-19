import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.check_release import ROOT_FILES, REQUIRED, audit


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'release.zip'
        self.payload = {name: b'# Document\n' for name in REQUIRED}
        self.payload['README.md'] = b'# Welcome\n[Install](docs/INSTALL.md#document)\n'

    def make_zip(self, *, payload=None, extra=None, corrupt=None, extra_entry=None):
        payload = payload if payload is not None else self.payload
        manifest = {'schema_version': 1, 'version': 'test', 'files': [
            {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}
            for name, raw in payload.items()]}
        files = {name: b'placeholder\n' for name in ROOT_FILES}
        files['package-manifest.json'] = json.dumps(manifest).encode()
        files.update({'payload/' + name: raw for name, raw in payload.items()})
        files.update(extra or {})
        if corrupt:
            files['payload/' + corrupt] = b'modified after signing\n'
        with ZipFile(self.path, 'w') as archive:
            for name, raw in files.items():
                archive.writestr('Codex-Token-Saver-test-windows-x64/' + name, raw)
            if extra_entry:
                archive.writestr(*extra_entry)
        return audit(self.path)

    def checks(self, result):
        return {item['check'] for item in result['issues']}

    def test_valid_source_release_and_anchors(self):
        result = self.make_zip()
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['package_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_hash_change_is_refused(self):
        self.assertIn('payload_checksum', self.checks(self.make_zip(corrupt='README.md')))

    def test_unmanifested_payload_is_refused(self):
        self.assertIn('manifest_payload_set', self.checks(self.make_zip(extra={'payload/new.py': b'x'})))

    def test_unexpected_top_level_file_is_refused(self):
        self.assertIn('outer_file_set', self.checks(self.make_zip(extra={'private.txt': b'x'})))

    def test_private_state_and_model_files_are_refused(self):
        for name in ('auth.json', '.env', 'headroom/desktop-state/activity.db',
                     'models/model.onnx', 'trace.log', '.git/config', 'node_modules/package.json'):
            with self.subTest(name=name):
                payload = {**self.payload, name: b'sensitive value must not appear in report'}
                result = self.make_zip(payload=payload)
                self.assertIn('private_or_runtime_file', self.checks(result))
                self.assertNotIn('sensitive value', json.dumps(result))

    def test_missing_contributor_document_is_refused(self):
        self.assertIn('required_document', self.checks(self.make_zip(
            payload={k: v for k, v in self.payload.items() if k != 'CONTRIBUTING.md'})))

    def test_installer_incompatible_hidden_root_file_is_refused(self):
        result = self.make_zip(payload={**self.payload, '.hidden-policy.toml': b'title = "Example"'})
        self.assertIn('installer_path_contract', self.checks(result))

    def test_broken_document_path_and_fragment_are_refused(self):
        for link, check in (('absent.md', 'missing_document_link'),
                            ('docs/INSTALL.md#missing', 'missing_document_anchor')):
            result = self.make_zip(payload={**self.payload, 'README.md': ('[Broken](' + link + ')').encode()})
            self.assertIn(check, self.checks(result))

    def test_fenced_examples_are_not_document_links(self):
        result = self.make_zip(payload={**self.payload, 'README.md': b'```md\n[Example](absent.md)\n```\n'})
        self.assertTrue(result['passed'], result)

    def test_personal_paths_are_redacted_and_examples_are_allowed(self):
        for user, passed in (('private-test-user', False), ('Example', True)):
            result = self.make_zip(payload={**self.payload, 'README.md': ('C:\\Users\\' + user + '\\file').encode()})
            self.assertEqual(result['passed'], passed)
            self.assertNotIn('private-test-user', json.dumps(result))

    def test_traversal_and_case_collisions_are_refused(self):
        for entry in ('../outside', 'Codex-Token-Saver-test-windows-x64/payload/readme.md'):
            result = self.make_zip(extra_entry=(entry, b'x'))
            self.assertIn('invalid_package', self.checks(result))
        self.assertFalse((Path(self.folder.name).parent / 'outside').exists())

    def test_invalid_zip_has_no_content_in_report(self):
        self.path.write_bytes(b'not a zip; private contents')
        result = audit(self.path)
        self.assertFalse(result['passed'])
        self.assertNotIn('private contents', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
