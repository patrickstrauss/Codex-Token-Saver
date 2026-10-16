[CmdletBinding()]
param(
    [string]$InstallDirectory = (Join-Path $env:USERPROFILE 'CodexTokenSaver'),
    [switch]$CoreOnly,
    [switch]$SkipIntegration,
    [ValidateSet('codex','standalone')][string]$Harness = 'codex',
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This package requires Windows x64.' }
$taskRoot = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
$taskDefault = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'CodexTokenSaver')).TrimEnd('\')
if (-not $SkipIntegration -and $taskRoot -ine $taskDefault) { throw 'Use the default installation folder, or -SkipIntegration for an isolated test.' }
for ($taskAncestor = $taskRoot; $taskAncestor; $taskAncestor = Split-Path -Parent $taskAncestor) {
    if ((Test-Path -LiteralPath $taskAncestor) -and ((Get-Item -LiteralPath $taskAncestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Install into a real local directory, not a junction or symbolic link.'
    }
}
$taskPayload = Join-Path $PSScriptRoot 'payload'
$taskManifestPath = Join-Path $PSScriptRoot 'package-manifest.json'
$taskManifest = Get-Content -LiteralPath $taskManifestPath -Raw | ConvertFrom-Json
if ($taskManifest.schema_version -ne 1 -or @($taskManifest.files).Count -lt 10) { throw 'Invalid package manifest.' }
$taskManifestHash = (Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash
$taskSeen = @{}
foreach ($taskFile in $taskManifest.files) {
    if ($taskFile.path -notmatch '^[A-Za-z0-9][A-Za-z0-9_./-]+$' -or $taskFile.path -match '(^|/)\.\.(/|$)' -or $taskFile.sha256 -notmatch '^[a-f0-9]{64}$' -or $taskSeen.ContainsKey($taskFile.path)) { throw 'Unsafe or duplicate package entry.' }
    $taskSeen[$taskFile.path] = $true
    $taskSource = Join-Path $taskPayload $taskFile.path
    if ((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash -ine $taskFile.sha256) { throw "Package checksum mismatch: $($taskFile.path)" }
}
$taskPins = Get-Content -LiteralPath (Join-Path $taskPayload 'packaging\dependencies.json') -Raw | ConvertFrom-Json
if ($Plan) {
    [ordered]@{version=$taskManifest.version;destination=$taskRoot;harness=$Harness;components=$(if ($CoreOnly) {'Headroom, RTK, dashboard'} else {'Headroom, RTK, dashboard, Serena, Playwright CLI, ast-grep, Laya'});integration=(-not $SkipIntegration);routing='existing connection preserved';models=$(if ($CoreOnly) {'no model downloaded'} else {'pinned local Laya classifier'});verified_files=@($taskManifest.files).Count} | ConvertTo-Json
    exit 0
}
$taskMarker = Join-Path $taskRoot 'team-install-source.json'
if ((Test-Path -LiteralPath $taskRoot) -and @(Get-ChildItem -LiteralPath $taskRoot -Force).Count -gt 0) {
    if (-not (Test-Path -LiteralPath $taskMarker)) { throw 'This folder contains an existing installation. Nothing was replaced. Use its library updater; source migration requires a reviewed backup.' }
    $taskExisting = Get-Content -LiteralPath $taskMarker -Raw | ConvertFrom-Json
    if ($taskExisting.package_sha256 -ine $taskManifestHash) { throw 'A different source release is already installed. This installer will not overwrite its runtime or settings.' }
    $taskPriorResult = Join-Path $taskRoot 'team-install-result.json'
    if (Test-Path -LiteralPath $taskPriorResult) {
        $taskPrior = Get-Content -LiteralPath $taskPriorResult -Raw | ConvertFrom-Json
        $taskPriorCodex = if ($taskPrior.PSObject.Properties.Name -contains 'codex_integration') { [bool]$taskPrior.codex_integration } else { $true }
        if ($taskPriorCodex -ne ($Harness -eq 'codex')) { throw 'The existing installation has a different client mode. Preserve it; use Connect-Harness.ps1 for additional clients or the documented uninstall/reinstall procedure.' }
    }
    foreach ($taskFile in $taskManifest.files) {
        $taskCurrent = Join-Path $taskRoot $taskFile.path
        if ((Test-Path -LiteralPath $taskCurrent) -and (Get-FileHash -LiteralPath $taskCurrent -Algorithm SHA256).Hash -ine $taskFile.sha256) { throw "Installed source was modified: $($taskFile.path). No files were replaced." }
    }
}
[void](New-Item -ItemType Directory -Path $taskRoot -Force)
[ordered]@{version=$taskManifest.version;package_sha256=$taskManifestHash} | ConvertTo-Json | Set-Content -LiteralPath $taskMarker -Encoding UTF8
foreach ($taskFile in $taskManifest.files) {
    $taskTarget = Join-Path $taskRoot $taskFile.path
    if (-not (Test-Path -LiteralPath $taskTarget)) {
        [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskTarget) -Force)
        Copy-Item -LiteralPath (Join-Path $taskPayload $taskFile.path) -Destination $taskTarget
    }
}
Copy-Item -LiteralPath $taskManifestPath -Destination (Join-Path $taskRoot 'packaging\installed-manifest.json') -Force
$taskDownloads = Join-Path $taskRoot 'downloads\team-installer'
[void](New-Item -ItemType Directory -Path $taskDownloads -Force)
[void](New-Item -ItemType Directory -Path (Join-Path $taskRoot 'tools') -Force)
function Get-VerifiedDownload($Pin, [string]$Name) {
    $taskDownload = Join-Path $taskDownloads $Name
    if (-not (Test-Path -LiteralPath $taskDownload)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host "Downloading $Name..."
        Invoke-WebRequest -UseBasicParsing -Uri $Pin.url -OutFile ($taskDownload + '.partial') -TimeoutSec 600
        if ((Get-FileHash -LiteralPath ($taskDownload + '.partial') -Algorithm SHA256).Hash -ine $Pin.sha256) { throw "Download checksum mismatch: $Name" }
        Move-Item -LiteralPath ($taskDownload + '.partial') -Destination $taskDownload
    }
    if ((Get-FileHash -LiteralPath $taskDownload -Algorithm SHA256).Hash -ine $Pin.sha256) { throw "Cached download checksum mismatch: $Name" }
    return $taskDownload
}
function Expand-VerifiedTool($Pin, [string]$Name, [string]$Exe, [string]$Destination) {
    if (Test-Path -LiteralPath (Join-Path $Destination $Exe)) { return }
    $taskArchive = Get-VerifiedDownload $Pin ($Name + '.zip')
    $taskExtract = Join-Path $taskDownloads ($Name + '-expanded')
    Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskExtract -Force
    $taskBinary = @(Get-ChildItem -LiteralPath $taskExtract -Filter $Exe -File -Recurse)
    if ($taskBinary.Count -ne 1) { throw "Unexpected archive contents: $Name" }
    [void](New-Item -ItemType Directory -Path $Destination -Force)
    Get-ChildItem -LiteralPath $taskBinary[0].Directory.FullName -File | Copy-Item -Destination $Destination
    $taskLicenseRoot = Join-Path $taskRoot ('tools\licenses\' + $Name)
    foreach ($taskLicense in @(Get-ChildItem -LiteralPath $taskExtract -File -Recurse | Where-Object Name -match '^(LICENSE|COPYING|NOTICE|AUTHORS)')) {
        $taskLicenseTarget = Join-Path $taskLicenseRoot $taskLicense.FullName.Substring($taskExtract.Length + 1)
        [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskLicenseTarget) -Force)
        Copy-Item -LiteralPath $taskLicense.FullName -Destination $taskLicenseTarget -Force
    }
}
Expand-VerifiedTool $taskPins.uv 'uv' 'uv.exe' (Join-Path $taskRoot 'tools')
Expand-VerifiedTool $taskPins.rtk 'rtk' 'rtk.exe' (Join-Path $taskRoot 'tools')
$taskUv = Join-Path $taskRoot 'tools\uv.exe'
# uv's pinned release verifies Python downloads against its embedded SHA-256 manifest.
# Managed Python and its cache stay under this bundle; no global Python or PATH changes.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot 'tools\python'
$env:UV_CACHE_DIR = Join-Path $taskRoot 'downloads\uv-cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_NO_MODIFY_PATH = '1'
function Invoke-BundleUv([string[]]$UvArguments) {
    Push-Location -LiteralPath $taskRoot
    try {
        & $taskUv --no-config @UvArguments
        if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed (uv exit $LASTEXITCODE). Rerun Install.cmd to retry." }
    } finally { Pop-Location }
}
Invoke-BundleUv @('python','install',$taskPins.python,'--no-registry','--no-bin')
$taskPython = [string](& $taskUv --no-config python find $taskPins.python)
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskPython)) { throw 'Managed Python was not installed.' }
$taskComponents = @('headroom','dashboard')
if (-not $CoreOnly) { $taskComponents += @('serena','laya') }
foreach ($taskComponent in $taskComponents) {
    $taskVenv = Join-Path $taskRoot ($taskComponent + '\.venv')
    $taskReady = Join-Path $taskVenv 'team-runtime-ready.json'
    # Bootstrap the native DLLs even when resuming an otherwise ready venv.
    # No elevation, global PATH change or machine-wide redistributable install.
    if (-not (Test-Path -LiteralPath (Join-Path $taskVenv 'Scripts\python.exe'))) { Invoke-BundleUv @('venv','--python',$taskPython,$taskVenv) }
    Invoke-BundleUv @('pip','install','--python',(Join-Path $taskVenv 'Scripts\python.exe'),'--require-hashes','--only-binary=:all:','--requirement','packaging/requirements-windows-runtime.txt')
    if (Test-Path -LiteralPath $taskReady) { Write-Host "Preserving installed $taskComponent runtime."; continue }
    Write-Host "Installing $taskComponent dependencies..."
    # Serena's proxy-tools ships as a source archive. Seed its hash-locked build
    # tools before installation so no unpinned isolated build environment is used.
    Invoke-BundleUv @('pip','sync','--python',(Join-Path $taskVenv 'Scripts\python.exe'),'--require-hashes','packaging/requirements-build.txt','packaging/requirements-windows-runtime.txt')
    Invoke-BundleUv @('pip','install','--python',(Join-Path $taskVenv 'Scripts\python.exe'),'--require-hashes','--no-build-isolation','--requirement',(Join-Path $taskRoot "packaging\requirements-$taskComponent.txt"))
    Invoke-BundleUv @('pip','check','--python',(Join-Path $taskVenv 'Scripts\python.exe'))
    '{"validated_dependencies":true}' | Set-Content -LiteralPath $taskReady -Encoding ascii
}
$taskTokenizer = Get-VerifiedDownload $taskPins.tokenizer 'o200k_base.tiktoken'
$taskTokenizerCache = Join-Path $taskRoot 'headroom\tokenizer-cache'
[void](New-Item -ItemType Directory -Path $taskTokenizerCache -Force)
Copy-Item -LiteralPath $taskTokenizer -Destination (Join-Path $taskTokenizerCache $taskPins.tokenizer.filename) -Force
$taskHeadroomPython = Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe'
if (-not $CoreOnly) {
    & $taskHeadroomPython (Join-Path $taskRoot 'packaging\install_cli_tools.py') $taskRoot
    if ($LASTEXITCODE -ne 0) { throw 'Bundled CLI validation failed. Codex settings were not changed.' }
    & $taskHeadroomPython (Join-Path $taskRoot 'packaging\install_laya_model.py') $taskRoot
    if ($LASTEXITCODE -ne 0) { throw 'Laya model validation failed. Codex settings were not changed.' }
}
& $taskHeadroomPython (Join-Path $taskRoot 'packaging\verify_install.py') $taskRoot
if ($LASTEXITCODE -ne 0) { throw 'Installed runtime smoke check failed. Codex settings were not changed.' }
if (-not $SkipIntegration) {
    # Record intent before registration so a partially completed setup can be disabled.
    [ordered]@{version=$taskManifest.version;completed=$false;integration=$true;codex_integration=($Harness -eq 'codex')} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $taskRoot 'team-install-result.json') -Encoding UTF8
    if ($Harness -eq 'codex') {
        & $taskHeadroomPython (Join-Path $taskRoot 'packaging\configure_install.py') $taskRoot
        if ($LASTEXITCODE -ne 0) { throw 'Codex tool registration failed. See the backup and error above.' }
    }
    & (Join-Path $taskRoot 'Install-Startup.ps1')
    if (-not $?) { throw 'Startup registration failed. Dependencies are installed; rerun to retry.' }
    & (Join-Path $taskRoot 'scripts\Register-App.ps1') -Root $taskRoot -Version $taskManifest.version
}
[ordered]@{version=$taskManifest.version;completed_at=(Get-Date -Format o);core_only=[bool]$CoreOnly;integration=(-not $SkipIntegration);codex_integration=($Harness -eq 'codex');source_sha256=$taskManifestHash} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $taskRoot 'team-install-result.json') -Encoding UTF8
Write-Host "Installed and checked: $taskRoot"
& $taskHeadroomPython (Join-Path $taskRoot 'storage_cleanup.py') --root $taskRoot --apply
# Housekeeping is best-effort and never turns a valid installation into a failure.
if (-not $SkipIntegration) {
    if ($Harness -eq 'codex') { Write-Host 'Restart Codex, then open Codex Token Saver from the Start menu. Enable optional tools in its controls.' }
    else { Write-Host 'Open Codex Token Saver from the Start menu. Use its Coding clients panel or Connect-Harness.ps1 to configure your MCP client.' }
}
