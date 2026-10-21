# Changelog

All notable changes to this repository. Dates are UTC. Nothing in this file
authorizes a phase, live trading, or a safety-core change; see
`PROJECT_RULES.md` and `CLAUDE.md`.

## Unreleased — Sprint 4c: news shadow runner, daily report, VPS unit and runbook (plan row R4c; Phase 6b design §11, §13, §14)

Log-only: the runner places, sizes, approves, modifies and cancels nothing,
holds no OKX keys, never loads `.env`, never calls an authenticated endpoint,
never opens the demo database, and reads the Phase 6a journal read-only.
Nothing in the trading runtime imports it.

### Added
- `scripts/run_news_shadow.py`: `--loop` (service), `--once`, `--dry-run
  [--fixtures]`, `--report [DAY]`, `--status`, `--no-model`; refuses a live mode
  without `ANTHROPIC_API_KEY` (exit 2); one instance per state directory;
  graceful SIGTERM.
- `app/news/shadow.py`: the cycle — public candles and exchange clock, ingestion,
  one triage call per headline (copies reuse it; stale and quarantined items never
  sent; later same-headline copies attached to their event without a call),
  stories, Opus classification with link candidates, corroboration and event
  building over **all of a story's articles** (`story_event`; identical to the
  R4b eval path for a story without earlier articles — tested on every eval case),
  a versioned event book so each Phase 6a decision is judged only on what was known
  then, effective signals, the shadow overlay, health (clock skew, source outage,
  stage failure → NO_EFFECT), atomic state that survives restarts.
- `app/news/phase6a.py`: incremental read-only journal reader; LONG signals and
  runtime entry decisions become candidates with their baseline (allowed, blocked
  with the runtime's reason, or "not observed" after a settle window — never
  allowed); exits, FLAT/HOLD and stops never become candidates.
- `app/news/market.py`: public OKX candles and server time, host and paths pinned,
  no credentials, confirmed candles only.
- `app/news/budget.py`: monthly spend cap (default $40) with daily pacing,
  worst-case reservation before each call, list-price cost after; `BudgetedClient`
  enforces it around the SDK client.
- `app/news/report.py`: `report-YYYY-MM-DD.md` from the logs and the journal alone
  (reproducible), with the price path after each would-block/reduce, manual-review
  lists and eight safety invariants recomputed from the logs and checked against
  the Phase 6a journal itself.
- `app/news/dryrun.py` and `tests/fixtures/news_shadow/`: four invented hours run
  offline end to end (fixture network that refuses every other URL, scripted
  model, journal replay) with checked expectations.
- `deploy/systemd/news-shadow.service` and `news-shadow.env.example`; runbook
  `docs/runbooks/NEWS_SHADOW.md` (capped key in its own workspace, own
  environment file, install, checks, report, cap, stop/remove, troubleshooting).
- `app/news/store.py`: record kinds `source_fetch`, `cycle_summary`,
  `runner_event`. `app/news/pipeline.py`: `IngestSummary` also returns the cycle's
  records and fetch entries (additive).
- Tests (offline): the dry run with the network and the real client blocked, each
  counterfactual, no hindsight, unhealthy states, spend cap and pacing (including
  concurrency), restart equivalence, corrupt state, the journal reader's edge
  cases, the report's invariant checks, the CLI in every mode, the unit file and
  the import boundaries.

### Fixed (found by the independent review of this step)
- `app/news/fetch.py`: `parse_rss` handed the response text to `feedparser.parse`,
  which fetches a body that looks like a URL and opens a body that looks like a
  local path; a tampered feed could have made the host read local files or call
  internal addresses (e.g. a cloud metadata service). It now always passes a byte
  stream.
- Evidence a story already had (an earlier price/volume confirmation, a counted
  source beyond the article cap) can no longer be erased by a later repeat, and a
  classifier link pools evidence only when category, assets and a distinctive
  headline word agree.
- The spend cap now covers every HTTP attempt (SDK retries off, retries made by
  `BudgetedClient` with a fresh reservation; a timeout is charged its worst case).
- The report: tolerant of a line cut inside a multi-byte character; an event live
  at midnight keeps its effect in the next day's report; the exits, double-counting
  and baseline checks verify against the journal and the deciding event; a spend
  cap that held back triage is reported; reports refuse the Phase 6a directory.
- The unit makes the repository `.env` and the PostgreSQL socket inaccessible; a
  clock that could not be verified for 30 minutes makes the news state unhealthy.
- `tests/test_paper_api.py`: its "fresh" heartbeat was stamped when pytest imported
  the module, so it went stale (> 60 s) once the suite before it grew; it is now
  stamped when the test runs.

### Verified live (public data only)
- One `--once --no-model` cycle on this laptop against the SEC, Federal Reserve and
  Coinbase status RSS feeds and OKX public candles and server time: all sources
  HTTP 200, 299 confirmed 5-minute candles per instrument, clock skew −0.15 s.

### Not done here
- The capitalized wire-credit fix in `app/news/corroborate.py` (owner decision).
- No run against the real AI model (no key on this machine).

## Unreleased — Sprint 4b: news eval set and harness (plan row R4b; Phase 6b design §15, master plan §5.2)

Log-only tooling: nothing here gates an entry, reaches an order path, or is read
by the trading runtime.

### Added
- `tests/fixtures/news_eval/`: 134 labeled synthetic stories in 13 kinds
  (corroborated events, syndicated copies, single-source rumors, satire, stale
  reposts, prompt-injection text, homoglyph and zero-width text, plus
  corroborated-but-harmless, one-source-plus-market, off-watchlist, speculation,
  contradicted claims and story linking), each with its expected final action,
  category and label rationale; public-style candle scenarios (`market.json`,
  including a look-ahead trap and a bullish pump); a hand-written recorded run
  with deliberate flaws (`recorded/sample_run.jsonl`); README. The data files are
  ASCII-only: hidden and look-alike characters are written as `\u` escapes.
  Every label was re-derived by a second agent before commit; the flagged cases
  were corrected (an ambiguous single-source flag, aggregator repeats, same-owner
  outlets, invented incidents at real companies and tokens, label-revealing site
  names, accepted categories) and the stale reposts' single-source flags made
  consistent with the design's independence rules.
- `app/news/evaluation.py`: runs each story through the production path (real
  sanitizer, `NewsClassifier` triage and classification, price/volume check on
  candles closed before the decision, `assess`, `build_event`,
  `effective_signal`) and scores schema validity per stage (gate ≥ 95 %),
  prohibited actions (gate 0), single-source effects (gate 0), final-action and
  category accuracy per kind and per category with Wilson intervals, missed and
  false effects, triage recall, story links, refusals, truncations, tokens,
  latency and a list-price cost estimate. Infrastructure errors (including a
  reply from another model; a dated snapshot of the requested model counts as
  that model) are never scored, and only a case's last attempt counts, while the
  cost counts every attempt. Recording (the header keeps the run's models and
  settings) and replay clients (payload-hash checked) and four scripted offline
  models (reference answers, never-acting, block-everything, broken output) for a
  self-test of the harness and the labels; markdown report.
- `scripts/eval_news_classifier.py`: live run only when `ANTHROPIC_API_KEY` is
  set (otherwise prints `not run: no API key` and exits 0; five SDK retries
  against rate limits), `--replay` with the recorded settings, `--self-test`,
  case/kind filters, repetitions, parallel workers, and `--resume`, which
  continues an interrupted run with its own cases, repetitions and models and
  refuses conflicting flags; outputs under `artifacts/news_eval/`.
- `docs/NEWS_AGENT.md`: the news agent and its eval in plain words for the owner.
- Tests (offline): the eval set's coverage, ASCII-only data, the real sanitizer
  on adversarial text, label consistency through the reference answers and the
  independence rules, the three baselines, exact scoring of the recorded run,
  record/replay integrity, labels never reaching the model, error isolation,
  served-model checks, cost of retried attempts, look-ahead, the report and the
  CLI in every mode including resume.

### Found, not fixed here (outside this step's scope)
- `app/news/corroborate.py` recognizes "Associated Press" and "Agence
  France-Presse" credits only in lower case, so capitalized credits count as
  independent sources (eval case `syn-ap-attribution-capitalized`).
- `merge_event` in `app/news/decay.py` replaces a live event's corroboration with
  the repeat's own, so a repeat backed by one credible source switches a
  corroborated event off. Both are proposed for R4c (`docs/PLAN_STATUS.md`
  section 2).

## Unreleased — Sprint 4a: news agent core, log-only (plan row R4a; Phase 6b design §4–7, §9, §13)

Phase 6b is authorized for log-only operation only; nothing here gates an
entry, touches an order path, or is imported by the trading runtime.

### Added
- `app/news/schema.py`: the design's `NewsEvent` with exactly its enums and
  strict validation; `TriageVerdict` / `ClassifierVerdict` structured-output
  models; `SourceItemRef` from ingestion records.
- `app/news/classifier.py`: Claude Haiku 5.5 triage + Claude Opus 5.5
  classification through the Anthropic SDK with structured outputs, the frozen
  §9 system prompt (verbatim, plus a reference appendix) behind a 1-hour
  prompt-cache marker, strict validation; any failure or a missing
  `ANTHROPIC_API_KEY` is NO_EFFECT; API host pinned.
- `app/news/corroborate.py`: source families (wire copies, social-post relays,
  same owner, verbatim headlines), LLM may only narrow; price/volume
  confirmation from public candles closed before the decision.
- `app/news/decay.py`: §6 TTLs, monotonic decay, source weights, thresholds and
  reduction tiers, effective signal, most-conservative combination, event
  assembly (`build_event`) and same-story merging without TTL refresh.
- `app/news/overlay.py`: pure shadow overlay that can only keep, shrink or
  block a new long entry. `app/news/dedup.py`: story-level `event_id`.
- `app/news/store.py`: append-only `logs/news_shadow` event and decision
  JSONL logs with secret redaction.
- Dependency: `anthropic==1.15.0` (hashed lockfile regenerated with uv;
  pip-audit clean).
- Tests (offline: fakes and a mock HTTP transport, no key): schema, classifier
  failure paths and the real SDK request shape, corroboration and look-ahead,
  decay monotonicity, overlay invariants, logs, and import boundaries in both
  directions.

## Unreleased — Sprint 2b: sizing, risk, timeframe and positioning data (master plan Sprint 2b, research only)

### Added
- `research/sizing.py`: vol-targeted entry fractions, crash-state de-risking,
  drawdown ladder (state machine), the 390-variant sizing grid; all series
  backward-looking (look-ahead tests). `research/bracket.py`: take-profit,
  trailing-after-1R and time-stop exit brackets.
- `research/engine.py`: per-bar size matrices, reduce-only mid-trade
  de-risking (never adds), ladder in the loop, trailing stop, per-column time
  stops, MFE/MAE per trade; bit-for-bit the Sprint 2 engine with overlays off.
  Give-back metric (trades that reached +3 % unrealized yet closed negative).
- `research/resample.py`: UTC-aligned 1H → 6H bars (complete bars only).
- `app/datalake/binance_public.py` + `scripts/collect_binance_positioning.py`:
  Binance PUBLIC funding-rate (since 2019) and open-interest (since 2020-09 /
  2021-12, hourly from 5-minute bulk files, sha256-verified) history as
  research features only; lake layout `external/<venue>/…`; DuckDB views
  `binance_funding_rate`, `binance_metrics`. We never trade on Binance.
- `research/sized_walkforward.py`: two-stage walk-forward (rule, then sizing,
  both selected on the train slice; sizing under a train drawdown cap) with
  fixed replays (robustness, sizing sweep, ladder/bracket effects, slippage).
- `research/portfolio.py`: sleeve combination (daily compounding, buckets or
  daily rebalancing, equal-capital / equal-risk, correlation, portfolio ladder).
- `research/report_v1b.py` + `scripts/run_research_v1b.py`: Sprint 2b
  risk-adjusted gates (PF > 1.2, max DD < 20 % at the proposed sizing, Sharpe
  > 0.7, Calmar > 0.5, 4 of 5 positive years, ≥ 30 trades, ±30 % robustness,
  DSR reported), ranked paper-fleet shortlist, plain-English executive
  summary; `hold` always-long reference. Report
  `docs/research/ENSEMBLE_V1B_REPORT.md`. Docs: `docs/RESEARCH_LAB.md`,
  `docs/DATA_LAKE.md`.
- Lake writers retry the atomic replace on transient Windows file locks.

### Result
- 0 of 28 candidate configurations pass the Sprint 2b gates (0 of 28 with the
  fixed policy sizing as well). Sizing cut the median worst drawdown from
  54 % to 19 % but return fell in step (median Calmar 0.28 → 0.31); best
  single configuration S4 on ETH 6H (Calmar 0.58, max DD 13.2 %) misses only
  the 4-of-5 positive-years gate. Holdout untouched; nothing goes to demo.

## Unreleased — Sprint 2: research lab + ensemble v1 candidates (master plan Sprint 2)

### Added
- `research/`: dependency-free vectorized long-only sweep engine with the same
  execution conventions as the reviewed simulator (parity tested), features,
  candidates S0–S5 + SMA baseline in the `Strategy` contract via an adapter,
  cartesian sweeps with ±30 % robustness, walk-forward with purge gap and
  stitched out-of-sample curves, untouched 12-month holdout, Monte Carlo
  trade-order bootstrap, slippage stress, regime v1 labels, deflated Sharpe,
  hit-rate calibrated confidence. Runner `scripts/run_research.py`; report
  `docs/research/ENSEMBLE_V1_REPORT.md` (+ JSON). Docs: `docs/RESEARCH_LAB.md`.
- Import-boundary test: research code never imports execution, exchange,
  shadow, OKX client, notify, paper, live or the live strategy registry.

## Unreleased — Sprint 1: data lake v2 (master plan Sprint 1)

### Added
- `app/datalake/`: Parquet research lake over PUBLIC OKX data — resumable
  `history-candles` backfill (BTC/ETH × 1m 5m 1H 4H 1D, de-duplicated,
  year-partitioned, crash-safe cursors in `_state/`), SWAP statistics
  collectors as research features (funding rate, open interest, long/short
  ratio, taker volume), a public `liquidation-orders` WebSocket collector to
  JSON lines, DuckDB views, and a data-quality report (continuity, gaps,
  duplicates, alignment, OHLC coherence, outliers). Docs: `docs/DATA_LAKE.md`.
- Scripts: `backfill_history.py`, `collect_derivatives.py`,
  `collect_liquidations.py`, `data_quality_report.py`, `ingest_news.py`.
- `app/news/`: log-only news-ingestion skeleton (Phase 6b design §7.1–7.3):
  official RSS + GDELT sources, sanitization with audit hashes and flags,
  quarantine of injection/homoglyph/bidi-flagged items, dedup, JSON lines.
  No LLM call, no classification, no trading effect; the import boundary is
  tested. Docs: `docs/NEWS_INGESTION.md`.
- Dependencies: `duckdb`, `pyarrow` (now direct), `feedparser` (lockfile
  regenerated; pip-audit clean).

## Unreleased — Sprint 2c: regime gates, portfolio sizing, turnover (branch `sprint-2c/regime-portfolio`)

Research only (2026-10-20); no change under `app/execution`, `app/risk`,
`app/exchange` or `config/`. Result: 4 of 108 configurations pass the
walk-forward gates at the fixed policy sizing, the untouched holdout confirms
1 and contradicts 3; see `docs/research/ENSEMBLE_V1C_REPORT.md` and
`docs/RESEARCH_LAB.md`.

### Added
- `research/hmm.py` (numpy Gaussian HMM with a forward-only filter),
  `research/regime_v2.py` (3-state regime fitted per walk-forward train slice,
  entry gate / entry scale only), `research/events.py` + scheduled-event
  windows in the S0 filter (FOMC calendar, owner to verify),
  `research/strategies/turnover.py` + `S1h` hysteresis + `+S5s` re-test
  variants, `research/gated_walkforward.py`, portfolio-level sizing
  (`research/portfolio.py::combine_sized`), `research/report_v1c.py` (yearly
  gate v2 on rolling 12-month windows, holdout verdicts, machine-readable
  paper-fleet shortlist with controls), `scripts/run_research_v1c.py`
  (parallel, `--render-from-json`), tests for every component including
  no-look-ahead in HMM fitting/filtering.

## Unreleased — Sprint 0 (master plan `docs/MASTER_PLAN_2026-10-20.md`)

### Fixed
- **OKX WebSocket port 8443 cutoff (Oct 31, 2026):** every WebSocket default
  (`app/config.py`, `app/exchange/okx_public_ws.py`,
  `app/exchange/okx_demo_endpoints.py`, `.env.example`, phase docs) now
  connects without an explicit port (implicit 443). The fail-closed URL
  validators are unchanged and still accept `None`, `443` and `8443`.
  `tests/test_ws_defaults_no_port.py` asserts no default carries a port.
  Operator runbook: `docs/runbooks/VPS_8443_UPDATE.md`.
- Dashboard candle chart no longer anchors the y-axis at zero.

### Added
- `requirements.in` (direct deps) + generated, hashed, universal
  `requirements.txt` lockfile (uv); `.github/workflows/audit.yml` runs
  `pip-audit` on the locked set and checks lock/source sync; Dependabot
  config for pip and GitHub Actions.
- Alembic baseline (`alembic.ini`, `migrations/`, revision `0001`) matching
  the current `create_all` schema; `tests/test_migrations.py`;
  `docs/runbooks/DB_MIGRATIONS.md`. Runtime behavior unchanged.
- `docs/AUDIT_2026-10-20.md` and `docs/MASTER_PLAN_2026-10-20.md`.

### Changed
- CI and notify workflows run Python 3.13.
- Travel-mode guard also classifies `requirements.in`, `migrations/` and
  `alembic.ini` as safety-sensitive.
- Dependency security fixes found by `pip-audit`: `requests` 2.33.0,
  `python-dotenv` 1.2.2, `pytest` 9.0.3, `starlette` 1.3.1 (with
  `fastapi` 0.136.0).

### Removed
- `resume_claude_at_1.sh` (stale session-resume script).
