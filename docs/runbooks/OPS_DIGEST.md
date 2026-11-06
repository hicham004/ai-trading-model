# Runbook — the daily ops digest and the OKX changelog watcher (plan row R6)

**Audience:** the human operator, on the DigitalOcean Singapore VPS that runs the
Phase 6a shadow (`shadow.service`). **Agents cannot reach the VPS**; every step
here is an operator action. It is free unless you turn on the optional AI
summary (a few US cents a day).

## What it is, and what it is not

Two small timers next to the running services:

- **The daily digest** (`ops-digest.timer`, every day at **07:00 Beirut time**)
  sends you one Telegram message in plain English: what needs your attention,
  then how the Phase 6a shadow, the news shadow, the paper fleet and the
  changelog watcher did the day before (UTC). It is built from the files those
  services already write: the shadow's `heartbeat.json`, `state.json`, `ALERT`
  and journal (whose ledger lines mirror the demo fills and the reconciliations
  with the exchange), the news shadow's state, spend record and daily numbers,
  the fleet's saved state, and the watcher's state.
- **The OKX changelog watcher** (`okx-changelog-watch.timer`, every day at
  **06:30 Beirut time**) reads OKX's public API changelog,
  <https://www.okx.com/docs-v5/log_en/>, the page where OKX announced that
  WebSocket port 8443 stops on October 31, 2026. It remembers every entry it
  has seen and sends a Telegram message when a **new or edited** entry mentions
  something this system uses: the hosts (`www.okx.com`, `aws.okx.com`,
  `ws.okx.com`, `wspap.okx.com`), the ports, the REST endpoints, the WebSocket
  channels (`candle1H`, `orders`, ...) or the login and API-key rules. The full
  list, with the reason each item is on it, is `app/ops/okx_usage.py`.

What they never do:

- They place, size, approve, modify and cancel **nothing**. They cannot: they
  hold no OKX keys, call no OKX API (the watcher reads one public web page),
  never open the demo database, and nothing in trading reads their output.
  Stopping them changes nothing in trading.
- They never load the repository `.env` (the OKX demo keys); systemd makes it
  unreachable for both services, and the PostgreSQL socket too. They write only
  `logs/ops/`.
- A flag from the watcher changes nothing by itself. It is a prompt to read
  that entry and decide whether the system needs a change (with an agent
  session, like the port-8443 fix of Sprint 0).

## Reading the digest

The message starts with **NEEDS ATTENTION**. Each line is one of:

- **ACTION** — something is wrong now: the shadow is halted by an `ALERT` and
  waits for you; its heartbeat is more than 10 minutes old; no new 1H candle
  has closed for more than 2.5 hours (or none has arrived for 2.5 hours since
  it restarted); a reconciliation with the exchange was inconsistent; the
  digest cannot read the shadow's `ALERT` or heartbeat (it then cannot tell
  whether the shadow is halted or running) or finds its `state.json` damaged
  (the supervisor then refuses to restart); a news-shadow safety check FAILED
  (stop `news-shadow.service` and ask for a review); the news shadow has not
  saved a cycle for 30 minutes; the paper fleet's last cycle is more than 15
  minutes old.
- **CHECK** — worth a look: the shadow was down or without market data for
  hours (2 or more of yesterday's 24 hourly candles missing), its process
  started (a service restart, a reboot or a crash), internal restarts,
  demo-runtime errors and notable events (a deferred protective exit, a refused
  kill-switch release, an order this system did not place, ...), the
  market-continuity pause (entries paused after a candle gap; exits and stops
  still work), the private connection or the market feed below 95 % of the
  time it ran, the kill switch engaged (by the shadow's own daily cap, by you,
  or by a halt), a journal the digest could not read completely (then the
  downtime and uptime rules wait for complete data), a `state.json` the digest
  may not read, no shadow folder where the timer expects one, the news state
  healthy less than 90 % of the day, AI spend above 80 % of the news shadow's
  cap, stale fleet prices, a fleet drawdown ALARM, new changelog flags (the
  last 24 hours), changelog alerts not delivered yet, a changelog watcher that
  has not read the page for two days or has not run next to the shadow.

Then one section per part, each with **Now** (the latest files) and
**Yesterday** (the last full UTC day): candles (out of 24), signals and how many
cleared the 0.60 floor, entries allowed or blocked and why, fills and the cash
result after fees, reconciliations, uptime while it ran, runtime warnings; the
news shadow's cycles, articles, AI calls and spend (on the 1st of a month also
the month that just closed), events, what it would have blocked or reduced, and
its safety checks; the fleet's day count ("too early to judge" before day 30),
positions, best and worst account, the holdout-confirmed sleeve next to its
control, allocator v2, and from day 30 the weekly report's verdicts (how many
configurations are consistent with, worse or better than their backtest); the
changelog watcher's last check and its flags of the last 7 days with links. The
last line names the full reports.

A part that is not installed is said plainly ("not installed here yet") and is
not an alarm, with two exceptions on the server, both CHECK: a missing shadow
folder, and a changelog watcher that has not run next to the shadow. A file
that is half-written or unreadable becomes one line in the digest, never a
missing digest.

**The optional AI summary.** When `ANTHROPIC_API_KEY` is set in the digest's
environment file, Claude Opus 5.5 reads the finished digest and writes two to
four plain sentences, placed right after the NEEDS ATTENTION list and marked
"AI SUMMARY (Claude; it can be wrong, the facts decide)". Everything else is
unchanged. It is **not asked for at all on a day with an ACTION line**: those
lines speak for themselves. It is dropped, and the digest sent without it, when
the model refuses or is cut off, when it is empty, too long or contains a link
or a web address, and when it writes **any number, with its sign, that does not
appear in the digest** ("12 %" for a "-12.0 %" counts as invented). That check
stops invented figures; it cannot catch a wrong word ("all consistent"), which
is why the fixed lines come first. The message then ends with a note in plain
words ("AI summary left out: ..."). It has its own cap,
`OPS_DIGEST_AI_MONTHLY_CAP_USD` (default $3 a month; one summary costs about
2–4 US cents), counted the same way as the news shadow's spend
(`logs/ops/digest/_state/spend-YYYY-MM.json`).

## The first changelog check

The first check records the whole page (about 450 entries in October 2026) as
the baseline and sends only the **upcoming changes** and the entries of the
**last 30 days** that mention something this system uses. On 2026-10-22 that
was the port-8443 shutdown and OKX's coming SBE services (`orders` channel,
`wspap.okx.com`). From then on it sends only entries that are new or edited
since its last check: about one a week over the last year, most of them changes
to endpoints the demo uses (place order, instruments, the `orders` channel).

An alert that could not be delivered (Telegram down, or `TELEGRAM_DRY_RUN=1`)
is kept and sent again with the next checks for 7 days, even on days the page
itself cannot be read, and the digest lists it until then. If most of the page looks new at once (new ids or a new layout, not
news), the watcher takes it as its new baseline, flags only the upcoming changes
and sends one notice to skim the page by hand, instead of hundreds of alerts.

If the page cannot be read (network, a changed page layout, a block page, a
redirect), the check fails without forgetting what it knew; after **3 failed
checks in a row** it sends one alert, and the digest shows the failure from the
second day.

## Before you start

1. **The code is on the VPS.** It arrives with the `plan/auto` pull request
   (plan row G2). After the merge, update the checkout as in
   `docs/runbooks/VPS_8443_UPDATE.md`, Path B steps 1–2:

   ```bash
   cd /path/to/ai-trading-model                     # the checkout shadow.service runs from
   git fetch && git status                          # clean, on main
   git pull
   .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
   ```

   Updating the checkout does not restart `shadow.service`.

2. **Rotate the Telegram bot token first** if it was ever shown on a screen
   (CLAUDE.md, open item 8): BotFather → your bot → revoke and create a new
   token, then put the new one everywhere it is used (the shadow's environment,
   the GitHub secret if CI notifications are on, and step 1 below).

3. **Offline check** (no internet, no key, a few seconds):

   ```bash
   .venv/bin/python scripts/ops_digest.py --dry-run
   ```

   It builds a digest from the bundled test files (invented data) and must end
   with every line `check: ... ok`. It writes only to a new temporary folder.

## Step 1 — the services' own environment file

```bash
cd /path/to/ai-trading-model
sudo install -d -m 750 -o root -g root /etc/ai-trading
sudo install -m 600 -o root -g root deploy/systemd/ops.env.example /etc/ai-trading/ops.env
sudoedit /etc/ai-trading/ops.env
```

In the editor fill in `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` (no quotes,
no spaces). Leave `ANTHROPIC_API_KEY=` empty for now (see "The optional AI
summary" below). Save. Do not `cat` the file afterwards. **Never put OKX keys
here and never point the services at the repository `.env`.**

## Step 2 — look before you install

```bash
.venv/bin/python scripts/ops_digest.py                 # prints yesterday's digest; sends nothing, writes nothing
.venv/bin/python scripts/watch_okx_changelog.py        # one public fetch; prints what it would send; saves nothing
```

## Step 3 — folders, units and timers

```bash
cd /path/to/ai-trading-model
REPO=$(pwd)
RUN_AS=$(stat -c %U "$REPO")          # the user that owns the checkout
mkdir -p logs/ops && sudo chown -R "$RUN_AS": logs/ops   # the only folder the two services may write
for f in ops-digest.service ops-digest.timer okx-changelog-watch.service okx-changelog-watch.timer; do
  sed -e "s#/path/to/ai-trading-model#$REPO#g" -e "s#CHANGE_ME_USER#$RUN_AS#g" \
      deploy/systemd/$f | sudo tee /etc/systemd/system/$f > /dev/null
done
sudo systemd-analyze verify /etc/systemd/system/ops-digest.service /etc/systemd/system/okx-changelog-watch.service
sudo systemctl daemon-reload
sudo systemctl enable --now okx-changelog-watch.timer ops-digest.timer
systemctl list-timers 'ops-digest*' 'okx-changelog*' --no-pager
```

`systemd-analyze verify` must print nothing (or only warnings about other
units). `list-timers` shows the next run of each in your server's clock
(06:30 and 07:00 Beirut time). If the checkout is owned by `root`, the services
run as root but still without capabilities and with write access to
`logs/ops/` only.

## Step 4 — check it works (now, not tomorrow)

```bash
sudo systemctl start okx-changelog-watch.service      # the first check: baseline + recent flags to Telegram
journalctl -u okx-changelog-watch.service -n 20 --no-pager
# expect: okx changelog: ok (first check: baseline), 4xx entries (4xx new, 0 edited), N flagged
sudo systemctl start ops-digest.service               # today's digest to Telegram
journalctl -u ops-digest.service -n 20 --no-pager
# expect: ops digest YYYY-MM-DD: sent in 1 message(s); saved logs/ops/digest/digest-YYYY-MM-DD.md ...
.venv/bin/python scripts/watch_okx_changelog.py --status
sudo systemctl status shadow.service --no-pager && cat logs/shadow/heartbeat.json
# the Phase 6a run is untouched: state=running, fresh timestamp
```

To test without sending, set `TELEGRAM_DRY_RUN=1` in `/etc/ai-trading/ops.env`
first (then the log says `dry-run`), and set it back to `0` afterwards. The
watcher keeps what it found during a dry run and sends it with its first real
check.

## The optional AI summary

1. In the Anthropic console, in the capped workspace you made for the news
   shadow (`docs/runbooks/NEWS_SHADOW.md`, step 1), create a **second key** (for
   example `ops-digest-vps`), so either can be revoked alone. Its use counts
   against the same workspace limit.
2. `sudoedit /etc/ai-trading/ops.env`: paste it after `ANTHROPIC_API_KEY=`;
   keep or lower `OPS_DIGEST_AI_MONTHLY_CAP_USD`.
3. `sudo systemctl start ops-digest.service` and read the message: the summary
   is at the top. `logs/ops/digest/digest.jsonl` records each run's AI status
   (`ok`, `no_key`, `refusal`, `unverified_numbers`, `spend_cap:...`).

To turn it off, empty the key in the file (or revoke the key in the console).

## Alternative — cron instead of the timers

The timers are the recommended way: they follow Beirut's summer and winter time
by themselves and run a missed day once the server is back. With cron, the
times are in the server's clock (UTC on the VPS): 04:00 UTC is 07:00 in Beirut
in summer and 06:00 in winter. Put the two variables in a file only you can
read (`install -m 600 /dev/null ~/.config/ai-trading-ops.env`, then edit it),
and add with `crontab -e` as the user that owns the checkout:

```cron
30 3 * * * cd /path/to/ai-trading-model && mkdir -p logs/ops && set -a && . "$HOME/.config/ai-trading-ops.env" && set +a && .venv/bin/python scripts/watch_okx_changelog.py --send >> logs/ops/cron.log 2>&1
0 4 * * *  cd /path/to/ai-trading-model && mkdir -p logs/ops && set -a && . "$HOME/.config/ai-trading-ops.env" && set +a && .venv/bin/python scripts/ops_digest.py --send >> logs/ops/cron.log 2>&1
```

Cron gives none of the systemd protections (read-only system, no access to
`.env`): prefer the timers on the VPS.

## Files

| File | What it is |
|---|---|
| `logs/ops/digest/digest-YYYY-MM-DD.md` | The text that was sent (UTC day of the "yesterday" lines) |
| `logs/ops/digest/digest-YYYY-MM-DD.json` | Every fact behind it, for later review |
| `logs/ops/digest/digest.jsonl` | One line per run: sent or not, parts, AI status |
| `logs/ops/digest/_state/spend-YYYY-MM.json` | The AI summary's spend (only with a key) |
| `logs/ops/okx_changelog/changelog_state.json` | Every changelog entry seen, its hash, the flags of the last weeks, alerts not delivered yet |
| `logs/ops/okx_changelog/changelog.jsonl` | One line per check and per flag |

Both services follow `OPS_DIR` in `/etc/ai-trading/ops.env` (the watcher then
keeps its state in `$OPS_DIR/okx_changelog`, where the digest reads it); change
`ReadWritePaths` in both units to the same folder.

A few kilobytes a day (the changelog state is about 200 KB and does not grow
much).

## Stop, remove

```bash
sudo systemctl disable --now ops-digest.timer okx-changelog-watch.timer   # nothing in trading changes
sudo rm /etc/systemd/system/ops-digest.* /etc/systemd/system/okx-changelog-watch.* && sudo systemctl daemon-reload
```

Keep `logs/ops/okx_changelog/`: without it the next start makes a new baseline.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `ops digest not sent: --send needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID` (exit 2) | The environment file has no bot | Step 1 again, then `sudo systemctl start ops-digest.service` |
| `ops digest ...: NOT sent (failed: ...)` (exit 1, the unit shows failed) | Telegram refused or could not be reached; the digest is saved in `logs/ops/digest/` | Check the token and chat id; the next day's run tries again |
| `ops digest ...: sent ...; NOT saved` (exit 1) | The message went out, but `logs/ops/digest/` could not be written (a full disk, or a folder made by a `sudo` run) | `df -h`; `sudo chown -R "$RUN_AS": logs/ops` |
| `okx changelog: ... --- NOT sent (...); kept for the next check ---` | Telegram refused the alert | Nothing: it is sent again with the next checks for 7 days, and the digest lists it meanwhile |
| The digest says the shadow's journal, heartbeat, `ALERT` or `state.json` `could not be read (PermissionError)` | The service user cannot read `logs/shadow` | Make `logs/shadow` readable for the checkout's user (the shadow writes it with the default permissions unless it runs with a strict umask) |
| `The Phase 6a shadow has no heartbeat file` while the shadow runs | The shadow writes somewhere else | Set `PHASE6A_JOURNAL_DIR=` in `/etc/ai-trading/ops.env` to its folder |
| `okx changelog: FAILED (redirected)` | OKX moved the page | Open <https://www.okx.com/docs-v5/log_en/> in a browser; ask an agent session to update `CHANGELOG_URL` in `app/ops/okx_changelog.py` |
| `okx changelog: FAILED (no_entries)` or `(page_shrank)` | The page came back without its entries (a changed layout, or a block page) | Nothing is forgotten; if it repeats for days, ask an agent session to look at the parser with a saved copy (`--from-file`) |
| `okx changelog: FAILED (fetch_failed)` / `(http_status)` | No answer from OKX | `curl -sI https://www.okx.com/docs-v5/log_en/`; it retries the next day |
| `AI summary left out: unverified_numbers` | The AI wrote a number that is not in the facts; the guard dropped it | Nothing; the template was sent. If it repeats daily, turn the AI off |
| `AI summary left out: spend_cap:monthly_cap` | The AI cap of the month is reached | Nothing; it resumes next month (or raise the cap in the file) |

## Related

- `docs/runbooks/NEWS_SHADOW.md` (plan row G5) and `docs/runbooks/PAPER_FLEET.md`
  (plan row G6): until those run, their digest sections say "not installed".
- The Phase 6a shadow's own instant Telegram alerts (fills, ALERT, stale
  heartbeat) are separate and unchanged; the digest is the once-a-day overview.
