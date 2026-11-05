# Owner checklist — the steps only you can do (as of 2026-11-05)

Written for the owner. Everything an agent could do from this laptop has been
done or is queued in `docs/PLAN_STATUS.md`. Eight of the eleven items below need
your accounts, your keys or your VPS; three (9 to 11) are quick answers. They are in the order that unlocks the most.
Each one says what it is for, how long it takes, and exactly what to type.
Never paste a key, a token or a chat id into a chat, a screenshot or the repo.

| # | Step | Time | What it unlocks |
|---|---|---|---|
| 1 | Move the VPS shadow run off port 8443 (new account name) | 15 min (+ up to 3 days of waiting) | The demo shadow run keeps its eyes when OKX switches 8443 off |
| 2 | Change one GitHub setting, open and merge the `plan/auto` pull request | 20 min | Five months of work reaches `main`; the VPS can be updated; CI protects it |
| 3 | Update the VPS checkout, install the nightly database backup, stamp the database | 25 min | The VPS runs the merged code (port-less defaults, Alembic); a backup every night, with a proven restore |
| 4 | Copy the July to October shadow reports off the VPS | 10 min | The evidence summary (plan row R11) can be written |
| 5 | Demo stop drills on a new demo account, with the shadow run stopped | 2 h + a 2-week demo run | The exchange-side stop, the hard blocker for any live phase |
| 6 | Rotate the Telegram bot token | 10 min | Notifications you can trust (the old token was seen on screen) |
| 7 | An Anthropic API key with a cap, then start the news shadow on the VPS | 30 min | 30+ days of log-only news evidence (plan row G5) |
| 8 | Housekeeping: close pull request #7; later, the stale `demo` row | 5 min | Less noise; the partition guard stops failing closed on the stale row |
| 9 | Tokenized stocks: do you see XNVDA in the OKX app, and at what fee | 2 min | Whether plan row R21's data can ever lead to a trade on your account |
| 10 | Your risk budget (optional; the default is Trader) | 1 min | Whether the paper fleet also watches the Aggressive budget |
| 11 | A one-line go for the small demo fix (R14 part A) | 1 min | The demo run can open trades again; demo evidence starts being produced |

Nothing here changes what the system is allowed to do: demo only, spot,
long only, no AI touches an order.

---

## 1. Move the VPS shadow run off port 8443

**Why.** OKX is retiring WebSocket port 8443. On 2026-11-04 it still answered,
but with a "will be retired soon" notice. The day it stops, the shadow run
goes blind and fails closed. **Important correction:** the WebSocket URLs are
part of the demo account's fixed identity, so the fix needs a **new account
name** (`demo-shadow-1h-443`), not just new URLs. The earlier runbook was
wrong about this; the rewritten one is right.

**Do.** Follow `docs/runbooks/VPS_8443_UPDATE.md` step by step. In short:

```bash
cd /path/to/ai-trading-model
cat logs/shadow/heartbeat.json                 # "flat_at_lot": true is REQUIRED (see the runbook if it is false)
sudo systemctl stop shadow.service
cp -p .env ".env.bak-$(date +%F)" && chmod 600 ".env.bak-$(date +%F)"
# edit .env (or the systemd EnvironmentFile): the 3 port-less WS URLs,
# DEMO_ACCOUNT_NAME=demo-shadow-1h-443, SHADOW_PERIOD_ENABLED=1
# (values in a systemd EnvironmentFile? load it first: set -a; . /path/to/that/file; set +a)
.venv/bin/python scripts/run_shadow_period.py --gate-check     # expect armable=True
sudo systemctl start shadow.service
sudo ss -tnp | grep python | grep -E ":443|:8443"              # expect :443 only
```

If the gate says `WRONG ACCOUNT SCOPE`, the old account traded in the last 3
days: leave the service stopped and run the gate again after 3 full days.
A position still open under the old name must be closed first (the runbook's
step 1 says how); the new account could never sell it.
Then tell the next agent session "G1 is done" so the docs switch to the new
account name.

## 2. GitHub: one setting, one pull request

**Why.** Everything built since October 20 sits on branch `plan/auto` (50
commits: the port-less defaults, the data lake, three research sprints, the
news agent, the paper fleet, the ops digest). `main` is still at June 29.
Nothing can merge until the branch protection rule asks for the CI check by
its current name, `tests`.

**Do.**

1. Open <https://github.com/hicham004/ai-trading-model/settings/branches>.
   Edit the rule for `main`. Under "Require status checks to pass before
   merging", remove `tests + travel-mode safety guard` and add `tests`. Save.
2. Open <https://github.com/hicham004/ai-trading-model/compare/main...plan/auto?expand=1>.
   Title: `Plan runs 1 and 2: Sprints 0 to 2c, Phase 6b log-only news agent, paper fleet, ops digest`.
   Body: paste `docs/PR_PLAN_AUTO.md`.
3. Wait for the `tests` check to turn green (about 15 minutes), read the
   summary, then **Merge** (a merge commit, not squash, so the step hashes in
   `docs/PLAN_STATUS.md` stay true). If the check is red, do not merge: copy
   the failing step's summary into an agent session and let it fix the branch.
4. Later, when you want the exchange-side stop reviewed: a second pull request
   from `sprint-3/exchange-side-stops` into `main`, after an independent
   review (Codex or a fresh Claude review) and after step 5 below. Its
   runbook is on that branch.

## 3. Update the VPS checkout, install the backup, stamp the database

**Why.** After step 2 the VPS can run the merged code. Its database must be
stamped once so Alembic knows the existing tables, and until then nothing backs
that database up: the nightly `pg_dump` the plan assumed was never installed.

**Do.** `docs/runbooks/VPS_8443_UPDATE.md`, section "After the Sprint 0 pull
request is merged": `git pull`, reinstall the hashed requirements. Then
`docs/runbooks/DB_MIGRATIONS.md`, steps 1 to 3 in that order: install the
nightly backup timer and take the first backup, run the restore drill (it
restores the backup into a scratch database, compares it with the live one and
drops it again), then `alembic stamp head` and `alembic check`. Then gate check
and restart as the 8443 runbook says. While there, install the daily ops
digest and the OKX changelog watcher (`docs/runbooks/OPS_DIGEST.md`, about 15
minutes, free) after step 6: they are the early warning for the next 8443-type
change and the daily check while you are away.

## 4. Copy the shadow evidence off the VPS

**Why.** The July to October daily reports and journals on the VPS were never
analysed. One page of evidence (entries, fills, PnL, restarts, alerts) is
plan row R11; an agent writes it once the files are here.

**Do.** From your laptop (the last section of `docs/runbooks/VPS_8443_UPDATE.md`):

```bash
mkdir -p docs/evidence/shadow-2026-07-to-10
scp 'vps:/path/to/ai-trading-model/logs/shadow/report-*.md' docs/evidence/shadow-2026-07-to-10/
scp 'vps:/path/to/ai-trading-model/logs/shadow/journal-*.jsonl' docs/evidence/shadow-2026-07-to-10/
```

Then tell an agent session "G4 files are in docs/evidence"; it redacts and
writes the summary, and R11 becomes buildable.

## 5. Demo stop drills (the hard blocker for any live phase)

**Why.** Today the protective stop lives in software: it works only while the
process is alive. Sprint 3 built an exchange-side stop (an OKX conditional
sell order placed right after each fill), tested without credentials. Only
you can run the seven drills with demo keys. Until they pass and an
independent review signs off, no live phase is possible.

**Hazard, read first.** The VPS shadow run reconciles every fill and every
balance move of the OKX demo account behind its key, against a baseline it
recorded on its first day. A drill fill on the same OKX account, even under a
different local account name, looks foreign or out of scope to it and the
supervisor disarms permanently; and because the balance check has no time
window, that shadow account can never reconcile again. So either:

- **use a different OKX account** for the drills (its own demo environment
  and keys): the shadow run is untouched. This is the simpler path; or
- **stop `shadow.service` before the drills** and accept that the shadow run
  afterwards starts under yet another new account name (a fresh balance
  baseline), once the drill fills are older than OKX's 3-day fills window.
  Agents update the docs to the new name when you tell them.

**Do.** `docs/runbooks/DEMO_STOP_DRILLS.md` on branch
`sprint-3/exchange-side-stops`, on a machine with the demo keys in `.env`
(never printed), a NEW local account name (`demo-exec-v2`), then the 2-week
demo run it asks for. Record each drill's outcome in `docs/evidence/`
without keys or ids.

## 6. Rotate the Telegram bot token

**Why.** The token was seen on screen during the VPS setup. Anyone who saw it
can post as the bot. Notifications are observability only, but you should be
able to trust them.

**Do.** In Telegram, open BotFather, `/mybots`, the bot, "API Token",
"Revoke current token". Put the new token into the VPS service environment
(`EnvironmentFile` or exported variable, never the repo). Prefer a moment when
the heartbeat says `"flat_at_lot": true`: a restart rebuilds the strategy
window and would exit an open position. Then:

```bash
sudo systemctl restart shadow.service
# a test message must arrive. The notifier reads the token from the shell environment and never
# prints it; load the service's file first, and --strict makes a failed send exit non-zero.
set -a; . /path/to/the/EnvironmentFile; set +a
.venv/bin/python scripts/notify_telegram.py --event report_ready --title "token rotated" --details "test after rotation" --strict
cat logs/shadow/heartbeat.json                            # a fresh heartbeat
```

Delete the unused GitHub Actions secrets `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` (Settings, Secrets and variables, Actions): no workflow
uses them any more.

## 7. News shadow: a capped API key, then 30+ days (plan row G5)

**Why.** The news agent is built and tested offline (log-only, it can never
touch an order). It needs a real key to classify real headlines; 30 days of
its log are the evidence for whether a news brake is ever worth using.

**Do.** Follow `docs/runbooks/NEWS_SHADOW.md`. In short: in the Anthropic
console create a workspace with a **$50 monthly limit** and a key for it; on
the VPS run the eval first (`scripts/eval_news_classifier.py`, about $4 to
$10) and start the shadow only if all three safety gates pass; the service
caps itself at $40 a month. Read the spend line after a week. Do this after
step 2 so the VPS has the R4d news rules.

## 8. Housekeeping

- Close pull request #7 ("Codex review smoke test", open since June): it has
  no purpose now.
- The stale, empty `demo` account row shares the demo key fingerprint with
  the real account, so the partition guard fails closed on it. Deleting it
  is a reviewed cleanup (CLAUDE.md open item 3): ask an agent session for the
  exact read-only check and the one `DELETE`, and run it on the VPS yourself.

## 9. Tokenized US stocks: two minutes in the OKX app

Plan row R21 collects data on OKX's tokenized US stocks (pairs such as
XNVDA/USDT); nothing trades them. Only you can see what your account may do:

1. In the OKX app or website, search for `XNVDA` (or `XQQQ`) under Spot. Do
   you see the pair and its order book, and does the order form open (do not
   place an order)? If the pair is hidden or greyed out, your account's region
   cannot trade them; the data collection (R21) still runs, but no trading step
   will be planned until that changes.
2. Open your account's fee page (Profile → Fees, or `okx.com/fees`) and read
   the spot maker/taker rate shown for a tokenized-stock pair. The regular spot
   schedule is 0.08 % / 0.10 %; OKX has not published the rate for these pairs
   anywhere we could read.
3. Tell the next agent session both answers in one line ("I see XNVDA, 0.10 %
   taker" or "hidden"). No screenshots of account pages.

## 10. Your risk budget (optional; the default is Trader)

`docs/TRADER_PLAN_2026-11-05.md`, section 4.1, describes three risk budgets:
Reference (today's), Trader (a 20 % volatility target with at most 2 % of the
account at risk on one stop: about 1.7 to 2 times today's size and today's
drawdowns on most sleeves, less on SOL, whose stop is widest) and Aggressive
(25 % and 2.5 %). Plan row R18
tests all three and puts the Trader version of each passing rule into the
paper fleet beside the existing accounts. Nothing moves to the demo account
without your separate go. If you also want to watch the Aggressive tier in the
fleet, say so in one line; otherwise nothing is needed.

## 11. A one-line go for the small demo fix (R14 part A)

The demo shadow run on the VPS has very likely been unable to open a trade
since June 21: after its one round trip, fee crumbs smaller than one lot made it
believe it still holds a position (`docs/PLAN_STATUS.md`, section 2, "From
R14"). Part A of the R14 design fixes that in the reviewed safety core (dust no
longer counts as an open position). It is a small change, but it touches
`app/execution`, so an agent may not build it under the blanket go: it needs
your one-line go, then an independent review, the merge (step 2) and the VPS
update (step 3). Until then no demo evidence is being produced. One line is
enough: "go for R14 part A".

---

## What happens by itself meanwhile

- **The plan runner** (Windows task "AI Trading plan runner", Fable 5.1 at
  max effort) built rows R4e and R12 to R16 on 2026-11-04 and, since
  2026-11-05, builds R17 to R22 (the Trader Plan rows: fleet hygiene, Trader
  Policy v1, research round 3, breadth, tokenized-stocks data and design, fill
  costs) one chat at a time on `plan/auto`, pushing that branch after each
  clean step; it never touches `main`. Progress: `docs/PLAN_STATUS.md`, section 0; details:
  `artifacts/plan-runner/summary.md`. Stop it after the current step by
  creating the file `artifacts\plan-runner\STOP`.
- **The paper fleet** (Windows task "AI Trading paper fleet") runs 24 pretend
  accounts forward on live public prices from its own checkout at
  `C:\Users\Admin\Desktop\ai-trading-fleet`. Free, no keys, nothing can
  trade. Weekly report: `C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\reports\`.
  It needs about 60 days before the numbers mean anything (plan row G7). Its
  checkout was updated and the task restarted on 2026-11-04 at 23:00 UTC (01:00
  Beirut time), so the
  four accounts added by plan rows R12, R13 and R16 (SOL, BTC and DOGE) are
  running; rows R18 to R20 will add more, each time by the same update-and-restart
  step (`docs/runbooks/PAPER_FLEET.md`, "Updating the fleet's code"), which an
  agent session can do for you. Row R17 (built 2026-11-05) needs that step once
  too: it gives the SOL and DOGE accounts their funding and open-interest data;
  until the restart, `c11` runs as plain S1 and the weekly report labels its bars
  "S5 running without data".
- The laptop must stay on and plugged in (it does not sleep on power; keep
  the lid open, closing it may put it to sleep). After a sleep both tasks
  simply continue and the fleet catches up bar by bar. After a reboot both
  tasks start again when you log on (each has a logon trigger); the runner
  then waits for 20 quiet minutes before its next row.
