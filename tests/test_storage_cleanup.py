"""Storage reclamation must not remove active code, recovery data or shared caches."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import storage_cleanup as storage
from desktop_proxy_control import routing_lock


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file('packaging/dependencies.json', '{}')
        self.file('headroom/.venv/pyvenv.cfg', 'baseline')
        self.file('tools/uv.exe', 'fixture')
        self.workers = patch.object(storage, 'running_workers', return_value=[])
        self.workers.start()
        self.addCleanup(self.workers.stop)

    def file(self, relative, content='keep'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def runtime(self, parent, component, key, age=2 * storage.DAY):
        relative = f'{parent}/{component}-1.0.0-{key * 32}'
        self.file(relative + '/Scripts/python.exe')
        path = self.root / relative
        os.utime(path, (time.time() - age,) * 2)
        return relative

    def record(self, relative, value):
        return self.file(relative, json.dumps(value))

    def test_preview_then_apply_removes_only_old_unselected_generated_runtime(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        selected = self.runtime('updates/runtimes', 'headroom', 'b')
        previous = self.runtime('updates/runtimes', 'headroom', 'c')
        fresh = self.runtime('updates/runtimes', 'headroom', 'd', age=0)
        unknown = self.file('updates/runtimes/my-files/important.txt')
        self.record('updates/active.json', {'schema': 1, 'headroom': {'version': '1.0.0', 'runtime': selected},
                                          'headroom_previous': {'version': '1.0.0', 'runtime': previous}})
        preview = storage.cleanup(self.root)
        self.assertEqual([v['path'] for v in preview['artifacts']], [old])
        self.assertTrue((self.root / old).exists())
        result = storage.cleanup(self.root, apply=True)
        self.assertFalse((self.root / old).exists())
        for name in (selected, previous, fresh, 'headroom/.venv'):
            self.assertTrue((self.root / name).is_dir())
        self.assertTrue(unknown.is_file())
        self.assertGreater(result['logical_bytes_removed'], 0)

    def test_optional_current_and_rollback_survive(self):
        for component in ('serena', 'laya'):
            old = self.runtime(component + '/runtimes', component, 'a')
            current = self.runtime(component + '/runtimes', component, 'b')
            previous = self.runtime(component + '/runtimes', component, 'c')
            self.record(component + '/runtime.json', {'schema_version': 1, 'version': '1.0.0',
                'python_path': current + '/Scripts/python.exe',
                'previous': {'python_path': previous + '/Scripts/python.exe'}})
            storage.cleanup(self.root, apply=True)
            self.assertFalse((self.root / old).exists())
            self.assertTrue((self.root / current).is_dir())
            self.assertTrue((self.root / previous).is_dir())

    def test_older_baseline_worker_protects_unselected_imported_packages(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        self.record('updates/active.json', {'schema': 1})
        with patch.object(storage, 'running_workers', return_value=[{'started': 1, 'refs': []}]):
            result = storage.cleanup(self.root, apply=True)
        self.assertTrue(result['older_workers_preserved'])
        self.assertTrue((self.root / old).exists())

    def test_explicit_live_runtime_is_retained_case_insensitively(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        with patch.object(storage, 'running_workers', return_value=[{'started': time.time() + 10, 'refs': [old.upper()]}]):
            storage.cleanup(self.root, apply=True)
        self.assertTrue((self.root / old).exists())

    def test_missing_process_inspection_never_deletes(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        with patch.object(storage, 'running_workers', side_effect=subprocess.TimeoutExpired('CIM', 25)):
            result = storage.cleanup(self.root, apply=True)
        self.assertIn('skipped', result)
        self.assertTrue((self.root / old).exists())

    def test_bad_metadata_and_escape_fail_closed(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        for content in ('invalid', '[]', '{"schema":2}',
                        '{"schema":1,"headroom":{"runtime":"../outside"}}'):
            with self.subTest(content=content):
                self.file('updates/active.json', content)
                self.assertIn('skipped', storage.cleanup(self.root, apply=True))
                self.assertTrue((self.root / old).exists())

    def test_busy_update_lock_defers_every_mutation(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        with routing_lock(self.root / 'updates/operation.lock'):
            result = storage.cleanup(self.root, apply=True)
        self.assertIn('skipped', result)
        self.assertTrue((self.root / old).exists())

    def test_runtime_selected_between_preview_and_deletion_is_preserved(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        real_selection = storage._selection
        calls = []
        def selection(root):
            if calls:
                return {old.casefold()}, 0
            calls.append(True)
            return real_selection(root)
        with patch.object(storage, '_selection', side_effect=selection):
            storage.cleanup(self.root, apply=True)
        self.assertTrue((self.root / old).exists())

    def test_shared_caches_models_history_and_backups_are_untouched(self):
        protected = [self.file(name) for name in ('models/custom.bin', 'headroom/desktop-state/originals/abc',
                      'data/rtk/history.db', 'backups/user-backup', '.cache/huggingface/model',
                      'laya/model/model.safetensors', 'downloads/keep.zip')]
        storage.cleanup(self.root, apply=True)
        self.assertTrue(all(p.read_text() == 'keep' for p in protected))

    def test_private_cache_uses_locked_uv_prune_no_force_or_shared_path(self):
        (self.root / 'updates/cache').mkdir(parents=True)
        (self.root / 'downloads/uv-cache').mkdir(parents=True)
        with patch.object(storage.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = storage.cleanup(self.root, apply=True)
        self.assertEqual(len(result['caches']), 2)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertIn('--ci', argv)
            self.assertIn('--cache-dir', argv)
            self.assertNotIn('--force', argv)
            self.assertTrue(Path(argv[-1]).is_relative_to(self.root))
            self.assertEqual(call.kwargs['env']['UV_LOCK_TIMEOUT'], '1')

    def test_cache_busy_is_deferred_and_next_daily_pass_is_bounded(self):
        (self.root / 'updates/cache').mkdir(parents=True)
        with patch.object(storage.subprocess, 'run', side_effect=subprocess.TimeoutExpired('uv', 60)):
            result = storage.cleanup(self.root, apply=True)
        self.assertEqual(result['caches'][0]['status'], 'deferred')
        self.assertIn('skipped', storage.cleanup(self.root, apply=True, automatic=True))

    def test_unmanaged_directory_is_never_cleaned(self):
        (self.root / 'packaging/dependencies.json').unlink()
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        self.assertIn('skipped', storage.cleanup(self.root, apply=True))
        self.assertTrue((self.root / old).exists())

    def test_link_in_candidate_preserves_outside_files(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        outside = self.file('outside/keep.txt')
        try:
            (self.root / old / 'linked').symlink_to(outside.parent, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symbolic links is unavailable.')
        os.utime(self.root / old, (time.time() - 2 * storage.DAY,) * 2)
        result = storage.cleanup(self.root, apply=True)
        self.assertTrue(outside.is_file())
        self.assertTrue((self.root / old).is_dir())
        self.assertTrue(result['errors'])

    def test_legacy_fixture_requires_explicit_flag_and_real_fixture_markers(self):
        relative = 'updates/verification-bundle-20260913'
        self.file(relative + '/bundle_updates.py')
        self.file(relative + '/headroom/.venv/pyvenv.cfg')
        path = self.root / relative
        os.utime(path, (time.time() - 2 * storage.DAY,) * 2)
        self.assertEqual(storage.cleanup(self.root)['artifacts'], [])
        result = storage.cleanup(self.root, apply=True, legacy_tests=True)
        self.assertFalse(path.exists())
        self.assertEqual(result['artifacts'][0]['reason'], 'legacy_test_fixture')

    def test_failed_candidate_of_current_update_can_be_removed_without_waiting_a_day(self):
        fresh = self.runtime('updates/runtimes', 'headroom', 'a', age=0)
        unowned = self.file('data/user-file')
        result = storage.cleanup(self.root, apply=True, fresh_candidates={fresh, 'data'})
        self.assertFalse((self.root / fresh).exists())
        self.assertTrue(unowned.is_file())
        self.assertEqual(result['artifacts'][0]['path'], fresh)

    def test_selected_fresh_candidate_is_never_removed(self):
        fresh = self.runtime('updates/runtimes', 'headroom', 'a', age=0)
        self.record('updates/active.json', {'schema': 1, 'headroom': {'version': '1.0.0', 'runtime': fresh}})
        storage.cleanup(self.root, apply=True, fresh_candidates={fresh})
        self.assertTrue((self.root / fresh).exists())

    def test_older_worker_does_not_keep_unpublished_failed_candidate_forever(self):
        old = self.runtime('updates/runtimes', 'headroom', 'a')
        fresh = self.runtime('updates/runtimes', 'headroom', 'b', age=0)
        self.record('updates/active.json', {'schema': 1})
        with patch.object(storage, 'running_workers', return_value=[{'started': 1, 'refs': []}]):
            storage.cleanup(self.root, apply=True, fresh_candidates={fresh})
        self.assertFalse((self.root / fresh).exists())
        self.assertTrue((self.root / old).exists())

    def test_low_disk_update_stops_before_creating_a_runtime(self):
        from bundle_updates import BundleUpdater, UpdateError
        self.file('headroom/.venv/Scripts/python.exe')
        with patch.object(BundleUpdater, '_current_versions', return_value={}):
            updater = BundleUpdater(self.root)
        from collections import namedtuple
        usage = namedtuple('usage', 'total used free')(10 ** 10, 10 ** 10 - 1024, 1024)
        with patch('bundle_updates.shutil.disk_usage', return_value=usage):
            with self.assertRaisesRegex(UpdateError, 'Not enough free disk space'):
                updater._stage_headroom({'version': '1.0.0'})
        self.assertFalse((self.root / 'updates/runtimes').exists())


if __name__ == '__main__':
    unittest.main()
