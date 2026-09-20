"""Run the tray update function with a simulated API and no Windows UI."""
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows tray uses PowerShell')
def test_tray_desktop_counts_and_failure_clear_previous_status():
    tray = Path(__file__).resolve().parents[2] / 'Tray.ps1'
    script = r'''
$ErrorActionPreference = 'Stop'
$taskTokens = $null
$taskErrors = $null
$taskAst = [System.Management.Automation.Language.Parser]::ParseFile($env:TASK_TRAY_SOURCE, [ref]$taskTokens, [ref]$taskErrors)
if ($taskErrors.Count) { throw ($taskErrors | Out-String) }
$taskFunction = $taskAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Update-TrayStats'}, $true)
Invoke-Expression $taskFunction.Extent.Text
function Write-TrayStatus { param($Ready, $ErrorText, $Stats) }
function Write-TrayLog { param($Message) }
$script:taskFail = $false
function Invoke-RestMethod {
    param($Uri)
    if ($script:taskFail) { throw 'offline' }
    if ($Uri -like '*/api/request-proxy') {
        return [pscustomobject]@{mode='optimized';savings=[pscustomobject]@{available=$true;saved_tokens=456}}
    }
    return [pscustomobject]@{
        rtk = [pscustomobject]@{active=$true;total_saved=100}
        desktop_headroom = [pscustomobject]@{configured=$true;data_status='recorded';total_saved=-120;read_count=2;retrieve_count=1}
        headroom = [pscustomobject]@{active=$false;total_saved=234}
    }
}
$taskTray = [pscustomobject]@{Text=''}
$taskRtkItem = [pscustomobject]@{Text=''}
$taskDesktopHeadroomItem = [pscustomobject]@{Text=''}
$taskHeadroomItem = [pscustomobject]@{Text=''}
$taskRequestItem = [pscustomobject]@{Text=''}
$script:taskLastError = ''
Update-TrayStats
$taskRecorded = @{desktop=$taskDesktopHeadroomItem.Text;tooltip=$taskTray.Text;proxy=$taskHeadroomItem.Text;request=$taskRequestItem.Text}
$script:taskFail = $true
Update-TrayStats
@{recorded=$taskRecorded;failed=@{desktop=$taskDesktopHeadroomItem.Text;proxy=$taskHeadroomItem.Text;request=$taskRequestItem.Text}} | ConvertTo-Json -Depth 5 -Compress
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env={**os.environ, 'TASK_TRAY_SOURCE': str(tray)},
                            text=True, capture_output=True, check=True, timeout=15)
    states = json.loads(result.stdout)
    assert '-120' in states['recorded']['desktop']
    assert '2 reads' in states['recorded']['desktop']
    assert '1 retrieval' in states['recorded']['desktop']
    assert 'Headroom requests ~456' in states['recorded']['tooltip']
    assert '456' in states['recorded']['request']
    assert 'optimized' in states['recorded']['request']
    assert len(states['recorded']['tooltip']) <= 63
    assert 'CLI proxy' in states['recorded']['proxy']
    assert 'unavailable' in states['failed']['desktop']
    assert 'unavailable' in states['failed']['proxy']
    assert 'unavailable' in states['failed']['request']
