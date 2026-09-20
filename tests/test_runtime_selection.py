"""Runtime updates are local, confined, and pinned before third-party imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='headroom-runtime-selection ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline = self.make_runtime('headroom/.venv', '0.37.0', 'baseline')
        self.first = self.make_runtime('updates/runtimes/headroom-1-one', '1.0.0', 'first')
        self.second = self.make_runtime('updates/runtimes/headroom-2-two', '2.0.0', 'second')
        self.manifest = self.root / 'updates/active.json'

    def make_runtime(self, relative, version, marker):
        runtime = self.root / relative
        site = runtime / 'Lib/site-packages'
        for package in ('headroom', 'mcp', 'tomlkit'):
            folder = site / package
            folder.mkdir(parents=True)
            (folder / '__init__.py').write_text('MARKER = ' + repr(marker) + '\n')
        metadata = site / ('headroom_ai-' + version + '.dist-info')
        metadata.mkdir()
        (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: headroom-ai\nVersion: ' + version + '\n')
        (runtime / 'pyvenv.cfg').write_text('version_info = 3.13\ninclude-system-site-packages = false\n')
        return runtime

    def activate_manifest(self, runtime=None, version='1.0.0'):
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        entry = None if runtime is None else {'runtime': str(runtime.relative_to(self.root)).replace('\\', '/'), 'version': version}
        self.manifest.write_text(json.dumps({'schema': 1, 'headroom': entry}))

    def select(self, **kwargs):
        from runtime_selection import selected_runtime
        return selected_runtime(self.root, python_version=(3, 13), **kwargs)

    def test_missing_manifest_and_explicit_null_keep_baseline(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.select()
        self.assertEqual(result['source'], 'baseline')
        self.assertEqual(result['version'], '0.37.0')
        self.assertIsNone(result['diagnostic'])
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.activate_manifest()
        self.assertEqual(self.select()['source'], 'baseline')

    def test_active_runtime_requires_matching_metadata_and_python(self):
        self.activate_manifest(self.first)
        result = self.select()
        self.assertEqual(result['source'], 'active')
        self.assertEqual(Path(result['runtime']), self.first.resolve())
        (self.first / 'pyvenv.cfg').write_text('version = 3.12.11\n')
        self.assertEqual(self.select()['source'], 'baseline')
        self.assertIsNotNone(self.select()['diagnostic'])

    def test_bad_manifests_and_unmanaged_paths_fall_back(self):
        entries = [
            {'schema': 2, 'headroom': None},
            {'schema': 1, 'headroom': {'runtime': '../elsewhere', 'version': '1.0.0'}},
            {'schema': 1, 'headroom': {'runtime': str(self.first), 'version': '1.0.0'}},
            {'schema': 1, 'headroom': {'runtime': 'https://example.invalid/runtime', 'version': '1.0.0'}},
            {'schema': 1, 'headroom': {'runtime': 'headroom/.venv', 'version': '0.37.0'}},
            {'schema': 1, 'headroom': {'runtime': 'updates/runtimes/missing', 'version': '1.0.0'}},
            {'schema': 1, 'headroom': {'runtime': 'updates/runtimes/headroom-1-one', 'version': '9.9.9'}},
            {'schema': 1, 'headroom': 'invalid'},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                self.manifest.write_text(json.dumps(entry))
                result = self.select()
                self.assertEqual(result['source'], 'baseline')
                self.assertIsNotNone(result['diagnostic'])
        self.manifest.write_text('{bad')
        self.assertEqual(self.select()['source'], 'baseline')

    def test_incomplete_candidate_does_not_replace_baseline(self):
        self.activate_manifest(self.first)
        (self.first / 'Lib/site-packages/mcp/__init__.py').unlink()
        result = self.select()
        self.assertEqual(result['source'], 'baseline')
        self.assertIsNotNone(result['diagnostic'])

    def test_candidate_interpreter_ignores_other_active_runtime(self):
        self.activate_manifest(self.second, '2.0.0')
        result = self.select(prefix=self.first)
        self.assertEqual(result['source'], 'candidate')
        self.assertEqual(Path(result['runtime']), self.first.resolve())

    def test_invalid_candidate_interpreter_keeps_own_packages_with_diagnostic(self):
        self.activate_manifest(self.second, '2.0.0')
        (self.first / 'Lib/site-packages/mcp/__init__.py').unlink()
        result = self.select(prefix=self.first)
        self.assertEqual(result['source'], 'candidate')
        self.assertEqual(Path(result['runtime']), self.first.resolve())
        self.assertIsNotNone(result['diagnostic'])

    def test_explicit_validation_override_does_not_activate_manifest(self):
        self.activate_manifest(self.second, '2.0.0')
        before = self.manifest.read_bytes()
        descriptor = {'runtime': 'updates/runtimes/headroom-1-one', 'version': '1.0.0'}
        result = self.select(candidate=descriptor)
        self.assertEqual(Path(result['runtime']), self.first.resolve())
        script = "import json,sys; from runtime_selection import activate_headroom_runtime; value=activate_headroom_runtime(sys.argv[1],candidate=" + repr(descriptor) + "); import headroom; print(json.dumps([value['source'],value['version'],headroom.MARKER]))"
        self.assertEqual(json.loads(self.run_python(script).stdout), ['active', '1.0.0', 'first'])
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_explicit_baseline_override_ignores_active_manifest(self):
        self.activate_manifest(self.first)
        before = self.manifest.read_bytes()
        result = self.select(candidate={'version': '0.37.0', 'runtime': None})
        self.assertEqual(result['source'], 'baseline')
        self.assertIsNone(result['diagnostic'])
        self.assertEqual(self.manifest.read_bytes(), before)
        result = self.select(candidate={'version': '0.99.0', 'runtime': None})
        self.assertIsNotNone(result['diagnostic'])

    def test_symlinked_runtime_outside_managed_directory_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'updates/runtimes/escaped'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating test symlinks is unavailable on this Windows account')
        self.manifest.write_text(json.dumps({'schema': 1, 'headroom': {'runtime': 'updates/runtimes/escaped', 'version': '1.0.0'}}))
        self.assertEqual(self.select()['source'], 'baseline')

    def run_python(self, source):
        environment = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, '-c', source, str(self.root)], env=environment,
                              capture_output=True, text=True, timeout=15, check=True)

    def test_process_pins_first_selection_but_fresh_process_sees_update(self):
        self.activate_manifest(self.first)
        script = '''
import json,sys
from pathlib import Path
from runtime_selection import activate_headroom_runtime
root=Path(sys.argv[1])
first=activate_headroom_runtime(root)
(root/'updates/active.json').write_text(json.dumps({'schema':1,'headroom':{'runtime':'updates/runtimes/headroom-2-two','version':'2.0.0'}}))
second=activate_headroom_runtime(root)
import headroom
print(json.dumps([first['version'],second['version'],headroom.MARKER]))
'''
        self.assertEqual(json.loads(self.run_python(script).stdout), ['1.0.0', '1.0.0', 'first'])
        fresh = self.run_python("import json,sys; from runtime_selection import activate_headroom_runtime; value=activate_headroom_runtime(sys.argv[1]); import headroom; print(json.dumps([value['version'],headroom.MARKER]))")
        self.assertEqual(json.loads(fresh.stdout), ['2.0.0', 'second'])

    def test_pth_paths_are_confined_and_executable_lines_are_not_run(self):
        self.activate_manifest(self.first)
        site = self.first / 'Lib/site-packages'
        (site / 'extra').mkdir()
        marker = self.root / 'pth-executed.txt'
        (site / 'local.pth').write_text("extra\n../../../../outside\nimport pathlib; pathlib.Path(" + repr(str(marker)) + ").touch()\n")
        output = self.run_python("import json,sys; from runtime_selection import activate_headroom_runtime; activate_headroom_runtime(sys.argv[1]); print(json.dumps(sys.path))")
        paths = json.loads(output.stdout)
        self.assertIn(str((site / 'extra').resolve()), paths)
        self.assertNotIn(str((self.root / 'outside').resolve()), paths)
        self.assertFalse(marker.exists())

    def test_already_imported_baseline_package_prevents_mixing(self):
        self.activate_manifest(self.first)
        script = '''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'headroom/.venv/Lib/site-packages'))
import headroom
from runtime_selection import activate_headroom_runtime
value=activate_headroom_runtime(root)
print(json.dumps([value['source'],headroom.MARKER,value['diagnostic']]))
'''
        result = json.loads(self.run_python(script).stdout)
        self.assertEqual(result[:2], ['baseline', 'baseline'])
        self.assertIsNotNone(result[2])

    def test_initialization_failure_restores_paths_shims_and_dll_handles(self):
        self.activate_manifest(self.first)
        script = '''
import json,sys,os,types
from runtime_selection import activate_headroom_runtime
import runtime_selection
old_paths=list(sys.path)
shims={name:types.ModuleType(name) for name in ('pywin32_bootstrap','pywin32_system32')}
sys.modules.update(shims)
handles=[]
class Handle:
    closed=False
    def close(self): self.closed=True
def add_dll(path):
    handle=Handle(); handles.append(handle); return handle
os.add_dll_directory=add_dll
def fail(): raise RuntimeError('Injected cache invalidation failure')
runtime_selection.importlib.invalidate_caches=fail
first=activate_headroom_runtime(sys.argv[1])
second=activate_headroom_runtime(sys.argv[1])
print(json.dumps([first['source'], bool(first['diagnostic']), second==first,
 sys.path==old_paths, all(sys.modules.get(k) is v for k,v in shims.items()),
 all(h.closed for h in handles), len(runtime_selection._dll_handles)]))
'''
        self.assertEqual(json.loads(self.run_python(script).stdout), ['baseline', True, True, True, True, True, 0])
