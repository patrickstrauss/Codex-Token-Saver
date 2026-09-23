[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'), [switch]$Plan)
$ErrorActionPreference = 'Stop'
$taskConfigurationDisabled = $false
$taskOperationLock = $null
try {
    if (@(Get-Process -Name Codex -ErrorAction SilentlyContinue).Count -gt 0) {
        throw 'Close Codex completely, then run Disable-Token-Saver.cmd again. This command does not force Codex to close.'
    }
    $taskRoot = [IO.Path]::GetFullPath($BundleRoot).TrimEnd('\')
    $taskPython = Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
        throw 'The installation or its Python runtime is missing. Nothing was changed. Do not reinstall just to disable it. Follow the deleted-installation recovery steps in docs\PROCESS-RECOVERY.md from this package: disable only owned startup entries and stale bundle MCP registrations, and restore any owned Codex route before restarting Windows.'
    }
    foreach ($taskRequired in @('desktop_proxy_control.py', 'Tray.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskRoot $taskRequired) -PathType Leaf)) {
            throw 'The installed bundle is incomplete. Nothing was changed. Follow the deleted-installation recovery steps in docs\PROCESS-RECOVERY.md.'
        }
    }
    . (Join-Path $PSScriptRoot 'scripts\Startup-Ownership.ps1')
    . (Join-Path $PSScriptRoot 'scripts\Disable-Startup.ps1')
    $taskScheduler = New-Object -ComObject 'Schedule.Service'
    $taskScheduler.Connect()
    $taskFolder = $taskScheduler.GetFolder('\')
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'Codex Token Saver.lnk'
    $taskStartupPlan = Get-BundleDisableStartupPlan $taskFolder $taskRoot $taskShortcut $taskShell
    $taskArguments = @((Join-Path $PSScriptRoot 'disable_bundle.py'), '--root', $taskRoot)
    if ($Plan) { $taskArguments += '--plan' } else {
        # Interoperates with Python's existing msvcrt byte-range operation lock.
        $taskLockDirectory = Join-Path $taskRoot 'updates'
        [void](New-Item -ItemType Directory -Path $taskLockDirectory -Force)
        $taskOperationLock = [IO.File]::Open((Join-Path $taskLockDirectory 'operation.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try { $taskOperationLock.Lock(0, 1) } catch { throw 'Another bundle setup or update is running. Wait for it to finish, then retry disabling.' }
        $taskArguments += '--operation-lock-held'
    }
    $taskOutput = & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Codex integration recovery did not complete. Startup and running workers were left available; request compression may already be paused. Keep the error above for review.'
    }
    $taskIntegration = ($taskOutput -join "`n") | ConvertFrom-Json
    if ($Plan) {
        [pscustomobject]@{plan=$true;tasks=@($taskStartupPlan.tasks.name);shortcut=$taskShortcut;integrations=$taskIntegration} | ConvertTo-Json -Depth 6
        exit 0
    }
    if (-not $taskIntegration.integrations_disabled) { throw 'Integration disable result was incomplete; startup was preserved.' }
    $taskConfigurationDisabled = $true
    $taskStartup = Disable-BundleStartup $taskStartupPlan $taskRoot $taskIntegration.backup
    [pscustomobject]@{success=$true;integrations_disabled=$true;startup=$taskStartup;backup=$taskIntegration.backup;
        processes_stopped=$false;restart_windows_required=$true} | ConvertTo-Json -Depth 6
    Write-Host 'Codex Token Saver integrations and automatic startup are disabled.'
    Write-Host 'Save your work and restart Windows to stop existing Headroom/Python processes. This command does not stop processes or restart Windows.'
    Write-Host 'Installation files, history, models and backups were retained. Unrelated Codex settings and applications were preserved.'
} catch {
    Write-Error -ErrorAction Continue $_.Exception.Message
    if ($taskConfigurationDisabled) {
        Write-Host 'PARTIAL: Codex integrations are disabled, but Windows startup cleanup did not finish. Review Task Scheduler and the error above before relying on startup being disabled.'
    }
    exit 1
} finally {
    if ($null -ne $taskOperationLock) { $taskOperationLock.Dispose() }
}
