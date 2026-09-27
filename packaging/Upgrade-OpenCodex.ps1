[CmdletBinding()]
param([switch]$CheckOnly, [switch]$Rollback)
$ErrorActionPreference = 'Stop'
$taskRoot = Join-Path $env:USERPROFILE 'CodexTokenSaver'
$taskOcx = Join-Path $env:ProgramFiles 'OpenCodex'
$taskPackage = Join-Path $PSScriptRoot 'TokenSaver'
$taskPython = Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'
$taskTool = Join-Path $taskPackage 'payload\candidate_upgrade.py'
$taskPointer = Join-Path $taskRoot 'upgrade-backups\last-candidate.json'
if (-not (Test-Path -LiteralPath $taskPython) -or -not (Test-Path -LiteralPath (Join-Path $taskOcx 'ocx.exe'))) {
    throw 'This upgrade requires an existing full Token Saver installation and OpenCodex in Program Files.'
}
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskAdmin = (New-Object Security.Principal.WindowsPrincipal($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $CheckOnly -and -not $taskAdmin) { throw 'Run Upgrade.cmd as administrator under the same Windows account. Program Files requires elevation.' }
# Only inspect names. Never terminate a client or a listener.
$taskRunning = @(Get-Process -Name 'Codex','ocx','opencodex-desktop','token-saver-tray' -ErrorAction SilentlyContinue)
if ($taskRunning.Count -gt 0 -and -not $CheckOnly) {
    throw ('Close these apps fully before upgrading: ' + (($taskRunning.ProcessName | Sort-Object -Unique) -join ', '))
}
if ($CheckOnly) {
    Write-Output ('Existing installation found. Running apps: ' + (($taskRunning.ProcessName | Sort-Object -Unique) -join ', '))
    exit 0
}
if ($Rollback) {
    $taskSettings = Get-Content -LiteralPath (Join-Path $taskRoot 'proxy\settings.json') -Raw | ConvertFrom-Json
    $taskMigration = Join-Path $taskRoot 'proxy\migration-receipt.json'
    if ($taskSettings.mode -eq 'opencodex' -or (Test-Path -LiteralPath $taskMigration)) {
        throw 'A routing handoff has started. Use the recovery instructions before rolling source files back; active routes and retained originals must be preserved.'
    }
    $taskPrevious = Get-Content -LiteralPath $taskPointer -Raw | ConvertFrom-Json
    & $taskPython $taskTool rollback --backup $taskPrevious.backup
    if ($LASTEXITCODE -ne 0) { throw 'Source rollback refused; keep the backup and inspect its journal.' }
    Write-Output 'Source files restored. No client settings were changed.'
    exit 0
}
$taskBackup = Join-Path $taskRoot ('upgrade-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N'))
& $taskPython $taskTool upgrade --package $taskPackage --opencodex-package (Join-Path $PSScriptRoot 'OpenCodex') --bundle $taskRoot --opencodex $taskOcx --backup $taskBackup
if ($LASTEXITCODE -ne 0) { throw ('Upgrade did not complete. Inspect backup journal: ' + $taskBackup) }
[ordered]@{backup=$taskBackup;package=$taskPackage} | ConvertTo-Json | Set-Content -LiteralPath $taskPointer -Encoding UTF8
& $taskPython (Join-Path $taskRoot 'packaging\verify_install.py') $taskRoot
if ($LASTEXITCODE -ne 0) {
    & $taskPython $taskTool rollback --backup $taskBackup
    throw 'Installed runtime verification failed. Check the rollback result above before proceeding.'
}
Write-Output 'Source upgrade verified. Close this administrator window, run Connect.cmd normally, then restart Windows. See START-HERE.md.'
