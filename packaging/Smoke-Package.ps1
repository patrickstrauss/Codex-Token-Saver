[CmdletBinding()]
param([Parameter(Mandatory)][string]$PackageDirectory, [switch]$CoreOnly, [string]$EvidenceDirectory = '')
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Test-InstallPlan.ps1') -PackageDirectory $PackageDirectory
if (-not $?) { throw 'Install plan regression check failed.' }
$taskSandbox = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-package-' + [guid]::NewGuid().ToString('N'))
$taskInstall = Join-Path $taskSandbox 'bundle'
$taskProfile = Join-Path $taskSandbox 'codex'
[void](New-Item -ItemType Directory -Path $taskProfile -Force)
$taskConfig = 'model = "preserve-this-model"' + "`n" + 'model_reasoning_effort = "high"' + "`n" + 'approval_policy = "untrusted"' + "`n" + 'openai_base_url = "https://existing.example/v1"' + "`n"
[IO.File]::WriteAllText((Join-Path $taskProfile 'config.toml'), $taskConfig)
[IO.File]::WriteAllText((Join-Path $taskProfile 'AGENTS.md'), 'Preserve these personal instructions.')
[IO.File]::WriteAllText((Join-Path $taskProfile 'auth.json'), '{"synthetic":"untouched"}')
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly -Plan
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly
if (-not $?) { throw 'Fresh package install failed.' }
$taskPython = Join-Path $taskInstall 'headroom\.venv\Scripts\python.exe'
& $taskPython (Join-Path $taskInstall 'packaging\test_configure_install.py')
if ($LASTEXITCODE -ne 0) { throw 'Configuration rollback fault test failed.' }
& $taskPython (Join-Path $taskInstall 'packaging\verify_first_run.py') --root $taskInstall --package $PackageDirectory --codex-home $taskProfile
if ($LASTEXITCODE -ne 0) { throw 'Fresh RTK history or artifact repair check failed.' }
& $taskPython (Join-Path $taskInstall 'scripts\benchmark_modules.py') --installed $taskInstall --output (Join-Path $taskSandbox 'performance-benchmark.json') --repeats 3
if ($LASTEXITCODE -ne 0) { throw 'Offline compression quality benchmark failed. See the benchmark output above.' }
$taskPreviousCodex = $env:CODEX_HOME
try {
    $env:CODEX_HOME = $taskProfile
    & $taskPython (Join-Path $taskInstall 'packaging\configure_install.py') $taskInstall
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic profile registration failed.' }
    $taskBefore = Get-Content -LiteralPath (Join-Path $taskProfile 'config.toml') -Raw
    & $taskPython (Join-Path $taskInstall 'packaging\configure_install.py') $taskInstall
    if ($LASTEXITCODE -ne 0) { throw 'Repeated registration failed.' }
    if ((Get-Content -LiteralPath (Join-Path $taskProfile 'config.toml') -Raw) -cne $taskBefore) { throw 'Configuration registration is not idempotent.' }
    if ((Get-Content -LiteralPath (Join-Path $taskProfile 'auth.json') -Raw) -cne '{"synthetic":"untouched"}') { throw 'Authentication changed.' }
    if ((Get-Content -LiteralPath (Join-Path $taskProfile 'AGENTS.md') -Raw) -notlike '*Preserve these personal instructions.*') { throw 'Personal guidance changed.' }
    if ($taskBefore -notlike '*model = "preserve-this-model"*' -or $taskBefore -notlike '*openai_base_url = "https://existing.example/v1"*' -or $taskBefore -match 'model_provider') { throw 'Model or routing changed.' }
} finally { $env:CODEX_HOME = $taskPreviousCodex }
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly
if (-not $?) { throw 'Repeated package install failed.' }
try {
    $env:CODEX_HOME = $taskProfile
    & $taskPython (Join-Path $taskInstall 'packaging\qualify_lifecycle.py') --root $taskInstall --package $PackageDirectory --codex-home $taskProfile
    if ($LASTEXITCODE -ne 0) { throw 'Source upgrade, rollback or integration removal failed.' }
    & (Join-Path $taskInstall 'Uninstall-Token-Saver.ps1') -BundleRoot $taskInstall -Plan
    if (-not $?) { throw 'Uninstall preview failed.' }
    if (-not (Test-Path -LiteralPath $taskInstall)) { throw 'Uninstall preview moved files.' }
    # Windows registration is exercised only on a clean CI runner, never a daily profile.
    if ($env:CI -eq 'true') {
        & (Join-Path $taskInstall 'scripts\Register-App.ps1') -Root $taskInstall -Version 'qualification'
        if (-not $?) { throw 'Windows Installed apps registration failed.' }
    }
    & (Join-Path $taskInstall 'Uninstall-Token-Saver.ps1') -BundleRoot $taskInstall -Yes
    if (-not $?) { throw 'Isolated uninstall failed.' }
    if (Test-Path -LiteralPath $taskInstall) { throw 'Uninstall left the installation directory.' }
    if (@(Get-ChildItem -LiteralPath (Join-Path $taskSandbox 'CodexTokenSaver-Backups') -Directory).Count -ne 1) { throw 'Uninstall backup is missing.' }
    if ($env:CI -eq 'true' -and (Test-Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexTokenSaver')) { throw 'Uninstall left the Windows Apps entry.' }
    & (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly
    if (-not $?) { throw 'Clean reinstall after uninstall failed.' }
} finally { $env:CODEX_HOME = $taskPreviousCodex }
if ($EvidenceDirectory) {
    [void](New-Item -ItemType Directory -Path $EvidenceDirectory -Force)
    Copy-Item -LiteralPath (Join-Path $taskSandbox 'performance-benchmark.json') -Destination $EvidenceDirectory
    Copy-Item -LiteralPath (Join-Path $taskSandbox 'lifecycle-result.json') -Destination $EvidenceDirectory
    & $taskPython (Join-Path $taskInstall 'packaging\make_inventory.py') --root $taskInstall --output (Join-Path $EvidenceDirectory 'runtime-inventory.json')
    if ($LASTEXITCODE -ne 0) { throw 'Runtime inventory failed.' }
}
Write-Output 'PASS: source upgrade, injected rollback, owned integration removal, uninstall preview, backup-preserving uninstall and clean reinstall.'
Write-Output "PASS: fresh RTK history, dashboard readiness, artifact repair, runtime checks, compression quality benchmark, repeated install, and isolated Codex settings preservation. Evidence: $taskSandbox"
