[CmdletBinding()]
param([string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'))
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($BundleRoot)
$taskPython = Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'
$taskScript = Join-Path $PSScriptRoot 'scripts\setup_request_compression.py'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Install the bundle first; its Headroom runtime is missing.'
}
Write-Host 'Preparing request compression. This downloads a public local model and validates this machine.'
Write-Host 'Codex routing stays unchanged. After setup, use Request compression on the dashboard to enable it.'
& $taskPython $taskScript --bundle-root $taskRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
