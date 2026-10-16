[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'), [switch]$Plan, [switch]$Yes)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\Maintenance-Guard.ps1')
. (Join-Path $PSScriptRoot 'scripts\Startup-Ownership.ps1')
$taskRoot = Assert-BundleDirectory $BundleRoot
$taskResult = Get-Content -LiteralPath (Join-Path $taskRoot 'team-install-result.json') -Raw | ConvertFrom-Json
$taskBackupParent = Join-Path (Split-Path -Parent $taskRoot) 'CodexTokenSaver-Backups'
$taskBackup = Join-Path $taskBackupParent ('uninstalled-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'))
if ($Plan) {
    [pscustomobject]@{root=$taskRoot;backup=$taskBackup;restore_owned_integrations=[bool]$taskResult.integration;
        preserve='All installation data, histories and configuration backups';stop_processes=$false} | ConvertTo-Json
    exit 0
}
if (-not $Yes) {
    Write-Host 'Close Codex first. This restores owned integrations and removes startup. All bundle files will be preserved in a backup.'
    if ((Read-Host 'Type UNINSTALL to continue') -cne 'UNINSTALL') { Write-Host 'Cancelled.'; exit 0 }
}
if ($taskResult.integration) {
    # The existing disable path validates ownership, backs up settings, restores
    # the route and disables startup BEFORE any workers/files can be removed.
    & (Join-Path $taskRoot 'Disable-Token-Saver.ps1') -BundleRoot $taskRoot
    if (-not $?) { throw 'Integration recovery failed. Installation and startup recovery data were preserved.' }
}
Assert-BundleIdle $taskRoot
if ($taskResult.integration) {
    & (Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe') (Join-Path $taskRoot 'unregister_install.py') $taskRoot
    if ($LASTEXITCODE -ne 0) { throw 'Owned integration removal failed. Installation was preserved.' }
}
# Do not move a folder while an updater is committing a transaction.
[void](New-Item -ItemType Directory -Path (Join-Path $taskRoot 'updates') -Force)
[void](New-Item -ItemType Directory -Path (Join-Path $taskRoot 'backups') -Force)
$taskLock = [IO.File]::Open((Join-Path $taskRoot 'updates\operation.lock'), 'OpenOrCreate', 'ReadWrite', 'ReadWrite')
try { $taskLock.Lock(0,1) } catch { $taskLock.Dispose(); throw 'Another update is running. Retry when it finishes.' }
try {
    $taskScheduler = New-Object -ComObject 'Schedule.Service'
    $taskScheduler.Connect()
    $taskFolder = $taskScheduler.GetFolder('\')
    $taskOwnedTasks = @()
    foreach ($taskSpec in @(@('Codex Token Saver','tray'), @('Codex Token Saver Proxy','proxy'))) {
        $taskFound = @($taskFolder.GetTasks(1) | Where-Object Name -eq $taskSpec[0])
        if ($taskFound.Count) {
            if (-not (Test-BundleStartupTask $taskFound[0] $taskRoot $taskSpec[1])) { throw 'An unrelated startup task uses this name; it was preserved.' }
            $taskOwnedTasks += $taskFound[0]
        }
    }
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcuts = @()
    foreach ($taskLocation in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Startup'))) {
        $taskShortcut = Join-Path $taskLocation 'Codex Token Saver.lnk'
        if (Test-Path -LiteralPath $taskShortcut) {
            $taskLink = $taskShell.CreateShortcut($taskShortcut)
            $taskOwned = Test-BundleStartupAction $taskRoot 'tray' $taskLink.TargetPath $taskLink.Arguments $taskLink.WorkingDirectory
            if ($taskLocation -eq [Environment]::GetFolderPath('Programs') -and
                $taskLink.TargetPath -ieq (Join-Path $taskRoot 'bin\token-saver-tray.exe') -and
                $taskLink.Arguments -ceq '-OpenDashboard' -and $taskLink.WorkingDirectory.TrimEnd('\') -ieq $taskRoot) { $taskOwned = $true }
            if (-not $taskOwned) { throw 'An unrelated shortcut uses this name; it was preserved.' }
            $taskShortcuts += $taskShortcut
        }
    }
    $taskRegistry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexTokenSaver'
    if (Test-Path -LiteralPath $taskRegistry) {
        if ((Get-ItemProperty -LiteralPath $taskRegistry).InstallLocation -ine $taskRoot) { throw 'The Apps entry belongs to another installation; preserved.' }
    }
    # Validate resolved source and destination before the directory move.
    [void](New-Item -ItemType Directory -Path $taskBackupParent -Force)
    if ((Get-Item -LiteralPath $taskBackupParent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Backup folder must not be a link.' }
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($taskBackup))) -ine [IO.Path]::GetFullPath($taskBackupParent)) { throw 'Unsafe backup destination.' }
    foreach ($task in $taskOwnedTasks) { [IO.File]::WriteAllText((Join-Path $taskRoot ('backups\uninstall-' + $task.Name.Replace(' ','-') + '.xml')), [string]$task.Xml) }
    # No worker remains. Release the lock handle so Windows can move its folder.
    $taskLock.Dispose(); $taskLock = $null
    Set-Location -LiteralPath (Split-Path -Parent $taskRoot)
    Move-Item -LiteralPath $taskRoot -Destination $taskBackup -ErrorAction Stop
    foreach ($task in $taskOwnedTasks) { $taskFolder.DeleteTask($task.Name,0) }
    foreach ($taskShortcut in $taskShortcuts) { Remove-Item -LiteralPath $taskShortcut -ErrorAction Stop }
    if (Test-Path -LiteralPath $taskRegistry) { Remove-Item -LiteralPath $taskRegistry -ErrorAction Stop }
    Write-Host "Uninstalled. All files and recovery backups are retained at: $taskBackup"
    Write-Host 'After confirming Codex works normally, you can delete that backup yourself to reclaim disk space.'
} catch {
    if (Test-Path -LiteralPath $taskBackup) { Write-Host "Installation data was moved safely to $taskBackup. Windows entry cleanup did not finish; keep this path and the error for recovery." }
    throw
} finally { if ($null -ne $taskLock) { $taskLock.Dispose() } }
