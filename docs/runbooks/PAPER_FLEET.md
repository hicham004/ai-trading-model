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
  buy-and-hold* (`ctl-bh-…`) on BTC and ETH, 4H and 6H.

20 accounts in all. Each one follows exactly the research rules — the same
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

## Check that it works (first hour)

```bash
journalctl -u paper-fleet.service -n 30 --no-pager      # VPS; option B: read the PowerShell window
# expect "paper fleet created: …/logs/paper_fleet (20 accounts, …)" and, once a 4H or 6H bar closes
# (00, 04, 08, 12, 16, 20 h UTC), a line "cycle N: bars {…} …"
.venv/bin/python scripts/run_paper_fleet.py --status
# every account with its equity (10,000.00 at the start), "flat"/"long", data "fresh"
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

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `paper fleet not started: the fleet's shared rules … changed` or `the rules of c0… changed` (exit 2, no restart loop) | The updated code or shortlist changes rules the running accounts were started with; mixing them would spoil the record | Keep the old folder as the record of the old fleet and start the new one in a new folder: `PAPER_FLEET_DIR=/path/to/ai-trading-model/logs/paper_fleet_v2` in `/etc/ai-trading/paper-fleet.env`, the same path in `ReadWritePaths` of the unit, then `mkdir -p` that folder, `chown` it to the service user (step 3 of option A), `sudo systemctl daemon-reload` and restart. (A configuration *added* to the shortlist simply joins the running fleet from that moment, and one *removed* is retired with its journal kept: neither needs a new folder.) |
| `another instance holds …/fleet.lock` (exit 3) | A manual `--loop`/`--once` is running on the same folder | Stop the manual run; the service tries again by itself a minute later |
| `paper fleet not started yet: public data not ready …` (exit 3) | The very first start found no fresh public prices (network down, or OKX not answering), or the last bar's final hourly candle was not published yet, so it did not create a fleet from incomplete data | Check the network (`curl -s https://www.okx.com/api/v5/public/time`); the service tries again every minute and creates the fleet once the data is there |
| `… S5 accounts run on 'okx' positioning data, not 'none' …` (exit 2) | A manual run used another `--positioning-source` than the fleet was started with | Run it without that option (the default is the one the service uses) |
| `--status` shows data **STALE** | No new public candle for more than 2.5 hours | Check the network (`curl -s https://www.okx.com/api/v5/public/time`); it recovers by itself and catches up |
| Report: "missing bars skipped" | OKX never delivered one hourly candle of a bar | Nothing; after the next bar closes the fleet waits 90 more minutes for the late candle, then skips that one bar, as a real feed outage would |
| Report: **FOMC calendar runs out** | The built-in central-bank meeting calendar (`research/events.py`) has no dates after 2026-12-09 | Add the 2027 dates (plan row R7 verifies the existing ones); until then the no-trade filter does not block entries around meetings |
| `paper fleet not started yet: public data not complete yet, pf-s1s2s4-btceth-vt15-alloc2 not added …` (exit 3) | A new account joins only once its markets are ready: the bar that closed last is complete (OKX publishes the last hourly candle seconds to minutes after the hour) and no earlier bar still waits for a late candle | Nothing: the service tries again every minute. Until the account joins, the whole fleet waits; then every account catches up bar by bar with the same records as if it had never stopped. A candle that never arrives delays the join until the fleet gives up on it (90 minutes after the next bar closed), as it would anyway |
| `paper fleet resume: … (20 accounts, …)` and `accounts added: pf-s1s2s4-btceth-vt15-alloc2; retired: none` after updating the code | The fleet was started before plan row R5b with 19 accounts; the allocator-v2 account joins it now, with its own start and warm-up, and counts from that moment. The 19 accounts continue unchanged | Nothing. The state file is upgraded in place (version 2), so an older checkout can no longer open it (`fleet state version 2 is not 1`, exit 2): keep the updated code |
| `journal_set_aside` in `fleet.jsonl`, a file `journals/<account>.unfinished-<time>.jsonl` | An earlier start of that account was interrupted after its journal was written but before the state was saved (a crash or a full disk) | Nothing: the account started again cleanly and the interrupted file is kept for reference |
| `decision_error` in a journal | One account could not compute a decision for one bar | That account keeps its stops but takes no new position until the next good decision; if it repeats, ask for a review |
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
