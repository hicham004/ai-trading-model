# Runbook — the tokenized-stocks data collector (plan row R21)

**Audience:** the human operator, or an agent session acting for the owner on this laptop.
Starting the collector is an owner action; it costs nothing (public market data only) and
nothing it does can trade. Design and findings: `docs/research/TOKENIZED_STOCKS_FEASIBILITY.md`,
`docs/design/TOKENIZED_STOCKS.md`.

## What it is, and what it is not

`scripts/collect_xstocks.py` reads OKX's public market-data pages for the 15 most traded
tokenized US stock pairs (`docs/research/xstocks_universe.json`: XCRCL, XGOOGL, XQQQ, XINTC,
XSOXL, XMSTR, XSNDK, XNVDA, XSPCX, XMU, XAMD, XSKHY, XSPY, XMRVL, XTSLA, all `-USDT`) and writes:

- the venue's parameters for each pair once a day (`instruments/<day>.json`);
- 1H and daily (`1Dutc`) candles back to each pair's listing, topped up every hour
  (`candles/<pair>/<bar>/<year>.parquet`);
- an order-book snapshot of every pair (400 levels requested, the levels within 2 % of mid
  stored, with the spread and the depth within 0.5 % computed) at four kinds of moments
  (`books/<pair>/<day>.jsonl`):

| Slot | When | In UTC |
|---|---|---|
| `us_open` | 09:30 New York, Monday to Friday (US holidays included and labelled) | 14:30 in winter, 13:30 in summer (converted at run time) |
| `us_close` | 16:00 New York, Monday to Friday | 21:00 in winter, 20:00 in summer |
| `utc_03` | 03:00 UTC every day | 03:00 |
| `sat_12` | 12:00 UTC on Saturdays | 12:00 |

A slot missed by less than 30 minutes (a restart, a sleep) is still taken; one missed by more
is skipped and recorded as such by its absence. Everything lives under `data/lake/xstocks/`
(git-ignored) in the research lake's layout.

- It places, sizes, approves, modifies and cancels **nothing**; it holds **no keys** and never
  sends the demo header; its only network path is the data lake's GET-only public client on
  six public endpoints (instruments, tickers, candles, history-candles, books, price-limit).
- It does not touch the paper fleet's folder, the demo database, `shadow.service` or the news
  shadow, and the app's instrument allowlist (BTC-USDT, ETH-USDT) is unchanged.
- The universe is fixed in the committed file; `--select-universe` is not run again unless the
  owner decides to start a new record (it refuses to overwrite without `--force`).

## Where it runs

**On the server (what runs since 2026-11-06 11:32 UTC, on the droplet `ubuntu-s-1vcpu-1gb-sgp1`; the
laptop task is disabled):** next to the paper fleet, installed with it by
the one line of `docs/runbooks/PAPER_FLEET.md`, option A1, as `xstocks-data.service` from the
checkout `/opt/ai-trading-research` (the user `ai-research`, the system read-only except
`data/lake/xstocks/`, every home folder hidden, capped at a quarter of a core and 512 MB, first in
line for the out-of-memory killer). The server never sleeps, so no US-open or US-close snapshot is
missed for a closed laptop lid. Status: `sudo bash /opt/ai-trading-research/scripts/vps_research_setup.sh
status`; its log: `sudo journalctl -u xstocks-data -n 30 --no-pager`. A first install on the server
starts its own lake (the candle history comes back in about five minutes; the few laptop snapshots
stay on the laptop), and the laptop task is then disabled (one record, one place).

**On the laptop (how it ran from 2026-11-05 until the move):** next to the paper fleet, from the fleet's own checkout (`C:\Users\Admin\Desktop\ai-trading-fleet`,
`docs/runbooks/PAPER_FLEET.md`, option B2), so that the plan runner's edits in the repository
folder never reach a running collector. The checkout must carry plan row R21 (update it first:
the fleet's "Updating the fleet's code" step, which also restarts the fleet; the collector can be
set up in the same session).

## Setup (once, about five minutes)

```powershell
cd C:\Users\Admin\Desktop\ai-trading-fleet
git pull                                                   # plan/auto with row R21 (after the fleet's STOP file, as its runbook says)
.venv\Scripts\python.exe scripts\collect_xstocks.py --status      # "universe selected 2026-11-05T08:11:15Z", every pair with 0 rows: nothing collected here yet
.venv\Scripts\python.exe scripts\collect_xstocks.py --once --snapshot-now   # the first pass: parameters, 42,000 candles (about 4 minutes), one ad-hoc book per pair
.venv\Scripts\python.exe scripts\collect_xstocks.py --status      # every pair: 1H 2,6xx rows from 2026-07-16, 1Dutc 11x rows, snapshots 1

# the task: at logon, in the logged-on session (like the fleet's), restart on failure, never stopped on battery
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Admin\Desktop\ai-trading-fleet\scripts\xstocks-task.ps1"' `
    -WorkingDirectory 'C:\Users\Admin\Desktop\ai-trading-fleet'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'AI Trading xstocks data' -Action $action -Trigger $trigger -Settings $settings `
    -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited)
Start-ScheduledTask -TaskName 'AI Trading xstocks data'
```

`scripts/xstocks-task.ps1` runs `collect_xstocks.py --loop`, appends its output to
`logs\xstocks\console.log`, watches for the STOP file, and starts the collector again a minute
after it exits (exit code 2, a setup problem, stops the loop instead). The loop itself: a full
pass at the start (the first run collects the whole history if `--once` was skipped), then the
snapshots at their slots, the 1H candles topped up 90 seconds after every hour, the daily candles
and the parameter record once a day after 00:00 UTC.

## Check that it works (first day)

```powershell
Get-ScheduledTask -TaskName 'AI Trading xstocks data' | Select-Object State      # Running
Get-Content C:\Users\Admin\Desktop\ai-trading-fleet\logs\xstocks\console.log -Tail 20
# "xstocks collector started: 15 pairs, lake ...\data\lake\xstocks", then one line per pair and bar ("added=0" once the history is in),
# "top-up <hour>: bars ['1H'], 15 candle(s) added" every hour, and at the next slot "snapshot us_open@...: 15 book(s) stored"
C:\Users\Admin\Desktop\ai-trading-fleet\.venv\Scripts\python.exe C:\Users\Admin\Desktop\ai-trading-fleet\scripts\collect_xstocks.py --status
# the 1H "max" within the last hour; "slots taken" growing by 2 on weekdays (3 on the day's 03:00 UTC pass, 4 with Saturday's)
```

The first `us_open` snapshot comes at 14:30 UTC (winter) on the first weekday after the start;
the first `us_close` at 21:00 UTC. Verified live on 2026-11-05 from the repository folder: a
52-minute `--loop --max-minutes 52` run started 08:15:24 UTC, topped the 1H candles up at
09:01:30 UTC ("bars ['1H'], 15 candle(s) added") and stopped by itself at 09:07:24 UTC with 0
errors; no snapshot slot fell inside that window.

## Reading the data

```powershell
C:\Users\Admin\Desktop\ai-trading-fleet\.venv\Scripts\python.exe C:\Users\Admin\Desktop\ai-trading-fleet\scripts\collect_xstocks.py --report --out C:\Users\Admin\Desktop\ai-trading-fleet\logs\xstocks\feasibility.json
```

prints the four tables of the feasibility report (universe and parameters; history and volume;
weekend gaps, open jumps and weekend falls; spread and depth per slot) from the files, no network,
and writes their JSON. The report in the repository (`docs/research/TOKENIZED_STOCKS_FEASIBILITY.md`)
is rewritten from these at the decision gate (plan section 6.2, step 4; 60-90 days). An agent
session can read the lake directly with `research.xstocks_data.read_xstock_candles` and
`read_snapshots`.

## Status, stop, restart, update, remove

```powershell
New-Item C:\Users\Admin\Desktop\ai-trading-fleet\logs\xstocks\STOP     # STOP: the wrapper ends the collector within ~15 s and exits (task: Ready)
Start-ScheduledTask -TaskName 'AI Trading xstocks data'                # run it again; it resumes (candle cursors and taken slots are on disk)
Unregister-ScheduledTask -TaskName 'AI Trading xstocks data' -Confirm:$false   # remove the task; keep data\lake\xstocks\ (it is the record)
```

Use the STOP file to stop, not `Stop-ScheduledTask` (which ends only the wrapper and leaves the
collector running until the next start, exactly as with the fleet). Updating the code: STOP, `git
pull` in the checkout, `--status`, start the task; the collector resumes. A pair that OKX delists
or suspends is reported in the daily parameter record (`missing` / `not_live`) and in the pass
lines; it stays in the universe and its series simply stop growing.

Two collectors on one folder would write the same files: the wrapper ends a leftover collector
process before starting a new one, and `--once` runs from the repository folder write a different
lake (`data\lake\xstocks` of that folder), so the fleet checkout's record is never mixed with
the runner's.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `xstocks collector not started: no universe file at docs\research\xstocks_universe.json` (exit 2) | The checkout does not carry plan row R21, or the file was deleted | Update the checkout (`git pull`); never re-run `--select-universe` to replace it unless a new record is wanted |
| `ERROR PublicRestError: rate limited (HTTP 429)` lines | OKX's public limit was hit (the fleet and the collector share this machine's address) | Nothing; the client retries, the loop goes on, the next top-up fills what was missed. If it repeats every hour, raise `--sleep` to 0.3 in the wrapper's command line |
| `snapshot ...: 0 book(s) stored, 15 error(s)` | The network or OKX was down at the slot | The slot stays untaken for 30 minutes and the loop retries every 30 seconds; after that it is missed, which the absence in `--status` shows |
| `instruments: ERROR ...` | The parameter page could not be read at the day's first pass | The next day's pass records it; the candle walk uses the last recorded `listTime` |
| `XSPY-USDT: no listTime recorded, candles skipped` | No parameter record exists yet (the very first pass failed on the instruments page) | Run `--once` again once the network is back |
| `--status` shows a pair's 1H `max` more than two hours old while the task runs | The hourly top-up is failing for that pair (OKX not answering, or the pair suspended: see `not_live` in `instruments\latest.json`) | Read `console.log`; a suspended pair is left as it is |
| `the collector exited with code 2 ... not restarting` in `console.log` | A setup problem (the universe file, a bad option) | Fix it, then `Start-ScheduledTask` |

## Disk and memory

The 112 days of candles for the 15 pairs take 1.7 MB; a snapshot record is 5-12 KB (the levels
within 2 % of mid), so the four daily slots add about 0.5 MB a day, about 45 MB per quarter. The
collector uses one CPU core for a few seconds an hour and about 150 MB of memory while it runs.
Measured on Linux (2026-11-06): the first pass (42,414 candles, 15 order books, 0 errors) took 3.5 minutes and peaked at 308 MB; as a service with one thread per maths library it held 65 to 100 MB (capped at 512 MB and a quarter of a core).

## After 60-90 days (plan section 6.2, step 4)

Hand the lake (`data\lake\xstocks\`) or the `--report` output to an agent session for the
decision gate: are spreads, weekend falls and depth at the open and close good enough for the
Trader policy's stops? The answer feeds an owner decision; nothing here authorizes a strategy
study, demo trading or any change to the safety core.
