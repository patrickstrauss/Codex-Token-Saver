$ErrorActionPreference = 'Stop'
$bundleRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) {
    throw 'The installed Windows .NET Framework C# compiler was not found.'
}
$sourcePath = Join-Path $PSScriptRoot 'CodexLauncher.cs'
foreach ($launcherName in @('codex-saver', 'codex-headroom')) {
    $outputPath = Join-Path $bundleRoot ("bin\" + $launcherName + '.exe')
    & $compiler /nologo /target:exe /platform:anycpu /optimize+ ("/out:" + $outputPath) $sourcePath
    if ($LASTEXITCODE -ne 0) {
        throw "$launcherName compilation failed (exit $LASTEXITCODE)."
    }
    Get-Item -LiteralPath $outputPath | Select-Object FullName, Length
}
