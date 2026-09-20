$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$taskDialog = New-Object System.Windows.Forms.OpenFileDialog
$taskDialog.Title = 'Select your local GGUF model for summaries'
$taskDialog.Filter = 'GGUF model (*.gguf)|*.gguf'
$taskDialog.CheckFileExists = $true
if ($taskDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
$taskModel = [IO.Path]::GetFullPath($taskDialog.FileName)
if ([IO.Path]::GetExtension($taskModel) -ine '.gguf') { throw 'Choose a GGUF model.' }
$taskDirectory = Join-Path $PSScriptRoot 'local-compaction'
[void](New-Item -ItemType Directory -Path $taskDirectory -Force)
$taskConfig = Join-Path $taskDirectory 'model.json'
if (Test-Path -LiteralPath $taskConfig) {
    Copy-Item -LiteralPath $taskConfig -Destination ($taskConfig + '.backup-' + (Get-Date -Format 'yyyyMMddHHmmssffff'))
}
$taskJson = [ordered]@{model_path=$taskModel;max_context_tokens=8192} | ConvertTo-Json
[IO.File]::WriteAllText($taskConfig + '.tmp', $taskJson, (New-Object Text.UTF8Encoding $false))
Move-Item -LiteralPath ($taskConfig + '.tmp') -Destination $taskConfig -Force
[System.Windows.Forms.MessageBox]::Show('Model selected. Open Codex Token Saver and enable Local summaries and llama.cpp when ready. No model was loaded.', 'Codex Token Saver') | Out-Null
