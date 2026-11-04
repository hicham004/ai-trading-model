# Owner checklist — the steps only you can do (as of 2026-11-04)

Written for the owner. Everything an agent could do from this laptop has been
done or is queued in `docs/PLAN_STATUS.md`. The eight items below need your
accounts, your keys or your VPS. They are in the order that unlocks the most.
Each one says what it is for, how long it takes, and exactly what to type.
Never paste a key, a token or a chat id into a chat, a screenshot or the repo.

| # | Step | Time | What it unlocks |
|---|---|---|---|
| 1 | Move the VPS shadow run off port 8443 (new account name) | 15 min (+ up to 3 days of waiting) | The demo shadow run keeps its eyes when OKX switches 8443 off |
| 2 | Change one GitHub setting, open and merge the `plan/auto` pull request | 20 min | Five months of work reaches `main`; the VPS can be updated; CI protects it |
| 3 | Update the VPS checkout, stamp the database | 10 min | The VPS runs the merged code (port-less defaults, Alembic) |
| 4 | Copy the July to October shadow reports off the VPS | 10 min | The evidence summary (plan row R11) can be written |
| 5 | Demo stop drills on a new demo account, with the shadow run stopped | 2 h + a 2-week demo run | The exchange-side stop, the hard blocker for any live phase |
| 6 | Rotate the Telegram bot token | 10 min | Notifications you can trust (the old token was seen on screen) |
| 7 | An Anthropic API key with a cap, then start the news shadow on the VPS | 30 min | 30+ days of log-only news evidence (plan row G5) |
| 8 | Housekeeping: close pull request #7; later, the stale `demo` row | 5 min | Less noise; the partition guard stops failing closed on the stale row |

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

## 3. Update the VPS checkout

**Why.** After step 2 the VPS can run the merged code. Its database must be
stamped once so Alembic knows the existing tables.

**Do.** `docs/runbooks/VPS_8443_UPDATE.md`, section "After the Sprint 0 pull
request is merged": `git pull`, reinstall the hashed requirements,
`alembic stamp head`, gate check, restart. While there, install the daily ops
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

---

## What happens by itself meanwhile

- **The plan runner** (Windows task "AI Trading plan runner", Fable 5.1 at
  max effort) builds rows R4e, R12, R13, R14, R15 and R16 one chat at a time
  on `plan/auto` and pushes that branch after each clean step; it never
  touches `main`. Progress: `docs/PLAN_STATUS.md`, section 0; details:
  `artifacts/plan-runner/summary.md`. Stop it after the current step by
  creating the file `artifacts\plan-runner\STOP`.
- **The paper fleet** (Windows task "AI Trading paper fleet") runs 20 pretend
  accounts forward on live public prices from its own checkout at
  `C:\Users\Admin\Desktop\ai-trading-fleet`. Free, no keys, nothing can
  trade. Weekly report: `C:\Users\Admin\Desktop\ai-trading-fleet\logs\paper_fleet\reports\`.
  It needs about 60 days before the numbers mean anything (plan row G7).
- The laptop must stay on and plugged in (it does not sleep on power; keep
  the lid open, closing it may put it to sleep). After a sleep both tasks
  simply continue and the fleet catches up bar by bar. After a reboot both
  tasks start again when you log on (each has a logon trigger); the runner
  then waits for 20 quiet minutes before its next row.
