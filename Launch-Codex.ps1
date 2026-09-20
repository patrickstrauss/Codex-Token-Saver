param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CodexArguments)
# Compatibility entry point. Prefer codex-saver.cmd for exact native argument quoting.
& (Join-Path $PSScriptRoot 'dashboard\.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'launch_codex.py') -- @CodexArguments
exit $LASTEXITCODE
