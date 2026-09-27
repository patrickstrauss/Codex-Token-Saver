[CmdletBinding()]
param([switch]$Status)
$ErrorActionPreference = 'Stop'
$taskRoot = Join-Path $env:USERPROFILE 'CodexTokenSaver'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run Connect.cmd normally, not as administrator, so OpenCodex runs with your normal account permissions.'
}
if (-not $Status -and @(Get-Process -Name 'Codex' -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Close Codex fully before changing its connection.' }
$taskPython = Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'
$taskScript = Join-Path $taskRoot 'opencodex_migration.py'
if ($Status) {
    & $taskPython $taskScript status
} else {
    & $taskPython $taskScript connect --start
}
if ($LASTEXITCODE -ne 0) { throw 'Connection could not be verified. Keep this output and follow START-HERE.md; do not change provider URLs manually.' }
if (-not $Status) { Write-Output 'Handoff recorded. A warming result means the old worker is still draining. Restart Windows, open OpenCodex, then run Check.cmd before reopening Codex.' }
