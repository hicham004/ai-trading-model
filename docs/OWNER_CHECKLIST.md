# Owner checklist — the steps only you can do (as of 2026-11-06)

Written for the owner. Everything an agent could do from this laptop has been
done or is queued in `docs/PLAN_STATUS.md`. Nine of the twelve items below need
your accounts, your keys or your VPS; three (9 to 11) are quick answers. Step 12,
listed first, is the one to do first: it lets the laptop be switched off. They are in the order that unlocks the most.

**2026-11-06: you deleted the old droplet.** It ran the demo shadow run, so that test has stopped,
and its June-October files went with it unless DigitalOcean kept a snapshot. Steps 1, 3 and 4, the
server parts of steps 6 and 11, and the "on the VPS" part of step 7 were about that server: they wait
until you decide to run the demo test again, and a session then rewrites them for the new server. Two
tidy-ups take a minute: in OKX demo trading, delete the old demo API key (it was tied to the deleted
server); in Telegram's BotFather, revoke the old bot token.
Each one says what it is for, how long it takes, and exactly what to type.
Never paste a key, a token or a chat id into a chat, a screenshot or the repo.

| # | Step | Time | What it unlocks |
|---|---|---|---|
| 12 | **Done 2026-11-06:** a new small server, then one line in its console, for the paper fleet and the stock recorder | 15 min | The 60-day test keeps running with the laptop off |
| 1 | Move the VPS shadow run off port 8443 (new account name) (waits: the old server was deleted) | 15 min (+ up to 3 days of waiting) | The demo shadow run keeps its eyes when OKX switches 8443 off |
| 2 | Change one GitHub setting, open and merge the `plan/auto` pull request | 20 min | Five months of work reaches `main`; the VPS can be updated; CI protects it |
| 3 | Update the VPS checkout, install the nightly database backup, stamp the database (waits: the old server was deleted) | 25 min | The VPS runs the merged code (port-less defaults, Alembic); a backup every night, with a proven restore |
| 4 | Copy the July to October shadow reports off the VPS (gone with the old server, unless a snapshot exists) | 10 min | The evidence summary (plan row R11) can be written |
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
XNVDA/USDT); nothing trades them. Built 2026-11-05: the collector, its first run
(the 15 most traded pairs, 112 days of hourly candles, one order book each), the
feasibility report (`docs/research/TOKENIZED_STOCKS_FEASIBILITY.md`) and the design
note (`docs/design/TOKENIZED_STOCKS.md`). What keeps collecting (the open and close
order books the decision needs) is a laptop task next to the paper fleet,
`AI Trading xstocks data`, started for you on 2026-11-05 at 19:12 UTC
(`docs/runbooks/XSTOCKS_DATA.md`; free, public data, nothing trades). Only you can
see what your account may do:

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

## 10. Your risk budget (decided 2026-11-05: Trader beside Reference)

`docs/TRADER_PLAN_2026-11-05.md`, section 4.1, describes three risk budgets:
Reference (today's), Trader (a 20 % volatility target with at most 2 % of the
account at risk on one stop: about 1.7 to 2 times today's size and today's
drawdowns on most sleeves, less on SOL, whose stop is widest) and Aggressive
(25 % and 2.5 %). Plan row R18a (done 2026-11-05,
`docs/research/TRADER_POLICY_V1_REPORT.md`) tested all three: all five
confirmed rules pass the plan's gates at the Trader tier with the brakes on,
and the Trader version of each is recorded for the paper fleet; plan row R18b
adds those accounts beside the existing ones (the fleet's loader has to learn
the tier-tagged rows first). Nothing moves to the demo account without your
separate go. Your "do what you recommend" of 2026-11-05 settled this: the Trader
tier runs beside the Reference accounts (the seven R18b accounts since the 19:05 UTC
restart and the two R23 accounts — the S8 forward control and S1 BTC-USDT 6H, both
at the Trader tier — since the 21:17 UTC restart, both on 2026-11-05), the
Aggressive tier does not. If you
ever want to watch the Aggressive tier too (it passed on all five, at about 1.2
times the Trader drawdowns), say so in one line; otherwise nothing is needed.

## 11. The small demo fix (R14 part A): given the go on 2026-11-05, two steps left for you

The demo shadow run on the VPS has very likely been unable to open a trade
since June 21: after its one round trip, fee crumbs smaller than one lot made it
believe it still holds a position (`docs/PLAN_STATUS.md`, section 2, "From
R14"). Part A of the R14 design fixes that in the reviewed safety core (dust no
longer counts as an open position; releasing a dead process's lock also disarms).
Your "do what you recommend" of 2026-11-05 was taken as the go. It is being
built on its own small branch from `main`, `sprint-6/position-persistence`, with
an independent review recorded in that branch (`docs/R14A_PART_A_REVIEW_NOTES.md`),
and pushed when its tests and review pass. Then two things only you can do:

1. **Merge it** (step 2's mechanics, but this branch first: it is small and does
   not wait for the big `plan/auto` merge): open
   `https://github.com/hicham004/ai-trading-model/compare/main...sprint-6/position-persistence`,
   press "Create pull request", wait for the `tests` check, press "Merge".
2. **Update the VPS** (waits: the old server was deleted on 2026-11-06; this applies when a demo run
   is set up again) (step 3, `docs/runbooks/VPS_8443_UPDATE.md`'s update steps),
   only while the heartbeat says the account is flat at lot precision. The first
   LONG that clears the 0.60 floor afterwards is the proof (design section 10,
   check V2): its decision reason is anything but `position_already_open`.

Until both are done, no demo evidence is being produced.

---

## 12. A new small server for the paper fleet and the stock recorder (done 2026-11-06)

**Done.** The droplet `ubuntu-s-1vcpu-1gb-sgp1` runs both programs since 2026-11-06 at 11:32 UTC
(13:32 Beirut time), and the laptop's copies are switched off. The steps below stay for the record and
for a new server later.

**Why.** The paper fleet needs about 60 days of prices before its numbers mean anything, and the
stock recorder has to be awake at the US open and close every weekday. Both run on this laptop now,
and the laptop cannot stay on for 60 days. A small server in the cloud is on all the time. Your old
droplet was deleted on 2026-11-06, so this step creates a new one first. It costs about $6 a month;
delete it when the test is over if you no longer need it.

**Is it safe?** Yes. The two programs hold no keys and can place no orders. They run as their own
user with no password and no rights, capped in memory and CPU. If a demo run is ever put on the same
server again, the setup keeps the two apart: the programs cannot see the demo run's keys or its
database, and they are stopped first if memory runs short. It was tested on a copy of the server's
system, with a fake demo run and fake keys next to it.

**Do (about 15 minutes; a few clicks and one line to paste).**

1. Open `cloud.digitalocean.com`, click the green **Create** button at the top, then **Droplets**.
2. Choose the region **Singapore**, the image **Ubuntu 24.04 (LTS) x64**, the plan **Basic**,
   **Regular**, and the **$6/month** size (1 GB of memory). Under authentication choose
   **Password** and save it somewhere safe. Leave the rest as it is (no paid backups) and click
   **Create Droplet**.
3. When it shows an IP address, click its name, then **Console** at the top right. A black window
   opens, already logged in. First type this short line by hand (do not paste it) and press Enter;
   it stops the console from gluing hidden characters (`^[[200~`) to whatever you paste next:
   `bind 'set enable-bracketed-paste off'`
4. Paste this line (right-click → Paste) and press Enter:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/hicham004/ai-trading-model/plan/auto/scripts/vps_research_setup.sh -o /tmp/research_setup.sh && sudo bash /tmp/research_setup.sh
   ```

5. Wait for the last lines. `DONE.` means both programs run. `STOPPED:` explains why in plain words,
   and nothing that matters was changed; show it to an agent session.
6. Tell an agent session "the server runs the fleet". It switches off the laptop's copies (one
   record, one place).

**What you lose.** Almost nothing. The server starts a fresh record, so the 60 days count from that
day. The laptop's first two days stay on the laptop as an archive.

**Later.** In a new console window, type the `bind` line of step 3 by hand first. To see how they are
doing, paste
`sudo bash /opt/ai-trading-research/scripts/vps_research_setup.sh status` in the same console.
When a plan row adds an account to the fleet, its note in `docs/PLAN_STATUS.md` asks you to paste
`sudo bash /opt/ai-trading-research/scripts/vps_research_setup.sh update`.

---

## What happens by itself meanwhile

- **The plan runner** (Windows task "AI Trading plan runner", Fable 5.1 at
  max effort) built rows R4e and R12 to R16 on 2026-11-04 and R17 to R22 (the
  Trader Plan rows: fleet hygiene, Trader Policy v1, research round 3, breadth,
  tokenized-stocks data and design, fill costs) on 2026-11-05, one chat at a
  time on `plan/auto`, pushing that branch after each clean step; it never
  touches `main`. It stopped at 12:47 Beirut time on 2026-11-05 at R10, which
  needs your go; your "do what you recommend" that evening opened rows R23 (two
  more fleet accounts) and R24 (the measured cost profile for future studies), so
  it runs again and then stops at R10 once more. Progress: `docs/PLAN_STATUS.md`, section 0; details:
  `artifacts/plan-runner/summary.md`. Stop it after the current step by
  creating the file `artifacts\plan-runner\STOP`.
- **The paper fleet** runs 33 pretend accounts forward on live public prices on
  the new droplet since 2026-11-06 at 11:32 UTC (`paper-fleet.service`, checkout
  `/opt/ai-trading-research`; step 12). Free, no keys, nothing can trade. Look at
  it with `sudo bash /opt/ai-trading-research/scripts/vps_research_setup.sh status`
  in the droplet's console; reports are in `/opt/ai-trading-research/logs/paper_fleet/reports/`.
  The 60 days of plan row G7 count from that start. The Windows task "AI Trading
  paper fleet" is disabled; its folder `C:\Users\Admin\Desktop\ai-trading-fleet`
  keeps the laptop record of 2026-11-04 to 06 as an archive. Before the move, its
  checkout was updated and the task restarted on 2026-11-04 at 23:00 UTC (01:00
  Beirut time; the four accounts of rows R12, R13 and R16 joined) and again on
  2026-11-05 at 19:05 UTC (21:05 Beirut time; the seven Trader-tier accounts of
  row R18b joined, and row R17's funding and open-interest data for SOL and DOGE
  went live, so `c11` runs with its filter again). A later row that adds an account
  now needs the `update` line in the droplet's console (its row says so); the first
  30-day verdicts come about 2026-12-06.
- **The tokenized-stocks collector** (plan row R21) runs on the new droplet since
  2026-11-06 at 11:32 UTC (`xstocks-data.service`): the history of the 15 pairs is
  in, and it takes the US-open and US-close order books every weekday plus the
  03:00 UTC and Saturday-noon books (`docs/runbooks/XSTOCKS_DATA.md`). The 60-90
  days before the decision in plan section 6.2 count from that day. Free, public
  data, nothing trades. The laptop task "AI Trading xstocks data" is disabled.
- Since step 12 (2026-11-06) only the plan runner lives on the laptop, and the laptop may be off: the
  runner simply waits, starts again when you log on (logon trigger) and then waits for 20 quiet
  minutes before its next row.
