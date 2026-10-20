# Changelog

All notable changes to this repository. Dates are UTC. Nothing in this file
authorizes a phase, live trading, or a safety-core change; see
`PROJECT_RULES.md` and `CLAUDE.md`.

## Unreleased — Sprint 3: execution v2 in demo (branch `sprint-3/exchange-side-stops`)

Built 2026-10-20; **demo validation pending the owner's drills, independent
review required, not merged.** Safety-core change (`app/exchange/`,
`app/execution/`, `app/shadow/`, `migrations/`, `scripts/run_demo_trading.py`).

### Added
- **Exchange-side protective stop** (master plan Sprint 3 item 1): an OKX SPOT
  conditional SELL algo order (market on trigger; OCO when the take-profit leg
  is on) placed for every open position and kept in sync with the fill-derived
  position; durable `demo_algo_orders` ledger (Alembic `0002`), deterministic
  `algoClOrdId`, UNKNOWN-resolve-by-query, amend/cancel/never-two-stops/never-
  lower, cancel-first on software exits, venue-created child SELL mapped to a
  local exit intent, algo reconciliation (foreign algo orders fail closed, never
  cancelled), `orders-algo` private-WS channel, stop guard alarm that blocks
  entries and raises a supervisor ALERT. Six algo endpoints added to the strict
  allowlist with a SELL-only `tdMode=cash` parameter whitelist.
- **Entry policy** (item 2): `DEMO_ENTRY_POLICY=post_only_then_market` —
  post-only at/inside the spread, timeout, one budgeted marketable fallback,
  expected vs realized slippage persisted.
- **Mechanical exit bracket** (item 3): take-profit (OCO leg), trailing (amend
  upward only), time stop — all OFF by default; the protective stop is mandatory.
- **Drills and docs** (item 4): `docs/PHASE6A_EXECUTION_V2.md`,
  `docs/runbooks/DEMO_STOP_DRILLS.md`, operator commands `--stops`,
  `--place-test-position`, `--tighten-test-stop`, `--close-test-position`
  (smoke-test + opt-in + armed only), read-only `GET /demo/stops` and
  `stop_alarm` in `GET /demo/health`, `tests/test_demo_stops.py`.
- Account identity: every new setting defaults to the reviewed behaviour; opting
  in requires a NEW demo account name (`demo-shadow-1h` is untouched).

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
