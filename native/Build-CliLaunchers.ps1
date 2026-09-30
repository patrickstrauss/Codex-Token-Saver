$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $taskCompiler)) { throw 'Windows .NET Framework C# compiler was not found.' }
[void](New-Item -ItemType Directory -Path (Join-Path $taskRoot 'bin') -Force)
foreach ($taskName in @('playwright-cli', 'ast-grep')) {
    & $taskCompiler /nologo /target:exe /platform:anycpu /optimize+ ("/out:" + (Join-Path $taskRoot ('bin\' + $taskName + '.exe'))) (Join-Path $PSScriptRoot 'CliLauncher.cs')
    if ($LASTEXITCODE -ne 0) { throw "CLI launcher build failed: $taskName" }
}
