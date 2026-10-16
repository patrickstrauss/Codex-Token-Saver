[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'))
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $BundleRoot 'headroom\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The team Headroom runtime is missing. Finish installation first.' }
& $taskPython (Join-Path $PSScriptRoot 'repair_team_setup.py') --root $BundleRoot
if ($LASTEXITCODE -ne 0) { throw 'Repair stopped. Keep the error text; do not delete your installation.' }
$taskModeReceipt = Join-Path $BundleRoot 'team-install-result.json'
$taskNative = $true
if (Test-Path -LiteralPath $taskModeReceipt) {
    $taskMode = Get-Content -LiteralPath $taskModeReceipt -Raw | ConvertFrom-Json
    if ($taskMode.PSObject.Properties.Name -contains 'codex_integration') { $taskNative = [bool]$taskMode.codex_integration }
}
Write-Host 'Repair complete. Select Restart / repair dashboard from the tray.'
if ($taskNative) { Write-Host 'Reopen Codex and review the shared command hook in Settings > Hooks > Reload hooks > User.' }
else { Write-Host 'Review connected clients in Toolkit > Coding clients. Codex configuration was not changed.' }
