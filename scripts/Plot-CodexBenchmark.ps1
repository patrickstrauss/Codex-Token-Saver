[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InputJson,
    [Parameter(Mandatory=$true)][string]$OutputPng
)
$ErrorActionPreference = 'Stop'
$taskReport = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
$taskRows = @($taskReport.samples)
$taskExpected = @('log-diagnosis','symbol-tracing','structural-audit','tested-code-fix','patch-review')
$taskPairs = @($taskRows | ForEach-Object { $_.case + ':' + $_.arm } | Sort-Object -Unique)
if (-not $taskReport.complete -or $taskRows.Count -ne 10 -or $taskPairs.Count -ne 10) {
    throw 'Chart requires a complete five-pair study, including failed attempts.'
}
$taskTotals = @{}
$taskFull = $taskReport.metadata.configuration -eq 'full'
foreach ($taskArm in @('native','bundle')) {
    $taskSamples = @($taskRows | Where-Object arm -eq $taskArm)
    if ($taskSamples.Count -ne 5 -or @(Compare-Object $taskExpected @($taskSamples | ForEach-Object case)).Count) {
        throw 'Unexpected benchmark cases.'
    }
    foreach ($taskSample in $taskSamples) {
        if ($null -eq $taskSample.usage -or $taskSample.usage.input_tokens -isnot [ValueType] -or
            $taskSample.usage.input_tokens -is [bool] -or $taskSample.usage.input_tokens -lt 0 -or
            $taskSample.usage.cached_input_tokens -isnot [ValueType] -or $taskSample.usage.cached_input_tokens -is [bool] -or
            $taskSample.usage.cached_input_tokens -lt 0 -or $taskSample.usage.cached_input_tokens -gt $taskSample.usage.input_tokens -or
            $taskSample.wall_seconds -isnot [ValueType] -or $taskSample.wall_seconds -is [bool] -or
            $taskSample.wall_seconds -lt 0 -or
            [double]::IsNaN([double]$taskSample.wall_seconds) -or [double]::IsInfinity([double]$taskSample.wall_seconds) -or
            [double]$taskSample.usage.input_tokens -ne [math]::Floor([double]$taskSample.usage.input_tokens)) { throw 'Missing or invalid measurements.' }
    }
    $taskTotals[$taskArm] = @{
        input_tokens = ($taskSamples | ForEach-Object { $_.usage.input_tokens } | Measure-Object -Sum).Sum
        cached_input_tokens = ($taskSamples | ForEach-Object { $_.usage.cached_input_tokens } | Measure-Object -Sum).Sum
        wall_seconds = [math]::Round(($taskSamples | Measure-Object wall_seconds -Sum).Sum, 3)
        passed = @($taskSamples | Where-Object { $_.passed -eq $true }).Count
    }
    $taskTotals[$taskArm].uncached_input_tokens = $taskTotals[$taskArm].input_tokens - $taskTotals[$taskArm].cached_input_tokens
    foreach ($taskKey in @('input_tokens','cached_input_tokens','uncached_input_tokens','wall_seconds','passed')) {
        if ($taskTotals[$taskArm][$taskKey] -ne $taskReport.summary.arms.$taskArm.$taskKey) {
            throw 'Summary does not match the raw attempts.'
        }
    }
}
if ($taskTotals.native.input_tokens -le 0 -or $taskTotals.native.wall_seconds -le 0) { throw 'Baseline must be positive.' }
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$taskChart = New-Object System.Windows.Forms.DataVisualization.Charting.Chart
try {
    $taskChart.Width = 1600; $taskChart.Height = 940
    $taskChart.BackColor = [Drawing.Color]::White
    $taskChart.AntiAliasing = 'All'
    $taskChart.TextAntiAliasingQuality = 'High'
    function Add-ChartText($taskText, $taskX, $taskY, $taskWidth, $taskHeight, $taskSize, $taskBold, $taskColor) {
        $taskTitle = New-Object System.Windows.Forms.DataVisualization.Charting.Title
        $taskTitle.Text = $taskText
        $taskStyle = if ($taskBold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
        $taskTitle.Font = New-Object Drawing.Font('Segoe UI', $taskSize, $taskStyle)
        $taskTitle.ForeColor = [Drawing.ColorTranslator]::FromHtml($taskColor)
        $taskTitle.Alignment = 'MiddleLeft'
        $taskTitle.Position = New-Object System.Windows.Forms.DataVisualization.Charting.ElementPosition($taskX,$taskY,$taskWidth,$taskHeight)
        [void]$taskChart.Titles.Add($taskTitle)
    }
    $taskTitle = if ($taskFull) { 'Codex Token Saver | full coding configuration' } else { 'Codex Token Saver | explicit-tool pilot' }
    Add-ChartText $taskTitle 3 3 94 6 23 $true '#172B4D'
    $taskDate = ([datetimeoffset]::Parse($taskReport.started_at)).ToString('dd MMMM yyyy',[Globalization.CultureInfo]::InvariantCulture)
    Add-ChartText ('5 paired synthetic tasks | ' + $taskReport.metadata.configured_model + ' | ' + $taskReport.metadata.reasoning_effort + ' reasoning | ' + $taskDate) 3 10 94 5 12 $false '#526174'
    $taskIndex = 0
    foreach ($taskMetric in @('input_tokens','wall_seconds')) {
        $taskLeft = 3 + $taskIndex * 49
        $taskName = 'metric' + $taskIndex
        $taskNative = $taskTotals.native[$taskMetric]; $taskBundle = $taskTotals.bundle[$taskMetric]
        $taskDelta = ($taskBundle / $taskNative - 1) * 100
        $taskHeading = if ($taskIndex -eq 0) { 'Input tokens (including cached)' } else { 'Total task time' }
        $taskUnit = if ($taskIndex -eq 0) { 'input' } else { 'time' }
        $taskDirection = if ($taskDelta -ge 0) { 'more' } else { 'less' }
        Add-ChartText $taskHeading $taskLeft 21 45 5 17 $true '#172B4D'
        Add-ChartText ('Bundle: {0:0.0}% {1} {2}' -f [math]::Abs($taskDelta),$taskDirection,$taskUnit) $taskLeft 27 45 5 14 $true '#975A16'
        $taskArea = New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea($taskName)
        $taskArea.Position = New-Object System.Windows.Forms.DataVisualization.Charting.ElementPosition($taskLeft,35,45,41)
        $taskArea.InnerPlotPosition = New-Object System.Windows.Forms.DataVisualization.Charting.ElementPosition(21,3,74,80)
        $taskArea.AxisX.IsReversed = $true
        $taskArea.AxisX.MajorGrid.Enabled = $false; $taskArea.AxisX.MajorTickMark.Enabled = $false
        $taskArea.AxisX.LineWidth = 0
        $taskArea.AxisX.IsLabelAutoFit = $false
        $taskArea.AxisX.LabelStyle.Font = New-Object Drawing.Font('Segoe UI',14)
        $taskArea.AxisY.Minimum = 0
        $taskArea.AxisY.Maximum = [math]::Max($taskNative,$taskBundle) * 1.4
        $taskArea.AxisY.LabelStyle.Format = if ($taskIndex -eq 0) { '#,0' } else { '0' }
        $taskArea.AxisY.LabelStyle.Font = New-Object Drawing.Font('Segoe UI',10)
        $taskArea.AxisY.LabelStyle.Enabled = $false
        $taskArea.AxisY.MajorGrid.LineColor = [Drawing.ColorTranslator]::FromHtml('#E7ECF2')
        $taskArea.AxisY.LineColor = [Drawing.ColorTranslator]::FromHtml('#C8D1DC')
        $taskArea.AxisY.MajorTickMark.Enabled = $false
        [void]$taskChart.ChartAreas.Add($taskArea)
        $taskSeries = New-Object System.Windows.Forms.DataVisualization.Charting.Series($taskName)
        $taskSeries.ChartType = 'Bar'; $taskSeries.ChartArea = $taskName
        $taskSeries.Font = New-Object Drawing.Font('Segoe UI',14,[Drawing.FontStyle]::Bold)
        $taskSeries['PointWidth'] = '0.40'
        foreach ($taskArm in @('native','bundle')) {
            $taskValue = $taskTotals[$taskArm][$taskMetric]
            $taskPoint = $taskSeries.Points.AddXY($(if ($taskArm -eq 'native') { 'Native' } else { 'Bundle' }),$taskValue)
            $taskSeries.Points[$taskPoint].Color = [Drawing.ColorTranslator]::FromHtml($(if ($taskArm -eq 'native') { '#316FC4' } else { '#13857D' }))
            $taskSeries.Points[$taskPoint].Label = if ($taskIndex -eq 0) { '{0:N0}' -f $taskValue } else { '{0:0.0} s' -f $taskValue }
        }
        [void]$taskChart.Series.Add($taskSeries)
        $taskIndex++
    }
    $taskUncached = if ($taskTotals.native.uncached_input_tokens -gt 0) { '{0:+0.0;-0.0;0.0}%' -f (($taskTotals.bundle.uncached_input_tokens / $taskTotals.native.uncached_input_tokens - 1) * 100) } else { 'rate unavailable' }
    Add-ChartText ('Uncached input: Native {0:N0} | Bundle {1:N0} ({2})' -f $taskTotals.native.uncached_input_tokens,$taskTotals.bundle.uncached_input_tokens,$taskUncached) 3 78 94 5 14 $true '#172B4D'
    Add-ChartText ('Strict checks passed: Native {0}/5 | Bundle {1}/5' -f $taskTotals.native.passed,$taskTotals.bundle.passed) 3 84 94 5 15 $true '#172B4D'
    $taskScope = if ($taskFull) { 'Automatic Headroom compression and the command hook enabled. Browser tasks excluded.' } else { 'Explicit tools only. Automatic Headroom compression, RTK hooks and browser tasks excluded.' }
    Add-ChartText $taskScope 3 91 94 4 11 $false '#526174'
    Add-ChartText 'No quota/billing savings measured. Five small tasks on one machine; all attempts retained.' 3 96 94 3 10 $false '#526174'
    $taskOutput = [IO.Path]::GetFullPath($OutputPng)
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $taskOutput) -Force)
    $taskChart.SaveImage($taskOutput,[System.Windows.Forms.DataVisualization.Charting.ChartImageFormat]::Png)
    Write-Output $taskOutput
} finally { $taskChart.Dispose() }
