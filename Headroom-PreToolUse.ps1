param([string]$BundleRoot = $PSScriptRoot)

# This hook only changes the visible pending command. It never runs that command.
# Unsupported input returns {} so the original Codex permission flow can continue.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$script:reason = 'unsupported_event'

function Test-HeadroomCommand {
    param([string]$Name, [string[]]$Arguments)
    if ($Arguments.Count -eq 0) { return $false }
    # Interactive modes and explicit stdin inputs must keep their original stream.
    if (@($Arguments | Where-Object { $_ -in @('-', '--pdb', '--trace', '--interactive', '-i', '--watch', '-w', '--watchAll', '--paginate') }).Count) {
        return $false
    }
    # Machine output and exact selection modes must remain byte-for-byte output.
    # This mirrors the installed native RTK launcher's conservative exclusions.
    foreach ($argument in $Arguments) {
        if ($argument -match '^--(?:json|format|output-format|message-format|porcelain|pretty|replace)(?:=|$)' -or
            $argument -in @('--raw', '--numstat', '--name-only', '--name-status', '-z', '--null', '--null-data',
                '--files', '--files-with-matches', '--files-without-match', '--count', '--count-matches',
                '--vimgrep', '--only-matching', '-l', '-o', '-r', '-c', '--help', '-h', '--version')) {
            return $false
        }
    }
    switch ($Name.ToLowerInvariant()) {
        'git' {
            if ($Arguments[0] -eq '--no-pager') { $Arguments = @($Arguments | Select-Object -Skip 1) }
            if ($Arguments.Count -eq 0) { return $false }
            if ($Arguments[0] -eq 'status') { return $true }
            if ($Arguments[0] -eq 'log') {
                return -not @($Arguments | Where-Object { $_ -match '^(?:-p|-u|-U|-c$|-L|--patch|--cc|--raw|--numstat|--stat|--check|--word-diff|--ext-diff|--textconv)' }).Count
            }
            return $false
        }
        'rg' { return $true }
        'pytest' { return $true }
        'cargo' { return $Arguments[0] -in @('build', 'test', 'check', 'clippy') }
        'dotnet' { return $Arguments[0] -in @('build', 'test') }
        'python' { return $Arguments.Count -ge 2 -and $Arguments[0] -eq '-m' -and $Arguments[1] -eq 'pytest' }
        'python3' { return $Arguments.Count -ge 2 -and $Arguments[0] -eq '-m' -and $Arguments[1] -eq 'pytest' }
        'uv' {
            return $Arguments.Count -ge 2 -and $Arguments[0] -eq 'run' -and $Arguments[1] -eq 'pytest'
        }
        'rtk' {
            if ($Arguments[0] -notin @('git', 'rg', 'pytest', 'cargo', 'dotnet', 'python', 'python3', 'uv')) { return $false }
            return Test-HeadroomCommand -Name $Arguments[0] -Arguments @($Arguments | Select-Object -Skip 1)
        }
    }
    return $false
}

function Get-HeadroomCommandReplacement {
    param($Statement, [string]$CommandText, [string]$Wrapper)
    # Only direct children of EndBlock are supplied here. Never search the AST
    # recursively: an assignment, pipeline, or nested expression may consume the
    # exact native output. Its independent siblings remain eligible.
    if ($Statement -isnot [System.Management.Automation.Language.PipelineAst] -or
        $Statement.PipelineElements.Count -ne 1 -or $Statement.Background) {
        $script:reason = 'complex_syntax'; return $null
    }
    $command = $Statement.PipelineElements[0]
    if ($command -isnot [System.Management.Automation.Language.CommandAst] -or
        $command.Redirections.Count -or $command.InvocationOperator -notin @('Unknown', 'Ampersand') -or
        $command.CommandElements.Count -lt 2) {
        $script:reason = 'complex_syntax'; return $null
    }
    $elements = @($command.CommandElements)
    $executableElement = $elements[0]
    if ($executableElement -isnot [System.Management.Automation.Language.StringConstantExpressionAst] -or
        $executableElement.StringConstantType -notin @('BareWord', 'SingleQuoted', 'DoubleQuoted')) {
        $script:reason = 'dynamic_input'; return $null
    }
    $executable = [string]$executableElement.Value
    # Bash hooks do not expose the actual selected shell. An explicit Windows
    # drive path is required; bare git/rtk could resolve differently in Bash.
    if ($executable -notmatch '^[A-Za-z]:[\\/]' -or [IO.Path]::GetExtension($executable) -ine '.exe') {
        $script:reason = 'ambiguous_shell'; return $null
    }
    if ($command.InvocationOperator -ne 'Ampersand') {
        # A quoted executable is not an invocation without &, and bare Windows
        # paths have shell-dependent backslash semantics.
        $script:reason = 'ambiguous_shell'; return $null
    }
    if (-not [IO.File]::Exists($executable)) { $script:reason = 'missing_executable'; return $null }
    $executable = [IO.Path]::GetFullPath($executable)
    if ($executable -ieq [IO.Path]::GetFullPath($wrapper)) { $script:reason = 'already_wrapped'; return $null }
    $arguments = @()
    foreach ($element in @($elements | Select-Object -Skip 1)) {
        if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
            $element.StringConstantType -in @('BareWord', 'SingleQuoted', 'DoubleQuoted')) {
            $arguments += [string]$element.Value
        }
        elseif ($element -is [System.Management.Automation.Language.CommandParameterAst] -and $null -eq $element.Argument) {
            $arguments += [string]$element.Extent.Text
        }
        else { $script:reason = 'dynamic_input'; return $null }
    }
    $name = [IO.Path]::GetFileNameWithoutExtension($executable)
    if (-not (Test-HeadroomCommand -Name $name -Arguments $arguments)) {
        $script:reason = 'unsupported_command'; return $null
    }
    # Preserve the argument source verbatim. Re-encoding values would change
    # native argv rules on Windows PowerShell (embedded quotes and empty args).
    $argumentText = $CommandText.Substring($elements[1].Extent.StartOffset,
        $elements[-1].Extent.EndOffset - $elements[1].Extent.StartOffset)
    $replacement = "& '" + $Wrapper.Replace("'", "''") + "' -- '" + $executable.Replace("'", "''") + "' " + $argumentText
    return @{
        start = $command.Extent.StartOffset
        length = $command.Extent.EndOffset - $command.Extent.StartOffset
        text = $replacement
    }
}

function Get-HeadroomRewrite {
    param($Event)
    if ($null -eq $Event -or $Event -is [array] -or $Event.tool_name -ne 'Bash' -or
        ($Event.hook_event_name -and $Event.hook_event_name -ne 'PreToolUse')) { return $null }
    if ($null -eq $Event.tool_input -or $Event.tool_input.command -isnot [string] -or
        [string]::IsNullOrWhiteSpace($Event.tool_input.command)) {
        $script:reason = 'invalid_input'; return $null
    }
    $wrapper = Join-Path $BundleRoot 'bin\headroom-run.exe'
    $runtime = Join-Path $BundleRoot 'headroom\.venv\Scripts\python.exe'
    $runner = Join-Path $BundleRoot 'headroom_run.py'
    if (-not ([IO.File]::Exists($wrapper) -and [IO.File]::Exists($runtime) -and [IO.File]::Exists($runner))) {
        $script:reason = 'missing_runtime'; return $null
    }
    $commandText = $Event.tool_input.command
    if ($commandText.Length -gt 65536) { $script:reason = 'oversized_input'; return $null }
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($commandText, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { $script:reason = 'parse_error'; return $null }
    foreach ($token in $tokens) {
        if ($token.Kind -eq 'Comment' -and $token.Text -match '(?im)^\s*(?:#|<#)\s*headroom:\s*exact\b') {
            $script:reason = 'exact_opt_out'; return $null
        }
        if ($token.Kind -eq 'LineContinuation' -or $token.Text -eq '--%') {
            $script:reason = 'complex_syntax'; return $null
        }
    }
    if ($ast.ParamBlock -or $ast.BeginBlock -or $ast.ProcessBlock -or $ast.DynamicParamBlock -or
        $ast.UsingStatements.Count -or $ast.EndBlock.Traps.Count) {
        $script:reason = 'complex_syntax'; return $null
    }
    $replacements = @()
    foreach ($statement in $ast.EndBlock.Statements) {
        $replacement = Get-HeadroomCommandReplacement -Statement $statement -CommandText $commandText -Wrapper $wrapper
        if ($null -ne $replacement) { $replacements += $replacement }
    }
    if ($replacements.Count -eq 0) { return $null }
    # Original offsets remain valid while replacing from right to left. Newlines,
    # semicolons, comments, skipped statements, and argument source stay verbatim.
    # Status consumers see the native wrapper's unchanged exit code; no extra
    # PowerShell command is inserted between the invocation and $?/$LASTEXITCODE.
    $updatedCommand = $commandText
    foreach ($replacement in @($replacements | Sort-Object { $_.start } -Descending)) {
        $updatedCommand = $updatedCommand.Remove($replacement.start, $replacement.length).Insert($replacement.start, $replacement.text)
    }
    $updatedInput = [ordered]@{}
    foreach ($property in $Event.tool_input.PSObject.Properties) { $updatedInput[$property.Name] = $property.Value }
    $updatedInput['command'] = $updatedCommand
    $script:reason = 'supported_external'
    return @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; permissionDecision = 'allow'; updatedInput = $updatedInput } }
}

$response = $null
try {
    $raw = [Console]::In.ReadToEnd()
    if ($raw.Length -le 131072) { $response = Get-HeadroomRewrite ($raw | ConvertFrom-Json) }
    else { $script:reason = 'oversized_input' }
}
catch { $script:reason = 'invalid_input'; $response = $null }

# Diagnostics deliberately contain no command text, arguments, paths or contents.
try {
    $state = Join-Path $BundleRoot 'headroom\desktop-state'
    [void][IO.Directory]::CreateDirectory($state)
    $outcome = if ($null -ne $response) { 'rewritten' } else { 'skipped' }
    $entry = @{ timestamp = [DateTime]::UtcNow.ToString('o'); outcome = $outcome; reason = $script:reason } | ConvertTo-Json -Compress
    [IO.File]::AppendAllText((Join-Path $state 'hook-events.jsonl'), $entry + "`n", (New-Object System.Text.UTF8Encoding($false)))
}
catch { }
if ($null -eq $response) { [Console]::Out.Write('{}') }
else { [Console]::Out.Write(($response | ConvertTo-Json -Depth 20 -Compress)) }
exit 0
