[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'), [switch]$Plan, [switch]$Interactive)
$ErrorActionPreference = 'Stop'
$taskConfigurationDisabled = $false
$taskOperationLock = $null
$taskDialogMutex = $null
$taskOwnsDialogMutex = $false
$taskUiReady = $false
$taskUseUi = $Interactive -and -not $Plan

function Show-DisableDialog([string]$Message, [string]$Buttons = 'OK', [string]$Icon = 'Information') {
    $taskDefaultButton = if ($Buttons -eq 'OK') { [Windows.Forms.MessageBoxDefaultButton]::Button1 } else { [Windows.Forms.MessageBoxDefaultButton]::Button2 }
    return [Windows.Forms.MessageBox]::Show($Message, 'Disable Codex Token Saver',
        [Windows.Forms.MessageBoxButtons]::$Buttons, [Windows.Forms.MessageBoxIcon]::$Icon, $taskDefaultButton).ToString()
}

function Confirm-InteractiveDisable {
    $taskMessage = @'
Disable Codex Token Saver completely?

This turns off the bundle's Codex tools, automatic command hook and Windows startup, and restores its managed request connection.

Your files, original content, history, models and backups are retained.

Close Codex when prompted, then save your work and restart Windows yourself to stop existing processes. This window will not close apps or restart Windows.

Re-enabling the bundle later requires its setup/recovery steps.

Select OK to continue, or Cancel to make no changes.
'@
    if ((Show-DisableDialog $taskMessage 'OKCancel' 'Warning') -ne 'OK') { return $false }
    while (@(Get-Process -Name Codex -ErrorAction SilentlyContinue).Count -gt 0) {
        $taskChoice = Show-DisableDialog "Codex is still open. Nothing has been changed.`n`nClose Codex completely, then select Retry. Select Cancel to leave the bundle running." 'RetryCancel' 'Information'
        if ($taskChoice -ne 'Retry') { return $false }
    }
    return $true
}

function Invoke-InteractiveDisableHelper([string]$Python, [string[]]$HelperArguments) {
    $taskPreviousErrorAction = $ErrorActionPreference
    try {
        # Windows PowerShell represents native stderr as ErrorRecords. Collect
        # every line before deciding success, so a hidden window retains why it failed.
        $ErrorActionPreference = 'Continue'
        $taskLines = & $Python @HelperArguments 2>&1
        $taskNativeExitCode = $LASTEXITCODE
        return [pscustomobject]@{exit_code=$taskNativeExitCode;output=@($taskLines | ForEach-Object { [string]$_ })}
    } finally { $ErrorActionPreference = $taskPreviousErrorAction }
}

try {
    if ($taskUseUi) {
        $taskDialogCreated = $false
        $taskUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $taskDialogMutex = New-Object Threading.Mutex($true, ('Local\CodexTokenSaverDisable-' + $taskUserSid), [ref]$taskDialogCreated)
        if (-not $taskDialogCreated) { Write-Host 'The disable window is already open.'; exit 0 }
        $taskOwnsDialogMutex = $true
        Add-Type -AssemblyName System.Windows.Forms
        $taskUiReady = $true
        if (-not (Confirm-InteractiveDisable)) { Write-Host 'Cancelled. Nothing was changed.'; exit 0 }
    }
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
    $taskShortcut = Join-Path ([Environment]::GetFolderPath('Startup', 'DoNotVerify')) 'Codex Token Saver.lnk'
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
    if ($taskUseUi) {
        $taskCommand = Invoke-InteractiveDisableHelper $taskPython $taskArguments
        $taskOutput = $taskCommand.output
        $taskHelperExitCode = $taskCommand.exit_code
    } else {
        $taskOutput = & $taskPython @taskArguments
        $taskHelperExitCode = $LASTEXITCODE
    }
    if ($taskHelperExitCode -ne 0) {
        $taskHelperFailure = 'Codex integration recovery did not complete. Startup and running workers were left available; request compression may already be paused.'
        if ($taskUseUi) {
            $taskReason = [string]($taskOutput | Where-Object { $_.Trim() } | Select-Object -Last 1)
            if ($taskReason) { $taskHelperFailure += "`n`n" + $taskReason.Substring(0, [Math]::Min(1200, $taskReason.Length)) }
        } else { $taskHelperFailure += ' Keep the error above for review.' }
        throw $taskHelperFailure
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
    if ($taskUseUi) {
        if ($null -ne $taskOperationLock) { $taskOperationLock.Dispose(); $taskOperationLock = $null }
        [void](Show-DisableDialog ("Codex Token Saver integrations and automatic startup are disabled.`n`nSave your work, then restart Windows yourself to stop existing processes. Your files, history, models and backups were retained.`n`nBackup: " + $taskIntegration.backup + "`n`nRe-enabling requires the setup/recovery steps."))
    }
} catch {
    $taskFailure = $_.Exception.Message
    Write-Error -ErrorAction Continue $_.Exception.Message
    if ($taskConfigurationDisabled) {
        Write-Host 'PARTIAL: Codex integrations are disabled, but Windows startup cleanup did not finish. Review Task Scheduler and the error above before relying on startup being disabled.'
    }
    if ($taskUiReady) {
        if ($null -ne $taskOperationLock) { $taskOperationLock.Dispose(); $taskOperationLock = $null }
        $taskDetail = ($_ | Out-String)
        if ($taskOutput) { $taskDetail += "`n" + ($taskOutput | Out-String) }
        $taskLogPath = $null
        try {
            $taskLogFolder = if ($taskRoot -and (Test-Path -LiteralPath $taskRoot -PathType Container)) { Join-Path $taskRoot 'logs' } else { [IO.Path]::GetTempPath() }
            [void](New-Item -ItemType Directory -Path $taskLogFolder -Force)
            $taskLogPath = Join-Path $taskLogFolder ('token-saver-disable-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.log')
            $taskDetail | Set-Content -LiteralPath $taskLogPath -Encoding UTF8
        } catch { $taskLogPath = $null }
        $taskMessage = 'Disable did not complete.' + "`n`n" + $taskFailure
        if ($taskConfigurationDisabled) { $taskMessage += "`n`nPARTIAL: Codex integrations are disabled, but Windows startup cleanup did not finish." }
        if ($taskLogPath) { $taskMessage += "`n`nError details: " + $taskLogPath }
        $taskMessage += "`n`nRecovery guide: " + (Join-Path $PSScriptRoot 'docs\PROCESS-RECOVERY.md')
        [void](Show-DisableDialog $taskMessage 'OK' 'Error')
    }
    exit 1
} finally {
    if ($null -ne $taskOperationLock) { $taskOperationLock.Dispose() }
    if ($null -ne $taskDialogMutex) {
        if ($taskOwnsDialogMutex) { $taskDialogMutex.ReleaseMutex() }
        $taskDialogMutex.Dispose()
    }
}
