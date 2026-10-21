# Plan status — AI Trading Model

This is the live status of [`MASTER_PLAN_2026-10-20.md`](MASTER_PLAN_2026-10-20.md).
`scripts/plan-runner.ps1` reads the table in section 0 and builds the first row that is
not Done in a fresh, unattended chat — one chat per row, so nothing compounds. Decisions a
chat may not make collect in section 2 for the owner.

Status words: **Done** — built, tested and committed on its branch (merging is the owner's,
row G2). **Open** — the runner may build it. **Open, not blocking** on a 🚦 row — an owner
action the runner passes over. **Optional** — needs the owner's go; the runner stops there.
A 🚦 row that is plain **Open** stops the runner. **In progress** — another chat is on it.

## 0. Status

| Step | What | Scope | Status |
|---|---|---|---|
| S0 | Sprint 0: OKX port-8443 fix, hashed lockfile, pip-audit CI, Alembic baseline, hygiene | Branch `sprint-0/okx-8443-and-hygiene`. Plan Sprint 0. | Done 2026-10-20 (acb17f6) |
| S1 | Sprint 1: Parquet data lake, 7-year history backfill, derivatives collectors, log-only news ingestion skeleton | Branch `sprint-1/data-lake-v2`. Plan Sprint 1. | Done 2026-10-20 (c088ced) |
| S2 | Sprint 2: research lab, strategies S0 to S5, walk-forward; 0 of 42 pass | Branch `sprint-2/research-lab`. `docs/research/ENSEMBLE_V1_REPORT.md`. | Done 2026-10-20 (fd922f3) |
| S2b | Sprint 2b: sizing, risk, 6H bars, Binance positioning history; 0 of 28 pass | Branch `sprint-2b/sizing-and-risk` (its tip 18979e2 adds the planner's decisions). `docs/research/ENSEMBLE_V1B_REPORT.md`. | Done 2026-10-20 (fd8ff66) |
| S2c | Sprint 2c: regime gates, portfolio sizing, lower turnover, paper-fleet shortlist; 4 of 108 pass walk-forward, the holdout confirms 1 | Branch `sprint-2c/regime-portfolio`. `docs/research/ENSEMBLE_V1C_REPORT.md`, `docs/research/paper_fleet_shortlist_v1c.json`. | Done 2026-10-20 (3e8a75e) |
| S3 | Sprint 3: exchange-side protective stops, post-only entry policy, optional exit bracket, stop alarm — built and tested without credentials | Branch `sprint-3/exchange-side-stops` (based on S0, safety core). `docs/PHASE6A_EXECUTION_V2.md`. Demo drills are row G3. | Done 2026-10-20 (701cbbb) |
| G1 | 🚦 Owner: put the three port-less WebSocket URLs in the VPS `.env` and restart `shadow.service` **before Oct 31** | `docs/runbooks/VPS_8443_UPDATE.md`, Path A. Works with the code deployed today. | Open, not blocking |
| G2 | 🚦 Owner: open and merge the pull requests — research stack in order S0, S1, S2, S2b, S2c, then `plan/auto`; S3 as its own PR against `main` after S0 and after an independent review | GitHub. The travel-mode check fails on purpose where safety or governance files change. | Open, not blocking |
| G3 | 🚦 Owner: run the demo stop drills with demo keys on a NEW demo account, then a 2-week demo run | `docs/runbooks/DEMO_STOP_DRILLS.md`. Never on `demo-shadow-1h`. | Open, not blocking |
| G4 | 🚦 Owner: copy the July–October shadow reports and journals off the VPS into `docs/evidence/` | `docs/runbooks/VPS_8443_UPDATE.md`, last section. | Open, not blocking |
| R4a | Sprint 4a: news agent core, log-only | Phase 6b design sections 4–7, 9 and 13; plan section 5.2. Load the claude-api skill first. Build on the Sprint 1 `app/news` skeleton (fetch, items, sanitize, dedup, store, pipeline): `schema.py` (Pydantic event model and enums exactly as the design); `classifier.py` (Anthropic Python SDK: Haiku 5.5 triage, then Opus 5.5 classification with structured outputs, the frozen and cached system prompt of design section 9, strict validation; any failure or a missing key gives NO_EFFECT); `corroborate.py` (independent-source rules, and price/volume confirmation from public data known before the decision only); `decay.py` (TTL, monotonic decay, source weights, thresholds); `overlay.py` (a pure function that can only block or shrink a new long and never sees exits); append-only JSONL event and decision logs. Add `anthropic` to the lockfile. Tests offline with a mocked client, plus an import-boundary test: `app/news` imports nothing from `app/execution`, `app/risk` or an authenticated exchange client. | Done 2026-10-20 (808608f) |
| R4b | Sprint 4b: news eval set and harness | Design section 15; plan section 5.2. At least 100 labeled fixtures under `tests/fixtures/news_eval/`: corroborated events, syndicated copies, single-source rumors, satire, stale reposts, prompt-injection text, homoglyph and zero-width text, each with its expected action; realistic synthetic headlines, no article bodies. `scripts/eval_news_classifier.py` scores schema validity, prohibited actions, single-source effects and per-category accuracy, calls the model only when `ANTHROPIC_API_KEY` is set and otherwise prints "not run: no API key" and exits 0. Offline tests for the scorer with recorded outputs. `docs/NEWS_AGENT.md` in plain words for the owner. | Done 2026-10-21 (d5374b7) |
| R4c | Sprint 4c: news shadow runner, daily report, VPS unit and runbook | Design sections 11 and 14. `scripts/run_news_shadow.py`: a log-only loop (ingest, sanitize, dedup, classify, corroborate, decay, effective signal, shadow overlay against Phase 6a journal snapshots read from files — never the demo database or any order path); daily `logs/news_shadow/report-YYYY-MM-DD.md`; a `--dry-run --fixtures` mode that runs end to end with no network and no key; a monthly spend cap; a systemd unit file; `docs/runbooks/NEWS_SHADOW.md` for installing it on the VPS with a capped key. No trading mutation, no authenticated OKX access. | Done 2026-10-21 (941c63f) |
| R4d | News rules: the owner's two approved fixes | Owner decisions of 2026-10-21 (section 2). (1) Wire credits: `app/news/corroborate.py` also recognises "Associated Press" and "Agence France-Presse" credits in any capitalisation (eval story `syn-ap-attribution-capitalized`), so copies of one wire story count as one source. (2) HIGH tier: articles on the outlets' own domains (reuters.com, apnews.com, bloomberg.com, wsj.com, dowjones.com, ft.com) get tier HIGH even when an aggregator such as GDELT found them; every other aggregator hit stays MEDIUM. WSJ, Dow Jones Newswires, Barron's and MarketWatch share one owner (Dow Jones) and never count as two independent sources. Tests for both; the free eval self-check still passes (re-label an eval story only where the new rules change its right answer, and list those stories in the report); `docs/NEWS_AGENT.md` and the source-tier open question in `docs/PHASE6B_DESIGN.md` updated. Log-only: changes stay in `app/news`, its tests, the eval fixtures and docs. | Done 2026-10-21 (be96305) |
| G5 | 🚦 Owner: create an Anthropic API key with a monthly cap and start the news shadow on the VPS for 30+ days | `docs/runbooks/NEWS_SHADOW.md` (written by R4c). Expected cost: about $10–40 a month. Owner decisions 2026-10-21: merge R4d first; run the news eval with the capped key and start only if all three of its safety gates pass; $40 a month cap in the service plus a $50 limit on the key for the first month. | Open, not blocking |
| R5a | Sprint 5a: paper fleet | Plan Sprint 5, item 3. Run `docs/research/paper_fleet_shortlist_v1c.json` forward on live PUBLIC OKX data, each configuration as its own local paper account: the confirmed sleeve (S1+S5 on BTC-USDT 6H), the jointly sized BTC+ETH × S1/S2/S4 portfolio (15 % vol target, 7.5/15 % ladder) as one configuration, the other shortlisted rows, and the controls (hold with policy sizing on BTC and ETH, plain buy-and-hold). Use the reviewed local paper engine where it fits, or a forward runner in `research/` that reuses the research strategies through the Strategy-contract adapter; prefer additive changes over edits to `app/paper`. One journal per configuration; `scripts/run_paper_fleet.py`; a weekly ranking report that compares forward results with walk-forward and holdout expectations (tolerance bands, controls first); a systemd unit and `docs/runbooks/PAPER_FLEET.md`. Smoke-run it live for about 30 minutes on public data. No demo account, no authenticated access. | Done 2026-10-21 (004522d) |
| R5b | Sprint 5b: portfolio allocator v2 for the paper fleet | Plan Sprint 5, item 2. Portfolio vol target, correlation cap, portfolio drawdown ladder, weekly loss limit and cooldowns as an optional allocator configuration in the paper fleet and `research/`, with tests and a section in the fleet report. Not in `app/risk`: the demo and live risk manager stays the reviewed core until a separately approved review. | Open |
| G6 | 🚦 Owner: start the paper fleet 24/7 (the VPS, or this laptop left on) | `docs/runbooks/PAPER_FLEET.md` (written by R5a). Free: public data only. | Open, not blocking |
| R6 | Ops digest and OKX change watcher | Plan section 5.4. `scripts/ops_digest.py`: a plain-English daily digest from the shadow heartbeat, journal and reconciliation files and the news-shadow and paper-fleet reports — a deterministic template, with an optional Claude summary only when `ANTHROPIC_API_KEY` is set — sent through the existing Telegram notifier with `TELEGRAM_DRY_RUN` honored. `scripts/watch_okx_changelog.py`: fetches the public OKX API changelog daily, remembers what it has seen, and flags new entries that mention the hosts, ports, paths, channels or auth this repository uses (the port-8443 kind of change). Cron and systemd lines; `docs/runbooks/OPS_DIGEST.md`. | Open |
| R7 | Event-calendar check | Verify the FOMC decision dates in `research/events.py` (2020–2026, written from memory in Sprint 2c) against the Federal Reserve's published meeting calendar; correct wrong dates with a test; add one paragraph to the owner-decisions section of `docs/research/ENSEMBLE_V1C_REPORT.md` on whether a correction could change any 2c verdict. Do not re-run the research and do not touch the holdout. If the official calendar cannot be reached, leave the dates, say so in that paragraph and in the report, and still commit. Also add the 2027 FOMC decision dates from the same official calendar (owner decision 2026-10-21; the built-in calendar ends 2026-12-09), with a test, and keep the paper fleet's journals resumable: check how its account fingerprints treat the calendar and say in the report what a fleet that is already running needs. | Open |
| R9 | Phase 9 design study: long and short through perpetual swaps with collateral at least equal to the position (no leverage) | Plan, strategic note after Sprint 2b; v1c report acceptance clause. Paper only: long/short trend numbers 2020–2025 with funding costs, the extra safety rules, the review path. No code near execution, no derivatives access. | Open — the owner's go for this paper-only study, 2026-10-21; Phase 9 itself is not authorized |
| R10 | Governance slim-down | Plan section 7: one CHANGELOG, short per-phase records, a `research/` sandbox with lighter rules, travel-mode rules that stop blocking routine research pull requests while the safety-path guard stays. | Optional — needs the owner's go |
| R11 | Evidence summary of the July–October shadow run | One page from the files of G4: entries, fills, PnL, restarts, alerts. | Optional — needs G4's files first |
| G7 | 🚦 Phase 7 validation: at least 60 days of forward evidence from the paper fleet, the news shadow and demo with exchange-side stops, then the owner's go or no-go | Plan section 8. | Open |

## 1. How it runs

- It runs as the Windows scheduled task **AI Trading plan runner**, in its own PowerShell
  window: `.\scripts\plan-runner.ps1 -WaitForIdle -Push -MaxSteps 40`. It waits until no
  chat in this folder has written for 20 minutes, then runs one fresh chat per Open row on
  branch `plan/auto` (Opus 5.5, max effort), commits each step there after all checks
  pass, and pushes that branch — never `main`. A usage limit is waited out, then the chat
  resumes where it stopped.
- Stop after the current step: create the file `artifacts\plan-runner\STOP`, or close the
  window to stop at once. Run it again: `Start-ScheduledTask -TaskName 'AI Trading plan runner'`.
- See what would run next without starting anything: `.\scripts\plan-runner.ps1 -DryRun`.
- What happened: `artifacts\plan-runner\summary.md`, and one report per step next to it.

## 2. Decisions waiting for the owner

Each line: the decision, then the recommendation. Chats add to this list instead of guessing.

- From R4d: a small log-only follow-up row before G5, (a) recognising credits to the Financial
  Times ("the Financial Times reported") like the wire credits, now that ft.com is HIGH, and
  (b) making the URL cleaner (`app/news/items.py`, `canonicalize_url`) skip a malformed link
  instead of failing the whole collection round (details: `docs/NEWS_AGENT.md`, known gaps).
  Recommendation: yes to both; each can only make the news log more careful or more complete.

### Decided — the owner, 2026-10-21 ("yes to all of your recommendations")

- R9, the paper-only long/short design study: **yes**. R9 is Open. Trading shorts,
  derivatives access and Phase 9 itself stay unauthorized.
- Sprint 2c acceptance: **yes**. The Phase 7/8 product is risk-managed exposure plus a news
  brake. The paper fleet (R5a) decides between the confirmed sleeve, the jointly sized
  portfolio and the controls.
- Sprint 3 design: **accepted**. The protective stop is a stand-alone exchange order placed
  right after each fill, not attached to the entry order. The drills (G3) measure the
  seconds between fill and stop. Independent review and the drills are still required
  before any live use.
- R4a news source tiers: **yes**. HIGH = Reuters, AP, Bloomberg, Dow Jones/WSJ (one owner
  family) and the Financial Times. Built in R4d. Log-only either way.
- R4b news eval: **yes**. Run it with the capped key before the news shadow starts and after
  any prompt or model change. A FAIL on any of its three safety gates means the shadow
  does not start.
- R4b/R4c news-rule fix (1), the "Associated Press" / "Agence France-Presse" credit gap:
  **yes**, built in R4d before G5. Fix (2) was done in R4c.
- R4c AI budget: **yes**. The service stops at $40 a month and the key has a $50 limit for
  the first month. Read the spend line after a week, then adjust.
- R5a FOMC calendar: **yes**. R7 also adds the 2027 dates.

The last three came in after the owner's answer. They were taken under the same "yes" and
the owner was told; each is easy to reverse.
