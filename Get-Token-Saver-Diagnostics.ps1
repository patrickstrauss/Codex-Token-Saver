[CmdletBinding()]
param(
    [string]$BundleRoot = (Join-Path $env:USERPROFILE 'CodexTokenSaver'),
    [string]$OutputPath = (Join-Path $env:TEMP ('token-saver-diagnostics-' + [guid]::NewGuid().ToString('N') + '.json'))
)
$ErrorActionPreference = 'Stop'

function Get-TokenSaverProcessSnapshot {
    param([object[]]$Processes, [string]$BundleRoot)
    $prefix = [IO.Path]::GetFullPath($BundleRoot).TrimEnd('\') + '\'
    $byId = @{}
    $selected = @{}
    foreach ($item in $Processes) {
        $byId[[int]$item.ProcessId] = $item
        # Include unexplained upstream launchers too: these may belong to an
        # independent MCP registration and must not be mistaken for our proxy.
        if ([string]$item.Name -match '^headroom(?:-run)?\.exe$' -or
            ([string]$item.ExecutablePath).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
            ([string]$item.CommandLine).IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $selected[[int]$item.ProcessId] = $true
        }
    }
    do {
        $added = $false
        foreach ($item in $Processes) {
            if (-not $selected.ContainsKey([int]$item.ProcessId) -and $selected.ContainsKey([int]$item.ParentProcessId)) {
                $selected[[int]$item.ProcessId] = $true
                $added = $true
            }
        }
    } while ($added)
    foreach ($item in $Processes | Sort-Object CreationDate,ProcessId) {
        if (-not $selected.ContainsKey([int]$item.ProcessId)) { continue }
        $role = 'Unclassified'
        # Classify locally, but never write raw command arguments to the report.
        $command = [string]$item.CommandLine
        if ($command -match 'desktop_proxy_service\.py') { $role = 'Proxy supervisor' }
        elseif ($command -match 'proxy_runtime\.py') { $role = 'Compression backend' }
        elseif ($command -match 'desktop_proxy\.py') { $role = 'Request relay' }
        elseif ($command -match 'desktop_mcp\.py') { $role = 'Local file MCP' }
        elseif ($command -match 'serena_mcp\.py|serena\.cli') { $role = 'Serena MCP' }
        elseif ($command -match 'headroom_run\.py') { $role = 'Command output worker' }
        elseif ($command -match '\bmcp\s+serve\b') { $role = 'Upstream Headroom MCP' }
        elseif ($command -match '\bheadroom\.cli\b.*\bproxy\b') { $role = 'Optional CLI proxy' }
        elseif ($command -match 'dashboard[\\/]app\.py') { $role = 'Dashboard' }
        elseif ($command -match 'Tray\.ps1|token-saver-tray\.exe') { $role = 'Tray' }
        $parent = $byId[[int]$item.ParentProcessId]
        [pscustomobject]@{
            pid = [int]$item.ProcessId; parent_pid = [int]$item.ParentProcessId
            name = [string]$item.Name; parent_name = if ($parent) { [string]$parent.Name } else { $null }
            executable_path = [string]$item.ExecutablePath
            inside_bundle = ([string]$item.ExecutablePath).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
            role = $role; created_at = if ($item.CreationDate) { $item.CreationDate.ToUniversalTime().ToString('o') } else { $null }
            working_set_mb = [Math]::Round([double]$item.WorkingSetSize / 1MB, 1)
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $root = [IO.Path]::GetFullPath($BundleRoot)
    $snapshot = @(Get-CimInstance Win32_Process)
    $processes = @(Get-TokenSaverProcessSnapshot -Processes $snapshot -BundleRoot $root)
    $version = $null
    $receipt = Join-Path $root 'team-install-source.json'
    if (Test-Path -LiteralPath $receipt -PathType Leaf) {
        try { $version = [string](Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json).version } catch { $version = 'unreadable' }
    }
    $tasks = @()
    try {
        $tasks = @(Get-ScheduledTask | Where-Object { $_.TaskPath -eq '\' -and $_.TaskName -in @('Codex Token Saver','Codex Token Saver Proxy') } |
            Select-Object TaskName,State)
    } catch { $tasks = @([pscustomobject]@{error='Scheduled task status unavailable'}) }
    $report = [ordered]@{
        schema=1; captured_at=[DateTime]::UtcNow.ToString('o'); version=$version
        install_exists=(Test-Path -LiteralPath $root -PathType Container)
        process_count=$processes.Count; processes=$processes; startup_tasks=$tasks
        note='Read-only snapshot. Paths can identify a user; review before sharing. No raw command lines, environment, authentication or conversation contents included. Working sets can include shared memory.'
    }
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), ($report | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    Write-Host ('Diagnostic report: ' + [IO.Path]::GetFullPath($OutputPath))
}
