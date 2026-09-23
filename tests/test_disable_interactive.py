"""Exercise dialog decisions without performing recovery or changing Windows startup."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows interactive recovery')
class DisableInteractiveTests(unittest.TestCase):
    def run_powershell(self, script, **environment):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                env={**os.environ, **environment}, capture_output=True, text=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_cancel_retry_and_closed_codex_decisions(self):
        result = self.run_powershell(r'''
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:DISABLE_SOURCE,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Confirm-InteractiveDisable'},$true)
if (-not $function) { throw 'Interactive disable confirmation is missing' }
Invoke-Expression $function.Extent.Text
function Show-DisableDialog { param($Message,$Buttons,$Icon)
    $script:dialogs.Add(@{message=$Message;buttons=$Buttons;icon=$Icon})
    $result=$script:choices[$script:choiceIndex]; $script:choiceIndex++; return $result
}
function Get-Process { param($Name,$ErrorAction)
    if ($Name -cne 'Codex') { throw 'Unexpected process lookup' }
    $script:processChecks++
    if ($script:processChecks -le $script:runningChecks) { return [pscustomobject]@{Id=1} }
}
$all=@()
foreach ($case in @(
    @{choices=@('Cancel');running=10},
    @{choices=@('OK','Cancel');running=10},
    @{choices=@('OK','Retry');running=1},
    @{choices=@('OK');running=0}
)) {
    $script:dialogs=New-Object 'System.Collections.Generic.List[object]'
    $script:choices=$case.choices; $script:choiceIndex=0; $script:processChecks=0; $script:runningChecks=$case.running
    $accepted=Confirm-InteractiveDisable
    $all+=@{accepted=$accepted;checks=$script:processChecks;dialogs=@($script:dialogs.ToArray())}
}
ConvertTo-Json -InputObject @($all) -Depth 7 -Compress
''', DISABLE_SOURCE=str(ROOT / 'Disable-Token-Saver.ps1'))
        self.assertEqual([case['accepted'] for case in result], [False, False, True, True])
        self.assertEqual(result[0]['checks'], 0)
        self.assertEqual(result[1]['dialogs'][1]['buttons'], 'RetryCancel')
        self.assertEqual(result[2]['checks'], 2)
        text = result[0]['dialogs'][0]['message']
        for word in ('startup', 'Codex', 'history', 'restart Windows', 'setup'):
            self.assertIn(word, text)

    def test_tray_launches_only_fixed_disable_script_hidden(self):
        result = self.run_powershell(r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:TRAY_SOURCE,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-DisableBundle'},$true)
if (-not $function) { throw 'Tray disable launcher is missing' }
Invoke-Expression $function.Extent.Text
$taskRoot='C:\Test Bundle'
function Test-Path { param($LiteralPath,$PathType) return $true }
function Start-Process { param($FilePath,$ArgumentList,$WindowStyle)
    @{executable=$FilePath;arguments=$ArgumentList;window_style=$WindowStyle} | ConvertTo-Json -Compress
}
Start-DisableBundle
''', TRAY_SOURCE=str(ROOT / 'Tray.ps1'))
        self.assertEqual(result['window_style'], 'Hidden')
        self.assertEqual(result['executable'].lower(), str(Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe').lower())
        self.assertEqual(result['arguments'], '-NoProfile -STA -ExecutionPolicy Bypass -File "C:\\Test Bundle\\Disable-Token-Saver.ps1" -Interactive'.replace('\\\\', '\\'))

    def test_hidden_helper_keeps_native_stderr_and_exit_code(self):
        result = self.run_powershell(r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:DISABLE_SOURCE,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-InteractiveDisableHelper'},$true)
if (-not $function) { throw 'Interactive native error capture is missing' }
Invoke-Expression $function.Extent.Text
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('disable-error-fixture-' + [Guid]::NewGuid().ToString('N') + '.py')
try {
    [IO.File]::WriteAllText($fixture, 'import sys; print("fixture: foreign MCP registration", file=sys.stderr); sys.exit(7)')
    $result=Invoke-InteractiveDisableHelper $env:TEST_PYTHON @($fixture)
} finally { if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture } }
if ($ErrorActionPreference -ne 'Stop') { throw 'Caller error policy was changed' }
$result | ConvertTo-Json -Compress
''', DISABLE_SOURCE=str(ROOT / 'Disable-Token-Saver.ps1'), TEST_PYTHON=os.sys.executable)
        self.assertEqual(result['exit_code'], 7)
        self.assertIn('fixture: foreign MCP registration', '\n'.join(result['output']))

    @unittest.skipUnless(os.environ.get('TOKEN_SAVER_NATIVE_UI_TEST') == '1', 'Opt-in local native dialog test')
    def test_real_native_cancel_does_not_create_bundle_files(self):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        with tempfile.TemporaryDirectory(prefix='disable-ui-cancel-') as folder:
            target = Path(folder) / 'never-installed'
            process = subprocess.Popen(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                                        '-File', str(ROOT / 'Disable-Token-Saver.ps1'), '-Interactive', '-BundleRoot', str(target)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 12
                found = []
                @callback_type
                def visit(window, _):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    title = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(window, title, len(title))
                    if pid.value == process.pid and title.value == 'Disable Codex Token Saver':
                        found.append(window)
                    return True
                while not found and process.poll() is None and time.monotonic() < deadline:
                    user32.EnumWindows(visit, 0)
                    time.sleep(.05)
                self.assertTrue(found, 'Native confirmation did not appear')
                self.assertTrue(user32.PostMessageW(found[0], 0x0111, 2, 0))  # WM_COMMAND / IDCANCEL.
                output, errors = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 0, output + errors)
                self.assertFalse(target.exists(), 'Cancel created files in the target bundle')
            finally:
                if process.poll() is None:
                    process.terminate()  # Only this test's owned dialog process, never an installed worker.
                    process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
