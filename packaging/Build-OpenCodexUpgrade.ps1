[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TokenSaverPackage, [Parameter(Mandatory=$true)][string]$OpenCodexPackage, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $taskOutput) { throw 'Output already exists; choose a fresh release directory.' }
[void](New-Item -ItemType Directory -Path $taskOutput)
Copy-Item -LiteralPath $TokenSaverPackage -Destination (Join-Path $taskOutput 'TokenSaver') -Recurse
Copy-Item -LiteralPath $OpenCodexPackage -Destination (Join-Path $taskOutput 'OpenCodex') -Recurse
$taskOcx = Join-Path $taskOutput 'OpenCodex'
$taskFiles = @(Get-Item -LiteralPath (Join-Path $taskOcx 'ocx.exe'))
$taskFiles += Get-ChildItem -LiteralPath (Join-Path $taskOcx 'gui') -File -Recurse
$taskEntries = @($taskFiles | Sort-Object FullName | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($taskOcx.Length + 1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
[ordered]@{schema_version=1;version='2.64.0-token-saver-candidate';files=$taskEntries} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskOcx 'package-manifest.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Upgrade-OpenCodex.ps1') -Destination $taskOutput
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Connect-OpenCodex.ps1') -Destination $taskOutput
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\docs\OPENCODEX-INTEGRATION.md') -Destination (Join-Path $taskOutput 'START-HERE.md')
foreach ($taskAction in @('Upgrade','Connect','Check','Rollback')) {
    $taskScript = if ($taskAction -in @('Upgrade','Rollback')) { 'Upgrade-OpenCodex.ps1' } else { 'Connect-OpenCodex.ps1' }
    $taskFlag = if ($taskAction -eq 'Check') {' -Status'} elseif ($taskAction -eq 'Rollback') {' -Rollback'} else {''}
    @('@echo off', ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0' + $taskScript + '"' + $taskFlag), 'pause') |
        Set-Content -LiteralPath (Join-Path $taskOutput ($taskAction + '.cmd')) -Encoding ascii
}
Compress-Archive -LiteralPath $taskOutput -DestinationPath ($taskOutput + '.zip')
((Get-FileHash -LiteralPath ($taskOutput + '.zip') -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($taskOutput + '.zip')) |
    Set-Content -LiteralPath ($taskOutput + '.zip.sha256') -Encoding ascii
Write-Output ($taskOutput + '.zip')
