# Changelog

All notable changes to this repository. Dates are UTC. Nothing in this file
authorizes a phase, live trading, or a safety-core change; see
`PROJECT_RULES.md` and `CLAUDE.md`.

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
