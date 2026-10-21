# VPS runbook — start the news shadow (Phase 6b, log-only)

**Audience:** the human operator, on the DigitalOcean Singapore VPS that runs the
Phase 6a shadow (`shadow.service`). **Agents cannot reach the VPS**; every step
here is an operator action (plan row G5).

## What it is, and what it is not

The news shadow is a **separate, log-only observer** next to the Phase 6a run.
Every 5 minutes it reads a few news sources — the SEC and Federal Reserve press
feeds, the Coinbase status page, and GDELT, a free index of world news — cleans
and de-duplicates the headlines, asks Claude (Haiku 5.5 first, Opus 5.5 for real
candidates) whether a story makes a new bitcoin or ether position riskier, and
applies the fixed rules: two independent sources or a matching market move,
fading over a few hours, then stopping. For every new-long decision the Phase 6a
run makes, it writes down what the news layer **would** have done: nothing,
reduce, or block.

- It places, sizes, approves, modifies and cancels **nothing**. It cannot.
- It has **no OKX keys**, never loads the repository `.env`, never calls an
  authenticated OKX endpoint and never opens the demo database. It reads the
  Phase 6a journal files (`logs/shadow/journal-*.jsonl`) read-only.
- It never touches `shadow.service`. Stopping, restarting or removing it changes
  nothing in trading.
- It writes only `logs/news_shadow/` (logs, daily reports, its state) and
  `data/news/` (the cleaned headlines), and it cannot read the repository `.env`
  or reach the PostgreSQL socket. systemd enforces this.
- Anything that goes wrong (no key, AI down, spend cap reached, a source down, a
  skewed clock) means **no effect** in the log, never a block.

**Cost.** Estimated $10–40 a month in Claude API calls. The service stops
calling the AI at its own monthly cap (default **$40**), and no single day may
use more than twice its even share of what is left that month. The spend limit
you set on the API key's workspace in the Anthropic console is the hard backstop.

## Before you start

1. **The code is on the VPS.** The news shadow arrives with the `plan/auto` pull
   request (plan row G2). After it is merged, update the checkout the same way as
   `docs/runbooks/VPS_8443_UPDATE.md`, Path B steps 1–2:

   ```bash
   cd /path/to/ai-trading-model                     # the checkout shadow.service runs from
   git fetch && git status                          # clean, on main
   git pull
   .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
   ```

   Updating the checkout does not restart `shadow.service`; it keeps running the
   code it started with until you restart it.

2. **Offline check on the VPS** (no key, no internet, a few seconds):

   ```bash
   .venv/bin/python scripts/run_news_shadow.py --dry-run
   ```

   It must end with `safety checks: all passed` and every `expect ... ok`. It
   writes only to a new temporary folder (printed at the end).

3. **Recommended: run the news eval once with the key from step 1 below**
   (`docs/NEWS_AGENT.md`, about $4–10). A FAIL on any of its three safety gates is
   a reason not to start the shadow.

## Step 1 — a capped Anthropic API key (Anthropic console, in the browser)

1. Create a separate **workspace** for the news shadow (for example
   `news-shadow`).
2. In that workspace's limits, set a **monthly spend limit** a little above the
   software cap, for example **$50** with the default $40 cap.
3. Create an **API key inside that workspace** (for example `news-shadow-vps`).
   Copy it once, straight into step 2. Never paste it into a chat, an issue, a
   screenshot or the repository.

## Step 2 — the service's own environment file (VPS)

The key goes into a root-only file that only this service reads. **Never put it
in the repository `.env`** (that file holds the OKX demo keys) and never point
the service at that file.

```bash
cd /path/to/ai-trading-model
sudo install -d -m 750 -o root -g root /etc/ai-trading
sudo install -m 600 -o root -g root deploy/systemd/news-shadow.env.example /etc/ai-trading/news-shadow.env
sudoedit /etc/ai-trading/news-shadow.env
```

In the editor, paste the key after `ANTHROPIC_API_KEY=` (no quotes, no spaces)
and, if you want, change `NEWS_SHADOW_MONTHLY_CAP_USD`. Save. Do not `cat` the
file afterwards.

## Step 3 — folders and the service file

```bash
cd /path/to/ai-trading-model
REPO=$(pwd)
RUN_AS=$(stat -c %U "$REPO")          # the user that owns the checkout
mkdir -p logs/news_shadow data/news   # the only two folders the service may write
sudo chown -R "$RUN_AS": logs/news_shadow data/news
sed -e "s#/path/to/ai-trading-model#$REPO#g" -e "s#CHANGE_ME_USER#$RUN_AS#g" \
    deploy/systemd/news-shadow.service | sudo tee /etc/systemd/system/news-shadow.service > /dev/null
sudo systemd-analyze verify /etc/systemd/system/news-shadow.service
```

`systemd-analyze verify` must print nothing (or only warnings about other
units). If the checkout is owned by `root`, the service runs as root but still
with no capabilities and write access only to the two news folders.

The unit blocks the repository `.env` itself, but it cannot block copies of it.
If `.env.bak-*` files are still in the checkout from the port-8443 update and that
update is confirmed, delete them: they hold the same secrets as `.env`.

```bash
ls -la .env.bak-* 2>/dev/null && rm -i .env.bak-*
```

## Step 4 — start it

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now news-shadow.service
sudo systemctl status news-shadow.service --no-pager
```

## Step 5 — check it works (first 15 minutes)

```bash
journalctl -u news-shadow.service -n 30 --no-pager
# expect a line every ~5 minutes:  cycle N: healthy=True items=... triage=... stories=... decisions=... errors=0
.venv/bin/python scripts/run_news_shadow.py --status
# spend this month, the last cycle, live events, and "ANTHROPIC_API_KEY in this environment: no"
# (correct: your shell does not have the key, only the service does)
ls logs/news_shadow/
# events-YYYY-MM-DD.jsonl, decisions-YYYY-MM-DD.jsonl (after the first Phase 6a decision), report-YYYY-MM-DD.md, _state/
sudo systemctl status shadow.service --no-pager && cat logs/shadow/heartbeat.json
# the Phase 6a run is untouched: state=running, fresh timestamp
```

The first cycle reads the feeds' backlog; anything older than 24 hours is logged
and skipped without an AI call. The first Phase 6a candidate shows up at the next
hourly LONG signal of the 1H strategy, which can take hours or days.

## The daily report

`logs/news_shadow/report-YYYY-MM-DD.md` is rebuilt every 15 minutes from the
logs alone, and yesterday's report again during the first hours after midnight
(UTC), once the price path after late decisions is in the journal. Rebuild any
day by hand with `.venv/bin/python scripts/run_news_shadow.py --report YYYY-MM-DD`.
The logs grow by a few MB a day.

- **In short** — cycles, health, articles, AI calls and spend, events, and the
  Phase 6a decisions the news layer would have blocked or reduced.
- **Safety checks** — eight counts that must all be 0 (no single-source or
  expired event with an effect, nothing evaluated that is not a new-long decision
  in the Phase 6a journal, no size increase, no double counting, no effect while
  unhealthy, no already-blocked entry counted as prevented, and no entry taken as
  allowed unless the journal says the runtime allowed it). **If any says FAIL:
  stop the service and ask for a review.**
- **Shadow entry overlays** — each Phase 6a new-long decision: what the existing
  rules decided, what the news layer would have done, and the price 6 hours
  later (a description, not a trade result).
- **Events, sources, AI calls** — what was seen, confirmed, and spent.
- **For manual review** — possible missed events and possible false blocks. Read
  these by hand; they are prompts for judgment, not scores.

Nothing in the report claims profit. The 30-day pass criteria are in
`docs/PHASE6B_DESIGN.md` section 11.

## Money: what happens at the cap

- At the monthly cap (or a day's pace limit) the shadow stops calling the AI;
  it keeps collecting and logging news, and every story it could not classify is
  logged as such. The report's runner section says "the spend cap stopped
  classification". It starts again on the next day (pace) or month (cap).
- The spend shown is an estimate from list prices; the console's billing page is
  the real bill.
- To change the cap: `sudoedit /etc/ai-trading/news-shadow.env`, then
  `sudo systemctl restart news-shadow.service`.

## Stop, restart, remove

```bash
sudo systemctl stop news-shadow.service       # nothing in trading changes
sudo systemctl restart news-shadow.service    # state survives: events, spend, health history
sudo systemctl disable --now news-shadow.service
sudo rm /etc/systemd/system/news-shadow.service && sudo systemctl daemon-reload
```

To cut off the AI completely, delete the key in the Anthropic console. The
service then fails its AI calls (no effect) until you stop it.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `news shadow not started: ANTHROPIC_API_KEY is not set` (exit 2, no restart loop) | The environment file has no key | Step 2 again, then `sudo systemctl restart news-shadow.service` |
| `another instance holds .../runner.lock` | A manual `--once`/`--loop` is running | Stop the manual run |
| `healthy=False` with `clock_skew` | The VPS clock is off by more than 30 s | `timedatectl status`; enable NTP (`sudo timedatectl set-ntp true`) |
| `healthy=False` with `clock_unverified` | The exchange clock could not be read for 30 minutes, so the clock cannot be checked | Check the VPS network; it recovers by itself when the check succeeds |
| `healthy=False` with `all_sources_failed` | No source answered this cycle | Check the VPS network; it recovers by itself |
| Report: "Phase 6a journal directory not found" | The journal is not at `logs/shadow` | Set `PHASE6A_JOURNAL_DIR=` in the environment file |
| Many `rate_limited` failures in the first days | A new key starts with low rate limits | Nothing; failed calls are no effect and are not billed |
| `spend record problem` in `--status` | The month's spend file is unreadable; the shadow treats the month as spent | Check the console's real spend, then remove `logs/news_shadow/_state/spend-YYYY-MM.json` and restart |

## After 30 days (plan rows G5 → G7)

Copy `logs/news_shadow/` (reports and JSONL logs) off the VPS, the same way as
the Phase 6a evidence (`docs/runbooks/VPS_8443_UPDATE.md`, last section), and
hand it to an agent session for the review against the design's section 11
criteria. Passing them does not authorize anything: using news to gate demo or
live entries needs a separate decision from you.
