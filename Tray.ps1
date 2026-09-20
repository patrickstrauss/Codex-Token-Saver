param([switch]$OpenDashboard)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskLogDir = Join-Path $taskRoot 'logs'
[void](New-Item -ItemType Directory -Path $taskLogDir -Force)
$taskLog = Join-Path $taskLogDir 'tray.log'
$taskTray = $null
$taskTimer = $null
$taskMutex = $null
$taskOwnsMutex = $false
$script:taskLastError = ''
$script:taskRequestStatus = $null
$script:taskReminderTask = $null

function Write-TrayLog([string]$Message) {
    Add-Content -LiteralPath $taskLog -Value ((Get-Date -Format o) + ' ' + $Message)
}
function Write-TrayStatus([bool]$Ready, [string]$ErrorText, $Stats) {
    [pscustomobject]@{timestamp=(Get-Date -Format o);pid=$PID;dashboard=$Ready;error=$ErrorText;headroom_optional=$true;headroom_active=[bool]$Stats.headroom.active;desktop_headroom_configured=[bool]$Stats.desktop_headroom.configured;desktop_headroom_saved=$Stats.desktop_headroom.total_saved;desktop_headroom_data_status=$Stats.desktop_headroom.data_status;install_root=$taskRoot} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'tray-status.json')
}
function Start-Dashboard {
    try { $null = & (Join-Path $taskRoot 'Start-Services.ps1') }
    catch { Write-TrayLog $_.Exception.Message }
}
function Update-TrayStats {
    try {
        $taskStats = Invoke-RestMethod -Uri 'http://127.0.0.1:8095/api/stats' -TimeoutSec 2
        if ($null -eq $taskStats.rtk) { throw 'Unexpected service on dashboard port.' }
        if ($taskStats.rtk.active) {
            $taskRtkItem.Text = 'RTK: ~{0:N0} tokens avoided (all history)' -f [long]$taskStats.rtk.total_saved
            $taskTooltip = 'RTK ~{0:N0}' -f [long]$taskStats.rtk.total_saved
        } else {
            $taskRtkItem.Text = 'RTK: history unavailable or stale'
            $taskTooltip = 'RTK unavailable'
        }
        $taskDesktop = $taskStats.desktop_headroom
        if ($null -ne $taskDesktop.total_saved) {
            $taskDesktopHeadroomItem.Text = 'Headroom desktop: {0:N0} net content tokens; {1:N0} reads / {2:N0} commands / {3:N0} retrievals' -f [long]$taskDesktop.total_saved,[long]$taskDesktop.read_count,[long]$taskDesktop.command_count,[long]$taskDesktop.retrieve_count
            if (-not $taskDesktop.configured) { $taskDesktopHeadroomItem.Text += ' (not configured)' }
            $taskTooltip += ' | Headroom {0:N0} net' -f [long]$taskDesktop.total_saved
        } else {
            $taskDesktopHeadroomItem.Text = 'Headroom desktop: records unavailable'
            $taskTooltip += ' | Headroom records unavailable'
        }
        try {
            $script:taskRequestStatus = Invoke-RestMethod -Uri 'http://127.0.0.1:8095/api/request-proxy' -TimeoutSec 4
            $taskRequest = $script:taskRequestStatus
            if ($taskRequest.savings.available) {
                $taskRequestItem.Text = 'Headroom requests: ~{0:N0} tokens avoided; {1}' -f [long]$taskRequest.savings.saved_tokens,$taskRequest.mode
                $taskTooltip = 'RTK ~{0:N0} | Headroom requests ~{1:N0}' -f [long]$taskStats.rtk.total_saved,[long]$taskRequest.savings.saved_tokens
            } else {
                $taskRequestItem.Text = 'Headroom requests: savings unavailable; ' + $taskRequest.mode
            }
        } catch {
            $script:taskRequestStatus = $null
            $taskRequestItem.Text = 'Headroom requests: status unavailable'
        }
        $taskTray.Text = $taskTooltip.Substring(0, [Math]::Min(63, $taskTooltip.Length))
        if ($taskStats.headroom.active) {
            $taskHeadroomItem.Text = 'Headroom CLI proxy: running (optional)'
        } elseif ($null -ne $taskStats.headroom.total_saved) {
            $taskHeadroomItem.Text = 'Headroom CLI proxy: off; {0:N0} previously recorded' -f [long]$taskStats.headroom.total_saved
        } else { $taskHeadroomItem.Text = 'Headroom CLI proxy: off (optional)' }
        Write-TrayStatus $true '' $taskStats
        $script:taskLastError = ''
    } catch {
        $taskTray.Text = 'Token Saver dashboard unavailable; Codex unaffected'
        $taskRtkItem.Text = 'RTK: dashboard unavailable'
        $taskDesktopHeadroomItem.Text = 'Headroom desktop: dashboard unavailable'
        $taskRequestItem.Text = 'Headroom requests: dashboard unavailable'
        $script:taskRequestStatus = $null
        $taskHeadroomItem.Text = 'Headroom CLI proxy: dashboard unavailable'
        Write-TrayStatus $false $_.Exception.Message $null
        if ($script:taskLastError -ne $_.Exception.Message) {
            Write-TrayLog $_.Exception.Message
            $script:taskLastError = $_.Exception.Message
        }
    }
}

function Update-SummaryReminder {
    try {
        $taskReminderScript = Join-Path $taskRoot 'summary_reminders.py'
        if (-not (Test-Path -LiteralPath $taskReminderScript -PathType Leaf)) { return }
        $taskReminderJson = & (Join-Path $taskRoot 'headroom\.venv\Scripts\python.exe') $taskReminderScript
        if ($LASTEXITCODE -ne 0) { return }
        $taskReminder = ($taskReminderJson | ConvertFrom-Json).notification
        if ($null -eq $taskReminder) { return }
        if ($taskReminder.task_id -notmatch '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$') { return }
        $script:taskReminderTask = $taskReminder.task_id
        $taskReminderTitle = [string]$taskReminder.title
        if ($taskReminderTitle.Length -gt 100) { $taskReminderTitle = $taskReminderTitle.Substring(0, 100) }
        $taskReminderText = "{0}`nReported context: {1:N0}%. Click to review or create a local summary." -f $taskReminderTitle,[double]$taskReminder.context_percent
        $taskTray.ShowBalloonTip(10000, 'Local summary reminder', $taskReminderText, [Windows.Forms.ToolTipIcon]::Info)
    } catch {
        # Reminder failures must not interrupt service recovery or the tray.
        Write-TrayLog ('Summary reminder unavailable: ' + $_.Exception.GetType().Name)
    }
}

try {
    Write-TrayLog ('Tray starting; PID ' + $PID + '; root ' + $taskRoot)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $taskCreated = $false
    $taskMutex = New-Object System.Threading.Mutex($true, 'Local\CodexTokenSaverTrayV2', [ref]$taskCreated)
    if (-not $taskCreated) {
        if ($OpenDashboard) { Start-Process 'http://127.0.0.1:8095/' }
        $taskMutex.Dispose()
        $taskMutex = $null
        exit
    }
    $taskOwnsMutex = $true
    $taskTray = New-Object System.Windows.Forms.NotifyIcon
    $taskTray.Icon = [Drawing.SystemIcons]::Information
    $taskIconPath = Join-Path $taskRoot 'token-saver.ico'
    if (Test-Path -LiteralPath $taskIconPath) { $taskTray.Icon = New-Object Drawing.Icon($taskIconPath) }
    $taskTray.Text = 'Codex Token Saver - starting dashboard'
    $taskTray.Visible = $true
    $taskMenu = New-Object System.Windows.Forms.ContextMenuStrip
    $taskTray.ContextMenuStrip = $taskMenu
    $taskOpenItem = $taskMenu.Items.Add('Open savings dashboard')
    $taskRtkItem = $taskMenu.Items.Add('RTK: loading')
    $taskRtkItem.Enabled = $false
    $taskRequestItem = $taskMenu.Items.Add('Headroom requests: loading')
    $taskRequestItem.Enabled = $false
    $taskDesktopHeadroomItem = $taskMenu.Items.Add('Headroom desktop: loading')
    $taskDesktopHeadroomItem.Enabled = $false
    $taskHeadroomItem = $taskMenu.Items.Add('Headroom CLI proxy: optional')
    $taskHeadroomItem.Enabled = $false
    [void]$taskMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
    $taskRepairItem = $taskMenu.Items.Add('Restart / repair dashboard')
    $taskSummaryItem = $taskMenu.Items.Add('Local summary reminders')
    $taskGuideItem = $taskMenu.Items.Add('Open setup and recovery guide')
    $taskQuitItem = $taskMenu.Items.Add('Quit tray (services keep running)')
    $taskOpenItem.Add_Click({ Start-Dashboard; Start-Process 'http://127.0.0.1:8095/' })
    $taskTray.Add_MouseClick({ param($sender,$eventArgs); if ($eventArgs.Button -eq [Windows.Forms.MouseButtons]::Left) { Start-Dashboard; Start-Process 'http://127.0.0.1:8095/' } })
    $taskRepairItem.Add_Click({ Start-Dashboard; Update-TrayStats })
    $taskSummaryItem.Add_Click({ Start-Process 'http://127.0.0.1:8095/#local-summary-panel' })
    $taskTray.Add_BalloonTipClicked({
        if ($script:taskReminderTask) {
            Start-Process ('http://127.0.0.1:8095/?summary_task=' + $script:taskReminderTask + '#local-summary-panel')
        }
    })
    $taskGuideItem.Add_Click({ Start-Process notepad.exe -ArgumentList ('"' + (Join-Path $taskRoot 'README.md') + '"') })
    $taskQuitItem.Add_Click({ [Windows.Forms.Application]::Exit() })
    Start-Dashboard
    Update-TrayStats
    Update-SummaryReminder
    if ($OpenDashboard) { Start-Process 'http://127.0.0.1:8095/' }
    $script:taskTick = 0
    $taskTimer = New-Object Windows.Forms.Timer
    $taskTimer.Interval = 15000
    $taskTimer.Add_Tick({
        $script:taskTick++
        if (($script:taskTick % 4) -eq 0) { Start-Dashboard; Update-SummaryReminder }
        Update-TrayStats
    })
    $taskTimer.Start()
    [Windows.Forms.Application]::Run()
} catch {
    Write-TrayLog ('Fatal startup error: ' + ($_ | Out-String))
    Write-TrayStatus $false $_.Exception.Message $null
    exit 1
} finally {
    if ($taskTimer) { $taskTimer.Stop(); $taskTimer.Dispose() }
    if ($taskTray) { $taskTray.Visible=$false; $taskTray.Dispose() }
    if ($taskMutex) {
        if ($taskOwnsMutex) { $taskMutex.ReleaseMutex() }
        $taskMutex.Dispose()
    }
}
