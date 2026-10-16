[CmdletBinding()]
param([string]$Version = 'dev', [string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\.scratch\packages' }
if ($Version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$') { throw 'Use a simple release version.' }
$taskRepo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies.json') -Raw | ConvertFrom-Json
if (@($taskPins.PSObject.Properties.Name | Where-Object { $_ -in @('langmem','llama','llama_cpp') }).Count) {
    throw 'Retired summary/inference dependency pins must be removed before packaging.'
}
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
$taskStage = Join-Path $taskOutput ('Codex-Token-Saver-' + $Version + '-windows-x64')
if (Test-Path -LiteralPath $taskStage) { throw "Output already exists: $taskStage" }
$taskPayload = Join-Path $taskStage 'payload'
[void](New-Item -ItemType Directory -Path $taskPayload -Force)
# Explicit source families; never traverse installed runtimes, hidden state, caches or models.
$taskRetired = @('local_summaries.py','local_summary_engine.py','local_summary_mcp.py','summary_reminders.py',
    'Select-Local-Model.ps1','Select-Local-Model.cmd','verify_local_summary.py')
$taskFiles = @(Get-ChildItem -LiteralPath $taskRepo -File | Where-Object {
    $_.Extension -in @('.py','.ps1','.ico') -and $_.Name -notin $taskRetired
})
foreach ($taskDoc in @('README.md','LICENSE','THIRD-PARTY-NOTICES.md','SECURITY.md','LIBRARY-UPDATES.md','DESKTOP-REQUEST-PROXY.md','INSTALL-PLAN.md','HEADROOM-COMPARISON.md','dashboard\LICENSE','native\README.md')) {
    $taskFiles += Get-Item -LiteralPath (Join-Path $taskRepo $taskDoc)
}
foreach ($taskLauncher in @('Repair-Team-Setup.cmd','Setup-Request-Compression.cmd','Disable-Token-Saver.cmd','Uninstall-Token-Saver.cmd','Get-Token-Saver-Diagnostics.cmd')) {
    $taskFiles += Get-Item -LiteralPath (Join-Path $taskRepo $taskLauncher)
}
foreach ($taskDirectory in @('native','scripts','packaging','dashboard','serena')) {
    $taskFiles += Get-ChildItem -LiteralPath (Join-Path $taskRepo $taskDirectory) -File |
        Where-Object { $_.Name -notin $taskRetired -and ($_.Extension -in @('.py','.ps1','.cs','.html','.yml') -or
            ($taskDirectory -eq 'serena' -and $_.Name -eq 'tool-schemas.json') -or
            ($taskDirectory -eq 'packaging' -and $_.Name -in @('dependencies.json','package.json','package-lock.json','laya-model.json',
                'requirements-build.txt','requirements-headroom.txt','requirements-dashboard.txt','requirements-serena.txt','requirements-laya.txt'))) }
}
$taskFiles += Get-ChildItem -LiteralPath (Join-Path $taskRepo 'dashboard\static') -File -Recurse |
    Where-Object Extension -in @('.css','.js','.svg','.png','.ico','.woff2')
$taskFiles += Get-ChildItem -LiteralPath (Join-Path $taskRepo 'docs\benchmarks') -File |
    Where-Object Extension -in @('.md','.json')
foreach ($taskDoc in @('INSTALL.md','BENCHMARK.md','RELEASE-CHECKLIST.md','TEAM-INSTALL.md','USING-BUNDLE.md','CLI-TOOLS.md','LAYA-ROUTER.md','SERENA-INTEGRATION.md','SERENA-TESTING.md','CONTROL-UI-VALIDATION.md','PERFORMANCE-CHECK.md','PROCESS-RECOVERY.md','NATIVE-CODEX.md','OPENCODEX-INTEGRATION.md','OPENCODEX-COMPATIBILITY.md')) {
    $taskFiles += Get-Item -LiteralPath (Join-Path $taskRepo ('docs\' + $taskDoc))
}
foreach ($taskDoc in @('README.md','VALIDATION.md','token-saver-v2.64.0.patch','offline-witness.json')) {
    $taskFiles += Get-Item -LiteralPath (Join-Path $taskRepo ('docs\opencodex\' + $taskDoc))
}
foreach ($taskFile in ($taskFiles | Sort-Object FullName -Unique)) {
    if (($taskFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked source files are not packageable.' }
    $taskRelative = $taskFile.FullName.Substring($taskRepo.Length + 1)
    $taskDestination = Join-Path $taskPayload $taskRelative
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force)
    Copy-Item -LiteralPath $taskFile.FullName -Destination $taskDestination
}
[void](New-Item -ItemType Directory -Path (Join-Path $taskPayload 'bin') -Force)
foreach ($taskBuild in @('Build-RtkLauncher.ps1','Build-HeadroomLauncher.ps1','Build-CodexLaunchers.ps1','Build-TrayLauncher.ps1','Build-CliLaunchers.ps1')) {
    & (Join-Path $taskPayload ('native\' + $taskBuild)) | Out-Null
}
# Kept only because the existing startup installer checks for its legacy fallback.
'@echo off', '"%~dp0rtk.exe" %*' | Set-Content -LiteralPath (Join-Path $taskPayload 'bin\rtk.cmd') -Encoding ascii
foreach ($taskEntry in @('Install.cmd','Install.ps1','Upgrade-App.cmd','Upgrade-App.ps1','Repair-Team-Setup.cmd','Setup-Request-Compression.cmd','Disable-Token-Saver.cmd','Uninstall-Token-Saver.cmd','Get-Token-Saver-Diagnostics.cmd')) {
    Copy-Item -LiteralPath (Join-Path $taskRepo $taskEntry) -Destination $taskStage
}
$taskEntries = @(Get-ChildItem -LiteralPath $taskPayload -File -Recurse | Sort-Object FullName | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($taskPayload.Length + 1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
[ordered]@{schema_version=1;version=$Version;files=$taskEntries} | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $taskStage 'package-manifest.json') -Encoding UTF8
$taskZip = $taskStage + '.zip'
Compress-Archive -LiteralPath $taskStage -DestinationPath $taskZip
((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($taskZip)) |
    Set-Content -LiteralPath ($taskZip + '.sha256') -Encoding ascii
Write-Output $taskZip
