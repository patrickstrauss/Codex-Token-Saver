# Called only after Codex is closed and the owned route/integrations are disabled.
# The caller first loads Startup-Ownership.ps1; neither helper enumerates processes.
function Get-BundleDisableStartupPlan($Folder, [string]$Root, [string]$ShortcutPath, $Shell) {
    $tasks = @()
    foreach ($task in @($Folder.GetTasks(1))) {
        $kind = if ($task.Name -ieq 'Codex Token Saver') { 'tray' }
                elseif ($task.Name -ieq 'Codex Token Saver Proxy') { 'proxy' } else { $null }
        if (-not $kind) { continue }
        if (-not (Test-BundleStartupTask $task $Root $kind)) {
            throw ('Startup task is not owned by this installation; preserved: ' + $task.Name)
        }
        $tasks += [pscustomobject]@{name=$task.Name;kind=$kind;xml=[string]$task.Xml}
    }
    $shortcutBytes = $null
    if (Test-Path -LiteralPath $ShortcutPath) {
        $shortcut = $Shell.CreateShortcut($ShortcutPath)
        if (-not (Test-BundleStartupAction $Root 'tray' $shortcut.TargetPath $shortcut.Arguments $shortcut.WorkingDirectory)) {
            throw 'The Startup shortcut is not owned by this installation; preserved.'
        }
        $shortcutBytes = [IO.File]::ReadAllBytes($ShortcutPath)
    }
    return [pscustomobject]@{folder=$Folder;tasks=$tasks;shortcut=$ShortcutPath;shortcut_bytes=$shortcutBytes}
}

function Disable-BundleStartup($Plan, [string]$Root, [string]$BackupRoot) {
    $result = [ordered]@{disabled_tasks=@();retired_shortcut=$null}
    foreach ($snapshot in $Plan.tasks) {
        $task = $Plan.folder.GetTask($snapshot.name)
        if ([string]$task.Xml -cne $snapshot.xml -or -not (Test-BundleStartupTask $task $Root $snapshot.kind)) {
            throw ('Startup task changed concurrently; preserved: ' + $snapshot.name)
        }
        $backup = Join-Path $BackupRoot ($snapshot.name.Replace(' ', '-') + '.xml')
        [IO.File]::WriteAllText($backup, $snapshot.xml, (New-Object Text.UTF8Encoding($false)))
        $task.Enabled = $false
        if ($Plan.folder.GetTask($snapshot.name).Enabled) { throw ('Could not disable startup task: ' + $snapshot.name) }
        $result.disabled_tasks += $snapshot.name
    }
    if ($null -ne $Plan.shortcut_bytes) {
        if (-not (Test-Path -LiteralPath $Plan.shortcut -PathType Leaf) -or
            [Convert]::ToBase64String([IO.File]::ReadAllBytes($Plan.shortcut)) -cne [Convert]::ToBase64String($Plan.shortcut_bytes)) {
            throw 'Startup shortcut changed concurrently; preserved.'
        }
        $backup = Join-Path $BackupRoot 'Codex-Token-Saver-Startup.lnk'
        [IO.File]::WriteAllBytes($backup, $Plan.shortcut_bytes)
        Remove-Item -LiteralPath $Plan.shortcut -ErrorAction Stop
        $result.retired_shortcut = $Plan.shortcut
    }
    return [pscustomobject]$result
}
