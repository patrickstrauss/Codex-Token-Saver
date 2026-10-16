import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import importlib.util

SPEC = importlib.util.spec_from_file_location('source_upgrade', Path(__file__).resolve().parents[1] / 'packaging/source_upgrade.py')
upgrade_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade_module)


class SourceUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.package = self.base / 'installed', self.base / 'release'
        self.root.mkdir()
        (self.root / 'packaging').mkdir()
        (self.root / 'settings').mkdir()
        (self.root / 'settings/user.json').write_bytes(b'private preferences')
        self.make_manifest(self.root, 'old', {'app.py': b'old', 'retired.py': b'old'}, 'packaging/installed-manifest.json')
        self.make_manifest(self.package / 'payload', 'new', {'app.py': b'new', 'new.py': b'new'}, '../package-manifest.json')

    def make_manifest(self, folder, version, files, name):
        folder.mkdir(parents=True, exist_ok=True)
        for path, data in files.items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(data)
        value = {'schema_version': 1, 'version': version, 'files': [
            {'path': p, 'sha256': hashlib.sha256(b).hexdigest()} for p, b in files.items()]}
        (folder / name).write_text(json.dumps(value))

    def test_success_preserves_data_and_backs_up_removed_source(self):
        result = upgrade_module.upgrade(self.root, self.package)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'new')
        self.assertFalse((self.root / 'retired.py').exists())
        self.assertEqual((self.root / 'settings/user.json').read_bytes(), b'private preferences')
        self.assertEqual((Path(result['backup']) / 'retired.py').read_bytes(), b'old')

    def test_failed_validation_rolls_back_added_removed_and_changed_files(self):
        with self.assertRaisesRegex(RuntimeError, 'probe failed'):
            upgrade_module.upgrade(self.root, self.package, validate=lambda _: (_ for _ in ()).throw(RuntimeError('probe failed')))
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old')
        self.assertEqual((self.root / 'retired.py').read_bytes(), b'old')
        self.assertFalse((self.root / 'new.py').exists())

    def test_tampered_payload_and_local_edits_are_preserved(self):
        (self.package / 'payload/app.py').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            upgrade_module.upgrade(self.root, self.package)
        (self.package / 'payload/app.py').write_bytes(b'new')
        (self.root / 'app.py').write_bytes(b'personal changes')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            upgrade_module.upgrade(self.root, self.package)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'personal changes')

    def test_plan_has_no_writes_and_unowned_file_blocks(self):
        self.assertTrue(upgrade_module.upgrade(self.root, self.package, plan=True)['plan'])
        self.assertFalse((self.root / 'backups').exists())
        (self.root / 'new.py').write_bytes(b'user data')
        with self.assertRaisesRegex(ValueError, 'Unowned'):
            upgrade_module.upgrade(self.root, self.package)

    def test_traversal_absolute_and_case_collisions_are_rejected(self):
        for name in ('../escape', 'C:/Windows/file', 'a/../b', '/absolute', 'a//b', 'a./b', 'CON', 'dir/LPT1.txt'):
            with self.assertRaises(ValueError):
                upgrade_module.checked_path(self.root, name)
        path = self.package / 'package-manifest.json'
        data = json.loads(path.read_text())
        data['files'].append(dict(data['files'][0], path='APP.py'))
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            upgrade_module.upgrade(self.root, self.package)

    def test_runtime_pin_changes_require_clean_reinstall(self):
        self.make_manifest(self.root, 'old', {'packaging/requirements-headroom.txt': b'old'}, 'packaging/installed-manifest.json')
        self.make_manifest(self.package / 'payload', 'new', {'packaging/requirements-headroom.txt': b'new'}, '../package-manifest.json')
        with self.assertRaisesRegex(ValueError, 'Runtime pins changed'):
            upgrade_module.upgrade(self.root, self.package)

    def test_added_and_removed_runtime_locks_also_require_reinstall(self):
        for old, new in (({}, {'packaging/requirements-native.txt': b'new'}),
                         ({'packaging/requirements-native.txt': b'old'}, {})):
            with self.subTest(added=bool(new)):
                self.make_manifest(self.root, 'old', {'app.py': b'old', **old}, 'packaging/installed-manifest.json')
                self.make_manifest(self.package / 'payload', 'new', {'app.py': b'new', **new}, '../package-manifest.json')
                with self.assertRaisesRegex(ValueError, 'Runtime pins changed'):
                    upgrade_module.upgrade(self.root, self.package, plan=True)


if __name__ == '__main__':
    unittest.main()
