[CmdletBinding()]
param([Parameter(Mandatory)][string]$PackageDirectory, [switch]$CoreOnly)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Test-InstallPlan.ps1') -PackageDirectory $PackageDirectory
if (-not $?) { throw 'Install plan regression check failed.' }
$taskSandbox = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-package-' + [guid]::NewGuid().ToString('N'))
$taskInstall = Join-Path $taskSandbox 'bundle'
$taskProfile = Join-Path $taskSandbox 'codex'
[void](New-Item -ItemType Directory -Path $taskProfile -Force)
$taskConfig = 'model = "preserve-this-model"' + "`n" + 'model_reasoning_effort = "high"' + "`n" + 'approval_policy = "untrusted"' + "`n"
[IO.File]::WriteAllText((Join-Path $taskProfile 'config.toml'), $taskConfig)
[IO.File]::WriteAllText((Join-Path $taskProfile 'AGENTS.md'), 'Preserve these personal instructions.')
[IO.File]::WriteAllText((Join-Path $taskProfile 'auth.json'), '{"synthetic":"untouched"}')
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly -Plan
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly
if (-not $?) { throw 'Fresh package install failed.' }
$taskPython = Join-Path $taskInstall 'headroom\.venv\Scripts\python.exe'
& $taskPython (Join-Path $taskInstall 'packaging\test_configure_install.py')
if ($LASTEXITCODE -ne 0) { throw 'Configuration rollback fault test failed.' }
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
    if ($taskBefore -notlike '*model = "preserve-this-model"*' -or $taskBefore -match 'openai_base_url|model_provider|base_url') { throw 'Model or routing changed.' }
} finally { $env:CODEX_HOME = $taskPreviousCodex }
& (Join-Path $PackageDirectory 'Install.ps1') -InstallDirectory $taskInstall -SkipIntegration -CoreOnly:$CoreOnly
if (-not $?) { throw 'Repeated package install failed.' }
Write-Output "PASS: fresh install, runtime checks, compression quality benchmark, repeated install, and isolated Codex settings preservation. Evidence: $taskSandbox"
