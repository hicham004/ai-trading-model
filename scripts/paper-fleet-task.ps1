<#
.SYNOPSIS
Runs the paper fleet on this Windows machine as a scheduled task (docs/runbooks/PAPER_FLEET.md, option B2).

.DESCRIPTION
Starts `python scripts/run_paper_fleet.py --loop` from the repository this script lives in, appends its
output to logs\paper_fleet\console.log, watches it, and starts it again a minute after it exits (the fleet
exits by itself after 10 failed cycles in a row; systemd would restart it the same way on the VPS).
Public market data only; no keys; nothing here can place an order.

Stop it: Stop-ScheduledTask -TaskName 'AI Trading paper fleet' ends this process tree at once; or create
the file logs\paper_fleet\STOP, and within about -PollSeconds this script ends the fleet process and exits
without starting it again. Both are safe: a cycle that could not be saved is redone from the last saved
state when the fleet next runs (Start-ScheduledTask). This script always exits with code 0 so the task
scheduler never restarts it in a loop; the reasons are in console.log.

.EXAMPLE
.\scripts\paper-fleet-task.ps1                 # run in this window
.\scripts\paper-fleet-task.ps1 -Once           # one cycle, then exit (a smoke test)
#>
[CmdletBinding()]
param(
    [int]$RestartSeconds = 60,
    [int]$PollSeconds = 15,
    [switch]$Once
)

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Write-Error "No .venv in $repo; create it first (see the runbook)."; exit 0 }
$logDir = Join-Path $repo 'logs\paper_fleet'
[IO.Directory]::CreateDirectory($logDir) | Out-Null
$console = Join-Path $logDir 'console.log'
$stopFile = Join-Path $logDir 'STOP'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
Set-Location $repo

function Write-Console([string]$Message) {
    [IO.File]::AppendAllText($console, ('{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Message) + "`r`n")
}

function Stop-Tree([Diagnostics.Process]$Process) {
    if (-not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F | Out-Null }
}

$mode = '--loop'
if ($Once) { $mode = '--once' }
while ($true) {
    if (Test-Path $stopFile) {
        Remove-Item $stopFile -ErrorAction SilentlyContinue
        Write-Console 'STOP file found: not starting the fleet again.'
        break
    }
    Write-Console ('starting: .venv\Scripts\python.exe scripts\run_paper_fleet.py {0} --log-level INFO' -f $mode)
    # cmd.exe does the redirection so Python's stderr (its log lines) lands in the file unchanged.
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = 'cmd.exe'
    $startInfo.Arguments = ('/c .venv\Scripts\python.exe -u scripts\run_paper_fleet.py {0} --log-level INFO >> logs\paper_fleet\console.log 2>&1' -f $mode)
    $startInfo.WorkingDirectory = $repo
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $stopped = $false
    while (-not $process.HasExited) {
        if (Test-Path $stopFile) {
            Stop-Tree $process
            $stopped = $true
            break
        }
        Start-Sleep -Seconds $PollSeconds
    }
    [void]$process.WaitForExit(30000)
    if ($stopped) {
        Remove-Item $stopFile -ErrorAction SilentlyContinue
        Write-Console 'STOP file found: the fleet was stopped and is not started again (Start-ScheduledTask resumes it).'
        break
    }
    $code = $process.ExitCode
    Write-Console ('the fleet exited with code {0}' -f $code)
    if ($Once) { break }
    # Exit code 2 is a setup problem a restart cannot fix (changed rules, wrong options): say so and stop.
    if ($code -eq 2) {
        Write-Console 'exit code 2 means a setup problem (see the runbook''s troubleshooting table); not restarting.'
        break
    }
    Start-Sleep -Seconds $RestartSeconds
}
exit 0
