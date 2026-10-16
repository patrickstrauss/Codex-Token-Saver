from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import windows_runtime


class WindowsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.previous = windows_runtime._handles
        windows_runtime._handles = []
        self.addCleanup(setattr, windows_runtime, '_handles', self.previous)

    def test_missing_private_runtime_is_actionable_for_installer(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(windows_runtime.sys, 'platform', 'win32'), patch.object(windows_runtime.sys, 'prefix', folder):
            windows_runtime.prepare_private_runtime()  # Preserve legacy installs.
            with self.assertRaisesRegex(RuntimeError, 'rerun this release installer'):
                windows_runtime.prepare_private_runtime(required=True)

    def test_private_search_handles_stay_alive_without_path_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Scripts').mkdir()
            (root / 'msvcp140.dll').touch()
            handles = [Mock(), Mock()]
            with patch.object(windows_runtime.sys, 'platform', 'win32'), patch.object(windows_runtime.sys, 'prefix', folder), patch.object(windows_runtime.os, 'add_dll_directory', create=True, side_effect=handles) as add, patch.dict(windows_runtime.os.environ, {'PATH': 'unchanged'}):
                windows_runtime.prepare_private_runtime(required=True)
                windows_runtime.prepare_private_runtime(required=True)
                self.assertEqual([call.args[0] for call in add.call_args_list], [str(root), str(root / 'Scripts')])
                self.assertEqual(windows_runtime._handles, handles)
                self.assertEqual(windows_runtime.os.environ['PATH'], 'unchanged')
                for handle in handles:
                    handle.close.assert_not_called()

    def test_non_windows_does_not_use_windows_loader(self):
        with patch.object(windows_runtime.sys, 'platform', 'linux'), patch.object(windows_runtime.os, 'add_dll_directory', create=True) as add:
            windows_runtime.prepare_private_runtime(required=True)
            add.assert_not_called()
