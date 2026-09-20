$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskSelf = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
$taskParent = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskSelf.ParentProcessId)"
$taskPython = Join-Path $taskRoot 'dashboard\.venv\Scripts\python.exe'
$taskResult = [ordered]@{
    timestamp = (Get-Date -Format o)
    parent = $taskParent.Name
    stable_root = $taskRoot
    runtime_version = (& $taskPython --version | Out-String).Trim()
    codex_version = (& (Join-Path $taskRoot 'bin\codex-saver.cmd') --version | Out-String).Trim()
    codex_exit = $LASTEXITCODE
    rtk = (& (Join-Path $taskRoot 'bin\rtk.cmd') gain --all --format json | ConvertFrom-Json).summary
    status = (& $taskPython (Join-Path $taskRoot 'service_control.py') status | ConvertFrom-Json)
    shortcuts = @()
    resolved_rtk = (Get-Command rtk -ErrorAction SilentlyContinue).Source
}
$taskWsh = New-Object -ComObject WScript.Shell
foreach ($taskFolder in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Programs'))) {
    $taskLinkPath = Join-Path $taskFolder 'Codex Token Saver.lnk'
    $taskLink = $taskWsh.CreateShortcut($taskLinkPath)
    $taskResult.shortcuts += [pscustomobject]@{path=$taskLinkPath; exists=(Test-Path -LiteralPath $taskLinkPath); arguments=$taskLink.Arguments}
}
$taskResult | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $taskRoot 'external-verification.json') -Encoding UTF8
