[CmdletBinding()]
param([switch]$Start, [switch]$Plan)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$taskStableRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'CodexTokenSaver')).TrimEnd('\')
if ($taskRoot -ine $taskStableRoot) { throw "Run this installer from $taskStableRoot. No startup settings were changed." }
$taskInstaller = Join-Path $taskRoot 'Install-Startup.ps1'
$taskRestore = Join-Path $taskRoot 'Restore-Codex-Direct.ps1'
foreach ($taskRequired in @($taskInstaller, $taskRestore, (Join-Path $taskRoot 'desktop_proxy_control.py'))) {
    if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) { throw 'A required startup or recovery script is missing.' }
}
$taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskPrograms = Join-Path $env:USERPROFILE 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
$taskShortcutPath = Join-Path $taskPrograms 'Codex Token Saver - Restore Direct.lnk'
$taskPlan = & $taskInstaller -Plan | ConvertFrom-Json
$taskPlan | Add-Member NoteProperty shortcut $taskShortcutPath
if ($Plan) { $taskPlan | ConvertTo-Json -Depth 5; exit 0 }

# Both entry points install one tray task; the tray recovers the supervisor.
$taskBackupRoot = Join-Path $taskRoot 'backups\proxy-startup'
$taskResult = [ordered]@{
    timestamp = (Get-Date -Format o); plan = $taskPlan; task_registered = $false
    task_verified = $false; task_started = $false; shortcut_created = $false
    backups = @(); errors = @()
}
try {
    $taskInstallation = & $taskInstaller -Start:$Start | ConvertFrom-Json
    if (-not $taskInstallation.success) { throw 'The shared tray startup installation failed.' }
    $taskResult.task_registered = $true
    $taskResult.task_verified = $true
    $taskResult.task_started = [bool]$taskInstallation.scheduled_task.started
    $taskResult.backups += @($taskInstallation.backups)
    [void](New-Item -ItemType Directory -Path $taskPrograms -Force)
    if (Test-Path -LiteralPath $taskShortcutPath -PathType Leaf) {
        [void](New-Item -ItemType Directory -Path $taskBackupRoot -Force)
        $taskBackup = Join-Path $taskBackupRoot ('restore-shortcut-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.lnk')
        Copy-Item -LiteralPath $taskShortcutPath -Destination $taskBackup
        $taskResult.backups += $taskBackup
    }
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
    $taskShortcut.TargetPath = $taskPowerShell
    $taskShortcut.Arguments = '-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $taskRestore + '"'
    $taskShortcut.WorkingDirectory = $taskRoot
    $taskShortcut.WindowStyle = 7
    $taskShortcut.Description = 'Pause Headroom request compression and restore the owned Codex endpoint.'
    $taskIcon = Join-Path $taskRoot 'token-saver.ico'
    if (Test-Path -LiteralPath $taskIcon -PathType Leaf) { $taskShortcut.IconLocation = $taskIcon }
    $taskShortcut.Save()
    $taskReadback = $taskShell.CreateShortcut($taskShortcutPath)
    $taskResult.shortcut_created = [bool]($taskReadback.TargetPath -ieq $taskPowerShell -and $taskReadback.Arguments -ceq $taskShortcut.Arguments)
    if (-not $taskResult.shortcut_created) { throw 'The recovery shortcut did not match its planned target.' }
} catch { $taskResult.errors += $_.Exception.Message }
$taskResult['success'] = [bool]($taskResult.task_verified -and $taskResult.shortcut_created -and $taskResult.errors.Count -eq 0)
$taskStateRoot = Join-Path $taskRoot 'proxy'
[void](New-Item -ItemType Directory -Path $taskStateRoot -Force)
$taskJson = $taskResult | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText((Join-Path $taskStateRoot 'startup-result.json'), $taskJson, (New-Object Text.UTF8Encoding($false)))
$taskJson
if (-not $taskResult.success) { exit 1 }
