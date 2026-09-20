$ErrorActionPreference = 'Stop'
$bundleRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The installed Windows .NET Framework C# compiler was not found.' }
$outputPath = Join-Path $bundleRoot 'bin\token-saver-tray.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ ("/out:" + $outputPath) (Join-Path $PSScriptRoot 'TrayLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw "Tray launcher compilation failed (exit $LASTEXITCODE)." }
Get-Item -LiteralPath $outputPath | Select-Object FullName, Length
