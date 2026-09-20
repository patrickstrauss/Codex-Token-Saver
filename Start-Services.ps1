param([switch]$StatusOnly, [switch]$StartHeadroom)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'dashboard\.venv\Scripts\python.exe'
$taskAction = 'start'
if ($StatusOnly) { $taskAction = 'status' }
elseif ($StartHeadroom) { $taskAction = 'start-headroom' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Dashboard runtime is missing. See the recovery guide.' }
$taskResult = & $taskPython (Join-Path $PSScriptRoot 'service_control.py') $taskAction
if ($taskResult) { $taskResult | ConvertFrom-Json }
if ($LASTEXITCODE -ne 0) { throw 'The local service could not start. Codex desktop settings are unchanged. See logs.' }
