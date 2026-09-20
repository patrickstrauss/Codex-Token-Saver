param([switch]$Start, [switch]$Plan)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$taskStableRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'CodexTokenSaver')).TrimEnd('\')
if ($taskRoot -ine $taskStableRoot) {
    throw "Run this installer from $taskStableRoot. No startup settings were changed."
}
$taskService = Join-Path $taskRoot 'desktop_proxy_service.py'
$taskRestore = Join-Path $taskRoot 'Restore-Codex-Direct.ps1'
foreach ($taskRequired in @($taskService, $taskRestore, (Join-Path $taskRoot 'desktop_proxy_control.py'))) {
    if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) { throw 'A required proxy or recovery script is missing.' }
}
$taskPython = @(
    (Join-Path $taskRoot 'headroom\.venv\Scripts\pythonw.exe'),
    (Join-Path $taskRoot 'dashboard\.venv\Scripts\pythonw.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $taskPython) { throw 'No installed background Python runtime is available.' }
$taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskPrograms = Join-Path $env:USERPROFILE 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
$taskShortcutPath = Join-Path $taskPrograms 'Codex Token Saver - Restore Direct.lnk'
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskPlan = [ordered]@{
    task_name = 'Codex Token Saver Proxy'
    user = $taskUser
    root = $taskRoot
    action = $taskPython
    arguments = ('"' + $taskService + '" run')
    logon_type = 3
    run_level = 0
    delay = 'PT0S'
    execution_time_limit = 'PT0S'
    restart_interval = 'PT1M'
    restart_count = 10
    disallow_on_battery = $false
    stop_on_battery = $false
    shortcut = $taskShortcutPath
    shortcut_target = $taskPowerShell
    shortcut_arguments = ('-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $taskRestore + '"')
    start_requested = [bool]$Start
}
if ($Plan) { $taskPlan | ConvertTo-Json -Depth 5; exit 0 }

$taskBackupRoot = Join-Path $taskRoot 'backups\proxy-startup'
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'
$taskResult = [ordered]@{
    timestamp = (Get-Date -Format o)
    plan = $taskPlan
    task_registered = $false
    task_verified = $false
    task_started = $false
    shortcut_created = $false
    backups = @()
    errors = @()
}

try {
    $taskScheduler = New-Object -ComObject 'Schedule.Service'
    $taskScheduler.Connect()
    $taskSchedulerRoot = $taskScheduler.GetFolder('\')
    # Include hidden tasks and back up an existing exact name before replacing it.
    foreach ($taskExisting in $taskSchedulerRoot.GetTasks(1)) {
        if ($taskExisting.Name -ieq $taskPlan.task_name) {
            [void](New-Item -ItemType Directory -Path $taskBackupRoot -Force)
            $taskBackup = Join-Path $taskBackupRoot ('scheduled-task-' + $taskStamp + '.xml')
            [IO.File]::WriteAllText($taskBackup, [string]$taskExisting.Xml, (New-Object Text.UTF8Encoding($false)))
            $taskResult.backups += $taskBackup
            break
        }
    }
    $taskDefinition = $taskScheduler.NewTask(0)
    $taskDefinition.RegistrationInfo.Description = 'Keep the local Codex request relay available and supervise optional Headroom compression.'
    $taskDefinition.RegistrationInfo.Author = $taskUser
    $taskDefinition.Principal.UserId = $taskUser
    $taskDefinition.Principal.LogonType = $taskPlan.logon_type
    $taskDefinition.Principal.RunLevel = $taskPlan.run_level
    $taskDefinition.Settings.Enabled = $true
    $taskDefinition.Settings.StartWhenAvailable = $true
    $taskDefinition.Settings.DisallowStartIfOnBatteries = $taskPlan.disallow_on_battery
    $taskDefinition.Settings.StopIfGoingOnBatteries = $taskPlan.stop_on_battery
    $taskDefinition.Settings.RunOnlyIfIdle = $false
    $taskDefinition.Settings.RunOnlyIfNetworkAvailable = $false
    $taskDefinition.Settings.ExecutionTimeLimit = $taskPlan.execution_time_limit
    $taskDefinition.Settings.RestartInterval = $taskPlan.restart_interval
    $taskDefinition.Settings.RestartCount = $taskPlan.restart_count
    $taskDefinition.Settings.MultipleInstances = 2 # Ignore duplicate scheduled launches.
    $taskTrigger = $taskDefinition.Triggers.Create(9) # Current-user logon, no delay.
    $taskTrigger.UserId = $taskUser
    $taskTrigger.Enabled = $true
    $taskTrigger.Delay = $taskPlan.delay
    $taskAction = $taskDefinition.Actions.Create(0)
    $taskAction.Path = $taskPlan.action # pythonw stays attached to the supervisor until it exits.
    $taskAction.Arguments = $taskPlan.arguments
    $taskAction.WorkingDirectory = $taskRoot
    $taskRegistered = $taskSchedulerRoot.RegisterTaskDefinition(
        $taskPlan.task_name, $taskDefinition, 6, $taskUser, $null, 3, $null
    ) # Create/update with interactive token; no stored password or elevation.
    $taskResult.task_registered = $true
    $taskReadback = $taskRegistered.Definition
    $taskResult.task_verified = [bool](
        $taskReadback.Actions.Item(1).Path -ieq $taskPlan.action -and
        $taskReadback.Actions.Item(1).Arguments -ceq $taskPlan.arguments -and
        $taskReadback.Actions.Item(1).WorkingDirectory -ieq $taskRoot -and
        $taskReadback.Principal.LogonType -eq 3 -and $taskReadback.Principal.RunLevel -eq 0 -and
        $taskReadback.Settings.ExecutionTimeLimit -eq 'PT0S' -and
        $taskReadback.Settings.RestartInterval -eq 'PT1M' -and $taskReadback.Settings.RestartCount -eq 10 -and
        -not $taskReadback.Settings.DisallowStartIfOnBatteries -and -not $taskReadback.Settings.StopIfGoingOnBatteries
    )
    if (-not $taskResult.task_verified) { throw 'The registered task did not match its planned settings.' }

    [void](New-Item -ItemType Directory -Path $taskPrograms -Force)
    if (Test-Path -LiteralPath $taskShortcutPath -PathType Leaf) {
        [void](New-Item -ItemType Directory -Path $taskBackupRoot -Force)
        $taskBackup = Join-Path $taskBackupRoot ('restore-shortcut-' + $taskStamp + '.lnk')
        Copy-Item -LiteralPath $taskShortcutPath -Destination $taskBackup
        $taskResult.backups += $taskBackup
    }
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
    $taskShortcut.TargetPath = $taskPlan.shortcut_target
    $taskShortcut.Arguments = $taskPlan.shortcut_arguments
    $taskShortcut.WorkingDirectory = $taskRoot
    $taskShortcut.WindowStyle = 7
    $taskShortcut.Description = 'Pause Headroom request compression and restore the owned Codex endpoint.'
    $taskIcon = Join-Path $taskRoot 'token-saver.ico'
    if (Test-Path -LiteralPath $taskIcon -PathType Leaf) { $taskShortcut.IconLocation = $taskIcon }
    $taskShortcut.Save()
    $taskShortcutReadback = $taskShell.CreateShortcut($taskShortcutPath)
    $taskResult.shortcut_created = [bool](
        (Test-Path -LiteralPath $taskShortcutPath -PathType Leaf) -and
        $taskShortcutReadback.TargetPath -ieq $taskPlan.shortcut_target -and
        $taskShortcutReadback.Arguments -ceq $taskPlan.shortcut_arguments
    )
    if (-not $taskResult.shortcut_created) { throw 'The recovery shortcut did not match its planned target.' }
    if ($Start) {
        $taskRunning = $taskRegistered.Run($null)
        $taskResult.task_started = $true
        $taskResult['instance_guid'] = $taskRunning.InstanceGuid
    }
} catch {
    $taskResult.errors += $_.Exception.Message
}
$taskResult['success'] = [bool]($taskResult.task_registered -and $taskResult.task_verified -and $taskResult.shortcut_created -and $taskResult.errors.Count -eq 0)
$taskStateRoot = Join-Path $taskRoot 'proxy'
[void](New-Item -ItemType Directory -Path $taskStateRoot -Force)
$taskJson = $taskResult | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText((Join-Path $taskStateRoot 'startup-result.json'), $taskJson, (New-Object Text.UTF8Encoding($false)))
$taskJson
if (-not $taskResult.success) { exit 1 }
