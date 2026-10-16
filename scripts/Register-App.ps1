param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = 'Stop'
$taskRegistry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexTokenSaver'
if ((Test-Path -LiteralPath $taskRegistry) -and (Get-ItemProperty -LiteralPath $taskRegistry).InstallLocation -ine $Root) {
    throw 'An Apps entry belongs to another installation; it was preserved.'
}
[void](New-Item -Path $taskRegistry -Force)
$taskShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskValues = @{DisplayName='Codex Token Saver';DisplayVersion=$Version;Publisher='Codex Token Saver contributors';
    InstallLocation=$Root;DisplayIcon=(Join-Path $Root 'token-saver.ico');
    UninstallString=('"' + $taskShell + '" -NoProfile -NoExit -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'Uninstall-Token-Saver.ps1') + '"');
    URLInfoAbout='https://github.com/patrickstrauss/Codex-Token-Saver'}
foreach ($taskName in $taskValues.Keys) { New-ItemProperty -LiteralPath $taskRegistry -Name $taskName -Value $taskValues[$taskName] -PropertyType String -Force | Out-Null }
foreach ($taskName in @('NoModify','NoRepair')) { New-ItemProperty -LiteralPath $taskRegistry -Name $taskName -Value 1 -PropertyType DWord -Force | Out-Null }
