[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'))
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $BundleRoot 'headroom\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The team Headroom runtime is missing. Finish installation first.' }
& $taskPython (Join-Path $PSScriptRoot 'repair_team_setup.py') --root $BundleRoot
if ($LASTEXITCODE -ne 0) { throw 'Repair stopped. Keep the error text; do not delete your installation.' }
Write-Host 'Repair complete. Select Restart / repair dashboard from the tray, then reopen Codex.'
Write-Host 'Review the shared command hook in Codex Settings > Hooks > Reload hooks > User.'
