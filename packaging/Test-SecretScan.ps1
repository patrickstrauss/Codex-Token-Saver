[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-scan-control-' + [guid]::NewGuid().ToString('N'))
try {
    $taskWitness = Join-Path $taskRoot 'docs\opencodex\offline-witness.json'
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskWitness) -Force)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\docs\opencodex\offline-witness.json') -Destination $taskWitness
    $taskCleanReport = Join-Path $taskRoot 'clean-result.json'
    & (Join-Path $PSScriptRoot 'Check-Secrets.ps1') -Mode Directory -Target $taskRoot -ReportPath $taskCleanReport
    if (-not (Get-Content -LiteralPath $taskCleanReport -Raw | ConvertFrom-Json).passed) { throw 'Reviewed source hashes were not recognized.' }
    # Deliberately synthetic, randomly generated and never sent to a provider.
    $taskSynthetic = 'fixture_' + [guid]::NewGuid().ToString('N') + 'Qz7'
    [IO.File]::AppendAllText($taskWitness, "`napi_key = " + $taskSynthetic + "`n")
    $taskRejected = $false
    $taskFailReport = Join-Path $taskRoot 'negative-result.json'
    try { & (Join-Path $PSScriptRoot 'Check-Secrets.ps1') -Mode Directory -Target $taskRoot -ReportPath $taskFailReport }
    catch { $taskRejected = $true }
    $taskResult = Get-Content -LiteralPath $taskFailReport -Raw | ConvertFrom-Json
    if (-not $taskRejected -or $taskResult.passed -or $taskResult.findings -lt 1) { throw 'A new credential-like value was silently excluded.' }
    if (@($taskResult.locations | Where-Object { $_.rule -eq 'generic-api-key' }).Count -lt 1) { throw 'The generic API key exception was not tested.' }
    if ((Get-Content -LiteralPath $taskFailReport -Raw).Contains($taskSynthetic)) { throw 'Credential value leaked into public evidence.' }
    Write-Output 'PASS: exact source-hash exceptions only; new credential-like values are detected and redacted.'
    # The expected failing native scan must not become the enclosing CI step's exit code.
    $global:LASTEXITCODE = 0
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskRoot)
    $taskTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $taskResolved.StartsWith($taskTemp, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($taskResolved) -notmatch '^token-saver-scan-control-[0-9a-f]{32}$') { throw 'Unsafe control-fixture cleanup path.' }
    if (Test-Path -LiteralPath $taskResolved) {
        if (@(@(Get-Item -LiteralPath $taskResolved) + @(Get-ChildItem -LiteralPath $taskResolved -Recurse -Force) |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Linked control-fixture path refused.' }
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}
