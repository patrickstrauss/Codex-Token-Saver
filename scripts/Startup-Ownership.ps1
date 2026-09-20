# Pure action matching: never retire another program that happens to share a name.
function Test-BundleStartupAction([string]$Root, [string]$Kind, [string]$Target, [string]$Arguments, [string]$WorkingDirectory) {
    if ($WorkingDirectory.TrimEnd('\') -ine $Root.TrimEnd('\')) { return $false }
    if ($Kind -eq 'tray') {
        $launcher = Join-Path $Root 'bin\token-saver-tray.exe'
        $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $legacy = '-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $Root 'Tray.ps1') + '"'
        return (($Target -ieq $launcher -and $Arguments -ceq '') -or
                ($Target -ieq $powershell -and $Arguments -ceq $legacy))
    }
    if ($Kind -eq 'proxy') {
        $runtimes = @((Join-Path $Root 'headroom\.venv\Scripts\pythonw.exe'), (Join-Path $Root 'dashboard\.venv\Scripts\pythonw.exe'))
        return ($Target -in $runtimes -and $Arguments -ceq ('"' + (Join-Path $Root 'desktop_proxy_service.py') + '" run'))
    }
    return $false
}

function Test-BundleStartupTask($Task, [string]$Root, [string]$Kind) {
    $definition = $Task.Definition
    if ($definition.Actions.Count -ne 1 -or $definition.Principal.LogonType -ne 3 -or $definition.Principal.RunLevel -ne 0) { return $false }
    try {
        $account = [string]$definition.Principal.UserId
        if ($account.StartsWith('S-1-')) { $sid = New-Object Security.Principal.SecurityIdentifier($account) }
        else { $sid = (New-Object Security.Principal.NTAccount($account)).Translate([Security.Principal.SecurityIdentifier]) }
        if ($sid.Value -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) { return $false }
    } catch { return $false }
    $action = $definition.Actions.Item(1)
    return Test-BundleStartupAction $Root $Kind $action.Path $action.Arguments $action.WorkingDirectory
}

function Test-BundleStartupDuration($Value, [TimeSpan]$Expected) {
    try { return [Xml.XmlConvert]::ToTimeSpan([string]$Value) -eq $Expected }
    catch { return $false }
}

function Invoke-BundleStartupMigration($Folder, $Definition, [string]$Root, [string]$User,
        [string]$ShortcutPath, $Shell, [string]$BackupRoot, [switch]$Start) {
    $snapshots = @{}
    $written = @{}
    $touched = New-Object 'System.Collections.Generic.List[string]'
    $shortcutBytes = $null
    $shortcutAttempted = $false
    $result = @{backups=@();retired_startup_entries=@();scheduled_task=@{registered=$false;started=$false;start_requested=[bool]$Start}}
    # Validate every retiring entry before changing any startup registration.
    foreach ($task in $Folder.GetTasks(1)) {
        $kind = if ($task.Name -ieq 'Codex Token Saver') { 'tray' } elseif ($task.Name -ieq 'Codex Token Saver Proxy') { 'proxy' } else { continue }
        if (-not (Test-BundleStartupTask $task $Root $kind)) { throw 'An existing startup task is not owned by this bundle; preserved.' }
        $snapshots[$task.Name] = @{Xml=[string]$task.Xml;Enabled=[bool]$task.Enabled}
    }
    if (Test-Path -LiteralPath $ShortcutPath -PathType Leaf) {
        $shortcut = $Shell.CreateShortcut($ShortcutPath)
        if (-not (Test-BundleStartupAction $Root 'tray' $shortcut.TargetPath $shortcut.Arguments $shortcut.WorkingDirectory)) {
            throw 'Existing Startup shortcut is not owned by this bundle; preserved.'
        }
        $shortcutBytes = [IO.File]::ReadAllBytes($ShortcutPath)
    }
    [void](New-Item -ItemType Directory -Path $BackupRoot -Force)
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'
    foreach ($name in $snapshots.Keys) {
        $path = Join-Path $BackupRoot ($name.Replace(' ', '-') + '-' + $stamp + '.xml')
        [IO.File]::WriteAllText($path, $snapshots[$name].Xml, (New-Object Text.UTF8Encoding($false)))
        $result.backups += $path
    }
    if ($null -ne $shortcutBytes) {
        $path = Join-Path $BackupRoot ('retired-startup-' + $stamp + '.lnk')
        [IO.File]::WriteAllBytes($path, $shortcutBytes)
        $result.backups += $path
    }
    try {
        $touched.Add('Codex Token Saver')
        $registered = $Folder.RegisterTaskDefinition('Codex Token Saver', $Definition, 6, $User, $null, 3, $null)
        $written['Codex Token Saver'] = [string]$registered.Xml
        $readback = $registered.Definition
        $owned = Test-BundleStartupTask $registered $Root 'tray'
        if (-not $owned -or
            $readback.Actions.Item(1).Path -ine (Join-Path $Root 'bin\token-saver-tray.exe') -or
            [string]$readback.Actions.Item(1).Arguments -cne '' -or
            $readback.Settings.RestartCount -ne 10 -or
            -not (Test-BundleStartupDuration $readback.Settings.RestartInterval ([TimeSpan]::FromMinutes(1))) -or
            -not (Test-BundleStartupDuration $readback.Settings.ExecutionTimeLimit ([TimeSpan]::Zero)) -or
            $readback.Settings.DisallowStartIfOnBatteries -or $readback.Settings.StopIfGoingOnBatteries) {
            $argumentState = if ($null -eq $readback.Actions.Item(1).Arguments) { 'null' } elseif ([string]$readback.Actions.Item(1).Arguments -ceq '') { 'empty' } else { 'nonempty' }
            $diagnostic = @{owned=$owned;path=[string]$readback.Actions.Item(1).Path;arguments=$argumentState;
                restart_count=$readback.Settings.RestartCount;restart_interval=$readback.Settings.RestartInterval;
                execution_time_limit=$readback.Settings.ExecutionTimeLimit;
                disallow_battery=$readback.Settings.DisallowStartIfOnBatteries;stop_on_battery=$readback.Settings.StopIfGoingOnBatteries} | ConvertTo-Json -Compress
            throw ('The registered tray task did not match its planned settings. Readback: ' + $diagnostic)
        }
        $result.scheduled_task = @{registered=$true;started=$false;start_requested=[bool]$Start;path=$registered.Path;
            user=$readback.Principal.UserId;logon_type=$readback.Principal.LogonType;run_level=$readback.Principal.RunLevel;
            action=$readback.Actions.Item(1).Path;arguments=$readback.Actions.Item(1).Arguments;working_directory=$readback.Actions.Item(1).WorkingDirectory}
        if ($Start) {
            $running = $registered.Run($null)
            if ($null -eq $running) { throw 'Windows did not accept the tray startup launch.' }
            $result.scheduled_task.started = $true
            $result.scheduled_task.instance_guid = $running.InstanceGuid
            $result.scheduled_task.state_at_dispatch = $running.State
        }
        # Retire duplicates only after registration verification and requested dispatch.
        if ($snapshots.ContainsKey('Codex Token Saver Proxy')) {
            $proxy = $Folder.GetTask('Codex Token Saver Proxy')
            if ([string]$proxy.Xml -cne $snapshots['Codex Token Saver Proxy'].Xml) { throw 'The proxy task changed during migration; preserved.' }
            $touched.Add('Codex Token Saver Proxy')
            $proxy.Enabled = $false
            $written['Codex Token Saver Proxy'] = [string]$proxy.Xml
            if ($proxy.Enabled) { throw 'The legacy proxy startup task could not be disabled.' }
            $result.retired_startup_entries += 'Codex Token Saver Proxy'
        }
        if ($null -ne $shortcutBytes) {
            if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($ShortcutPath)) -cne [Convert]::ToBase64String($shortcutBytes)) {
                throw 'The Startup shortcut changed during migration; preserved.'
            }
            $shortcutAttempted = $true
            Remove-Item -LiteralPath $ShortcutPath -ErrorAction Stop
            $result.retired_startup_entries += $ShortcutPath
        }
        return $result
    } catch {
        $failure = $_.Exception.Message
        $rollbackErrors = @()
        if ($shortcutAttempted -and -not (Test-Path -LiteralPath $ShortcutPath)) {
            try { [IO.File]::WriteAllBytes($ShortcutPath, $shortcutBytes) } catch { $rollbackErrors += 'Startup shortcut restoration failed.' }
        }
        for ($index = $touched.Count - 1; $index -ge 0; $index--) {
            $name = $touched[$index]
            try {
                $current = $null
                foreach ($candidate in $Folder.GetTasks(1)) {
                    if ($candidate.Name -ieq $name) { $current = $candidate; break }
                }
                $kind = if ($name -eq 'Codex Token Saver') { 'tray' } else { 'proxy' }
                if ($null -ne $current -and [string]$current.Xml -cne $written[$name] -and
                    -not (Test-BundleStartupTask $current $Root $kind)) { throw 'A concurrent unowned task was preserved.' }
                if ($snapshots.ContainsKey($name)) {
                    $restored = $Folder.RegisterTask($name, $snapshots[$name].Xml, 6, $User, $null, 3, $null)
                    $restored.Enabled = $snapshots[$name].Enabled
                } elseif ($null -ne $current) { $Folder.DeleteTask($name, 0) }
            } catch { $rollbackErrors += ($name + ': ' + $_.Exception.Message) }
        }
        if ($rollbackErrors.Count) { $failure += ' Rollback: ' + ($rollbackErrors -join ' ') }
        throw $failure
    }
}
