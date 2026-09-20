$ErrorActionPreference = 'Stop'
$bundleRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) {
    throw 'The installed Windows .NET Framework C# compiler was not found.'
}
$sourcePath = Join-Path $PSScriptRoot 'RtkLauncher.cs'
$outputPath = Join-Path $bundleRoot 'bin\rtk.exe'
& $compiler /nologo /target:exe /platform:anycpu /optimize+ /reference:System.Web.Extensions.dll ("/out:" + $outputPath) $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "RTK launcher compilation failed (exit $LASTEXITCODE)."
}
Get-Item -LiteralPath $outputPath | Select-Object FullName, Length
