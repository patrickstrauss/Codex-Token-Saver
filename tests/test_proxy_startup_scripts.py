"""Execute startup planning and user recovery only in an isolated profile."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


@unittest.skipUnless(os.name == 'nt', 'Windows startup integration')
class ProxyStartupScriptsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'Install-ProxyStartup.ps1').is_file(), 'Proxy startup installer is missing')
        self.assertTrue((ROOT / 'Restore-Codex-Direct.ps1').is_file(), 'Direct recovery script is missing')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.profile = Path(self.folder.name)
        self.bundle = self.profile / 'CodexTokenSaver'
        self.bundle.mkdir()
        for name in ('Install-ProxyStartup.ps1', 'Install-Startup.ps1', 'Restore-Codex-Direct.ps1'):
            shutil.copy2(ROOT / name, self.bundle / name)
        for name in ('desktop_proxy_service.py', 'desktop_proxy_control.py'):
            (self.bundle / name).write_text('# isolated fixture\n')
        (self.bundle / 'Tray.ps1').write_text('# isolated fixture\n')
        (self.bundle / 'bin').mkdir()
        (self.bundle / 'bin/token-saver-tray.exe').write_bytes(b'plan fixture')
        runtime = self.bundle / 'headroom/.venv/Scripts'
        runtime.mkdir(parents=True)
        installed_venv = Path(sys.prefix)
        shutil.copy2(installed_venv / 'pyvenv.cfg', runtime.parent / 'pyvenv.cfg')
        for name in ('python.exe', 'pythonw.exe'):
            shutil.copy2(installed_venv / 'Scripts' / name, runtime / name)
        self.env = dict(os.environ, USERPROFILE=str(self.profile))

    def run_script(self, name, *args):
        return subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.bundle / name), *args],
                              env=self.env, capture_output=True, text=True, timeout=15,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def test_readonly_plan_has_stable_hidden_non_elevated_logon_action(self):
        before = set(self.bundle.rglob('*'))
        result = self.run_script('Install-ProxyStartup.ps1', '-Plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['task_name'], 'Codex Token Saver')
        self.assertEqual(Path(plan['action']).resolve(), (self.bundle / 'bin/token-saver-tray.exe').resolve())
        self.assertEqual(plan['arguments'], '')
        self.assertEqual(plan['logon_type'], 3)
        self.assertEqual(plan['run_level'], 0)
        self.assertEqual(plan['delay'], 'PT10S')
        self.assertEqual(plan['execution_time_limit'], 'PT0S')
        self.assertEqual(plan['restart_interval'], 'PT1M')
        self.assertEqual(plan['restart_count'], 10)
        self.assertFalse(plan['startup_fallback'])
        self.assertEqual(Path(plan['shortcut']).resolve(), (self.profile / 'AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Codex Token Saver - Restore Direct.lnk').resolve())
        self.assertEqual(set(self.bundle.rglob('*')), before)

    def test_wrong_install_location_is_rejected_without_writing_startup_state(self):
        self.env['USERPROFILE'] = str(self.profile / 'other')
        result = self.run_script('Install-ProxyStartup.ps1', '-Plan')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.bundle / 'proxy').exists())

    def test_restore_runs_only_the_owned_controller_pause_and_returns_restart_guidance(self):
        (self.bundle / 'desktop_proxy_control.py').write_text(
            'import json,pathlib,sys\n'
            'pathlib.Path(__file__).with_suffix(".args.json").write_text(json.dumps(sys.argv[1:]))\n'
            'print(json.dumps({"enabled":False,"route_enabled":False,"restart_required":True}))\n')
        result = self.run_script('Restore-Codex-Direct.ps1', '-Quiet')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['success'])
        self.assertIn('Restart Codex', data['message'])
        self.assertEqual(json.loads((self.bundle / 'desktop_proxy_control.args.json').read_text()), ['pause'])

    def test_restore_reports_owned_restoration_failure_without_claiming_success(self):
        (self.bundle / 'desktop_proxy_control.py').write_text(
            'import json\nprint(json.dumps({"error":"The endpoint was preserved."}))\nraise SystemExit(1)\n')
        result = self.run_script('Restore-Codex-Direct.ps1', '-Quiet')
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertFalse(data['success'])
        self.assertIn('preserved', data['message'])


if __name__ == '__main__':
    unittest.main()
