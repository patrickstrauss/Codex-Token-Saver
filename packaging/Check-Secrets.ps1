[CmdletBinding()]
param(
    [ValidateSet('History', 'Directory')][string]$Mode = 'History',
    [string]$Target = '',
    [string]$ReportPath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Target) { $Target = Join-Path $PSScriptRoot '..' }
$taskTarget = (Resolve-Path -LiteralPath $Target).Path
if (-not (Test-Path -LiteralPath $taskTarget -PathType Container)) { throw 'Scan target must be a directory.' }
$taskFolder = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-scan-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $taskFolder)
try {
    $taskZip = Join-Path $taskFolder 'gitleaks.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_windows_x64.zip' -OutFile $taskZip -TimeoutSec 120
    if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash -ine 'd29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e') { throw 'Secret scanner checksum mismatch.' }
    Expand-Archive -LiteralPath $taskZip -DestinationPath $taskFolder
    $taskArguments = @('git', $taskTarget, '--log-opts=--all')
    if ($Mode -eq 'Directory') { $taskArguments = @('dir', $taskTarget) }
    $taskPrivateReport = Join-Path $taskFolder 'findings.json'
    $taskArguments += @('--redact=100', '--no-banner', '--report-format=json', '--report-path', $taskPrivateReport)
    $taskConfig = Join-Path $PSScriptRoot 'secret-scanner.toml'
    if (Test-Path -LiteralPath $taskConfig) { $taskArguments += @('--config', $taskConfig) }
    # Never send source snippets or credentials to CI output or release evidence.
    $taskPreviousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'  # Native stderr is data in Windows PowerShell 5.1.
        & (Join-Path $taskFolder 'gitleaks.exe') @taskArguments 2>&1 | Out-Null
        $taskExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $taskPreviousErrorPreference }
    $taskFindings = @()
    if (Test-Path -LiteralPath $taskPrivateReport) {
        # Assign before enumerating: PowerShell 5.1 pipelines preserve an empty JSON array.
        $taskParsed = Get-Content -LiteralPath $taskPrivateReport -Raw | ConvertFrom-Json
        $taskFindings = @(foreach ($taskFinding in $taskParsed) {
            if ($null -eq $taskFinding) { continue }
            if (-not $taskFinding.File) { throw 'Invalid secret scanner report.' }
            $taskFinding
        })
    }
    $taskLocations = @($taskFindings | ForEach-Object {
        $taskFile = $_.File.Replace('\', '/')
        $taskPrefix = $taskTarget.Replace('\', '/').TrimEnd('/') + '/'
        if ($taskFile.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase)) { $taskFile = $taskFile.Substring($taskPrefix.Length) }
        if ([IO.Path]::IsPathRooted($taskFile) -or $taskFile.Contains('..')) { $taskFile = 'outside-target' }
        [ordered]@{ rule = $_.RuleID; file = $taskFile; line = $_.StartLine }
    })
    $taskSummary = [ordered]@{
        schema_version = 1; scanner = 'gitleaks'; scanner_version = '8.30.1'
        scope = $(if ($Mode -eq 'History') { 'all_git_refs' } else { 'release_directory' })
        passed = ($taskExit -eq 0); findings = $taskFindings.Count; locations = $taskLocations
        scanned_at = [DateTime]::UtcNow.ToString('o')
        limitations = 'Pattern-based scan; not a guarantee that no private information exists.'
    }
    if ($ReportPath) {
        $taskReport = [IO.Path]::GetFullPath($ReportPath)
        [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskReport) -Force)
        $taskSummary | ConvertTo-Json | Set-Content -LiteralPath $taskReport -Encoding UTF8
    }
    if ($taskExit -ne 0) { throw 'Secret scan failed. Review redacted location metadata; no source snippets or credential values were published.' }
    Write-Output ('PASS: ' + $taskSummary.scope + '; no detected secrets.')
} finally {
    # Delete only this invocation's resolved, generated temporary directory.
    $taskResolved = [IO.Path]::GetFullPath($taskFolder)
    $taskTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $taskResolved.StartsWith($taskTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($taskResolved) -notmatch '^token-saver-scan-[0-9a-f]{32}$') { throw 'Unsafe scanner cleanup path refused.' }
    $taskLinks = @(Get-Item -LiteralPath $taskResolved) + @(Get-ChildItem -LiteralPath $taskResolved -Recurse -Force)
    if (@($taskLinks | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Linked scanner cleanup path refused.' }
    Remove-Item -LiteralPath $taskResolved -Recurse -Force
}
