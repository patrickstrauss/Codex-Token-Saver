import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows startup recovery')
class DisableStartupTests(unittest.TestCase):
    def test_owned_startup_only_and_concurrent_changes(self):
        root = Path(__file__).resolve().parents[1]
        helper = root / 'scripts/Disable-Startup.ps1'
        self.assertTrue(helper.is_file(), 'Supported startup disable helper is missing')
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'exercise.ps1'
            script.write_text(r'''
param($Helper, $Work)
$ErrorActionPreference = 'Stop'
. $Helper
function Test-BundleStartupTask($Task, $Root, $Kind) { return $Task.Owned }
function Test-BundleStartupAction($Root, $Kind, $Target, $Arguments, $WorkingDirectory) { return $Target -eq 'owned' }
$root = Join-Path $Work 'bundle'
$backup = Join-Path $Work 'backup'
New-Item -ItemType Directory -Path $backup | Out-Null
$task = [pscustomobject]@{Name='Codex Token Saver'; Xml='before'; Enabled=$true; Owned=$true}
$other = [pscustomobject]@{Name='Other task'; Xml='other'; Enabled=$true; Owned=$false}
$folder = [pscustomobject]@{Tasks=@($task,$other)}
$folder | Add-Member ScriptMethod GetTasks { param($flags) return $this.Tasks }
$folder | Add-Member ScriptMethod GetTask { param($name) return $this.Tasks | Where-Object Name -eq $name }
$shortcut = Join-Path $Work 'Codex Token Saver.lnk'
$shell = [pscustomobject]@{}
$plan = Get-BundleDisableStartupPlan $folder $root $shortcut $shell
$result = Disable-BundleStartup $plan $root $backup
if ($task.Enabled -or -not $other.Enabled) { throw 'Incorrect task disabled' }
if ($result.disabled_tasks.Count -ne 1) { throw 'Expected one owned disabled task' }
$task.Enabled = $true
$plan = Get-BundleDisableStartupPlan $folder $root $shortcut $shell
$task.Xml = 'external change'
$blocked = $false
try { Disable-BundleStartup $plan $root $backup | Out-Null } catch { $blocked = $true }
if (-not $blocked -or -not $task.Enabled) { throw 'Concurrent task changed' }
$task.Owned = $false
$blocked = $false
try { Get-BundleDisableStartupPlan $folder $root $shortcut $shell | Out-Null } catch { $blocked = $true }
if (-not $blocked) { throw 'Unowned matching task accepted' }
Write-Output 'startup-disable-ok'
''', encoding='utf-8')
            completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                        '-File', str(script), str(helper), folder], capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn('startup-disable-ok', completed.stdout)


if __name__ == '__main__':
    unittest.main()
