param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
$taskResult = [ordered]@{ success = $false; message = ''; restart_required = $false }
try {
    $taskRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $taskStableRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'CodexTokenSaver')).TrimEnd('\')
    if ($taskRoot -ine $taskStableRoot) { throw 'Run Restore Direct from your installed CodexTokenSaver folder.' }
    $taskController = Join-Path $taskRoot 'desktop_proxy_control.py'
    if (-not (Test-Path -LiteralPath $taskController -PathType Leaf)) { throw 'The owned endpoint recovery controller is missing.' }
    $taskPython = @(
        (Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'),
        (Join-Path $taskRoot 'dashboard\.venv\Scripts\python.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $taskPython) { throw 'No installed Python runtime is available for owned endpoint recovery.' }
    $taskOutput = & $taskPython $taskController pause 2>$null
    $taskExit = $LASTEXITCODE
    $taskState = ($taskOutput -join "`n") | ConvertFrom-Json
    if ($taskExit -ne 0) {
        if ($taskState.error -is [string] -and $taskState.error.Length -le 1000) { throw $taskState.error }
        throw 'The endpoint could not be restored. Open the dashboard to inspect its current state.'
    }
    if ($taskState.enabled -ne $false -or $taskState.route_enabled -ne $false) {
        throw 'The endpoint remains configured. Open the dashboard to inspect its current state.'
    }
    $taskResult.success = $true
    $taskResult.restart_required = [bool]$taskState.restart_required
    $taskResult.message = 'Headroom request compression is paused and its owned Codex endpoint has been restored. Restart Codex when convenient, then continue your existing tasks. The relay remains available for tasks already loaded.'
} catch {
    $taskResult.message = 'Restore Direct did not complete: ' + $_.Exception.Message
}
$taskResult | ConvertTo-Json -Depth 4
if (-not $Quiet) {
    try {
        $taskShell = New-Object -ComObject WScript.Shell
        $taskIcon = 48
        if ($taskResult.success) { $taskIcon = 64 }
        [void]$taskShell.Popup($taskResult.message, 0, 'Codex Token Saver - Restore Direct', $taskIcon)
    } catch { }
}
if (-not $taskResult.success) { exit 1 }
