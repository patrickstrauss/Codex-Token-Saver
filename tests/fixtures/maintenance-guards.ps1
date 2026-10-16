$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\scripts\Maintenance-Guard.ps1')
$taskTemp = Join-Path ([IO.Path]::GetTempPath()) ('cts-guard-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $taskTemp)
'{}' | Set-Content -LiteralPath (Join-Path $taskTemp 'team-install-source.json')
$script:taskCodexOpen = $false
$script:taskWorkers = @()
function Get-Process { if ($script:taskCodexOpen) { [pscustomobject]@{Name='Codex'} } }
function Get-CimInstance { $script:taskWorkers }
try {
    if ((Assert-BundleDirectory $taskTemp) -ine $taskTemp) { throw 'Owned root rejected' }
    Assert-BundleIdle $taskTemp
    $script:taskCodexOpen = $true
    $taskRefused = $false
    try { Assert-BundleIdle $taskTemp } catch { $taskRefused = $_.Exception.Message -like 'Close Codex*' }
    if (-not $taskRefused) { throw 'Open Codex did not block maintenance' }
    $script:taskCodexOpen = $false
    foreach ($taskSpec in @(
        @{ProcessId=123;Name='python.exe';ExecutablePath=(Join-Path $taskTemp 'python.exe');CommandLine=''},
        @{ProcessId=124;Name='powershell.exe';ExecutablePath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';CommandLine=('powershell -File "' + (Join-Path $taskTemp 'Tray.ps1') + '"')}
    )) {
        $script:taskWorkers = @([pscustomobject]$taskSpec)
        $taskRefused = $false
        try { Assert-BundleIdle $taskTemp } catch { $taskRefused = $_.Exception.Message -like 'Bundle workers*' }
        if (-not $taskRefused) { throw 'Active bundle worker did not block maintenance' }
    }
    $script:taskWorkers = @([pscustomobject]@{ProcessId=125;Name='python.exe';ExecutablePath='C:\other\python.exe';CommandLine='python unrelated.py'})
    Assert-BundleIdle $taskTemp
    $taskRefused = $false
    try { Assert-BundleDirectory (Split-Path -Parent $taskTemp) } catch { $taskRefused = $true }
    if (-not $taskRefused) { throw 'Unowned parent accepted' }
    $taskPath = 'C:\Other;%SystemRoot%;' + (Join-Path $taskTemp 'bin') + ';C:\Last;'
    if ((Get-BundleUserPathWithoutInstall $taskPath $taskTemp) -cne 'C:\Other;%SystemRoot%;C:\Last;') { throw 'User PATH removal changed unrelated raw entries' }
    if ((Get-BundleUserPathWithoutInstall 'C:\Other;;C:\Last;' $taskTemp) -cne 'C:\Other;;C:\Last;') { throw 'Unrelated PATH changed' }
    Write-Output 'PASS: owned root, open Codex, Python worker, tray worker and unrelated worker guards.'
} finally {
    Remove-Item -LiteralPath (Join-Path $taskTemp 'team-install-source.json')
    [IO.Directory]::Delete($taskTemp)
}
