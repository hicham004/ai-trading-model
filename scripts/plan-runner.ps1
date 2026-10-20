<#
.SYNOPSIS
Runs docs/PLAN_STATUS.md unattended: one fresh Claude chat per row.

.DESCRIPTION
Adapted on 2026-10-20 from the TB Gym plan runner. It runs the status table in section 0 of
docs/PLAN_STATUS.md, whose rows point into docs/MASTER_PLAN_2026-10-20.md.

Each step is a new `claude -p` chat at max effort, on Opus 5.5 unless -RowModels names another
model for its row. It gets $stepIntro and the unattended-run rules in $sharedRules below. The
owner decided on 2026-10-20 that such a chat commits its own step on the runner branch
(plan/auto) once the full test suite, the travel-mode guard and git diff --check are clean. A
chat never pushes, merges or switches branches: deny rules block git push, merge and rebase,
ssh and scp, and the two demo-trading scripts. With -Push the runner itself pushes the runner
branch after each clean step: never main, and never again once a scan of the new commits has
found something that looks like a credential (the repository is public).

A chat that hits a usage limit is resumed where it stopped. A five-hour limit is waited out on
the same model. The owner decided on 2026-10-20 that every row runs on Opus 5.5 at max effort
and that a weekly limit (one resetting more than 12 hours away) is waited out too, so the plan
finishes while the owner is away. With -FallbackModel set, a weekly limit instead moves the
chat to that model at once, later rows stay on it until the limit resets, and Claude Code's
--fallback-model does the same for a model that is overloaded or unavailable.

A step starts only when the runner branch is checked out, no tracked file is changed, no chat in
this folder has written for -IdleMinutes, and the next row is Open (not a gate, Optional, Built,
Blocked or In progress). The runner stops after -MaxSteps, at the first step that does not end
clean with its row Done, when artifacts\plan-runner\STOP exists, or, with -NoNewStepAfter,
before a step that would start after that clock time. Logs, each chat's report and summary.md
go to artifacts\plan-runner\ (git-ignored).

.EXAMPLE
.\scripts\plan-runner.ps1 -DryRun                  # what would run next; starts nothing
.\scripts\plan-runner.ps1 -SelfTest                # one tiny chat per model outside the repo: model, effort, deny rules
.\scripts\plan-runner.ps1 -WaitForIdle -Push       # wait until other chats are finished, then run every Open row
.\scripts\plan-runner.ps1 -WaitForIdle -Push -NoNewStepAfter 08:00   # a night run that leaves the morning free
#>
[CmdletBinding()]
param(
    # A clock time such as 08:00: no step starts after its next occurrence (empty: no limit).
    [string]$NoNewStepAfter = '',
    [int]$MaxSteps = 12,
    [double]$StepHours = 8,
    [int]$IdleMinutes = 20,
    [int]$MaxLimitWaits = 12,
    # Row id pattern (-like) to model; a row matching none runs on $model below.
    [hashtable]$RowModels = @{},
    # After a weekly limit the chat carries on with this model, and so do later rows until that
    # limit resets. Empty (the owner, 2026-10-20: Opus only): the limit is waited out instead.
    [string]$FallbackModel = '',
    # The branch every step commits on. The runner never creates or switches branches.
    [string]$Branch = 'plan/auto',
    # Push the runner branch to origin after each clean step.
    [switch]$Push,
    # For testing the runner itself: another status file, repository or log folder.
    [string]$StatusFile = 'docs\PLAN_STATUS.md',
    [string]$RepoRoot = '',
    [string]$LogFolder = '',
    [switch]$WaitForIdle,
    [switch]$DryRun,
    [switch]$SelfTest,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ($RepoRoot) { $repositoryRoot = (Resolve-Path $RepoRoot).Path }
$planPath = $StatusFile
if (-not [IO.Path]::IsPathRooted($planPath)) { $planPath = Join-Path $repositoryRoot $StatusFile }
$logDir = Join-Path $repositoryRoot 'artifacts\plan-runner'
if ($LogFolder) { $logDir = $LogFolder }
$stopFile = Join-Path $logDir 'STOP'
$lockFile = Join-Path $logDir 'runner.lock'
$summaryPath = Join-Path $logDir 'summary.md'
$model = 'claude-opus-5-5'
$effort = 'max'
$chatPrefix = 'AI trading runner '
# Models whose weekly limit is used up, with when to try them again; their rows run on $FallbackModel.
$script:exhaustedUntil = @{}
# Set once a new commit looks like it holds a credential; from then on nothing is pushed.
$script:pushBlocked = ''
$utf8 = New-Object System.Text.UTF8Encoding($false)
$gateSign = [char]::ConvertFromUtf32(0x1F6A6)
[IO.Directory]::CreateDirectory($logDir) | Out-Null
try { [Console]::OutputEncoding = $utf8 } catch { }
if ($Branch -match '^(main|master)$') { throw 'The runner never commits on main: pass another -Branch.' }
$stepCutoff = $null
if ($NoNewStepAfter) {
    $stepCutoff = [datetime]::Today.Add([timespan]::Parse($NoNewStepAfter))
    if ($stepCutoff -le (Get-Date)) { $stepCutoff = $stepCutoff.AddDays(1) }
}

# Deny rules every chat gets. They hold even in bypassPermissions (-SelfTest checks).
$deniedTools = @(
    'Bash(git push *)', 'PowerShell(git push *)',
    'Bash(git merge *)', 'PowerShell(git merge *)',
    'Bash(git rebase *)', 'PowerShell(git rebase *)',
    'Bash(ssh *)', 'PowerShell(ssh *)', 'Bash(scp *)', 'PowerShell(scp *)',
    'Bash(*run_demo_trading.py*)', 'PowerShell(*run_demo_trading.py*)',
    'Bash(*run_shadow_period.py*)', 'PowerShell(*run_shadow_period.py*)'
)

# Text that looks like a credential. The repository is public, so a match stops all pushing.
$secretPatterns = @(
    'sk-ant-[A-Za-z0-9_-]{20,}',
    '-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'AKIA[0-9A-Z]{16}',
    'gh[pousr]_[A-Za-z0-9]{36}',
    '\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b'
)

# How each chat starts; $sharedRules continues it.
$stepIntro = @'
Read docs/PLAN_STATUS.md and do the next step: the first row of its section 0 status table
that is not Done. Rows whose status starts with "Open, not blocking" are the owner's and are
passed over. The row's third column is its scope: build what it names and nothing else, as
docs/MASTER_PLAN_2026-10-20.md and the documents the row points to describe it.

This chat runs unattended. scripts/plan-runner.ps1 started it, and nobody will see or answer
anything until it has finished. The runner expects the next step to be <<ROW>>. If the status
table gives a different row, change nothing and say why.

The safety contract in CLAUDE.md and PROJECT_RULES.md holds in full. For this run that means:
- Demo-only. No LLM output may place, size, approve, modify or cancel an order, and nothing
  built here may block or delay an exit, a protective stop, the kill switch or reconciliation.
- This laptop has no OKX credentials and no Anthropic API key. Never ask for, create, search
  for or store a credential. Build with fixtures, recorded responses and mocks. Code that
  would call a paid API refuses cleanly when its key is missing.
- Public data only: OKX public REST and WebSocket, Binance public research files, official
  RSS feeds. Never run scripts/run_demo_trading.py or scripts/run_shadow_period.py, never
  call an authenticated OKX endpoint, and never connect to the VPS (ssh, scp).
- Do not change app/execution, app/risk, app/exchange or config/ unless the row says so.
- Research: the 12-month holdout is evaluated only for configurations that pass
  walk-forward, and no gate changes after the results are in. If a gate looks wrong, say so
  in the report.

The owner's decisions for this run (2026-10-20):
- The owner approved building the Open rows of the status table, in order, on the branch
  plan/auto, without a preview round. The owner reviews the pull request afterwards.
- Phase 6b, the log-only news and event agent, is authorized (owner, 2026-06-30, GitHub
  issue #12; confirmed 2026-10-20). Using news to gate demo or live entries is not.
- A question the row and the docs do not settle: a technical one is yours (AGENTS.md). A
  business question, money (a paid service, a key, a subscription), a new risk or strategy
  parameter for the running demo, a safety-core change or a phase advancement is not
  delegated: leave that item out, add it with your recommendation as one line under section 2
  of docs/PLAN_STATUS.md and in your report, and build the rest of the row.
- A row too big to finish well in one chat: split it into parts (R4a1, R4a2), each with its
  scope, build and commit the first, and leave the others Open for the next chat.
'@

$sharedRules = @'
- Commit approved. When the step meets its definition of done and these checks pass, commit
  the step on the current branch, then record the hash in its status row in a second small
  commit, in the form the Done rows use. The checks: the full test suite
  (.venv\Scripts\python.exe -m pytest -q); the travel-mode guard
  (.venv\Scripts\python.exe scripts\check_travel_mode_safety.py --base <the commit this step
  started from>), whose flagged files must be ones the row is meant to change, named in the
  report; and git diff --check. Stage only the files this step changed, by explicit path.
  Never push, never merge, never create or switch branches, never amend, rebase or reset
  commits.
- A dependency change goes into requirements.in and the hashed requirements.txt, regenerated
  with the uv command in its header (uv is not on PATH here: install it into the .venv with
  pip first), and pip-audit must stay clean.
- If a check fails and you cannot fix it inside the step, do not commit. Set the row to
  "Built, not committed" with one line on what failed, and stop.

How an unattended run works:
- Ask nothing and do not use plan mode. State your plan in a message, then build.
- Background commands are stopped after 10 minutes here unless you pass a timeout. Start long
  ones (the full test suite, research runs, a live smoke run) with run_in_background and
  timeout 7200000. While one runs you may end your turn; you get another turn when it exits.
- Before your final message, stop the processes and background commands you started, and only
  those. Never kill processes by name.
- Leave scripts/plan-runner.ps1 and artifacts/plan-runner/ alone; they belong to the runner.
- Your final message is the owner's report, for an owner who is not technical: what the system
  can do now that it could not before, in plain words; test results; what was not done or not
  verified; each decision the owner needs to make, with your recommendation; and the next
  step. End it with exactly one of these lines:
  RUNNER-RESULT: done <<ROW>> <commit hash>
  RUNNER-RESULT: stopped <one-line reason>
'@
$stepPrompt = $stepIntro + "`n" + $sharedRules

$resumePrompt = 'The run stopped ({0}). Carry on with step {1} from where you stopped. The unattended-run rules in the first message still apply.'

function Write-Note([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm}  {1}' -f (Get-Date), $Message
    Write-Host $line
    [IO.File]::AppendAllText((Join-Path $logDir 'runner.log'), $line + "`r`n", $utf8)
}

function Get-RowModel([string]$RowId) {
    $chosen = $model
    foreach ($pattern in @($RowModels.Keys | Sort-Object)) {
        if ($RowId -like $pattern) { $chosen = [string]$RowModels[$pattern]; break }
    }
    if ($FallbackModel -and $script:exhaustedUntil.ContainsKey($chosen) -and (Get-Date) -lt $script:exhaustedUntil[$chosen]) {
        return $FallbackModel
    }
    return $chosen
}

function Get-RowModelText {
    $pairs = @($RowModels.Keys | Sort-Object | ForEach-Object { '{0} on {1}' -f $_, $RowModels[$_] })
    $text = 'every row on {0}' -f $model
    if ($pairs.Count -gt 0) { $text = '{0}; every other row on {1}' -f ($pairs -join ', '), $model }
    if ($FallbackModel) { $text += '; after a weekly limit, {0}' -f $FallbackModel }
    return $text
}

function Get-ShortText([string]$Text, [int]$Length) {
    $flat = ($Text -replace '\s+', ' ').Trim()
    if ($flat.Length -le $Length) { return $flat }
    return $flat.Substring(0, $Length) + '...'
}

# Outputs nothing for a missing field, so @(Get-Field ...) is empty rather than @($null).
function Get-Field($Object, [string]$Name) {
    if ($null -ne $Object) {
        $property = $Object.PSObject.Properties[$Name]
        if ($property) { $property.Value }
    }
}

function Get-ClaudeExe {
    $extensions = Join-Path $env:USERPROFILE '.vscode\extensions'
    $newest = Get-ChildItem -Path $extensions -Directory -Filter 'anthropic.claude-code-*' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $exe = Join-Path $_.FullName 'resources\native-binary\claude.exe'
            if ($_.Name -match '^anthropic\.claude-code-(\d+\.\d+\.\d+)' -and (Test-Path $exe)) {
                [pscustomobject]@{ Version = [version]$Matches[1]; Exe = $exe }
            }
        } |
        Sort-Object Version -Descending |
        Select-Object -First 1
    if (-not $newest) { throw "claude.exe was not found under $extensions." }
    return $newest.Exe
}

# --no-optional-locks keeps these reads from taking index.lock under a chat's git command.
function Invoke-Git {
    $output = & git -C $repositoryRoot --no-optional-locks @args
    if ($LASTEXITCODE -ne 0) { throw ('git {0} exited with {1}' -f ($args -join ' '), $LASTEXITCODE) }
    $output
}

function Get-TrackedChanges {
    @(Invoke-Git status --porcelain=v1 --untracked-files=no) | Where-Object { $_ }
}

function Get-Untracked {
    @(Invoke-Git status --porcelain=v1 --untracked-files=all) |
        Where-Object { $_ -like '?? *' } |
        ForEach-Object { $_.Substring(3) }
}

function Get-PlanRows {
    $inStatus = $false
    foreach ($line in ([IO.File]::ReadAllText($planPath, $utf8) -split "`r?`n")) {
        if ($line -match '^## 0\.') { $inStatus = $true; continue }
        if ($inStatus -and $line -match '^## ') { break }
        if (-not $inStatus -or $line -notmatch '^\|') { continue }
        # A chat may write the status in bold, **Done ...**.
        $cells = @($line.Trim().Trim('|').Split('|') | ForEach-Object { $_.Trim().Trim('*', '_', ' ') })
        if ($cells.Count -lt 4 -or $cells[0] -eq 'Step' -or $cells[0] -match '^-+$') { continue }
        [pscustomobject]@{
            Id = $cells[0]
            What = $cells[1]
            Gate = $cells[1].Contains($gateSign)
            Status = $cells[$cells.Count - 1]
        }
    }
}

# The first row that is not Done; a gate the owner marked "not blocking" is passed over.
function Get-NextRow {
    foreach ($row in @(Get-PlanRows)) {
        if ($row.Status -like 'Done*' -or $row.Status -like 'Open, not blocking*') { continue }
        return $row
    }
}

function Get-RowProblem($Row) {
    if ($null -eq $Row) { return 'every row of the plan is Done' }
    if ($Row.Gate) { return ('{0} is a gate: it needs the owner' -f $Row.Id) }
    if ($Row.Status -like 'Optional*') { return ('{0} is Optional: it needs the owner''s go' -f $Row.Id) }
    if ($Row.Status -notlike 'Open*') { return ('{0} is not Open: "{1}"' -f $Row.Id, (Get-ShortText $Row.Status 160)) }
}

function Get-ChatTitle([string]$Path) {
    $title = ''
    try {
        # The chat may be appending to its transcript right now.
        $stream = New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $reader = New-Object IO.StreamReader($stream, $utf8)
        try {
            while ($null -ne ($line = $reader.ReadLine())) {
                if ($line.Contains('"aiTitle":"') -and $line -match '"aiTitle":"([^"]*)"') { $title = $Matches[1] }
            }
        }
        finally {
            $reader.Dispose()
        }
    }
    catch { }
    return $title
}

# Chats in this folder whose transcript changed in the last -IdleMinutes, newest first.
function Get-RecentChats {
    $key = $repositoryRoot -replace '[^A-Za-z0-9]', '-'
    $projects = Join-Path $env:USERPROFILE '.claude\projects'
    $folder = @(Get-ChildItem -Path $projects -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq $key })
    if ($folder.Count -eq 0) { return }
    $since = (Get-Date).AddMinutes(-$IdleMinutes)
    Get-ChildItem -Path $folder[0].FullName -Filter '*.jsonl' -File |
        Where-Object { $_.LastWriteTime -gt $since } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            [pscustomobject]@{
                Id = $_.BaseName
                Minutes = [int][Math]::Floor(((Get-Date) - $_.LastWriteTime).TotalMinutes)
                Title = Get-ChatTitle $_.FullName
            }
        }
}

function Get-BranchProblem {
    $current = @(Invoke-Git rev-parse --abbrev-ref HEAD)[0]
    if ($current -ne $Branch) { return ('the checked-out branch is {0}, not {1}' -f $current, $Branch) }
}

function Get-StartBlocker([bool]$CheckChats) {
    $changes = @(Get-TrackedChanges)
    if ($changes.Count -gt 0) {
        return ('{0} tracked files are changed and not committed (first: {1})' -f $changes.Count, $changes[0].Substring(3))
    }
    if ($CheckChats) {
        $chats = @(Get-RecentChats)
        if ($chats.Count -gt 0) {
            return ('a chat wrote {0} min ago: "{1}" ({2}); the runner starts after {3} quiet minutes' -f $chats[0].Minutes, $chats[0].Title, $chats[0].Id, $IdleMinutes)
        }
    }
}

function Get-EnvironmentNotes {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        if ([System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus -eq 'Offline') {
            'On battery: tests and research runs take about twice as long. Keep the charger in and the lid open.'
        }
    }
    catch { }
    if (-not (Test-Path (Join-Path $repositoryRoot '.venv\Scripts\python.exe'))) {
        'The .venv is missing: the chats cannot run the test suite until it is rebuilt.'
    }
    $others = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'plan-runner\.ps1' -and $_.CommandLine -notmatch [regex]::Escape($repositoryRoot) })
    if ($others.Count -gt 0) {
        'Another project''s plan runner is running too. Both share the same Claude usage limits and this laptop''s CPU.'
    }
}

function Enter-RunnerLock {
    if (Test-Path $lockFile) {
        $text = [IO.File]::ReadAllText($lockFile).Trim()
        if ($text -match '^\d+$') {
            $other = Get-Process -Id ([int]$text) -ErrorAction SilentlyContinue
            if ($other -and $other.ProcessName -match '^(powershell|pwsh)$') {
                throw ('Another runner is running (process {0}). If it is not, delete {1}.' -f $text, $lockFile)
            }
        }
    }
    [IO.File]::WriteAllText($lockFile, [string]$PID, $utf8)
}

function Stop-ProcessTree([Diagnostics.Process]$Process) {
    if (-not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F | Out-Null }
}

function Read-ChatEvent([string]$Line, $Run) {
    # Tool output is most of the stream and holds nothing the runner needs.
    if ($Line.Length -gt 1000000) { return }
    $wanted = '"type":"system"', '"type":"result"', '"type":"assistant"', '"type":"rate_limit_event"'
    if (-not ($wanted | Where-Object { $Line.Contains($_) })) { return }
    try { $chatEvent = $Line | ConvertFrom-Json } catch { return }
    $type = Get-Field $chatEvent 'type'
    if ($type -eq 'rate_limit_event') {
        $Run.RateLimit = Get-Field $chatEvent 'rate_limit_info'
    }
    elseif ($type -eq 'system' -and (Get-Field $chatEvent 'subtype') -eq 'init') {
        $Run.Init = $chatEvent
        $Run.SessionId = Get-Field $chatEvent 'session_id'
        $Run.Model = Get-Field $chatEvent 'model'
        Write-Note ('Chat {0} started on {1}.' -f $Run.SessionId, $Run.Model)
        $onFallback = $Run.Fallback -and "$($Run.Model)" -like "$($Run.Fallback)*"
        if ("$($Run.Model)" -notlike "$($Run.Expected)*" -and -not $onFallback) { $Run.Stopped = ('it started on {0}, not {1}' -f $Run.Model, $Run.Expected) }
    }
    elseif ($type -eq 'result') {
        $Run.Result = $chatEvent
    }
    elseif ($type -eq 'assistant' -and -not (Get-Field $chatEvent 'parent_tool_use_id')) {
        foreach ($block in @(Get-Field (Get-Field $chatEvent 'message') 'content')) {
            if ((Get-Field $block 'type') -eq 'text') {
                $text = Get-ShortText ([string](Get-Field $block 'text')) 220
                if ($text) { Write-Host ('  {0:HH:mm}  {1}' -f (Get-Date), $text) }
            }
        }
    }
}

function Invoke-Chat {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WorkDir,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [string]$ResumeId,
        [string]$ChatModel = $script:model,
        [string[]]$ExtraArgs = @(),
        [string[]]$ExtraDeny = @()
    )
    $argList = @('-p', '--model', $ChatModel, '--effort', $effort,
        '--permission-mode', 'bypassPermissions', '--permission-prompts', 'none',
        '--output-format', 'stream-json', '--verbose', '--name', ('"{0}"' -f $Name))
    if ($ResumeId) { $argList += @('--resume', $ResumeId) }
    $fallback = ''
    if ($FallbackModel -and $FallbackModel -ne $ChatModel) {
        $fallback = $FallbackModel
        $argList += @('--fallback-model', $FallbackModel)
    }
    $argList += $ExtraArgs
    # Deny rules hold even in bypassPermissions. The list takes every value up to the end.
    $argList += '--disallowedTools'
    $argList += @(@($deniedTools) + $ExtraDeny | ForEach-Object { '"{0}"' -f $_ })

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = Get-ClaudeExe
    $startInfo.Arguments = $argList -join ' '
    $startInfo.WorkingDirectory = $WorkDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = $utf8
    $startInfo.StandardErrorEncoding = $utf8
    $startInfo.EnvironmentVariables['CLAUDE_CODE_EFFORT_LEVEL'] = $effort
    $startInfo.EnvironmentVariables['CLAUDE_CODE_SUBAGENT_MODEL'] = $ChatModel

    $run = [pscustomobject]@{ SessionId = $ResumeId; Expected = $ChatModel; Fallback = $fallback; Model = $null; Init = $null; Result = $null; RateLimit = $null; ExitCode = $null; Stopped = $null }
    $log = New-Object IO.StreamWriter($LogPath, $true, $utf8)
    $log.AutoFlush = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $finished = $false
    try {
        # The prompt goes through stdin as UTF-8: no command-line quoting, no code page.
        $stdin = New-Object IO.StreamWriter($process.StandardInput.BaseStream, $utf8)
        $stdin.Write($Prompt)
        $stdin.Close()
        $stderr = $process.StandardError.ReadToEndAsync()
        $deadline = (Get-Date).AddHours($StepHours)
        $lastOutput = Get-Date
        $pending = $process.StandardOutput.ReadLineAsync()
        while ($true) {
            if ($pending.Wait(15000)) {
                $line = $pending.Result
                if ($null -eq $line) { $finished = $true; break }
                $lastOutput = Get-Date
                $log.WriteLine($line)
                Read-ChatEvent $line $run
                if ($run.Stopped) { break }
                $pending = $process.StandardOutput.ReadLineAsync()
            }
            elseif ((Get-Date) -gt $deadline) {
                $run.Stopped = 'it ran past {0} hours' -f $StepHours
                break
            }
            elseif ($process.HasExited -and ((Get-Date) - $lastOutput).TotalSeconds -gt 60) {
                # A leftover child process can hold stdout open after claude.exe exits.
                $finished = $true
                break
            }
        }
    }
    finally {
        if ($finished) { [void]$process.WaitForExit(60000) }
        if (-not $process.HasExited) {
            Stop-ProcessTree $process
            [void]$process.WaitForExit(30000)
        }
        $log.Dispose()
    }
    if ($process.HasExited) { $run.ExitCode = $process.ExitCode }
    if ($stderr.Wait(5000) -and $stderr.Result.Trim()) {
        [IO.File]::WriteAllText($LogPath + '.stderr.txt', $stderr.Result, $utf8)
    }
    return $run
}

function Get-ResultText($Run) {
    return [string](Get-Field $Run.Result 'result')
}

# A usage limit or a passing API failure is worth a resume; anything else stops the runner.
function Test-Retryable($Run) {
    if ($Run.Stopped -or $null -eq $Run.Result) { return $false }
    if ((Get-Field $Run.RateLimit 'status') -eq 'rejected') { return $true }
    if (-not (Get-Field $Run.Result 'is_error')) { return $false }
    return (Get-ResultText $Run) -match '(?i)usage limit|limit reached|hit your limit|resets|overloaded|rate.?limit|\b(429|500|502|503|504|529)\b|timed? ?out|ECONN'
}

# Seconds until the usage window named in the chat's last rate-limit event resets, or 30
# minutes when it named none.
function Get-ResumeDelay($Run) {
    $resetsAt = $null
    if ((Get-Field $Run.RateLimit 'status') -eq 'rejected') { $resetsAt = Get-Field $Run.RateLimit 'resetsAt' }
    # Some limit messages carry the reset time themselves, as "...limit reached|<epoch seconds>".
    if (-not $resetsAt -and (Get-ResultText $Run) -match '\|(\d{10})\b') { $resetsAt = $Matches[1] }
    if ($resetsAt) {
        $seconds = ([DateTimeOffset]::FromUnixTimeSeconds([long]$resetsAt) - [DateTimeOffset]::UtcNow).TotalSeconds + 120
        if ($seconds -gt 60) { return [int]$seconds }
    }
    return 1800
}

# A weekly limit, the account's or one model's: it resets more than 12 hours away, or says so.
function Test-LongLimit($Run, [int]$Delay) {
    if ($Delay -gt 12 * 3600) { return $true }
    $type = [string](Get-Field $Run.RateLimit 'rateLimitType')
    if ((Get-Field $Run.RateLimit 'status') -eq 'rejected' -and $type -match '(?i)seven|week') { return $true }
    $text = Get-ResultText $Run
    return ($text -match '(?i)limit') -and ($text -match '(?i)week|seven.?day|7.?day')
}

function Get-UsageText($Run) {
    $windows = Get-Field $Run.RateLimit 'unifiedWindows'
    $parts = foreach ($name in 'five_hour', 'seven_day') {
        $used = Get-Field (Get-Field $windows $name) 'utilization'
        if ($null -ne $used) { '{0} {1:P0}' -f ($name -replace '_', '-'), [double]$used }
    }
    return (@($parts) -join ', ')
}

# Patterns from $secretPatterns that a line added since $From matches.
function Find-SecretPatterns([string]$From) {
    $added = @(Invoke-Git diff --unified=0 --no-color ('{0}..HEAD' -f $From)) |
        Where-Object { $_.StartsWith('+') -and -not $_.StartsWith('+++') }
    $text = @($added) -join "`n"
    foreach ($pattern in $secretPatterns) {
        if ($text -match $pattern) { $pattern }
    }
}

# Pushes the runner branch after a clean step. Returns '' when pushed, otherwise why not.
function Push-RunnerBranch([string]$From) {
    if (-not $Push) { return '' }
    if ($script:pushBlocked) { return 'not pushed: ' + $script:pushBlocked }
    $hits = @(Find-SecretPatterns $From)
    if ($hits.Count -gt 0) {
        $script:pushBlocked = 'a new commit matches a credential pattern ({0}); read it, then push by hand' -f ($hits -join ', ')
        return 'not pushed: ' + $script:pushBlocked
    }
    # git writes its progress to stderr; with Stop that would throw in Windows PowerShell.
    $ErrorActionPreference = 'Continue'
    $output = @(& git -C $repositoryRoot push --porcelain origin ('refs/heads/{0}:refs/heads/{0}' -f $Branch) 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
    foreach ($line in $output) { if ($line.Trim()) { Write-Note ('git push: ' + $line.Trim()) } }
    if ($code -ne 0) { return ('git push exited with {0}; the commits are safe locally' -f $code) }
    return ''
}

# Sleeps in five-minute pieces so a STOP file is noticed during a long wait.
function Wait-WithStop([int]$Seconds) {
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) {
        if (Test-Path $stopFile) { return }
        $left = [int][Math]::Ceiling(($until - (Get-Date)).TotalSeconds)
        Start-Sleep -Seconds ([Math]::Max(1, [Math]::Min(300, $left)))
    }
}

function Invoke-Step($Row) {
    $started = Get-Date
    $name = $chatPrefix + $Row.Id
    $base = Join-Path $logDir ('{0:yyyyMMdd-HHmm}-{1}' -f $started, ($Row.Id -replace '[^A-Za-z0-9.]', '_'))
    $log = $base + '.jsonl'
    $headBefore = @(Invoke-Git rev-parse HEAD)[0]
    $branchBefore = @(Invoke-Git rev-parse --abbrev-ref HEAD)[0]
    $untrackedBefore = @(Get-Untracked)
    $stepModel = Get-RowModel $Row.Id
    Write-Note ('Starting {0} in a new chat ({1}, effort {2}). Log: {3}' -f $Row.Id, $stepModel, $effort, $log)

    $run = Invoke-Chat -Prompt $stepPrompt.Replace('<<ROW>>', $Row.Id) -Name $name -WorkDir $repositoryRoot -LogPath $log -ChatModel $stepModel
    $fallbackNotes = New-Object System.Collections.Generic.List[string]
    $waits = 0
    while ((Test-Retryable $run) -and $waits -lt $MaxLimitWaits -and -not (Test-Path $stopFile)) {
        $waits++
        $reason = Get-ShortText (Get-ResultText $run) 200
        $delay = Get-ResumeDelay $run
        # A chat that never got a session id starts again with the whole step prompt.
        $prompt = $stepPrompt.Replace('<<ROW>>', $Row.Id)
        if ($run.SessionId) { $prompt = $resumePrompt -f $reason, $Row.Id }
        if (Test-LongLimit $run $delay) {
            $resetText = 'later this week'
            if ($delay -gt 12 * 3600) { $resetText = '{0:ddd HH:mm}' -f (Get-Date).AddSeconds($delay) }
            # A used-up weekly window resets days later: carry on with the fallback model, or wait.
            if ($FallbackModel -and $stepModel -ne $FallbackModel) {
                $script:exhaustedUntil[$stepModel] = (Get-Date).AddSeconds([Math]::Max($delay, 24 * 3600))
                $note = '{0} hit a limit that resets {1} ("{2}"); the chat carries on with {3}, and so do later rows until then' -f $stepModel, $resetText, $reason, $FallbackModel
                Write-Note $note
                $fallbackNotes.Add($note)
                $stepModel = $FallbackModel
                $run = Invoke-Chat -Prompt $prompt -Name $name -WorkDir $repositoryRoot -LogPath $log -ResumeId $run.SessionId -ChatModel $stepModel
                continue
            }
            # No reset time in the message: look again in six hours rather than every half hour.
            if ($delay -le 1800) { $delay = 6 * 3600 }
            $note = '{0} hit a limit that resets {1} ("{2}"); waiting until {3:ddd HH:mm}, then resuming the chat on the same model' -f $stepModel, $resetText, $reason, (Get-Date).AddSeconds($delay)
            Write-Note $note
            $fallbackNotes.Add($note)
        }
        else {
            Write-Note ('The chat stopped on "{0}". Resuming it at {1:HH:mm} ({2} of {3}).' -f $reason, (Get-Date).AddSeconds($delay), $waits, $MaxLimitWaits)
        }
        Wait-WithStop $delay
        if (Test-Path $stopFile) {
            Remove-Item $stopFile -ErrorAction SilentlyContinue
            $run.Stopped = 'the STOP file was found while waiting for a usage limit to reset'
            break
        }
        $run = Invoke-Chat -Prompt $prompt -Name $name -WorkDir $repositoryRoot -LogPath $log -ResumeId $run.SessionId -ChatModel $stepModel
    }

    $problems = New-Object System.Collections.Generic.List[string]
    if ($run.Stopped) { $problems.Add('the runner stopped the chat: ' + $run.Stopped) }
    elseif ($null -eq $run.Result) { $problems.Add(('the chat ended without a result (exit code {0})' -f $run.ExitCode)) }
    elseif (Get-Field $run.Result 'is_error') { $problems.Add('the chat ended with an error: ' + (Get-ShortText (Get-ResultText $run) 300)) }
    $changes = @(Get-TrackedChanges)
    if ($changes.Count -gt 0) { $problems.Add(('{0} tracked files are left changed and not committed' -f $changes.Count)) }
    $branchAfter = @(Invoke-Git rev-parse --abbrev-ref HEAD)[0]
    if ($branchAfter -ne $branchBefore) { $problems.Add(('the branch changed from {0} to {1}' -f $branchBefore, $branchAfter)) }
    $commits = @()
    if (@(Invoke-Git rev-parse HEAD)[0] -eq $headBefore) { $problems.Add('nothing was committed') }
    else { $commits = @(Invoke-Git log --oneline --no-decorate ('{0}..HEAD' -f $headBefore)) }
    # A row the chat split (R4a into R4a1 and R4a2) is gone; the next loop finds the rest.
    $rowAfter = @(Get-PlanRows | Where-Object { $_.Id -eq $Row.Id })
    if ($rowAfter.Count -gt 0 -and $rowAfter[0].Status -notlike 'Done*') {
        $problems.Add(('its row reads "{0}"' -f (Get-ShortText $rowAfter[0].Status 200)))
    }
    $newUntracked = @(Get-Untracked | Where-Object { $untrackedBefore -notcontains $_ })

    $report = Get-ResultText $run
    if ($report) { [IO.File]::WriteAllText($base + '-report.md', $report, $utf8) }
    $marker = ''
    if ($report -match '(?m)^\s*(RUNNER-RESULT:.*)$') { $marker = $Matches[1].Trim() }

    $ok = $problems.Count -eq 0
    $pushNote = ''
    if ($ok) { $pushNote = Push-RunnerBranch $headBefore }
    $outcome = 'stopped'
    if ($ok) { $outcome = 'done' }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add(('## {0}: {1}' -f $Row.Id, $outcome))
    $lines.Add(('- {0:yyyy-MM-dd HH:mm} to {1:HH:mm}, chat "{2}", session {3}, model {4}' -f $started, (Get-Date), $name, $run.SessionId, $run.Model))
    $billed = Get-Field $run.Result 'modelUsage'
    if ($billed) { $lines.Add('- Models used: ' + (($billed.PSObject.Properties | ForEach-Object { $_.Name }) -join ', ')) }
    foreach ($note in $fallbackNotes) { $lines.Add('- Fallback: ' + $note) }
    foreach ($commit in $commits) { $lines.Add('- Commit: ' + $commit) }
    foreach ($problem in $problems) { $lines.Add('- Problem: ' + $problem) }
    if ($Push -and $ok) {
        if ($pushNote) { $lines.Add('- Push: ' + $pushNote) }
        else { $lines.Add(('- Pushed {0} to origin.' -f $Branch)) }
    }
    if ($newUntracked.Count -gt 0) { $lines.Add('- New untracked files: ' + ($newUntracked -join ', ')) }
    if ($marker) { $lines.Add('- The chat says: ' + $marker) }
    $usage = Get-UsageText $run
    if ($usage) { $lines.Add('- Usage limits used at the end: ' + $usage) }
    $lines.Add(('- Report: {0}-report.md; log: {1}' -f $base, $log))
    [IO.File]::AppendAllText($summaryPath, ($lines -join "`r`n") + "`r`n`r`n", $utf8)
    Write-Note ('{0} {1}. {2}' -f $Row.Id, $outcome, ($problems -join '; '))
    return $ok
}

function Invoke-SelfTest([string]$TestModel) {
    $workDir = Join-Path $env:TEMP 'ai-trading-plan-runner-selftest'
    [IO.Directory]::CreateDirectory($workDir) | Out-Null
    $log = Join-Path $logDir ('selftest-{0:yyyyMMdd-HHmmss}-{1}.jsonl' -f (Get-Date), $TestModel)
    $prompt = "This is a self-test of an automation script. Do exactly three things.`n" +
        "1. Run this command with the Bash tool: echo runner-selftest-blocked hello`n" +
        "2. Run this command with the Bash tool: echo hello runner-selftest-inner`n" +
        "3. Reply with exactly two words, one for each command in order: BLOCKED if it was refused, RAN if it ran."
    Write-Note ('Self-test of {0}: one small chat in {1}. Log: {2}' -f $TestModel, $workDir, $log)
    $run = Invoke-Chat -Prompt $prompt -Name 'AI trading runner self-test' -WorkDir $workDir -LogPath $log -ChatModel $TestModel `
        -ExtraArgs @('--no-session-persistence', '--strict-mcp-config') -ExtraDeny @('Bash(echo runner-selftest-blocked *)', 'Bash(*runner-selftest-inner*)')
    $answer = Get-ShortText (Get-ResultText $run) 200
    $words = @([regex]::Matches($answer.ToUpperInvariant(), '\b(BLOCKED|RAN)\b') | ForEach-Object { $_.Value })
    $first = ''
    if ($words.Count -ge 1) { $first = $words[0] }
    $second = ''
    if ($words.Count -ge 2) { $second = $words[1] }
    $usage = Get-Field $run.Result 'modelUsage'
    $models = ''
    if ($usage) { $models = ($usage.PSObject.Properties | ForEach-Object { $_.Name }) -join ', ' }
    $effortFields = ''
    if ($run.Init) {
        $effortFields = ($run.Init.PSObject.Properties | Where-Object { $_.Name -match 'effort|thinking' } |
            ForEach-Object { '{0}={1}' -f $_.Name, ($_.Value | ConvertTo-Json -Compress -Depth 3) }) -join ', '
    }
    Write-Note ('Model at start: {0}. Models billed: {1}. Exit code: {2}.' -f $run.Model, $models, $run.ExitCode)
    Write-Note ('Effort fields at start: {0}' -f $(if ($effortFields) { $effortFields } else { 'none reported' }))
    Write-Note ('Answer: {0}. Refused tool calls: {1}.' -f $answer, @(Get-Field $run.Result 'permission_denials').Count)
    Write-Note ('Usage limits used: {0}. Retry if it hit a limit: {1}.' -f (Get-UsageText $run), (Test-Retryable $run))
    if ($second -eq 'BLOCKED') { Write-Note 'A deny rule with a leading wildcard held too, so the demo-script rules work.' }
    else { Write-Note 'A deny rule with a leading wildcard did NOT hold: the demo-script rules are not effective. The missing OKX credentials still stop those scripts.' }
    $passed = ("$($run.Model)" -like "$TestModel*") -and $null -ne $run.Result -and -not (Get-Field $run.Result 'is_error') -and $first -eq 'BLOCKED'
    if ($passed) { Write-Note ('Self-test passed: {0}, the effort flag accepted, and a deny rule held in bypassPermissions.' -f $TestModel) }
    else { Write-Note ('Self-test of {0} FAILED: read the log above.' -f $TestModel) }
    return $passed
}

function Get-CutoffText {
    if ($stepCutoff) { return ('; no step starts after {0:ddd HH:mm}' -f $stepCutoff) }
    return ''
}

function Show-DryRun {
    Write-Note ('Claude: {0}' -f (Get-ClaudeExe))
    Write-Note ('Status table: {0}{1}.' -f $planPath, (Get-CutoffText))
    Write-Note ('Each chat: --effort {0} ({1}), bypassPermissions, deny rules for git push/merge/rebase, ssh, scp and the demo-trading scripts, at most {2} hours. Branch: {3}.' -f $effort, (Get-RowModelText), $StepHours, $Branch)
    if ($Push) { Write-Note ('After each clean step the runner pushes {0} to origin, unless a new commit looks like it holds a credential.' -f $Branch) }
    else { Write-Note 'Nothing is pushed (no -Push).' }
    foreach ($note in @(Get-EnvironmentNotes)) { Write-Note ('Note: ' + $note) }
    foreach ($chat in @(Get-RecentChats)) {
        Write-Note ('Active in the last {0} min: "{1}" ({2}), {3} min ago' -f $IdleMinutes, $chat.Title, $chat.Id, $chat.Minutes)
    }
    $branchProblem = Get-BranchProblem
    if ($branchProblem) { Write-Note ('Would not start now: ' + $branchProblem) }
    $blocker = Get-StartBlocker $true
    if ($blocker) { Write-Note ('Would not start now: ' + $blocker) }
    elseif (-not $branchProblem) { Write-Note 'Nothing blocks a start now.' }
    $row = Get-NextRow
    $problem = Get-RowProblem $row
    if ($problem) { Write-Note ('Next row: ' + $problem) }
    else { Write-Note ('Next row: {0} on {1}, {2}' -f $row.Id, (Get-RowModel $row.Id), (Get-ShortText $row.What 120)) }
}

if ($SelfTest) {
    $allPassed = $true
    foreach ($testModel in @(@($model) + @($RowModels.Values) + @(@($FallbackModel) | Where-Object { $_ }) | Select-Object -Unique)) {
        if (-not (Invoke-SelfTest $testModel)) { $allPassed = $false }
    }
    if ($allPassed) { exit 0 }
    exit 1
}
if ($DryRun) {
    Show-DryRun
    exit 0
}

Enter-RunnerLock
try {
    $pushText = ''
    if ($Push) { $pushText = '; it pushes {0} after each clean step' -f $Branch }
    Write-Note ('Runner started on {0}: up to {1} steps{2}, each a new chat at {3} effort ({4}), on branch {5}{6}.' -f $planPath, $MaxSteps, (Get-CutoffText), $effort, (Get-RowModelText), $Branch, $pushText)
    foreach ($note in @(Get-EnvironmentNotes)) { Write-Note ('Note: ' + $note) }
    $steps = 0
    $lastBlocker = ''
    while ($true) {
        if (Test-Path $stopFile) {
            Remove-Item $stopFile
            Write-Note 'Found the STOP file: stopping before the next step.'
            break
        }
        $branchProblem = Get-BranchProblem
        if ($branchProblem) { Write-Note ('Stopping: ' + $branchProblem + '. The runner never switches branches.'); break }
        $blocker = Get-StartBlocker ($steps -eq 0 -and -not $Force)
        if ($blocker) {
            if (-not $WaitForIdle) { Write-Note ('Not starting: ' + $blocker); break }
            if ($blocker -ne $lastBlocker) { Write-Note ('Waiting: ' + $blocker) }
            $lastBlocker = $blocker
            Start-Sleep -Seconds 300
            continue
        }
        $row = Get-NextRow
        $problem = Get-RowProblem $row
        if ($problem) { Write-Note ('Stopping: ' + $problem + '.'); break }
        if ($steps -ge $MaxSteps) { Write-Note ('Stopping after {0} steps (-MaxSteps). Next is {1}.' -f $steps, $row.Id); break }
        if ($stepCutoff -and (Get-Date) -gt $stepCutoff) { Write-Note ('Stopping: it is past {0:HH:mm} (-NoNewStepAfter). Next is {1}.' -f $stepCutoff, $row.Id); break }
        $steps++
        if (-not (Invoke-Step $row)) { Write-Note ('Stopped. Read {0}' -f $summaryPath); break }
    }
}
finally {
    Remove-Item $lockFile -ErrorAction SilentlyContinue
}
