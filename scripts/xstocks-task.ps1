<#
.SYNOPSIS
Runs the tokenized-stocks data collector on this Windows machine as a scheduled task (docs/runbooks/XSTOCKS_DATA.md).

.DESCRIPTION
Starts `python scripts/collect_xstocks.py --loop` from the repository this script lives in, appends its output to
logs\xstocks\console.log, watches it, and starts it again a minute after it exits. Public market data only; no keys;
nothing here can place an order (plan row R21: log-only data on OKX's tokenized US stocks).

Stopping. Create the file logs\xstocks\STOP: within about -PollSeconds this script ends the collector process and
exits without starting it again (the task then shows Ready; Start-ScheduledTask resumes it, and the collector picks
up where it stopped: candle cursors and taken snapshots are on disk). Stop-ScheduledTask ends only this wrapper:
Windows does not end the collector process with it, so it keeps running until the next start of this script, which
first ends such a leftover process and then starts fresh. Both stops are safe: every write is atomic and resumable.

This script always exits with code 0 so the task scheduler never restarts it in a loop; the reasons are in console.log.

.EXAMPLE
.\scripts\xstocks-task.ps1                 # run in this window
.\scripts\xstocks-task.ps1 -Once           # one pass, then exit (a smoke test)
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
$logDir = Join-Path $repo 'logs\xstocks'
[IO.Directory]::CreateDirectory($logDir) | Out-Null
$console = Join-Path $logDir 'console.log'
$stopFile = Join-Path $logDir 'STOP'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
Set-Location $repo

# Appends one line even while the collector process holds the same file open for its own output.
function Write-Console([string]$Message) {
    $line = ('{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Message) + "`r`n"
    try {
        $stream = New-Object IO.FileStream($console, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes($line)
            $stream.Write($bytes, 0, $bytes.Length)
        }
        finally { $stream.Dispose() }
    }
    catch { }
}

function Stop-Tree([int]$ProcessId) {
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
}

# A collector process left over from a wrapper that was ended by Stop-ScheduledTask: end it, so two collectors never
# write the same files. Only processes running this repository's collector script are touched.
function Stop-LeftoverCollector {
    $pattern = [regex]::Escape((Join-Path $repo 'scripts\collect_xstocks.py'))
    $leftovers = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'collect_xstocks\.py') -and ($_.ExecutablePath -like ($repo + '\*') -or $_.CommandLine -match $pattern) })
    foreach ($proc in $leftovers) {
        Write-Console ('ending a leftover collector process {0} from an earlier wrapper' -f $proc.ProcessId)
        Stop-Tree ([int]$proc.ProcessId)
    }
    if ($leftovers.Count -gt 0) { Start-Sleep -Seconds 3 }
}

$mode = '--loop'
if ($Once) { $mode = '--once' }
while ($true) {
    if (Test-Path $stopFile) {
        Remove-Item $stopFile -ErrorAction SilentlyContinue
        Write-Console 'STOP file found: not starting the collector again.'
        break
    }
    Stop-LeftoverCollector
    Write-Console ('starting: .venv\Scripts\python.exe scripts\collect_xstocks.py {0} --log-level INFO' -f $mode)
    # cmd.exe does the redirection so Python's stderr (its log lines) lands in the file unchanged.
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = 'cmd.exe'
    $startInfo.Arguments = ('/c .venv\Scripts\python.exe -u scripts\collect_xstocks.py {0} --log-level INFO >> logs\xstocks\console.log 2>&1' -f $mode)
    $startInfo.WorkingDirectory = $repo
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $stopped = $false
    while (-not $process.HasExited) {
        if (Test-Path $stopFile) {
            Stop-Tree $process.Id
            $stopped = $true
            break
        }
        Start-Sleep -Seconds $PollSeconds
    }
    [void]$process.WaitForExit(30000)
    if ($stopped) {
        Remove-Item $stopFile -ErrorAction SilentlyContinue
        Write-Console 'STOP file found: the collector was stopped and is not started again (Start-ScheduledTask resumes it).'
        break
    }
    $code = $process.ExitCode
    Write-Console ('the collector exited with code {0}' -f $code)
    if ($Once) { break }
    # Exit code 2 is a setup problem a restart cannot fix (no universe file, wrong options): say so and stop.
    if ($code -eq 2) {
        Write-Console 'exit code 2 means a setup problem (see the runbook''s troubleshooting table); not restarting.'
        break
    }
    Start-Sleep -Seconds $RestartSeconds
}
exit 0
