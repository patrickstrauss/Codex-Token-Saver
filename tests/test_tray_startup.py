"""Run the hidden startup launcher and plan in an isolated Windows profile."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = Path(os.environ.get('WINDIR', r'C:\Windows'))
CSC = WINDOWS / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
POWERSHELL = WINDOWS / 'System32/WindowsPowerShell/v1.0/powershell.exe'


@unittest.skipUnless(os.name == 'nt', 'Windows startup')
class TrayStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Token Saver startup ภาษาไทย ')
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name).resolve()
        self.bundle = self.profile / 'CodexTokenSaver'
        (self.bundle / 'bin').mkdir(parents=True)
        self.launcher = self.bundle / 'bin/token-saver-tray.exe'
        self.env = dict(os.environ, USERPROFILE=str(self.profile))

    def test_hidden_launcher_has_no_console_preserves_working_directory_and_exit(self):
        source = ROOT / 'native/TrayLauncher.cs'
        self.assertTrue(source.exists(), 'Hidden tray launcher is missing')
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/out:' + str(self.launcher), str(source)],
                       check=True, capture_output=True)
        (self.bundle / 'Tray.ps1').write_text('''param([switch]$OpenDashboard)
Add-Type 'using System; using System.Runtime.InteropServices; public class ConsoleProbe { [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow(); }'
@{console=[ConsoleProbe]::GetConsoleWindow().ToInt64();open=[bool]$OpenDashboard;cwd=$PWD.Path;root=$PSScriptRoot} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'result.json')
exit 0
''', encoding='utf-8-sig')
        result = subprocess.run([str(self.launcher), '-OpenDashboard'], cwd=self.profile,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.bundle / 'result.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(data['console'], 0)
        self.assertTrue(data['open'])
        self.assertEqual(Path(data['cwd']), self.bundle)
        self.assertEqual(Path(data['root']), self.bundle)

    def test_unexpected_tray_exit_recovers_without_reopening_browser(self):
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/out:' + str(self.launcher),
                        str(ROOT / 'native/TrayLauncher.cs')], check=True, capture_output=True)
        (self.bundle / 'Tray.ps1').write_text('''param([switch]$OpenDashboard)
$counter = Join-Path $PSScriptRoot 'attempts.txt'
$attempts = if (Test-Path $counter) { [int](Get-Content $counter) } else { 0 }
($attempts + 1) | Set-Content $counter
[string][bool]$OpenDashboard | Add-Content (Join-Path $PSScriptRoot 'opened.txt')
if ($attempts -eq 0) { exit 37 }
exit 0
''', encoding='utf-8-sig')
        result = subprocess.run([str(self.launcher), '-OpenDashboard'], cwd=self.profile,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.bundle / 'attempts.txt').read_text().strip(), '2')
        self.assertEqual((self.bundle / 'opened.txt').read_text().splitlines(), ['True', 'False'])
        log = (self.bundle / 'logs/tray-launcher.log').read_text()
        self.assertIn('exit code 37', log)
        self.assertIn('Restarting tray', log)
        self.assertIn('exit code 0', log)

    def test_repeated_failures_are_bounded_and_report_original_exit_code(self):
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/out:' + str(self.launcher),
                        str(ROOT / 'native/TrayLauncher.cs')], check=True, capture_output=True)
        (self.bundle / 'Tray.ps1').write_text('''Add-Content (Join-Path $PSScriptRoot 'attempts.txt') 'attempt'
exit 37
''', encoding='utf-8-sig')
        result = subprocess.run([str(self.launcher)], cwd=self.profile, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(len((self.bundle / 'attempts.txt').read_text().splitlines()), 3)
        self.assertIn('Recovery limit reached', (self.bundle / 'logs/tray-launcher.log').read_text())

    def test_plan_is_readonly_single_hidden_least_privilege_logon_action(self):
        shutil.copy2(ROOT / 'Install-Startup.ps1', self.bundle)
        (self.bundle / 'Tray.ps1').write_text('# fixture')
        self.launcher.write_bytes(b'plan only')
        before = set(self.bundle.rglob('*'))
        # Guard the isolated test from old installers that silently ignore -Plan.
        runner = self.bundle / 'plan-test.ps1'
        runner.write_text('''$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot 'Install-Startup.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$null)
if ('Plan' -notin @($ast.ParamBlock.Parameters.Name.VariablePath.UserPath)) { throw 'Installer has no read-only plan.' }
function New-Object { param($ComObject) throw 'Plan attempted a Windows COM mutation.' }
& $path -Plan
''', encoding='utf-8-sig')
        before = set(self.bundle.rglob('*'))
        result = subprocess.run([str(POWERSHELL), '-NoProfile', '-File', str(runner)],
                                env=self.env, capture_output=True, text=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(Path(plan['action']), self.launcher)
        self.assertEqual(plan['arguments'], '')
        self.assertEqual(plan['task_name'], 'Codex Token Saver')
        self.assertEqual(plan['logon_type'], 3)
        self.assertEqual(plan['run_level'], 0)
        self.assertEqual(plan['restart_count'], 10)
        self.assertFalse(plan['startup_fallback'])
        self.assertEqual(set(self.bundle.rglob('*')), before)

    def test_migration_accepts_only_exact_owned_actions(self):
        helper = ROOT / 'scripts/Startup-Ownership.ps1'
        self.assertTrue(helper.exists(), 'Startup ownership validation is missing')
        runner = self.bundle / 'ownership-test.ps1'
        runner.write_text('''param($Helper)
. $Helper
$root = $PSScriptRoot
$ps = Join-Path $env:WINDIR 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'
$legacy = '-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $root 'Tray.ps1') + '"'
@(
    (Test-BundleStartupAction $root 'tray' $ps $legacy $root),
    (Test-BundleStartupAction $root 'tray' $ps ($legacy + ' -OpenDashboard') $root),
    (Test-BundleStartupAction $root 'tray' (Join-Path $root 'bin\\token-saver-tray.exe') '' $root),
    (Test-BundleStartupAction $root 'tray' (Join-Path $root 'other.exe') '' $root),
    (Test-BundleStartupAction $root 'proxy' (Join-Path $root 'headroom\\.venv\\Scripts\\pythonw.exe') ('"' + (Join-Path $root 'desktop_proxy_service.py') + '" run') $root),
    (Test-BundleStartupAction $root 'proxy' (Join-Path $root 'headroom\\.venv\\Scripts\\pythonw.exe') 'unrelated.py' $root),
    (Test-BundleStartupAction $root 'tray' $ps $legacy (Split-Path $root)),
    (Test-BundleStartupAction $root 'tray' $ps ($legacy + ' -File unrelated.ps1') $root)
) | ConvertTo-Json
''', encoding='utf-8-sig')
        result = subprocess.run([str(POWERSHELL), '-NoProfile', '-File', str(runner), str(helper)],
                                capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [True, False, True, False, True, False, False, False])

    def test_failed_migration_restores_task_xml_enabled_state_and_shortcut(self):
        for failure in ('readback', 'after-disable', 'after-remove', 'launch', 'unowned-shortcut'):
            with self.subTest(failure=failure):
                result = subprocess.run([str(POWERSHELL), '-NoProfile', '-File',
                    str(ROOT / 'tests/fixtures/startup-rollback.ps1'),
                    str(ROOT / 'scripts/Startup-Ownership.ps1'), str(self.bundle), failure],
                    capture_output=True, text=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertTrue(data['failed'])
                self.assertEqual(data['tray'], 'original-tray-xml')
                self.assertEqual(data['proxy'], 'original-proxy-xml')
                self.assertTrue(data['tray_enabled'])
                self.assertTrue(data['proxy_enabled'])
                self.assertEqual(data['shortcut'], 'original-shortcut-bytes')
                if failure == 'unowned-shortcut':
                    self.assertEqual(data['registrations'], 0)

    def test_migration_accepts_com_normalized_empty_arguments_and_durations(self):
        result = subprocess.run([str(POWERSHELL), '-NoProfile', '-File',
            str(ROOT / 'tests/fixtures/startup-rollback.ps1'),
            str(ROOT / 'scripts/Startup-Ownership.ps1'), str(self.bundle), 'normalized'],
            capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['failed'])
        self.assertEqual(data['tray'], 'replacement-tray-xml')
        self.assertFalse(data['proxy_enabled'])
        self.assertIsNone(data['shortcut'])


if __name__ == '__main__':
    unittest.main()
