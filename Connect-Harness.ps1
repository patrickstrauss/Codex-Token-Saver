[CmdletBinding()]
param(
    [ValidateSet('list','export','connect','disconnect','disconnect-all')][string]$Action = 'list',
    [ValidateSet('claude-code','gemini-cli','opencode','cursor','vscode','cline','kilo','windsurf-cascade','generic')][string]$Client,
    [ValidateSet('user','project')][string]$Scope = 'user',
    [string]$Project,
    [string]$Config,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'headroom\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Install the managed bundle runtime first.' }
$taskArgs = @((Join-Path $PSScriptRoot 'harness_clients.py'), $Action, '--scope', $Scope)
if ($Client) { $taskArgs += @('--client', $Client) }
if ($Project) { $taskArgs += @('--project', $Project) }
if ($Config) { $taskArgs += @('--config', $Config) }
if ($Apply) { $taskArgs += '--apply' }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Client setup did not complete. Review the error above; unrelated settings were preserved.' }
