[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'), [switch]$Plan)
$ErrorActionPreference = 'Stop'
# This entry point runs from the extracted new release, never from a web response.
$taskPayload = Join-Path $PSScriptRoot 'payload'
if (-not (Test-Path -LiteralPath $taskPayload)) { throw 'Run Upgrade-App.cmd from the fully extracted NEW release.' }
. (Join-Path $taskPayload 'scripts\Maintenance-Guard.ps1')
$taskRoot = Assert-BundleDirectory $BundleRoot
if (-not $Plan) { Assert-BundleIdle $taskRoot }
$taskArgs = @((Join-Path $taskPayload 'packaging\source_upgrade.py'), '--root', $taskRoot, '--package', $PSScriptRoot)
if ($Plan) { $taskArgs += '--plan' }
& (Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe') @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'App upgrade failed. Keep the error and backup above; do not delete the installation.' }
if (-not $Plan) { Write-Host 'Source update validated. Runtimes and component choices were preserved. Reopen Codex Token Saver.' }
