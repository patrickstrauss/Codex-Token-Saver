param($Helper, $FixtureRoot, $Failure)
$ErrorActionPreference = 'Stop'
. $Helper
if (-not (Get-Command Invoke-BundleStartupMigration -ErrorAction SilentlyContinue)) { throw 'Transactional migration is missing.' }
$script:fixtureRoot = $FixtureRoot
$script:failure = $Failure
function New-FixtureTask($Name, $Xml, $Kind) {
    $target = Join-Path $script:fixtureRoot 'bin\token-saver-tray.exe'
    $arguments = ''
    if ($Kind -eq 'proxy') {
        $target = Join-Path $script:fixtureRoot 'headroom\.venv\Scripts\pythonw.exe'
        $arguments = '"' + (Join-Path $script:fixtureRoot 'desktop_proxy_service.py') + '" run'
    }
    $actions = [pscustomobject]@{Count=1; Action=[pscustomobject]@{Path=$target;Arguments=$arguments;WorkingDirectory=$script:fixtureRoot}}
    $actions | Add-Member ScriptMethod Item { param($Index) return $this.Action }
    $task = [pscustomobject]@{
        Name=$Name; Xml=$Xml; Enabled=$true; Path=('\' + $Name)
        Definition=[pscustomobject]@{
            Actions=$actions
            Principal=[pscustomobject]@{UserId=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; LogonType=3;RunLevel=0}
            Settings=[pscustomobject]@{RestartCount=10;RestartInterval='PT1M';ExecutionTimeLimit='PT0S';DisallowStartIfOnBatteries=$false;StopIfGoingOnBatteries=$false}
        }
    }
    $task | Add-Member ScriptMethod Run { param($Arguments) if ($script:failure -eq 'launch') { throw 'Injected launch failure.' }; return [pscustomobject]@{InstanceGuid='test-only';State=4} }
    return $task
}
$folder = [pscustomobject]@{Tasks=@{}; Registrations=0}
$folder.Tasks['Codex Token Saver'] = New-FixtureTask 'Codex Token Saver' 'original-tray-xml' 'tray'
$folder.Tasks['Codex Token Saver Proxy'] = New-FixtureTask 'Codex Token Saver Proxy' 'original-proxy-xml' 'proxy'
$folder | Add-Member ScriptMethod GetTasks { param($Flags) return @($this.Tasks.Values) }
$folder | Add-Member ScriptMethod GetTask { param($Name) return $this.Tasks[$Name] }
$folder | Add-Member ScriptMethod RegisterTaskDefinition {
    param($Name,$Definition,$Flags,$User,$Password,$LogonType,$Security)
    $this.Registrations++
    $task = New-FixtureTask $Name 'replacement-tray-xml' 'tray'
    if ($script:failure -eq 'readback') { $task.Definition.Settings.RestartCount = 0 }
    if ($script:failure -eq 'normalized') {
        $task.Definition.Actions.Action.Arguments = $null
        $task.Definition.Settings.RestartInterval = 'PT60S'
        $task.Definition.Settings.ExecutionTimeLimit = 'P0D'
    }
    $this.Tasks[$Name] = $task
    return $task
}
$folder | Add-Member ScriptMethod RegisterTask {
    param($Name,$Xml,$Flags,$User,$Password,$LogonType,$Security)
    $kind = if ($Name -eq 'Codex Token Saver') { 'tray' } else { 'proxy' }
    $this.Tasks[$Name] = New-FixtureTask $Name $Xml $kind
    return $this.Tasks[$Name]
}
$shell = [pscustomobject]@{}
$shell | Add-Member ScriptMethod CreateShortcut {
    param($Path)
    $target = Join-Path $script:fixtureRoot 'bin\token-saver-tray.exe'
    if ($script:failure -eq 'unowned-shortcut') { $target = Join-Path $script:fixtureRoot 'unrelated.exe' }
    return [pscustomobject]@{TargetPath=$target; Arguments=''; WorkingDirectory=$script:fixtureRoot}
}
function Remove-Item {
    param($LiteralPath)
    if ($script:failure -eq 'after-disable') { throw 'Injected shortcut removal failure after disabling proxy.' }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath
    if ($script:failure -eq 'after-remove') { throw 'Injected failure after shortcut was removed.' }
}
$shortcut = Join-Path $FixtureRoot 'fixture-startup.lnk'
[IO.File]::WriteAllText($shortcut, 'original-shortcut-bytes')
$failed = $false
try {
    $null = Invoke-BundleStartupMigration $folder $null $FixtureRoot 'fixture-user' $shortcut $shell (Join-Path $FixtureRoot 'backups') -Start
} catch { $failed = $true }
@{
    failed=$failed;tray=$folder.Tasks['Codex Token Saver'].Xml;proxy=$folder.Tasks['Codex Token Saver Proxy'].Xml
    tray_enabled=$folder.Tasks['Codex Token Saver'].Enabled;proxy_enabled=$folder.Tasks['Codex Token Saver Proxy'].Enabled
    shortcut=$(if (Test-Path -LiteralPath $shortcut) { [IO.File]::ReadAllText($shortcut) } else { $null });registrations=$folder.Registrations
} | ConvertTo-Json
