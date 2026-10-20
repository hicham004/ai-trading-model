# Changelog

All notable changes to this repository. Dates are UTC. Nothing in this file
authorizes a phase, live trading, or a safety-core change; see
`PROJECT_RULES.md` and `CLAUDE.md`.

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
