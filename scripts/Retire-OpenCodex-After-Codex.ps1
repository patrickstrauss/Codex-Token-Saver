param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference = 'Stop'
$taskPlan = Get-Content -Raw -LiteralPath $Plan | ConvertFrom-Json
$taskDeadline = (Get-Date).AddHours(24)
function Get-OwnedProcess($record) {
    try {
        $taskProcess = Get-Process -Id $record.pid -ErrorAction Stop
        if ($taskProcess.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.started -or
            $taskProcess.Path -ne $record.path) { return $null }
        return $taskProcess
    } catch { return $null }
}
function Get-TurnCounts($value) {
    if ($null -eq $value) { return }
    foreach ($taskProperty in $value.PSObject.Properties) {
        if ($taskProperty.Name -eq 'activeTurnCount') { $taskProperty.Value }
        elseif ($taskProperty.Value -is [System.Management.Automation.PSCustomObject]) {
            Get-TurnCounts $taskProperty.Value
        }
    }
}
while ((Get-Date) -lt $taskDeadline) {
    $taskLoaded = @($taskPlan.codex | Where-Object { $null -ne (Get-OwnedProcess $_) })
    if ($taskLoaded.Count -eq 0) { break }
    Start-Sleep -Seconds 5
}
if ((Get-Date) -ge $taskDeadline) { exit 1 }
$taskReceipt = Join-Path $taskPlan.root 'proxy\native-handoff-receipt.json'
$taskHandoff = Get-Content -Raw -LiteralPath $taskReceipt | ConvertFrom-Json
if ($taskHandoff.phase -ne 'complete' -or $taskHandoff.root -ne $taskPlan.root) { exit 2 }
# A disk route change or newly re-enabled OpenCodex cancels retirement.
$taskExpected = 'openai_base_url = "http://127.0.0.1:8788/v1"'
if (-not ((Get-Content -LiteralPath $taskPlan.config) -contains $taskExpected)) { exit 2 }
$taskOcxConfig = Get-Content -Raw -LiteralPath $taskPlan.ocx_config | ConvertFrom-Json
if ($taskOcxConfig.clientIntegrations.codex -ne $false) { exit 2 }
$taskServer = $taskPlan.opencodex | Where-Object { $_.path -eq 'C:\Program Files\OpenCodex\ocx.exe' }
if ($taskServer -and (Get-OwnedProcess $taskServer)) {
    $taskStatus = & $taskServer.path system status --json | ConvertFrom-Json
    $taskCounts = @(Get-TurnCounts $taskStatus)
    if ($taskCounts.Count -eq 0 -or @($taskCounts | Where-Object { $_ -ne 0 }).Count -gt 0) { exit 3 }
}
$taskRetired = @()
# Stop the desktop first so it cannot restart the relay. Each handle is identity checked.
foreach ($taskRecord in ($taskPlan.opencodex | Sort-Object { $_.path -eq 'C:\Program Files\OpenCodex\ocx.exe' })) {
    if ($taskRecord.path -notin @('C:\Program Files\OpenCodex\ocx.exe', 'C:\Program Files\OpenCodex\opencodex-desktop.exe')) { exit 2 }
    $taskProcess = Get-OwnedProcess $taskRecord
    if ($null -ne $taskProcess) { $taskProcess.Kill(); $taskProcess.WaitForExit(5000) | Out-Null; $taskRetired += $taskRecord.pid }
}
@{phase='retired'; pids=$taskRetired; at=(Get-Date).ToUniversalTime().ToString('o')} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskPlan.root 'proxy\opencodex-retirement-result.json') -Encoding UTF8
