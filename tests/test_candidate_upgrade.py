import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import candidate_upgrade as upgrade


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.root = self.base / 'installed'
        self.source.mkdir(); self.root.mkdir()
        (self.source / 'app.py').write_bytes(b'new')
        (self.root / 'app.py').write_bytes(b'old')
        (self.root / 'auth.json').write_bytes(b'private')
        self.entries = [{'path': 'app.py', 'sha256': upgrade.digest(self.source / 'app.py')}]

    def plan(self):
        return upgrade.prepare([(self.source, self.root, self.entries)], self.base / 'backup')

    def test_apply_and_rollback_preserve_unlisted_state(self):
        plan = self.plan()
        upgrade.apply(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'new')
        self.assertEqual((self.root / 'auth.json').read_bytes(), b'private')
        upgrade.rollback(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old')
        self.assertEqual((self.root / 'auth.json').read_bytes(), b'private')

    def test_preflight_rejects_modified_installation_without_writes(self):
        plan = self.plan()
        (self.root / 'app.py').write_bytes(b'user edit')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            upgrade.apply(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'user edit')

    def test_rejects_source_tampering(self):
        plan = self.plan()
        (self.source / 'app.py').write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            upgrade.apply(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old')

    def test_rollback_preserves_external_edit(self):
        plan = self.plan(); upgrade.apply(plan)
        (self.root / 'app.py').write_bytes(b'external')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            upgrade.rollback(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'external')

    def test_failed_second_write_rolls_back_first(self):
        (self.source / 'other.py').write_bytes(b'added')
        self.entries.append({'path': 'other.py', 'sha256': upgrade.digest(self.source / 'other.py')})
        plan = self.plan()
        original = upgrade.replace
        def fail(path, data):
            if Path(path).name == 'other.py':
                raise OSError('file locked')
            return original(path, data)
        with patch.object(upgrade, 'replace', side_effect=fail):
            with self.assertRaises(OSError):
                upgrade.apply(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old')
        self.assertFalse((self.root / 'other.py').exists())

    def test_rejects_traversal_absolute_paths_and_state_payloads(self):
        self.assertEqual(upgrade.safe_source_path('dashboard/LICENSE'), 'dashboard/LICENSE')
        for path in ('../escape.py', '/absolute.py', 'C:/absolute.py', 'proxy/settings.json', 'auth.json', 'headroom/.venv/app.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                upgrade.safe_source_path(path)

    def test_backup_corruption_blocks_rollback(self):
        plan = self.plan(); upgrade.apply(plan)
        (self.base / 'backup' / '0.original').write_bytes(b'damaged')
        with self.assertRaisesRegex(RuntimeError, 'backup'):
            upgrade.rollback(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'new')

    def test_duplicate_destinations_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            upgrade.prepare([(self.source, self.root, self.entries * 2)], self.base / 'backup')

    def test_abandoned_lock_file_does_not_block_recovery(self):
        plan = self.plan()
        (self.base / 'backup' / 'operation.lock').write_bytes(b'0')
        upgrade.apply(plan)
        upgrade.rollback(plan)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old')


if __name__ == '__main__':
    unittest.main()
