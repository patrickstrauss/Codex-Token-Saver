[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskFolder = Join-Path ([IO.Path]::GetTempPath()) ('token-saver-scan-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $taskFolder)
$taskZip = Join-Path $taskFolder 'gitleaks.zip'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_windows_x64.zip' -OutFile $taskZip -TimeoutSec 120
if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash -ine 'd29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e') { throw 'Secret scanner checksum mismatch.' }
Expand-Archive -LiteralPath $taskZip -DestinationPath $taskFolder
& (Join-Path $taskFolder 'gitleaks.exe') git . --redact --no-banner --log-opts='--all'
if ($LASTEXITCODE -ne 0) { throw 'Secret scanning failed. Review findings privately; never publish a raw secret report.' }
