# Pull request text — `plan/auto` into `main` (plan row G2)

Paste the part below the line into the pull request body at
<https://github.com/hicham004/ai-trading-model/compare/main...plan/auto?expand=1>.
Suggested title: `Plan runs 1 and 2: Sprints 0 to 2c, Phase 6b log-only news agent, paper fleet, ops digest`.
Merge with a merge commit (not squash) so the step hashes recorded in
`docs/PLAN_STATUS.md` stay true. Before merging, the branch protection rule
for `main` must require the status check `tests` (its current name) instead
of `tests + travel-mode safety guard`.

---

## What this pull request contains

Everything built since 2026-10-20 on the stacked sprint branches and the
unattended plan runner's branch `plan/auto`. Status and hashes per step:
`docs/PLAN_STATUS.md`; the plan of record: `docs/MASTER_PLAN_2026-10-20.md`;
the audit that started it: `docs/AUDIT_2026-10-20.md`; the log of changes:
`CHANGELOG.md`.

**Safety contract: unchanged.** Demo-only (`x-simulated-trading: 1` to the
hostname allowlist), SPOT, long-only, leverage 1, the deterministic risk
manager's final veto, fail-closed reconciliation, no LLM output on any order
path. Phase 6b (the news agent) runs **log-only** as the owner authorized
(issue #12, reconfirmed 2026-10-20); news never gates an entry. No phase is
advanced by this pull request.

### Operations and hygiene (Sprint 0)
- Port-less OKX WebSocket defaults (the `:8443` retirement) with a test that
  no default carries a port; the validators still accept 443 and 8443.
- Hashed `requirements.txt` from `requirements.in` (uv), `pip-audit` in CI,
  Dependabot, Python 3.13 in CI, Alembic baseline revision 0001 (the runtime
  still uses `create_all`; stamping the VPS database is an operator step).
- Security bumps (requests, python-dotenv, pytest, starlette, fastapi 0.136).
- Travel mode removed entirely at the owner's request (2026-10-22); the CI
  job is now named `tests`.

### Data (Sprint 1)
- A Parquet data lake with a resumable public-candle backfill (BTC-USDT,
  ETH-USDT from 2019-12), OKX public derivatives collectors (funding, open
  interest, long/short, taker volume, liquidations), DuckDB views, a quality
  report; Binance public funding and open-interest history as research
  features only.

### Research (Sprints 2, 2b, 2c, R7, R9; simulation only, `research/`)
- An in-repo vectorised research engine, strategies S0 to S5, walk-forward
  with purge and an untouched 12-month holdout, sizing (vol targeting, crash
  de-risking, drawdown ladder), exit brackets, 6H bars, a 3-state HMM regime
  model, portfolio-level sizing, turnover variants, Monte Carlo and deflated
  Sharpe. Reports: `docs/research/ENSEMBLE_V1_REPORT.md`, `..._V1B_...`,
  `..._V1C_...`, `LONG_SHORT_STUDY_REPORT.md`, `ALLOCATOR_V2_REPORT.md`.
- Result in one line: of 108 Sprint 2c configurations exactly one survived
  both the walk-forward and the holdout (S1+S5 on BTC-USDT 6H, about +5% a
  year at under 10% drawdown); the jointly sized portfolio was contradicted
  by its holdout; mirrored shorts made the trend rules worse. The product
  framing the owner accepted is "risk-managed exposure plus a news brake".
- The FOMC calendar was checked against the Federal Reserve (all dates right)
  and extended to 2027.

### Phase 6b news agent, log-only (R4a to R4d)
- `app/news`: the Pydantic event schema, a two-stage classifier (Haiku 5.5
  triage, Opus 5.5 classification with structured outputs; any failure or a
  missing key gives `NO_EFFECT`), corroboration rules (wire credits, HIGH
  outlets by site, Dow Jones as one source), decay, and an overlay that can
  only block or shrink a new long and never sees exits. An import-boundary
  test: `app/news` imports nothing from execution, risk or an authenticated
  client.
- An eval set of 100+ labelled fixtures with a scorer, a log-only shadow
  runner with a daily report and a monthly spend cap, a systemd unit and the
  runbook `docs/runbooks/NEWS_SHADOW.md`.

### Paper fleet and allocator (R5a, R5b)
- 20 local paper accounts running the shortlist forward on live public OKX
  data (the confirmed sleeve, the jointly sized portfolio with and without
  allocator v2, hold-with-policy-sizing and buy-and-hold controls), journals,
  a weekly report against backtest expectations, a systemd unit and
  `docs/runbooks/PAPER_FLEET.md`. Started on the owner's laptop 2026-11-04.

### Ops (R6)
- A plain-English daily digest and an OKX API changelog watcher that flags
  changes to the hosts, ports, paths and channels this repository uses;
  systemd timers and `docs/runbooks/OPS_DIGEST.md`.

### The runner itself
- `scripts/plan-runner.ps1` and `docs/PLAN_STATUS.md`: one fresh chat per
  plan row, committing on `plan/auto` after the full suite and
  `git diff --check` pass; deny rules block push, merge, rebase, ssh, scp and
  the demo-trading scripts inside the chats. Default model Fable 5.1 since
  2026-11-04.

## Review notes
- Safety-sensitive paths changed (per `AGENTS.md`), the complete list against
  `main`: `app/config.py` (the three WebSocket URL defaults lose `:8443`; they
  are part of the demo account identity, hence runbook G1), `app/exchange/okx_demo_endpoints.py`
  and `app/exchange/okx_public_ws.py` (the same default URL constants; the
  validators are untouched), `app/notify/telegram.py` (the travel-mode CI
  notification labels removed; observability only), `requirements.in` and the
  hashed `requirements.txt`, `.github/` (CI on Python 3.13 named `tests`,
  `pip-audit`, Dependabot; `claude.yml` and `notify.yml` removed),
  `alembic.ini` and `migrations/` (baseline revision 0001 only).
  **Unchanged against `main`:** `app/execution`, `app/risk`, `app/shadow`,
  `app/strategy`, `config/`, `scripts/run_shadow_period.py`,
  `scripts/run_demo_trading.py`. Everything else is additive under
  `app/datalake`, `app/news`, `app/ops`, `research/`, `scripts/`, `deploy/`,
  `docs/`, `tests/`.
- Tests: the full offline suite (about 1,600 tests) passes on Windows; the CI
  run on Linux was green at `5021470` (the previous push) and runs again on
  this pull request; CI holds no secrets.
- Merging deploys nothing. The VPS checkout is updated by the operator
  (`docs/runbooks/VPS_8443_UPDATE.md`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
