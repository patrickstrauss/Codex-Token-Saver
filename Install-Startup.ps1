[CmdletBinding()]
param([switch]$Start, [switch]$Plan)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$taskStableRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'CodexTokenSaver')).TrimEnd('\')
if ($taskRoot -ine $taskStableRoot) {
    throw "Run this installer from $taskStableRoot, through Explorer, after migration. No startup settings were changed."
}
$taskTrayPath = Join-Path $taskRoot 'Tray.ps1'
$taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $taskTrayPath -PathType Leaf)) {
    throw "Tray script is missing: $taskTrayPath"
}
$taskLauncher = Join-Path $taskRoot 'bin\token-saver-tray.exe'
if (-not (Test-Path -LiteralPath $taskLauncher -PathType Leaf)) { throw 'Build native\Build-TrayLauncher.ps1 before installing startup.' }
$taskArguments = ''
$taskPlan = [ordered]@{
    task_name = 'Codex Token Saver'; action = $taskLauncher; arguments = $taskArguments
    logon_type = 3; run_level = 0; delay = 'PT10S'; execution_time_limit = 'PT0S'
    restart_interval = 'PT1M'; restart_count = 10; startup_fallback = $false
    disable_owned_legacy_task = 'Codex Token Saver Proxy'; remove_owned_startup_shortcut = $true
}
if ($Plan) { $taskPlan | ConvertTo-Json; exit 0 }
. (Join-Path $taskRoot 'scripts\Startup-Ownership.ps1')
$taskBackupRoot = Join-Path $taskRoot 'backups\startup'
$taskResultPath = Join-Path $taskRoot 'install-startup-result.json'
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskResult = [ordered]@{
    timestamp = (Get-Date -Format o)
    root = $taskRoot
    user = $taskUser
    shortcuts = @()
    user_path = [ordered]@{
        updated = $false
        verified = $false
        bin = (Join-Path $taskRoot 'bin')
        backup = $null
        limitation = $null
    }
    scheduled_task = [ordered]@{
        name = 'Codex Token Saver'
        registered = $false
        started = $false
        start_requested = [bool]$Start
        limitation = $null
    }
    startup_fallback_available = $false
    errors = @()
    backups = @()
    retired_startup_entries = @()
}

function Get-BundlePathKey([string]$Entry) {
    try {
        $taskExpanded = [Environment]::ExpandEnvironmentVariables($Entry.Trim().Trim('"'))
        if (-not $taskExpanded) { return '' }
        return [IO.Path]::GetFullPath($taskExpanded).TrimEnd('\', '/').ToLowerInvariant()
    } catch { return '' }
}

function Convert-BundleUserPath([AllowEmptyString()][string]$Original, [string]$StableBin, [string[]]$OldBins) {
    $taskOwnedKeys = @($OldBins | ForEach-Object { Get-BundlePathKey $_ })
    $taskOwnedKeys += Get-BundlePathKey $StableBin
    $taskEntries = @()
    if ($Original) { $taskEntries = @($Original -split ';') }
    $taskUpdatedEntries = New-Object 'System.Collections.Generic.List[string]'
    $taskInserted = $false
    foreach ($taskEntry in $taskEntries) {
        if ((Get-BundlePathKey $taskEntry) -in $taskOwnedKeys) {
            if (-not $taskInserted) {
                $taskUpdatedEntries.Add($StableBin)
                $taskInserted = $true
            }
        } else {
            # Keep unrelated entries byte-for-byte, including variables and empty entries.
            $taskUpdatedEntries.Add($taskEntry)
        }
    }
    if (-not $taskInserted) { $taskUpdatedEntries.Add($StableBin) }
    return ($taskUpdatedEntries -join ';')
}

try {
    $taskStableBin = Join-Path $taskRoot 'bin'
    if (-not (Test-Path -LiteralPath (Join-Path $taskStableBin 'rtk.cmd') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $taskRoot 'tools\rtk.exe') -PathType Leaf)) {
        throw 'The migrated RTK launcher or executable is missing; user PATH was not changed.'
    }
    $taskOldBins = @(
        (Join-Path $env:LOCALAPPDATA 'CodexTokenSaver\bin'),
        (Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\CodexTokenSaver\bin')
    )
    $taskEnvironmentKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        $taskHadPath = $taskEnvironmentKey.GetValueNames() -contains 'Path'
        $taskPathKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        $taskOldPath = ''
        if ($taskHadPath) {
            $taskPathKind = $taskEnvironmentKey.GetValueKind('Path')
            if ($taskPathKind -notin @([Microsoft.Win32.RegistryValueKind]::String, [Microsoft.Win32.RegistryValueKind]::ExpandString)) {
                throw 'User PATH has an unexpected registry value type; it was not changed.'
            }
            $taskOldPath = [string]$taskEnvironmentKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        }
        $taskNewPath = Convert-BundleUserPath $taskOldPath $taskStableBin $taskOldBins
        if ($taskNewPath -cne $taskOldPath) {
            [void](New-Item -ItemType Directory -Path $taskBackupRoot -Force)
            $taskPathBackup = Join-Path $taskBackupRoot ('user-path-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.json')
            [pscustomobject]@{timestamp=(Get-Date -Format o);registry_key='HKEY_CURRENT_USER\Environment';name='Path';existed=$taskHadPath;kind=$taskPathKind.ToString();value=$taskOldPath} |
                ConvertTo-Json | Set-Content -LiteralPath $taskPathBackup -Encoding UTF8
            $taskResult.user_path.backup = $taskPathBackup
            $taskCurrentPath = [string]$taskEnvironmentKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($taskCurrentPath -cne $taskOldPath) { throw 'User PATH changed concurrently; retry the installer.' }
            $taskEnvironmentKey.SetValue('Path', $taskNewPath, $taskPathKind)
            $taskResult.user_path.updated = $true
        }
        $taskReadPath = [string]$taskEnvironmentKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $taskResult.user_path.verified = ($taskReadPath -ceq $taskNewPath)
        if (-not $taskResult.user_path.verified) { throw 'User PATH read-back did not match the requested value.' }
        $taskResult.user_path['registry_kind'] = $taskEnvironmentKey.GetValueKind('Path').ToString()
        $taskResult.user_path['applies_to'] = 'New processes after the next Windows sign-in; existing processes retain their environment.'
        if ($taskResult.user_path.updated) {
            try {
                if (-not ('CodexTokenSaver.EnvironmentChange' -as [type])) {
                    Add-Type -Namespace CodexTokenSaver -Name EnvironmentChange -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode, SetLastError = true)]
public static extern System.IntPtr SendMessageTimeoutW(System.IntPtr window, uint message, System.UIntPtr wParam, string lParam, uint flags, uint timeout, out System.UIntPtr result);
'@
                }
                $taskNotifyResult = [UIntPtr]::Zero
                $taskNotifyStatus = [CodexTokenSaver.EnvironmentChange]::SendMessageTimeoutW(
                    [IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, 'Environment', 2, 1000, [ref]$taskNotifyResult
                )
                $taskResult.user_path['environment_notification_sent'] = ($taskNotifyStatus -ne [IntPtr]::Zero)
                if ($taskNotifyStatus -ne [IntPtr]::Zero) {
                    $taskResult.user_path.applies_to = 'New processes launched from refreshed Explorer; existing applications retain their environment.'
                }
            } catch {
                $taskResult.user_path['notification_limitation'] = $_.Exception.Message
            }
        }
    } finally {
        $taskEnvironmentKey.Dispose()
    }
} catch {
    $taskResult.user_path.limitation = $_.Exception.Message
    $taskResult.errors += ('user-path: ' + $_.Exception.Message)
}

function Install-BundleShortcut([string]$Folder, [string]$Label, [bool]$OpenDashboard) {
    if (-not $Folder) { throw "Windows did not return the $Label folder." }
    [void](New-Item -ItemType Directory -Path $Folder -Force)
    $taskShortcutPath = Join-Path $Folder 'Codex Token Saver.lnk'
    $taskBackupPath = $null
    if (Test-Path -LiteralPath $taskShortcutPath) {
        [void](New-Item -ItemType Directory -Path $taskBackupRoot -Force)
        $taskBackupName = $Label + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.lnk'
        $taskBackupPath = Join-Path $taskBackupRoot $taskBackupName
        Copy-Item -LiteralPath $taskShortcutPath -Destination $taskBackupPath
    }
    $taskWsh = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskWsh.CreateShortcut($taskShortcutPath)
    $taskShortcut.TargetPath = $taskLauncher
    $taskShortcut.Arguments = $taskArguments
    if ($OpenDashboard) { $taskShortcut.Arguments = '-OpenDashboard' }
    $taskShortcut.WorkingDirectory = $taskRoot
    $taskShortcut.WindowStyle = 7
    $taskShortcut.Description = 'Codex Token Saver local tray and savings dashboard'
    $taskIcon = Join-Path $taskRoot 'token-saver.ico'
    if (Test-Path -LiteralPath $taskIcon -PathType Leaf) { $taskShortcut.IconLocation = $taskIcon }
    $taskShortcut.Save()
    $taskReadback = $taskWsh.CreateShortcut($taskShortcutPath)
    [pscustomobject]@{
        kind = $Label
        path = $taskShortcutPath
        exists = (Test-Path -LiteralPath $taskShortcutPath -PathType Leaf)
        resolved_path = (Resolve-Path -LiteralPath $taskShortcutPath).ProviderPath
        target = $taskReadback.TargetPath
        resolved_target = (Resolve-Path -LiteralPath $taskReadback.TargetPath).ProviderPath
        arguments = $taskReadback.Arguments
        working_directory = $taskReadback.WorkingDirectory
        window_style = $taskReadback.WindowStyle
        tray_path = $taskTrayPath
        tray_exists = (Test-Path -LiteralPath $taskTrayPath -PathType Leaf)
        backup = $taskBackupPath
    }
}

foreach ($taskShortcutSpec in @(
    @{ Folder = [Environment]::GetFolderPath('Programs', 'DoNotVerify'); Label = 'start-menu'; OpenDashboard = $true }
)) {
    try {
        $taskShortcutResult = Install-BundleShortcut @taskShortcutSpec
        $taskResult.shortcuts += $taskShortcutResult
    } catch {
        $taskResult.errors += ($taskShortcutSpec.Label + ': ' + $_.Exception.Message)
    }
}

try {
    $taskScheduler = New-Object -ComObject 'Schedule.Service'
    $taskScheduler.Connect()
    $taskSchedulerRoot = $taskScheduler.GetFolder('\')
    $taskDefinition = $taskScheduler.NewTask(0)
    $taskDefinition.RegistrationInfo.Description = 'Run the local Codex Token Saver tray at user logon.'
    $taskDefinition.RegistrationInfo.Author = $taskUser
    $taskDefinition.Principal.UserId = $taskUser
    $taskDefinition.Principal.LogonType = 3 # TASK_LOGON_INTERACTIVE_TOKEN; no password stored.
    $taskDefinition.Principal.RunLevel = 0 # TASK_RUNLEVEL_LUA; never elevate.
    $taskDefinition.Settings.Enabled = $true
    $taskDefinition.Settings.StartWhenAvailable = $true
    $taskDefinition.Settings.DisallowStartIfOnBatteries = $false
    $taskDefinition.Settings.StopIfGoingOnBatteries = $false
    $taskDefinition.Settings.ExecutionTimeLimit = 'PT0S'
    $taskDefinition.Settings.MultipleInstances = 2 # TASK_INSTANCES_IGNORE_NEW.
    $taskDefinition.Settings.RestartInterval = $taskPlan.restart_interval
    $taskDefinition.Settings.RestartCount = $taskPlan.restart_count
    $taskTrigger = $taskDefinition.Triggers.Create(9) # TASK_TRIGGER_LOGON.
    $taskTrigger.UserId = $taskUser
    $taskTrigger.Enabled = $true
    $taskTrigger.Delay = 'PT10S'
    $taskAction = $taskDefinition.Actions.Create(0) # TASK_ACTION_EXEC.
    $taskAction.Path = $taskLauncher
    $taskAction.Arguments = $taskArguments
    $taskAction.WorkingDirectory = $taskRoot
    $taskShell = New-Object -ComObject WScript.Shell
    $taskStartupShortcut = Join-Path ([Environment]::GetFolderPath('Startup', 'DoNotVerify')) 'Codex Token Saver.lnk'
    $taskMigration = Invoke-BundleStartupMigration $taskSchedulerRoot $taskDefinition $taskRoot $taskUser $taskStartupShortcut $taskShell $taskBackupRoot -Start:$Start
    $taskResult.scheduled_task = $taskMigration.scheduled_task
    $taskResult.backups += $taskMigration.backups
    $taskResult.retired_startup_entries = $taskMigration.retired_startup_entries
} catch {
    $taskResult.scheduled_task.limitation = $_.Exception.Message
    $taskResult.errors += ('scheduled-task: ' + $_.Exception.Message)
    # The migration helper rolls back touched tasks and the exact Startup shortcut.
}

$taskResult['success'] = [bool]($taskResult.scheduled_task.registered -and $taskResult.errors.Count -eq 0)
$taskResult | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskResultPath -Encoding UTF8
$taskResult | ConvertTo-Json -Depth 8
if (-not $taskResult.success) { exit 1 }
