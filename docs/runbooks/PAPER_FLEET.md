# Runbook — the paper fleet (plan rows R5a → G6)

**Audience:** the human operator. Starting the fleet 24/7 is an owner action
(plan row G6): on the DigitalOcean VPS next to the Phase 6a shadow (option A,
recommended) or on this Windows laptop left on (option B). **Agents cannot
reach the VPS.** It costs nothing: public market data only.

## What it is, and what it is not

The paper fleet runs every configuration of the Sprint 2c shortlist
(`docs/research/paper_fleet_shortlist_v1c.json`) forward in time on live public
OKX prices, each as its own pretend account with 10,000 virtual USDT:

- the 10 shortlisted rules (`c01` … `c10`; `c01` is S1+S5 on BTC 6H, the only
  one the untouched 12-month holdout confirmed),
- the jointly sized BTC+ETH × S1/S2/S4 portfolio (`pf-s1s2s4-btceth-vt15`:
  15 % volatility target, drawdown ladder half at 7.5 %, flat at 15 %),
- its twin with **allocator v2** (`pf-s1s2s4-btceth-vt15-alloc2`, plan row
  R5b): the same six strategies and the same sizing, plus brakes that each
  scale its own sizing down — a bet holding more than 50 % of the money at the
  day's close is cut back to 50 % (BTC and ETH count as one bet while they move
  together), and 7 days out of the market after losing 5 % in a week — so the
  difference between the two accounts shows whether the brakes help,
- 8 controls: *always long with the policy sizing* (`ctl-hold-…`, the same
  volatility target, crash filter and drawdown ladder, no timing) and *plain
  buy-and-hold* (`ctl-bh-…`) on BTC and ETH, 4H and 6H,
- since plan row R12 (2026-11-04), the two configurations the replication study
  confirmed on a market the rules were never tuned on: S1+S5 and S1 on SOL-USDT
  6H without the regime gate (`c11-s1s5-sol-6h-none`, `c12-s1-sol-6h-none`;
  see "A configuration confirmed on another market" below),
- since plan row R13 (2026-11-04), the one configuration research round 1
  confirmed: S1 with new entries only on bars whose 30-day volume z-score is
  above 1, on BTC-USDT 4H with the regime gate (`c13-s1vc-btc-4h-gate`; see
  "A configuration confirmed by research round 1" below),
- since plan row R16 (2026-11-04), the one configuration research round 2
  confirmed: the same volume confirmation on S1, on DOGE-USDT 4H with the
  regime gate (`c14-s1vc-doge-4h-gate`; see "A configuration confirmed by
  research round 2" below).

24 accounts in all (20 before R12, 22 before R13, 23 before R16). Each one follows exactly the research rules — the same
entry rules, filters, sizing, stops, fees (0.10 %) and slippage (0.05 %) — and
writes every decision and every pretend fill into its own journal. Once a week
a report compares what each account did with what the backtest said it should
do, controls first.

Every 180 days each account (except plain buy-and-hold, which never sells)
closes its position and starts over, exactly as each test window of the
research's backtest did. That is what keeps its numbers comparable with the
research: the research re-sized every position at those restarts, and without
them a position held for months could only ever be made smaller.

- It places, sizes, approves, modifies and cancels **nothing**. Every fill is
  arithmetic on public prices inside the program.
- It needs and holds **no keys**: no OKX keys, no Anthropic key, no Telegram
  token. It talks only to OKX's public market-data pages (candles, funding rate,
  open interest), never to an account page. It never opens the demo database
  and never touches `shadow.service` or the news shadow.
- It writes only its own folder, `logs/paper_fleet/` (journals, reports, state
  and its own copy of the public price history).
- A good forward record approves nothing. It is evidence for your later
  decision at plan row G7 (Phase 7 validation), not the decision.

**Why it matters:** the research is a backtest. Only forward numbers — prices
that did not exist when the rules were chosen — show whether the edge is real.
The fleet produces them for free, next to the honest yardstick (holding with
the same risk controls).

## When the evidence starts to mean something

- Every account starts flat at the first 4-hour or 6-hour bar that closes after
  the fleet's very first start. Nothing earlier counts.
- First 30 days: the report says "too early" everywhere. Numbers move, but
  they are mostly noise.
- From 30 days: each account gets a verdict against its backtest (see "Reading
  the report"), and the ranking starts.
- From about 90 days: the ranking by risk-adjusted return starts to mean
  something. Plan row G7 asks for at least 60 days of forward evidence.

## Before you start (both options)

1. **The code is on the machine.** The fleet arrives with the `plan/auto` pull
   request (plan row G2). On the VPS, update the checkout as in
   `docs/runbooks/VPS_8443_UPDATE.md`, Path B steps 1–2:

   ```bash
   cd /path/to/ai-trading-model                     # the checkout shadow.service runs from
   git fetch && git status                          # clean, on main
   git pull
   .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
   ```

   Updating the checkout does not restart `shadow.service`.

2. **Offline check** (no internet, no keys, a few minutes):

   ```bash
   .venv/bin/python scripts/run_paper_fleet.py --dry-run          # VPS
   .venv\Scripts\python.exe scripts\run_paper_fleet.py --dry-run  # laptop (PowerShell)
   ```

   It replays the last 3 days of recorded prices (or a made-up market when the
   machine has no price history) through the whole fleet and must end with every
   line `check: … ok`. It writes only to a new temporary folder, printed at the
   end. Nothing is sent to the network.

## Option A (recommended) — the VPS, as a service

```bash
cd /path/to/ai-trading-model
REPO=$(pwd)
RUN_AS=$(stat -c %U "$REPO")                 # the user that owns the checkout
mkdir -p logs/paper_fleet && sudo chown -R "$RUN_AS": logs/paper_fleet
sed -e "s#/path/to/ai-trading-model#$REPO#g" -e "s#CHANGE_ME_USER#$RUN_AS#g" \
    deploy/systemd/paper-fleet.service | sudo tee /etc/systemd/system/paper-fleet.service > /dev/null
sudo systemd-analyze verify /etc/systemd/system/paper-fleet.service
sudo systemctl daemon-reload
sudo systemctl enable --now paper-fleet.service
sudo systemctl status paper-fleet.service --no-pager
```

`systemd-analyze verify` must print nothing (or only warnings about other
units). The service needs no environment file; `deploy/systemd/paper-fleet.env.example`
lists the three optional settings (none of them secret).

The first start downloads about 2.5 years of public hourly prices for BTC and
ETH from OKX (a minute or two) unless a research data lake exists on the
machine, in which case it copies that and only tops it up.

## Option B — this laptop

In a PowerShell window in the repository folder:

```powershell
.venv\Scripts\python.exe scripts\run_paper_fleet.py --loop
```

Leave the window open. If the laptop sleeps or the window is closed, the fleet
simply waits; when it runs again it catches up bar by bar, using for every
missed bar only the prices that existed at that bar, so the result is the same
as if it had never stopped. Do not run it on the VPS **and** the laptop as the
"real" fleet: pick one place and keep it there, so there is one record.

### Option B2 — this laptop, as a Windows scheduled task from its own checkout (what runs since 2026-11-04)

A window can be closed by mistake, and the repository folder is where the plan
runner's chats edit and test code. So the fleet runs from a **separate
checkout** of `plan/auto` with its own `.venv`, started by a scheduled task
that restarts it after a crash or a reboot. Runner chats never touch that
folder, and the fleet never sees a half-edited file.

```powershell
# one-time setup (done 2026-11-04)
cd C:\Users\Admin\Desktop
git clone --branch plan/auto "C:\Users\Admin\Desktop\AI Trading model" ai-trading-fleet
cd ai-trading-fleet
git remote set-url origin https://github.com/hicham004/ai-trading-model.git
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\run_paper_fleet.py --dry-run        # every line "check: ... ok"

# the task: at logon (a boot trigger and the S4U logon type need administrator rights, so the task
# runs in the logged-on session like the plan runner's), restart on failure, never stopped on battery
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Admin\Desktop\ai-trading-fleet\scripts\paper-fleet-task.ps1"' `
    -WorkingDirectory 'C:\Users\Admin\Desktop\ai-trading-fleet'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'AI Trading paper fleet' -Action $action -Trigger $trigger -Settings $settings `
    -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited)
Start-ScheduledTask -TaskName 'AI Trading paper fleet'
```

`scripts/paper-fleet-task.ps1` runs `run_paper_fleet.py --loop`, appends its
output to `logs\paper_fleet\console.log`, watches for the STOP file, and starts
the fleet again a minute after it exits (exit code 2, a setup problem, stops the
loop instead). Day to day:

```powershell
Get-ScheduledTask -TaskName 'AI Trading paper fleet' | Select-Object State          # Running
Get-Content C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\console.log -Tail 20
C:\Users\Admin\Desktop\ai-trading-fleet\.venv\Scripts\python.exe C:\Users\Admin\Desktop\ai-trading-fleet\scripts\run_paper_fleet.py --status
New-Item C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\STOP   # STOP: the wrapper ends the fleet within ~15 s and exits (task: Ready)
Start-ScheduledTask -TaskName 'AI Trading paper fleet'     # run it again; it resumes and catches up
```

Use the STOP file to stop, not `Stop-ScheduledTask`: that ends only the wrapper
script, and Windows leaves the fleet process itself running (verified
2026-11-04). It does no harm (the fleet keeps working on its own), and the next
`Start-ScheduledTask` first ends such a leftover process and starts fresh; but
to stop everything right now, use STOP.

Reports: `C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\reports\weekly-YYYY-Www.md`.
The laptop does not sleep while plugged in; if it sleeps or reboots anyway,
the task starts again when the owner logs on and the fleet catches up bar by
bar (missed bars are replayed with the prices of their own time).

**Updating the fleet's code** (a new shortlist account from a research row, a
bug fix): stop the task, `git pull` in the fleet checkout, run `--dry-run`,
start the task. If `git pull` refuses because an untracked file "would be
overwritten by merge", that file was copied in by hand before it was
committed: delete it and pull again (the pulled copy is the same content). The fleet resumes in its folder; an added account joins at
that restart, and changed rules of an existing account are refused (exit 2),
as the troubleshooting table says. A data fix reaches the running fleet the same
way: plan row R17's positioning data for the SOL and DOGE accounts (see
"Positioning data for the S5 filter on the replication markets" below) takes
effect at the first restart from a checkout that carries it.

**Moving the record to the VPS later** (option A): stop the task, copy the
whole `logs\paper_fleet\` folder to the VPS checkout at the same code
version (`git log -1` in both places), then start `paper-fleet.service`
there. The fleet resumes from the copied state; the laptop task stays stopped
(one record, one place).

## Check that it works (first hour)

```bash
journalctl -u paper-fleet.service -n 30 --no-pager      # VPS; option B: the PowerShell window; B2: logs\paper_fleet\console.log
# expect "paper fleet created: …/logs/paper_fleet (24 accounts, …)" (20 on code from before plan row R12, 22 before R13, 23 before R16) and, once a 4H or 6H bar closes
# (00, 04, 08, 12, 16, 20 h UTC), a line "cycle N: bars {…} …"
.venv/bin/python scripts/run_paper_fleet.py --status
# every account with its equity (10,000.00 at the start), "flat"/"long", data "fresh"; since plan row R17 also one line
# "positioning data (S5 filter, ...)" with a newest funding / open-interest value for EVERY market (none "missing"), and under
# each S5 account its label ("S5 data current")
sudo systemctl status shadow.service --no-pager && cat logs/shadow/heartbeat.json
# the Phase 6a run is untouched
```

The first decisions are made when the first bar closes after the start; the
first pretend fills happen one bar later (4–6 hours).

## Reading the report

`logs/paper_fleet/reports/weekly-YYYY-Www.md` — one file per week (Monday to
Sunday, UTC), rewritten every hour during the week ("week to date") and marked
"final" once the week is over. Rebuild any week by hand with
`scripts/run_paper_fleet.py --report 2026-W44`.

- **In short** — how long the fleet has run, how the controls did, the best
  account so far (only after 30 days), and how many accounts look consistent
  with, worse than or better than their backtest.
- **Controls (read these first)** — *always long with the policy sizing* and
  *plain buy-and-hold*. A timing rule is only worth anything if it beats these
  forward.
- **Ranking** — every configuration and the portfolio with its return, the
  difference to its control on the same market ("vs its control"), the worst
  fall from a peak ("Max DD"), trades, fees, and five checks against the
  backtest:
  - *Return*: is the forward return inside the range the backtest would
    plausibly produce over the same number of days (its yearly return ± 2
    standard deviations of its yearly ups and downs)? **below** = worse than the
    backtest, **above** = better, **within** = consistent.
  - *Sharpe* (from 90 days): the same question for return per unit of risk.
  - *Drawdown*: **above backtest worst** if the account fell further than the
    worst fall of its whole 5-year backtest; **ALARM** if 1.5 times that. An
    alarm is evidence against that configuration.
  - *Trade count*: about as many trades as the backtest made per year?
  - *Holdout pace*: the return range built from the untouched last 12 months of
    the research, where there is one.
- **Allocator v2** — the allocator-v2 account next to *v1 on the same
  sleeves* (the old rules booked inside the same journal, so the difference is
  the brakes alone) and the v1 portfolio account; every brake that acted (on
  how many days the 50 % cap trimmed the book, each weekly loss-limit trip with
  its date, the days in cash afterwards); what the allocator is doing now; and
  what the backtest expected. Its research: `docs/research/ALLOCATOR_V2_REPORT.md`.
  Note: over the untouched last 12 months of the research both portfolio
  accounts lost (v2 −9 %, v1 −15 %, while BTC fell 26 % and ETH 39 %); they run
  forward anyway because the forward record is the honest test.
- **This week** — the week's return, trades and fees, and what each account
  holds now.
- **Data and health** — the last bars processed, bars skipped because OKX
  never delivered a candle, the regime models in use, and warnings.

These ranges were fixed in the code before the fleet produced a single forward
number. Moving them after seeing results would be tuning on the forward test.

## Status, stop, restart, remove

```bash
.venv/bin/python scripts/run_paper_fleet.py --status       # reads files only, no network
sudo systemctl stop paper-fleet.service                    # nothing in trading changes
sudo systemctl restart paper-fleet.service                 # resumes; missed bars are caught up in order
sudo systemctl disable --now paper-fleet.service
sudo rm /etc/systemd/system/paper-fleet.service && sudo systemctl daemon-reload
```

Keep `logs/paper_fleet/` when you stop: it is the record. Deleting it and
starting again starts a new forward record from zero.

### A new FOMC calendar on a running fleet (plan row R7)

The no-trade filter reads its FOMC meeting calendar (`research/events.py`) when
the program starts. Plan row R7 checked that calendar against the Federal
Reserve's published one (all 2020–2026 dates right) and added the 2027 meetings;
before R7 it ended on 2026-12-09. A fleet started before R7 needs only the
updated checkout ("Before you start", step 1) and one restart, at any time
before the first 2027 meeting (statement on 2027-01-27; the filter's window
opens at 12:00 UTC that day):

```bash
sudo systemctl restart paper-fleet.service   # resumes in the same folder
```

Nothing else: the same folder, no new account, no migration. The calendar's
dates are not part of any fingerprint (the shared rules name the filter,
`FOMC±6/6h`, not its dates), so the fleet resumes, and every decision already
made stands. R7 changed no date before 2027, so a fleet restarted before that
first window continues exactly as if it had always had the new calendar
(tested); one restarted later simply did not block entries around the meetings
that passed in between. Without the restart the fleet keeps running but does
not block entries around the 2027 meetings, and the weekly reports the service
writes keep saying "FOMC calendar runs out".
A fleet started after R7 needs nothing until late 2027, when the 2028 dates are
added and the service restarted the same way (the report starts warning 60 days
before 2027-12-08; how to add them: `tests/fixtures/fomc_calendar/README.md`).

### A configuration confirmed on another market (plan row R12)

The replication study (`docs/research/REPLICATION_V1D_REPORT.md`) runs the Sprint 2c rules on
OKX spot markets they were never tuned on (XRP, DOGE, LINK, TRX, ADA, LTC, SOL). A configuration
reaches the fleet only when it passes every walk-forward gate on its market **and** that
market's untouched 12 months confirm it; the study then appends it to the shortlist file with a
`source` tag (`"study": "R12 replication"`), ranks continuing after the Sprint 2c rows, and
proves the fleet can still load its manifest — otherwise the file is put back untouched and the
report says so. A running fleet takes such an account at its next restart from an updated
checkout, exactly as the allocator-v2 account joined after plan row R5b ("Updating the fleet's
code" above: stop, `git pull`, `--dry-run`, start): the new account starts flat with 10,000
virtual USDT at the first bar that closes after the restart, existing accounts and their journals
are untouched, and the fleet's shared rules (its fleet fingerprint) do not change. A walk-forward
pass alone adds nothing. The fleet's public data path is not bound to BTC/ETH through
`app/okx/client.py` (it uses the lake's GET-only public client), so a new market needs no change
there; the fleet knows the study's markets and their OKX swaps (for the S5 funding feed) and
fetches public data only for the markets its accounts need.

**Outcome of the first study (2026-11-04):** two configurations were confirmed, both on
SOL-USDT 6H without the regime gate — S1 (`c12-s1-sol-6h-none`) and S1+S5
(`c11-s1s5-sol-6h-none`); they are rows 11 and 12 of the shortlist and the fleet now loads 22
accounts. The fleet running on the laptop since 2026-11-04 still has 20 until its checkout is
updated and the task restarted ("Updating the fleet's code" above); at that restart the two SOL
accounts start flat and the report's first SOL verdicts come 30 days later. They have no SOL
control account: the "vs its control" column stays empty for them, and their yardstick is the
backtest bands and the BTC/ETH controls. Their research: `docs/research/REPLICATION_V1D_REPORT.md`
(a fragile picture overall — 10 of 104 configurations passed walk-forward on the new markets, 8 of
those failed their holdout; the two SOL rows are one signal, S1 and S1+S5 traded identically over
the untouched 12 months).

### A configuration confirmed by research round 1 (plan row R13)

Research round 1 (`docs/research/RESEARCH_ROUND_1_REPORT.md`) tested three pre-registered entry
conditions on the unchanged Sprint 2c rules on BTC-USDT and ETH-USDT. The R12 rule applies
unchanged: a configuration reaches the fleet only when it passes every walk-forward gate **and**
the untouched 12 months confirm it; the study appends it to the shortlist file with a `source` tag
(`"study": "R13 research round 1"`), ranks continuing, and proves the fleet can still load its
manifest (otherwise the file is put back and the report says so).

**Outcome (2026-11-04):** one configuration — S1 with new entries only on bars whose 30-day volume
z-score is above 1 (`S1+VC`), on BTC-USDT 4H with the regime gate — is row 13
(`c13-s1vc-btc-4h-gate`); the fleet loaded 23 accounts after it (24 since plan row R16). It needs nothing the fleet does not
already have: one market, the volume of its own bars, the same sizing, filters and regime gate as
the other gated BTC 4H accounts. The laptop fleet started on 2026-11-04 has 20 accounts until its
checkout is updated and the task restarted ("Updating the fleet's code" above); at that restart the
account starts flat and its first verdict comes 30 days later, judged against its own backtest bands
and the BTC 4H controls. Read it as a hypothesis under forward test, not a result: it was one pass
among 20 comparisons, just above two gates (Calmar 0.55 against 0.5, Sharpe 0.71 against 0.7), its
rule was selected in only 2 of 9 walk-forward windows, and it was confirmed on a holdout whose
falling direction was known beforehand (+2.0 %, PF 1.41, 25 trades). The other two hypotheses — a
BTC-trend condition for ETH entries and dual momentum between BTC and ETH — failed walk-forward and
add nothing.

### A configuration confirmed by research round 2 (plan row R16)

Research round 2 (`docs/research/RESEARCH_ROUND_2_REPORT.md`) tested three pre-registered hypotheses
drawn from the failure analyses of the replication study and round 1: the round-1 volume
confirmation on the seven replication markets, and a slow trend filter (the close above its 200-day
moving average) for the breakout rule and as the exposure rule itself. The R12 rule applies
unchanged: a configuration reaches the fleet only when it passes every walk-forward gate **and**
the untouched 12 months confirm it; the study appends it to the shortlist file with a `source` tag
(`"study": "R16 research round 2"`), ranks continuing, and proves the fleet can still load its
manifest (otherwise the file is put back and the report says so).

**Outcome (2026-11-04):** one configuration — the volume confirmation on S1 (`S1+VC`), on DOGE-USDT
4H with the regime gate — is row 14 (`c14-s1vc-doge-4h-gate`); the fleet now loads 24 accounts.
DOGE-USDT is one of the replication study's markets, so the fleet already knows its public candle
path; the account needs no positioning feed (no S5) and the same sizing, filters and regime gate as
the other gated 4H accounts. The laptop fleet started on 2026-11-04 has 20 accounts until its
checkout is updated and the task restarted ("Updating the fleet's code" above); at that restart the
account starts flat and its first verdict comes 30 days later, judged against its own backtest bands
(walk-forward Calmar 0.83, 67 trades; holdout +1.8 %, PF 1.65, 18 trades); it has no DOGE control
account, so its "vs its control" column stays empty, as for the SOL accounts. Read it as a
hypothesis under forward test, not a result: the volume confirmation raised the risk-adjusted result
beside plain S1 in 25 of 28 configurations across the seven markets, but of its 5 walk-forward
passers the holdout confirmed only this one and contradicted the other four (including SOL-USDT 6H,
where plain S1's own holdout had been confirmed), and the holdout's falling direction was known
beforehand. The two slow-trend hypotheses could not be judged: the protocol's 20-train-trade
selection rule left them flat in most windows (untested rather than refuted; an owner decision in
`docs/PLAN_STATUS.md`, section 2). No TF or S2+TF account joined the fleet.

### Positioning data for the S5 filter on the replication markets (plan row R17)

The S5 positioning filter (the `+S5` in an account's name) blocks new entries while a market's
perpetual-swap funding rate or open interest looks crowded. The fleet fetched those two public
series through the app's collector, which knows only `BTC-USDT-SWAP` and `ETH-USDT-SWAP` (a bound
that also serves demo and paper trading and stays exactly as it is). So when the SOL and DOGE
accounts joined on 2026-11-04 at 23:00 UTC, every 30-minute refresh logged `positioning
SOL-USDT-SWAP: instrument 'SOL-USDT-SWAP' not allowed` (and the same for DOGE; cycle lines with
`errors=2`), the fleet's lake never received SOL funding or open interest, and the S5 filter of
`c11-s1s5-sol-6h-none` passed for lack of data — a missing series adds no constraint, as in the
research — so that account ran as plain S1 beside `c12`, and its journal said so only indirectly
(`funding_rate: None, oi_usd: None, entry_allowed: True`).

Since plan row R17 (2026-11-05):

- The Sprint 2c pair's swaps still go through the app's collector, unchanged. Every other fleet
  market's swap (`research.markets.RESEARCH_SWAP_FOR`: SOL, DOGE, XRP, ...) goes through a
  research-side fetch of the same two public endpoints (`research/positioning_data.py`: GET only,
  no keys, bounded to those markets, and it refuses BTC/ETH on purpose so their data can only come
  through the app's path). The error lines are gone, and the fleet lake fills with
  `derivatives/funding_rate/SOL-USDT-SWAP/8H` and `derivatives/open_interest/SOL-USDT-SWAP/1H` at
  the first refresh after the restart (100 days of funding, 10 days of open interest, then topped
  up every 30 minutes). The funding z-score needs 30 settlements (10 days), which that backfill
  covers, so the filter is fully in force from the restart on. DOGE's series are fetched too
  although `c14` has no S5 filter, so a future S5 account on DOGE starts with history. Checked
  live on 2026-11-05: both endpoints answer for SOL-USDT-SWAP and DOGE-USDT-SWAP in the BTC/ETH
  row format.
- Every S5 account's bar record now carries `positioning_data`: each series is `current` (a value
  at or before the bar's open, at most one of its own periods — 8 hours for funding, 1 hour for
  open interest — plus the 30-minute refresh window old), `stale` (older than that: the filter
  uses the last known value) or `missing` (that leg of the filter passes), with a `note` in plain
  words — `S5 data current`, or `S5 running without data: the filter passes (funding missing, open
  interest missing)`, or which single leg is missing or stale. `--status` prints the note under
  each S5 account and one line with the newest stored funding / open-interest value per market;
  the weekly report lists it in "In short" (while an account's last bar lacks data), in "This
  week" (`— S5 without data` next to the last decision) and in "Data and health" (how many bars
  since the start ran without complete data, the first and last of them). Bars written before R17
  carry only the ages and are read through the same rule, so `c11`'s early bars count too.
- No rule changed: the account fingerprints and the shared rules' fingerprint are exactly what the
  running fleet stored (pinned in `tests/test_paper_fleet_config.py`), and the
  `positioning_source` check is untouched, so the fleet resumes in its folder after the checkout
  update and the labels appear from the first bar after that restart (tested: a state written
  without the labels resumes, the series are backfilled at the resume, the later bars read
  "current").

**The period without the filter, for the record.** `c11-s1s5-sol-6h-none` ran without its funding
and open-interest data from its creation at 2026-11-04T22:59:50Z (01:00 Beirut time on
2026-11-05; `created_at` in `logs/paper_fleet/_state/fleet_state.json`) until the restart that
picks up this row. When the row was built (2026-11-05 02:03 UTC) the fleet had run 661 cycles since
its own start on 2026-11-04 14:55 UTC (the four new accounts joined at cycle 480), the account had
processed one bar (2026-11-04 18:00 UTC, decision flat) and made 0 trades, so no fill was affected.
The restart's `resume` record in `fleet.jsonl` gives the exact cycle at which the fix took effect;
the bars of `c11` before it stay labelled "without data" in the weekly report. (An offline
`--dry-run` on this laptop's research lake shows the same label for `c11`, because the research
lake holds no OKX positioning series for SOL; the live fleet fetches them.)

**What you do:** the update-and-restart step ("Updating the fleet's code" above: the STOP file,
`git pull` in the fleet checkout, `--dry-run`, start the task), once `plan/auto` carries this row.
Then check:

```powershell
Get-Content C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\console.log -Tail 20
# the resume line, then cycle lines with errors=0 (no "not allowed")
C:\Users\Admin\Desktop\ai-trading-fleet\.venv\Scripts\python.exe C:\Users\Admin\Desktop\ai-trading-fleet\scripts\run_paper_fleet.py --status
# a line "positioning data (S5 filter, ...)" with a funding and an open-interest time for SOL-USDT-SWAP and DOGE-USDT-SWAP, and after the
# next 6H bar closes (00, 06, 12, 18 h UTC) "S5 data current" under c11-s1s5-sol-6h-none
```

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `paper fleet not started: the fleet's shared rules … changed` or `the rules of c0… changed` (exit 2, no restart loop) | The updated code or shortlist changes rules the running accounts were started with; mixing them would spoil the record | Keep the old folder as the record of the old fleet and start the new one in a new folder: `PAPER_FLEET_DIR=/path/to/ai-trading-model/logs/paper_fleet_v2` in `/etc/ai-trading/paper-fleet.env`, the same path in `ReadWritePaths` of the unit, then `mkdir -p` that folder, `chown` it to the service user (step 3 of option A), `sudo systemctl daemon-reload` and restart. (A configuration *added* to the shortlist simply joins the running fleet from that moment, and one *removed* is retired with its journal kept: neither needs a new folder.) |
| `another instance holds …/fleet.lock` (exit 3) | A manual `--loop`/`--once` is running on the same folder | Stop the manual run; the service tries again by itself a minute later |
| `paper fleet not started yet: public data not ready …` (exit 3) | The very first start found no fresh public prices (network down, or OKX not answering), or the last bar's final hourly candle was not published yet, so it did not create a fleet from incomplete data | Check the network (`curl -s https://www.okx.com/api/v5/public/time`); the service tries again every minute and creates the fleet once the data is there |
| `… S5 accounts run on 'okx' positioning data, not 'none' …` (exit 2) | A manual run used another `--positioning-source` than the fleet was started with | Run it without that option (the default is the one the service uses) |
| `--status` shows data **STALE** | No new public candle for more than 2.5 hours | Check the network (`curl -s https://www.okx.com/api/v5/public/time`); it recovers by itself and catches up |
| Report: "missing bars skipped" | OKX never delivered one hourly candle of a bar | Nothing; after the next bar closes the fleet waits 90 more minutes for the late candle, then skips that one bar, as a real feed outage would |
| Report: **FOMC calendar runs out** | The built-in central-bank meeting calendar (`research/events.py`) has no dates after the one named, which is less than 60 days away or already past. Since plan row R7 the calendar runs to 2027-12-08; a service still running code from before R7 has the old one, which ended 2026-12-09 | Update the checkout and restart the service (see "A new FOMC calendar on a running fleet"): the fleet resumes in its folder. If the updated checkout still ends there, the next year's dates need adding first (`tests/fixtures/fomc_calendar/README.md`). Until then the no-trade filter does not block entries around meetings after that date |
| `paper fleet not started yet: public data not complete yet, pf-s1s2s4-btceth-vt15-alloc2 not added …` (exit 3) | A new account joins only once its markets are ready: the bar that closed last is complete (OKX publishes the last hourly candle seconds to minutes after the hour) and no earlier bar still waits for a late candle | Nothing: the service tries again every minute. Until the account joins, the whole fleet waits; then every account catches up bar by bar with the same records as if it had never stopped. A candle that never arrives delays the join until the fleet gives up on it (90 minutes after the next bar closed), as it would anyway |
| `paper fleet resume: … (20 accounts, …)` and `accounts added: pf-s1s2s4-btceth-vt15-alloc2; retired: none` after updating the code | The fleet was started before plan row R5b with 19 accounts; the allocator-v2 account joins it now, with its own start and warm-up, and counts from that moment. The 19 accounts continue unchanged | Nothing. The state file is upgraded in place (version 2), so an older checkout can no longer open it (`fleet state version 2 is not 1`, exit 2): keep the updated code |
| `journal_set_aside` in `fleet.jsonl`, a file `journals/<account>.unfinished-<time>.jsonl` | An earlier start of that account was interrupted after its journal was written but before the state was saved (a crash or a full disk) | Nothing: the account started again cleanly and the interrupted file is kept for reference |
| `decision_error` in a journal | One account could not compute a decision for one bar | That account keeps its stops but takes no new position until the next good decision; if it repeats, ask for a review |
| `positioning SOL-USDT-SWAP: instrument 'SOL-USDT-SWAP' not allowed` (or DOGE) in the cycle lines, `errors=2` every 30 minutes | Code from before plan row R17: the fleet asks the app's BTC/ETH-only collector for a replication market's swap, so the S5 filter of that market's accounts passes for lack of data | Update the checkout and restart ("Updating the fleet's code"); the series are backfilled at the restart |
| `S5 running without data: the filter passes` under an account in `--status`, or `S5 without data` in the weekly report | That S5 account's funding or open-interest series is missing (or stale) at its last bar: the positioning filter adds no constraint there and the account trades as its base rule; the report counts such bars since the start | On code before R17, for a SOL or DOGE account: update and restart. Otherwise read the `positioning data` line of `--status`: a `last refresh errors` entry means OKX did not answer (it recovers by itself and the next refresh backfills); a single stale open-interest hour is OKX's publishing delay, not a fault |
| `cycle failed` lines | Something outside the fleet failed (disk full, …) | `df -h`. A cycle that could not be saved is redone from the last saved state, so nothing is lost or counted twice; after 10 failures in a row the program exits and systemd restarts it a minute later |

## Disk and memory

About 5–6 MB of journals per month for all 20 accounts (measured on 3- and
10-day replays; the two portfolio accounts are the largest, about 0.7 MB a month
each), plus a few MB of price history. It uses one CPU core for a few seconds when a bar closes (up to about
a minute once every 180 days, when the regime models are refitted) and
about 150 MB of memory (measured live); the unit caps it at 50 % of a core and
2 GB.

## After 60+ days (plan row G7)

Copy `logs/paper_fleet/` (journals, reports, state) off the VPS, the same way as
the Phase 6a evidence (`docs/runbooks/VPS_8443_UPDATE.md`, last section), and
hand it to an agent session for the G7 review. Nothing here authorizes demo or
live trading of any configuration: that is a separate decision of yours.
