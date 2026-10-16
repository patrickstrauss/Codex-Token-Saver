# Maintenance never kills discovered processes.
function Assert-BundleIdle([string]$Root) {
    if (@(Get-Process -Name Codex -ErrorAction SilentlyContinue).Count) {
        throw 'Close Codex completely before maintenance. No apps were closed.'
    }
    $taskPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $taskWorkers = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($taskPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
         $_.ProcessId -ne $PID -and $_.Name -ne 'cmd.exe')
    })
    if ($taskWorkers.Count) {
        throw 'Bundle workers are still running. Disable Token Saver, restart Windows, then retry maintenance before opening Codex. No processes were stopped.'
    }
}

function Assert-BundleDirectory([string]$Root) {
    $taskFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ($taskFull -ieq [IO.Path]::GetPathRoot($taskFull).TrimEnd('\') -or
        -not (Test-Path -LiteralPath (Join-Path $taskFull 'team-install-source.json') -PathType Leaf)) {
        throw 'Not an owned package installation. Nothing was moved or removed.'
    }
    for ($taskAncestor = $taskFull; $taskAncestor; $taskAncestor = Split-Path -Parent $taskAncestor) {
        if ((Get-Item -LiteralPath $taskAncestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Maintenance through a junction or symbolic link is unsupported.'
        }
    }
    return $taskFull
}

function Get-BundleUserPathWithoutInstall([AllowEmptyString()][string]$Original, [string]$Root) {
    $taskBin = [IO.Path]::GetFullPath((Join-Path $Root 'bin')).TrimEnd('\')
    $taskEntries = @(foreach ($taskEntry in $Original.Split(';')) {
        $taskOwned = $false
        try {
            $taskExpanded = [Environment]::ExpandEnvironmentVariables($taskEntry.Trim().Trim('"'))
            if ($taskExpanded) { $taskOwned = [IO.Path]::GetFullPath($taskExpanded).TrimEnd('\') -ieq $taskBin }
        } catch { }
        if (-not $taskOwned) { $taskEntry }
    })
    return $taskEntries -join ';'
}
