[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this repair as administrator. It only replaces the verified OpenCodex executable; restart OpenCodex normally afterwards.'
}
$taskSource = Join-Path $PSScriptRoot 'OpenCodex\ocx.exe'
$taskTarget = Join-Path $env:ProgramFiles 'OpenCodex\ocx.exe'
$taskBefore = 'd63d90bb9b8f0a0ac3eb151a759f6b9e8cd2a1669b1f70fb515c36bf510cc59e'
$taskAfter = '90375b06f6f7636f01ab55291b89583ab51fb22630ef49be2e08736f4b2ed7cd'
$taskPrevious = Join-Path (Split-Path $taskTarget) 'ocx-token-saver-before-ui-fix.exe'
$taskStaged = Join-Path (Split-Path $taskTarget) 'ocx-token-saver-ui-fix.new'
if ((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash -ne $taskAfter) { throw 'Repair payload checksum mismatch.' }
$taskCurrent = (Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash
if ($taskCurrent -ne $taskAfter) {
    if ($taskCurrent -ne $taskBefore) { throw 'The installed executable changed. No files were replaced.' }
    if ((Test-Path -LiteralPath $taskPrevious) -or (Test-Path -LiteralPath $taskStaged)) { throw 'A previous repair is present. Inspect it before retrying.' }
    Copy-Item -LiteralPath $taskSource -Destination $taskStaged
    if ((Get-FileHash -LiteralPath $taskStaged -Algorithm SHA256).Hash -ne $taskAfter) { throw 'Staged repair checksum mismatch.' }
    Move-Item -LiteralPath $taskTarget -Destination $taskPrevious
    try {
        Move-Item -LiteralPath $taskStaged -Destination $taskTarget
    } catch {
        if (-not (Test-Path -LiteralPath $taskTarget)) { Move-Item -LiteralPath $taskPrevious -Destination $taskTarget }
        throw
    }
}
if ((Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash -ne $taskAfter) { throw 'Installed repair checksum mismatch.' }
[ordered]@{installed=$true;sha256=$taskAfter;previous=$taskPrevious} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'UI-INSTALL-RESULT.json') -Encoding UTF8
Write-Output 'OpenCodex UI repair installed. Restart OpenCodex normally; Windows does not need a restart.'
