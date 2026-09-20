[CmdletBinding()]
param([Parameter(Mandatory)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$taskHiddenParent = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-hidden-' + [guid]::NewGuid().ToString('N'))
$taskDestination = Join-Path $taskHiddenParent 'bundle'
[void](New-Item -ItemType Directory -Path $taskHiddenParent)
[IO.File]::SetAttributes($taskHiddenParent, ([IO.FileAttributes]::Directory -bor [IO.FileAttributes]::Hidden))
if (-not ([IO.File]::GetAttributes($taskHiddenParent) -band [IO.FileAttributes]::Hidden)) { throw 'Hidden-ancestor fixture was not created.' }
try {
    $taskOutput = & (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskDestination -SkipIntegration -Plan
    if (-not $?) { throw 'Plan failed under a hidden ancestor.' }
    $taskResult = ($taskOutput -join "`n") | ConvertFrom-Json
    if ($taskResult.destination -cne $taskDestination -or $taskResult.verified_files -lt 10) { throw 'Plan did not verify the package and requested destination.' }
    if (Test-Path -LiteralPath $taskDestination) { throw 'Plan unexpectedly created installation files.' }
    Write-Output "PASS: hidden ancestor accepted without writes (PowerShell $($PSVersionTable.PSVersion))."
} finally {
    [IO.File]::SetAttributes($taskHiddenParent, [IO.FileAttributes]::Directory)
    # Delete only this empty fixture directory; never recursively remove a target.
    if (@(Get-ChildItem -LiteralPath $taskHiddenParent -Force).Count -eq 0) { [IO.Directory]::Delete($taskHiddenParent) }
}
