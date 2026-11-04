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
| G1 | 🚦 Owner: move the VPS shadow run off WebSocket port 8443 — the three port-less URLs AND a new account name, `demo-shadow-1h-443`, in the VPS `.env`, then restart `shadow.service` | `docs/runbooks/VPS_8443_UPDATE.md` (rewritten 2026-11-04: the WebSocket URLs are part of the fixed demo account identity, so a URL change needs a new account name; the old runbook's Path A would have made `demo-shadow-1h` refuse to start). On 2026-11-04 OKX still accepted port 8443 but answered every connection with "port 8443 will be retired soon": the run is probably still alive and this is the most urgent owner step. `docs/OWNER_CHECKLIST.md`, step 1. | Open, not blocking |
| G2 | 🚦 Owner: open and merge the pull requests — ONE pull request from `plan/auto` into `main` (it already contains S0, S1, S2, S2b and S2c, so their branches need no PRs of their own); then S3 as its own PR against `main`, after an independent review | GitHub. One settings change first: Settings → Branches → edit the rule for `main` → under the required status checks, remove `tests + travel-mode safety guard` and add `tests` (the CI check's name since travel mode was removed, 2026-10-22); otherwise no pull request can merge. The pull request text is ready to paste: `docs/PR_PLAN_AUTO.md`. `docs/OWNER_CHECKLIST.md`, step 2. | Open, not blocking |
| G3 | 🚦 Owner: run the demo stop drills with demo keys on a NEW demo account, then a 2-week demo run | `docs/runbooks/DEMO_STOP_DRILLS.md` (on branch `sprint-3/exchange-side-stops`). Never on `demo-shadow-1h`, and never while `shadow.service` runs on the same OKX demo account: the shadow run reconciles every fill and balance move of that OKX account against its first-day baseline, so a drill fill disarms it permanently and that shadow account can never reconcile again. Simplest: a different OKX account (its own demo environment and keys) for the drills. Otherwise stop `shadow.service` first and, after the drills, restart the shadow run under yet another new account name once the drill fills are older than OKX's 3-day fills window. `docs/OWNER_CHECKLIST.md`, step 5. | Open, not blocking |
| G4 | 🚦 Owner: copy the July–October shadow reports and journals off the VPS into `docs/evidence/` | `docs/runbooks/VPS_8443_UPDATE.md`, last section. | Open, not blocking |
| R4a | Sprint 4a: news agent core, log-only | Phase 6b design sections 4–7, 9 and 13; plan section 5.2. Load the claude-api skill first. Build on the Sprint 1 `app/news` skeleton (fetch, items, sanitize, dedup, store, pipeline): `schema.py` (Pydantic event model and enums exactly as the design); `classifier.py` (Anthropic Python SDK: Haiku 5.5 triage, then Opus 5.5 classification with structured outputs, the frozen and cached system prompt of design section 9, strict validation; any failure or a missing key gives NO_EFFECT); `corroborate.py` (independent-source rules, and price/volume confirmation from public data known before the decision only); `decay.py` (TTL, monotonic decay, source weights, thresholds); `overlay.py` (a pure function that can only block or shrink a new long and never sees exits); append-only JSONL event and decision logs. Add `anthropic` to the lockfile. Tests offline with a mocked client, plus an import-boundary test: `app/news` imports nothing from `app/execution`, `app/risk` or an authenticated exchange client. | Done 2026-10-20 (808608f) |
| R4b | Sprint 4b: news eval set and harness | Design section 15; plan section 5.2. At least 100 labeled fixtures under `tests/fixtures/news_eval/`: corroborated events, syndicated copies, single-source rumors, satire, stale reposts, prompt-injection text, homoglyph and zero-width text, each with its expected action; realistic synthetic headlines, no article bodies. `scripts/eval_news_classifier.py` scores schema validity, prohibited actions, single-source effects and per-category accuracy, calls the model only when `ANTHROPIC_API_KEY` is set and otherwise prints "not run: no API key" and exits 0. Offline tests for the scorer with recorded outputs. `docs/NEWS_AGENT.md` in plain words for the owner. | Done 2026-10-21 (d5374b7) |
| R4c | Sprint 4c: news shadow runner, daily report, VPS unit and runbook | Design sections 11 and 14. `scripts/run_news_shadow.py`: a log-only loop (ingest, sanitize, dedup, classify, corroborate, decay, effective signal, shadow overlay against Phase 6a journal snapshots read from files — never the demo database or any order path); daily `logs/news_shadow/report-YYYY-MM-DD.md`; a `--dry-run --fixtures` mode that runs end to end with no network and no key; a monthly spend cap; a systemd unit file; `docs/runbooks/NEWS_SHADOW.md` for installing it on the VPS with a capped key. No trading mutation, no authenticated OKX access. | Done 2026-10-21 (941c63f) |
| R4d | News rules: the owner's two approved fixes | Owner decisions of 2026-10-21 (section 2). (1) Wire credits: `app/news/corroborate.py` also recognises "Associated Press" and "Agence France-Presse" credits in any capitalisation (eval story `syn-ap-attribution-capitalized`), so copies of one wire story count as one source. (2) HIGH tier: articles on the outlets' own domains (reuters.com, apnews.com, bloomberg.com, wsj.com, dowjones.com, ft.com) get tier HIGH even when an aggregator such as GDELT found them; every other aggregator hit stays MEDIUM. WSJ, Dow Jones Newswires, Barron's and MarketWatch share one owner (Dow Jones) and never count as two independent sources. Tests for both; the free eval self-check still passes (re-label an eval story only where the new rules change its right answer, and list those stories in the report); `docs/NEWS_AGENT.md` and the source-tier open question in `docs/PHASE6B_DESIGN.md` updated. Log-only: changes stay in `app/news`, its tests, the eval fixtures and docs. | Done 2026-10-21 (be96305) |
| G5 | 🚦 Owner: create an Anthropic API key with a monthly cap and start the news shadow on the VPS for 30+ days | `docs/runbooks/NEWS_SHADOW.md` (written by R4c). Expected cost: about $10–40 a month. Owner decisions 2026-10-21: merge R4d first; run the news eval with the capped key and start only if all three of its safety gates pass; $40 a month cap in the service plus a $50 limit on the key for the first month. | Open, not blocking |
| R5a | Sprint 5a: paper fleet | Plan Sprint 5, item 3. Run `docs/research/paper_fleet_shortlist_v1c.json` forward on live PUBLIC OKX data, each configuration as its own local paper account: the confirmed sleeve (S1+S5 on BTC-USDT 6H), the jointly sized BTC+ETH × S1/S2/S4 portfolio (15 % vol target, 7.5/15 % ladder) as one configuration, the other shortlisted rows, and the controls (hold with policy sizing on BTC and ETH, plain buy-and-hold). Use the reviewed local paper engine where it fits, or a forward runner in `research/` that reuses the research strategies through the Strategy-contract adapter; prefer additive changes over edits to `app/paper`. One journal per configuration; `scripts/run_paper_fleet.py`; a weekly ranking report that compares forward results with walk-forward and holdout expectations (tolerance bands, controls first); a systemd unit and `docs/runbooks/PAPER_FLEET.md`. Smoke-run it live for about 30 minutes on public data. No demo account, no authenticated access. | Done 2026-10-21 (004522d) |
| R5b | Sprint 5b: portfolio allocator v2 for the paper fleet | Plan Sprint 5, item 2. Portfolio vol target, correlation cap, portfolio drawdown ladder, weekly loss limit and cooldowns as an optional allocator configuration in the paper fleet and `research/`, with tests and a section in the fleet report. Not in `app/risk`: the demo and live risk manager stays the reviewed core until a separately approved review. | Done 2026-10-22 (b62df75) |
| G6 | 🚦 Owner: start the paper fleet 24/7 (the VPS, or this laptop left on) | `docs/runbooks/PAPER_FLEET.md` (written by R5a; option B2 added 2026-11-04). Free: public data only. Started on this laptop on 2026-11-04 as the Windows scheduled task **AI Trading paper fleet**, from a separate checkout (`C:\Users\Admin\Desktop\ai-trading-fleet`) so runner chats never disturb the record; it catches up after sleep. Moving it to the VPS later means copying its `logs/paper_fleet/` folder, not starting over. | Done 2026-11-04 (laptop task; the owner may move it to the VPS) |
| R6 | Ops digest and OKX change watcher | Plan section 5.4. `scripts/ops_digest.py`: a plain-English daily digest from the shadow heartbeat, journal and reconciliation files and the news-shadow and paper-fleet reports — a deterministic template, with an optional Claude summary only when `ANTHROPIC_API_KEY` is set — sent through the existing Telegram notifier with `TELEGRAM_DRY_RUN` honored. `scripts/watch_okx_changelog.py`: fetches the public OKX API changelog daily, remembers what it has seen, and flags new entries that mention the hosts, ports, paths, channels or auth this repository uses (the port-8443 kind of change). Cron and systemd lines; `docs/runbooks/OPS_DIGEST.md`. | Done 2026-10-22 (2bad1b3) |
| R7 | Event-calendar check | Verify the FOMC decision dates in `research/events.py` (2020–2026, written from memory in Sprint 2c) against the Federal Reserve's published meeting calendar; correct wrong dates with a test; add one paragraph to the owner-decisions section of `docs/research/ENSEMBLE_V1C_REPORT.md` on whether a correction could change any 2c verdict. Do not re-run the research and do not touch the holdout. If the official calendar cannot be reached, leave the dates, say so in that paragraph and in the report, and still commit. Also add the 2027 FOMC decision dates from the same official calendar (owner decision 2026-10-21; the built-in calendar ends 2026-12-09), with a test, and keep the paper fleet's journals resumable: check how its account fingerprints treat the calendar and say in the report what a fleet that is already running needs. | Done 2026-10-22 (330902a) |
| R9 | Phase 9 design study: long and short through perpetual swaps with collateral at least equal to the position (no leverage) | Plan, strategic note after Sprint 2b; v1c report acceptance clause. Paper only: long/short trend numbers 2020–2025 with funding costs, the extra safety rules, the review path. No code near execution, no derivatives access. | Done 2026-10-22 (264b09e) |
| R4e | News follow-up: Financial Times credits and malformed links, log-only | The R4d follow-up recommended in section 2 ("From R4d"; the owner's 2026-11-04 go covers it). (a) `app/news/corroborate.py`: a credit to the Financial Times ("the Financial Times reported", "FT reported", "according to the FT") counts like the wire credits — added as a *link* in both tables (`_LINKED_CREDITS` for the credit text and ft.com → "ft" in `_LINKED_SITES`, so the FT's own article and a copy crediting it fall into one family, as the Dow Jones precedent needed both), never into `_WIRE_ATTRIBUTION`, so the source count can only go down; one eval story and tests for the pair (FT original + a crediting outlet) and the pair (two outlets both crediting the FT). (b) `app/news/items.py`, `canonicalize_url`: a malformed link (`https://[::1/x`, a port above 65535) is skipped and logged instead of failing the whole collection round, so the shadow's SeenStore keeps the round's other items; tests. Re-label an eval story only where the new rules change its right answer and list those stories in the report; the free eval self-check still passes; `docs/NEWS_AGENT.md` known gaps updated. Changes stay in `app/news`, its tests, the eval fixtures and docs. | Done 2026-11-04 (fa0270c) |
| R12 | Replication study: the Sprint 2c rule families on OKX spot markets they were never tuned on, same rules, same gates | Research only, pre-registered, public data only, nothing under `app/` or `config/` changes. Question: do the Sprint 2c rules hold on other markets, or are they BTC-specific? Markets: up to 6 large OKX spot USDT pairs chosen BEFORE any result by public 24-hour volume among those with 1H history from before 2020-01-01 (candidates found 2026-11-04: XRP, LTC, ADA, LINK, BCH, DOGE, TRX, ETC, XLM, ATOM, ALGO) plus SOL-USDT (history from 2020-09-29); write the list and the reason into the report before running. Data: a research-only resumable collector under `research/` using the GET-only `app.datalake.okx_public_rest.OKXPublicRest` (the R9 precedent, `research/longshort_data.py`) writing 1H candles into the lake layout `data/lake/candles/<inst>/1H`; do NOT widen `ALLOWED_INSTRUMENTS` in `app/okx/client.py` (it also bounds demo and paper trading). Rules: exactly the Sprint 2c configurations — parameters, fixed policy sizing, S0 filter, HMM regime fitting, walk-forward windows and gates of `scripts/run_research_v1c.py` — for S1, S1+S5, S2, S2+S5 on 4H and 6H with regime modes none and gate, 6H resampled from 1H as before; S5 needs the market's own funding history: `app/datalake/binance_public.py` rejects every symbol but BTCUSDT/ETHUSDT (`_check_symbol`) and `research/data.py`'s `positioning_context` maps instruments through the app's symbol table, so the public Binance funding fetch (GET `/fapi/v1/fundingRate`), its store and the instrument-to-symbol lookup for the new markets live in `research/` too; a market whose funding coverage is below the Sprint 2b threshold is reported as run without S5, never as S1+S5. A new market's 12-month holdout is opened only for a configuration that passes walk-forward there, once, with an append-only ledger like R9's. Report `docs/research/REPLICATION_V1D_REPORT.md` plus results JSON: per market and rule the gate results, how many configurations pass, and the plain-English verdict (robust across markets, fragile, or BTC-specific), with the BTC/ETH numbers of 2c beside them. Confirmed passers are added to the paper fleet's shortlist the way the fleet's own rules allow (added accounts join; existing entries and running accounts untouched; a `source` tag per new entry) and `docs/runbooks/PAPER_FLEET.md` gets one paragraph on it (a running fleet takes new accounts at its next restart from an updated checkout); if the fleet's public data path is bound to BTC/ETH through `app/okx/client.py`, give the fleet the research-side collector for the new markets. No gate changes after results. | Done 2026-11-04 (971d54c) |
| R13 | Research round 1: up to three pre-registered hypotheses, judged forward | Plan section 5.3 (the research loop) with the Sprint 2c discipline, research only, nothing under `app/`. Before any run, write the pre-registration into the report: each hypothesis, why (the literature in plan section 2.6, or the failure analyses of the 2, 2b, 2c and R9 reports), the exact rule, parameters, markets, timeframes, and the v1c gates; then run walk-forward at the fixed policy sizing; a holdout only for walk-forward passers, once, through the ledger. Suggested candidates — new rules, not retunes of old ones: (1) a BTC-trend condition for ETH entries (ETH rules trade only while BTC's S1 trend is up); (2) an attention or volume confirmation for S1 entries (a 30-day volume z-score above 1 at the entry bar); (3) dual momentum between BTC and ETH (one position, the stronger 90-day performer, only while both trend up). The existing strategies' parameters stay as they are. Report `docs/research/RESEARCH_ROUND_1_REPORT.md` with the plain-English summary and a failure analysis for every hypothesis that fails; confirmed passers go to the fleet shortlist as new accounts, as in R12. Nothing here authorizes trading. | Done 2026-11-04 (5d89014) |
| R14 | Live-readiness design: position persistence across restarts, and lot-precision flatness in the safety core | CLAUDE.md open items 5 and 6; plan section 8, gate 6. Design and test plan ONLY — nothing under `app/`, `config/` or `migrations/` changes. `docs/design/POSITION_PERSISTENCE.md`: what a restart does today (the warm-up rebuilds the strategy window from live candles and exits any open position through the reviewed exit path), every restart scenario on the VPS (reboot, crash, gated auto-restart, deploy), what the demo store already persists (fills, positions, intents; the exchange-side stop on branch `sprint-3/exchange-side-stops`, see its `docs/PHASE6A_EXECUTION_V2.md`), the proposed reviewed change (resume the open position and its stop from the store, reconcile against the venue before any decision, fail closed on any mismatch), how the driver's stop check and exit gating should adopt `is_flat()` (open item 5), what can go wrong and the fail-closed answer to each, the full list of tests (adverse cases first), the migration if any, the review path (AGENTS.md) and the demo validation plan. End with the one decision the owner must make — build it on its own branch after this design is reviewed — as a line in section 2. | Done 2026-11-04 (b7d7aa6) |
| R15 | Reviewed migration workflow and database backups (tooling only) | CLAUDE.md open item 7; plan section 8, gate 7. No schema change, nothing under `app/` changes. (1) `tests/test_migrations.py` is already the models-vs-migrations guard (it upgrades an empty SQLite database and asserts `compare_metadata` is empty, and CI runs it): keep it, tighten it with `compare_type=True` if that stays green, and reference it from the runbook — do not rebuild or weaken it; (2) `scripts/db_backup.sh` and a systemd timer under `deploy/systemd/` for a nightly `pg_dump` with retention, plus a restore drill in `docs/runbooks/DB_MIGRATIONS.md` (how to upgrade the VPS database with a backup first, and how to prove a backup restores); (3) the runbook says plainly what the VPS still runs on (`create_all`; revision 0001 stamped or not) and gives the exact owner steps. Secrets stay in the service environment and are never printed. | Done 2026-11-04 (786585f) |
| R16 | Research round 2 | Plan section 5.3. Up to three more pre-registered hypotheses drawn from the failure analyses of R12 and R13, with the same discipline and report form (`docs/research/RESEARCH_ROUND_2_REPORT.md`). If nothing credible remains to test, say so in a short note in the report and mark the row Done. | Open |
| R10 | Governance slim-down | Plan section 7: one CHANGELOG, short per-phase records, a `research/` sandbox with lighter rules. (Travel mode itself was removed on 2026-10-22.) | Optional — needs the owner's go |
| R11 | Evidence summary of the July–October shadow run | One page from the files of G4: entries, fills, PnL, restarts, alerts. | Optional — needs G4's files first |
| G7 | 🚦 Phase 7 validation: at least 60 days of forward evidence from the paper fleet, the news shadow and demo with exchange-side stops, then the owner's go or no-go | Plan section 8. | Open |

## 1. How it runs

- It runs as the Windows scheduled task **AI Trading plan runner**, in its own PowerShell
  window: `.\scripts\plan-runner.ps1 -WaitForIdle -Push -MaxSteps 40`. It waits until no
  chat in this folder has written for 20 minutes, then runs one fresh chat per Open row on
  branch `plan/auto` (Fable 5.1 at max effort since 2026-11-04; Opus 5.5 before), commits each step there after all checks
  pass, and pushes that branch — never `main`. A usage limit is waited out, then the chat
  resumes where it stopped.
- Stop after the current step: create the file `artifacts\plan-runner\STOP`, or close the
  window to stop at once. Run it again: `Start-ScheduledTask -TaskName 'AI Trading plan runner'`.
- Second run launched 2026-11-04 (rows R4e, R12, R13, R14, R15, R16, then it stops at R10): the
  task was started after the launch commit and begins its first row once no chat in this folder
  has written for 20 minutes. Since 2026-11-04 the task also has a logon trigger, so after a
  reboot the run continues once the owner logs on. The paper fleet runs beside it as the task
  **AI Trading paper fleet** from its own checkout (`docs/runbooks/PAPER_FLEET.md`, option B2);
  the two never touch each other's files.
- See what would run next without starting anything: `.\scripts\plan-runner.ps1 -DryRun`.
- What happened: `artifacts\plan-runner\summary.md`, and one report per step next to it.

## 2. Decisions waiting for the owner

Each line: the decision, then the recommendation. Chats add to this list instead of guessing.

- From R4d: a small log-only follow-up row before G5, (a) recognising credits to the Financial
  Times ("the Financial Times reported") like the wire credits, now that ft.com is HIGH, and
  (b) making the URL cleaner (`app/news/items.py`, `canonicalize_url`) skip a malformed link
  instead of failing the whole collection round (details: `docs/NEWS_AGENT.md`, known gaps).
  Recommendation: yes to both; each can only make the news log more careful or more complete.
  Covered by the owner's 2026-11-04 go and built in row R4e.
- From R4e: whether to recognise credits to other named outlets (CNBC, CoinDesk, The Block,
  Cointelegraph, ...) the way the wires and the Financial Times are, so a copy crediting them
  counts as one source with the original. Recommendation: not now; let the 30-day news shadow's
  logs (G5) show which credits actually appear in the watched feeds, then add only those, each
  as a recognition that can only lower the source count.
- From R5b: the jointly sized portfolio's untouched last 12 months, opened for the first time as allocator v2's paired
  reference, lost 15.0 % (allocator v2: −9.2 %) in the 2025–26 bear market (BTC −26 %, ETH −39 %; the always-long
  controls lost 3–4 %, the confirmed S1+S5 BTC 6H sleeve made +2.3 %; `docs/research/ALLOCATOR_V2_REPORT.md`). Should
  the Sprint 2c framing (the fleet decides between the confirmed sleeve, the portfolio and the controls) change?
  Recommendation: change nothing in the fleet (both portfolio accounts keep running; forward evidence is free), but read
  the confirmed sleeve and the controls as the lead candidates at G7 and the portfolio as contradicted by its holdout.
- From R5b: the portfolio gates proved too easy (no robustness gate at portfolio level, profit factor pooled from sleeves
  that did not pass on their own, timeframes picked on out-of-sample numbers). Recommendation: pre-register for the next
  portfolio study that a portfolio counts as a candidate only when its sleeves pass on their own or its holdout confirms
  it; nothing already run is re-judged.
- From R6: install the daily digest and the OKX changelog watcher on the VPS (`docs/runbooks/OPS_DIGEST.md`, about 15
  minutes, free; rotate the exposed Telegram token first, CLAUDE.md open item 8). Recommendation: yes, right after G2 is
  merged: the watcher is the early warning for the next port-8443 kind of change, the digest the daily check while away.
- From R6: the digest's optional Claude summary (a second key in the capped news-shadow workspace, about $1 a month, its
  own $3 cap). Recommendation: start without it, since the template already says everything in plain words; revisit
  after G5.
- From R6: OKX's changelog of 2026-05-20 recommends a new REST domain, `openapi.okx.com`; `www.okx.com` "will continue to
  work and will not be deprecated". Switching would change the reviewed demo host allowlist (`app/exchange`, safety
  core). Recommendation: no change now; the watcher flags it if OKX ever announces a deprecation.
- From R6, for information: OKX's API documentation now says that continued use of its API means accepting the OKX API
  Agreement (seen 2026-10-22). Recommendation: read it once; this system uses demo trading and public data only.
- From R7, for G6: the FOMC calendar matched the Federal Reserve's for all 2020–2026 dates (nothing corrected, no 2c
  verdict changes) and now runs to 2027-12-08. A paper fleet started on code from before R7 keeps its folder and needs
  only the updated checkout and one restart before 2027-01-27 (`docs/runbooks/PAPER_FLEET.md`). Recommendation: start G6
  from a checkout that includes R7, and add the 2028 dates when the Fed publishes them (the fleet report warns from
  2027-10-09).

- From R9: Phase 9 itself. The long/short design study (`docs/PHASE9_DESIGN_STUDY.md`) found that adding the mirrored
  shorts made the trend rules worse in most cases (Calmar above long-only in 3 of 16 pairs; the BTC shorts lost in 7 of 8);
  one rule, S2 breakout on ETH 6H, passed every test, but the same rule on ETH 4H was contradicted by the holdout, whose
  falling direction was known before it was opened. Recommendation: no Phase 9 build now; revisit only with a short rule
  designed and pre-registered as one, judged on forward data.
- From R9: a paper-only long/short account for S2 on ETH 6H in the paper fleet (new scope: simulated shorts on public prices
  and OKX's public funding; no derivatives access, no key). Recommendation: not now; revisit at G7 if the fleet's long-only S2
  ETH accounts hold up.
- From R9, before any Phase 9 work: whether OKX offers USDT perpetual swaps to your account (your country of residence decides)
  and from the Singapore VPS is a question for OKX and, if needed, a lawyer. Recommendation: ask once, only if Phase 9 is ever
  considered.
- From R9, for information: the 12-month holdout (2025-10 to 2026-10) is used up for long/short questions (its falling
  direction was known). Recommendation: judge any future long/short study on forward data only.

- From 2026-11-04 (the planning session that started the second run): the paper fleet runs on this
  laptop, not the VPS, because agents cannot reach the VPS and the owner asked for the next steps
  without waiting. Recommendation: leave it there until G2 is merged and the VPS checkout is updated,
  then move the record by copying `logs/paper_fleet/` to the VPS and starting the service on the same
  code version (`docs/runbooks/PAPER_FLEET.md`); never run both as "the" fleet.
- From 2026-11-04, for information: OKX's changelog (2026-10-28) announces "SBE order entry and private
  data" as an upcoming change that names the demo environment and the orders channel; the 8443
  retirement entry was last updated 2026-10-22 and port 8443 still answered on 2026-11-04 with a
  retirement notice. Recommendation: nothing to build; the changelog watcher (R6, to be installed on
  the VPS) flags the next step of either change.
- From R12: the two configurations the replication study confirmed (S1 and S1+S5 on SOL-USDT 6H, no
  regime gate: +9.5 % with PF 5.5 over the untouched 12 months, the same 12 trades) are rows 11 and 12
  of the fleet shortlist; the fleet code loads 22 accounts. The laptop fleet started on 2026-11-04 has
  20 until its checkout is updated and the task restarted (`docs/runbooks/PAPER_FLEET.md`, "Updating
  the fleet's code"). Recommendation: update and restart it once `plan/auto` has landed; let the two
  SOL accounts run and judge them at G7 with the rest — they are one signal (the funding filter
  changed nothing on SOL) from the market with the shortest history.
- From R12, for information: the Sprint 2c families are fragile across markets — 10 of 104
  configurations passed walk-forward on the seven new markets, none of the three BTC passers
  replicated, and the holdout rejected 8 of the 10 (7 clearly; DOGE S2 4H gate was positive from 8
  trades, fewer than the 10 the v1c verdict asks for). Hold + policy sizing lost on every market's
  12 months, as on BTC/ETH. No gate changed after the results; the S2 family's three contradicted
  markets are the failure analysis rows R13 and R16 should start from. Nothing to decide.
- From R13: the one configuration research round 1 confirmed (S1 with new entries only on a 30-day
  volume z-score above 1, on BTC-USDT 4H with the regime gate: walk-forward Calmar 0.55 / Sharpe 0.71,
  +2.0 % with PF 1.41 over the untouched 12 months from 25 trades) is row 13 of the fleet shortlist
  (`c13-s1vc-btc-4h-gate`); the fleet code loads 23 accounts. The laptop fleet started on 2026-11-04
  has 20 until its checkout is updated and the task restarted (`docs/runbooks/PAPER_FLEET.md`,
  "Updating the fleet's code"). Recommendation: update and restart it once `plan/auto` has landed and
  judge the account at G7 with the rest — it is one pass among 20 comparisons that clears two gates by
  a hair, its rule was selected in only 2 of 9 windows, and the holdout's falling direction was known
  beforehand, so read it as a hypothesis under forward test, not a result.
- From R13, for information: H1 (ETH's rules only while BTC's trend is up) changed little beside the
  base rules (median Calmar 0.36 → 0.30; the HMM gate already stands aside in most of those bars) and
  H3 (dual momentum between BTC and ETH) churned (57 trades a year against 35, Calmar 0.11 against
  0.31 for plain S1); neither is worth a retest in this form. The volume confirmation gained most
  where the base rule was weakest (the gated 4H rules) and lost on 6H; a candidate for R16 is its
  strictness or the attention idea on R12's markets, pre-registered and fixed a priori, never swept.
  No gate changed after the results. Nothing to decide.
- From R14: whether to build the position-persistence and lot-precision change described in
  `docs/design/POSITION_PERSISTENCE.md` on its own branch after an independent review of that design.
  It is a safety-core change (`app/execution` driver, runtime and store, the shadow supervisor's
  start-up order, `scripts/run_demo_trading.py`), so building it is not delegated to the runner.
  Recommendation: yes, in two parts: part A (lot-precision gating: dust and an unsellable remainder
  no longer count as an open position; `--release-stale-lock` also disarms) first, as a small
  reviewed change from `main` once G2 has merged, deployed to the shadow run by runbook so Phase 6a
  can produce entries again; part B (the resume protocol: the strategy window rebuilt exactly from
  OKX's public candle history after the fail-closed gate, so a restart no longer sells a position
  the rule would have kept, with today's behaviour as the fallback) on top of
  `sprint-3/exchange-side-stops` after the G3 drills, validated by the design's demo drills on a
  non-shadow OKX account. Until part B is deployed, restart the shadow run only while the heartbeat
  says `flat_at_lot: true`.
- From R14, for information: an offline reproduction with the real driver shows that after the first
  round trip the sub-lot fee dust (seen live on June 11) makes every later entry fail with
  `position_already_open`, and that a candle low under the stale stop level skips the strategy for
  that candle. `demo-shadow-1h` made one round trip on June 21, so it has very likely been unable to
  open a position since; the G4 files settle it (daily reports after June 21 reading "FLAT at lot
  precision (sub-lot dust ...)", journal `event` lines with `position_already_open`). A hard crash
  (kill, out-of-memory, power loss) also leaves the dead process's lock in place, so the supervisor
  halts with `restart_budget_exhausted` within about two minutes and an open position is unmanaged
  until the operator runs `--release-stale-lock` and `--acknowledge-alert`. Nothing to decide now;
  both are addressed by the R14 change, and the lock rule stays operator-only by design.
- From 2026-11-04: one test in `tests/test_okx_changelog.py` compared the fixture's entry dates with
  the real clock and began failing on its own on 2026-10-29 (when the oldest flagged entry left the
  30-day first-run window), which would have stopped every runner chat at its full-suite check. Fixed in this session (the script's clock can be pinned by tests). No decision
  needed; recorded so nobody hunts for a code regression.
- From R15: the nightly backup, the restore drill and the Alembic stamp are owner steps on the VPS
  (`docs/runbooks/DB_MIGRATIONS.md`, steps 1–3, about 25 minutes, free; `docs/OWNER_CHECKLIST.md`
  item 3). Recommendation: do them right after G2 and the checkout update, in that order — backup
  and drill first, the stamp last — and before any future `alembic upgrade` (Sprint 3's revision
  0002 will be the first). Until step 1 is done nothing backs the VPS database up.
- From R15: a one-line section for the nightly backup in the daily ops digest (reading
  `latest.json`: last status, age, dumps kept). It is a small `app/ops` change, outside R15's
  "nothing under `app/`" scope, observability only. Recommendation: yes, as a small follow-up row.
- From R15: an off-host copy of the backups (today they live on the same disk as the database).
  Options: DigitalOcean's paid droplet backups, or the free weekly `rsync` to the laptop shown in
  the runbook. Recommendation: the free copy when convenient; the paid option before any live phase.
- From R15, for information: CLAUDE.md open item 7 ("no production migration workflow") describes
  the VPS correctly until the owner has installed the backup and stamped the database; after that
  the item's wording should change in a reviewed doc edit (CLAUDE.md is a phase-gate document, so
  the runner does not edit it). `tests/test_migrations.py` was tightened (types and server defaults
  compared) and stays green; `app/db/models.py` is identical on `main` and `plan/auto`, so the VPS
  schema equals the baseline and the stamp will match. Nothing to decide.
- From R16: the one configuration research round 2 confirmed (the round-1 volume confirmation on
  S1 — new entries only on a 30-day volume z-score above 1 — on DOGE-USDT 4H with the regime gate:
  walk-forward Calmar 0.83 from 67 trades, +1.8 % with PF 1.65 over the untouched 12 months from 18
  trades) is row 14 of the fleet shortlist (`c14-s1vc-doge-4h-gate`); the fleet code loads 24
  accounts. The laptop fleet started on 2026-11-04 has 20 until its checkout is updated and the task
  restarted (`docs/runbooks/PAPER_FLEET.md`, "Updating the fleet's code"). Recommendation: update and
  restart it once `plan/auto` has landed and judge the account at G7 with the rest — as a hypothesis,
  not a result: on the seven replication markets the condition raised Calmar beside plain S1 in 25 of
  28 configurations (a strong directional replication of round 1, consistent with its gated-4H
  pattern), but of its 5 walk-forward passers the holdout confirmed only this one and contradicted
  4, among them SOL-USDT 6H, where plain S1's own holdout had been confirmed (+9.5 %) and the
  filtered rule lost (-1.6 %).
- From R16: the two slow-trend hypotheses — the close above its 200-day moving average as an entry
  filter for the breakout rule (S2+TF) and as the exposure rule itself (TF, Faber's rule with the
  policy sizing) — could not be judged. The protocol's selection step needs a rule variant with 20
  train trades in a window, and the slow rules reached that in 53 of 180 and 13 of 180 windows, so
  they sat flat; where they traded they did not beat their comparison lines (Calmar up in 4 of 20
  and 3 of 20). Untested rather than refuted. Decision: whether to evaluate slow rules another way —
  (a) a forward control account "always long above the 200-day average, policy sizing" in the paper
  fleet beside the hold controls (free, judged forward, a fleet scope change), or (b) a
  pre-registered protocol variant with a lower qualification threshold for fixed rules (a new
  research row). Recommendation: (a) after G2, and not (b): a rule that trades a few times a year
  gives a backtest too few observations to clear gates built for weekly rules, while the fleet
  already judges hold + policy forward and would show the filter's worth beside it at G7.
- From R16, for information: nothing credible remains from the R12 and R13 failure analyses for a
  further round under this protocol — the fast cross-asset trend condition and dual momentum are not
  worth retesting (R13), the volume confirmation has now been replicated in direction and is in the
  fleet (c13, c14), the slow trend filter needs a different protocol (above), and the strictness of
  the volume confirmation stays deferred until the fleet has judged the z > 1 accounts. No gate,
  parameter or verdict rule changed after the results; all 90 reproductions of the stored Sprint 2c
  and R12 numbers matched. Recommendation: no further research round now; the next research work
  waits for the fleet's forward evidence (G7).

### Decided — the owner, 2026-11-04

- "Do the next appropriate steps without the need of my decisions" and "automate the process like
  we did previously with the plan runner, all on Fable max": the runner's default model is now
  Fable 5.1 at max effort (`scripts/plan-runner.ps1 -Model`), the rows R4e and R12–R16 above were
  opened under that go, the paper fleet (G6) was started on the laptop, and the owner steps that
  only the owner can do (G1–G5, the Telegram token, the stale `demo` row) are collected in
  `docs/OWNER_CHECKLIST.md`. The safety contract is unchanged: no row touches `app/execution`,
  `app/risk`, `app/exchange`, `app/shadow` or `config/`; R14 produces a design, and building it
  stays an explicit owner decision.

### Decided — the owner, 2026-10-22

- Remove travel mode and everything related to it: the CI safety guard
  (`scripts/check_travel_mode_safety.py`) and its tests, the `TRAVEL_MODE` switch, the CI
  Telegram notifications (`notify.yml`), the GitHub Claude action (`claude.yml`) and the
  travel docs. The CI check is now called `tests` (see G2 for the one GitHub setting). The
  trading safety contract in `CLAUDE.md` is unchanged.

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
