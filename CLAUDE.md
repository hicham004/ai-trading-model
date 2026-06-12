# AI Agent Rules

These rules apply to Claude Code, Codex, ChatGPT, and every other AI agent
working on this repository. Read this file before doing anything else; it is
loaded at the start of every session.

## Project Summary

An AI-assisted automated OKX trading system, built in human-approved phases.
The long-term goal is a controlled system that can eventually place trades
automatically. It is not merely a dashboard and not a manual trading
assistant. The current validated capability is authenticated **demo
(simulated)** trading only; live automation remains a future capability. The
repository is NOT authorized to place real trades or touch real funds.

## Phase Status

Phases 1-5 are COMPLETE and explicitly accepted by the human owner:

- **Phase 1** - data foundation (baseline).
- **Phase 2/2B** - strategy engine + backtesting with safety corrections;
  historical simulation and research only (accepted June 9, 2026).
- **Phase 3A/3B** - live UNAUTHENTICATED public OKX WebSocket market data
  (BTC-USDT, ETH-USDT) + hardening (accepted June 9, 2026).
- **Phase 4** - local paper trading: forward strategy evaluation on public
  data, virtual fills/balances, deterministic risk vetoes, local
  journaling/reconciliation (accepted June 9-10, 2026).
- **Phase 5** - authenticated OKX **demo/simulated** trading (BTC-USDT and
  ETH-USDT SPOT cash, long-only). Independently reviewed by Codex and accepted
  June 10, 2026; validated against the live OKX demo API June 10-11, 2026
  (authenticated reads, sustained 4-hour private WebSocket run, 481/481
  consistent reconciliations, kill switch, account-partition guard, and an
  owner-authorized operator round-trip validating fill handling, position
  sync, live software-stop tracking, the exit path, and post-exit
  reconciliation). Declared COMPLETE by the human owner on June 11, 2026.
  Records: `docs/PHASE5_DEMO_TRADING.md`, `docs/PHASE5_REVIEW_NOTES.md`,
  `docs/PHASE5_VALIDATION.md`.

**Phase 6a is AUTHORIZED** (human owner, June 11, 2026) — the mechanical
shadow period ONLY: a long-running unattended demo shadow run on the
`demo-seeded` account, SPOT BTC-USDT, long-only 1x, `x-simulated-trading: 1`,
software stop (accepted for demo per the documented live blocker),
`ma_crossover` UNTOUCHED. Scope: hardened shadow supervisor (gated
auto-restart, bounded restart budget, heartbeat file, daily log rollover),
decision journal, daily summary reports, persisted shadow risk caps
(10 USDT/entry, 1 open position, 3 entries/day, 1 USDT max daily loss then
disarm-for-day), and the offline `ma_crossover` clearance-rate study. The
supervisor may re-arm after a clean gated restart; ANY reconcile
inconsistency, wrong-scope, or foreign detection means permanent disarm until
the operator intervenes. No changes to the reviewed safety core; the live run
is started only by the human operator.

**Phase 6b (news agent, log-only) is designed but NOT authorized.** Phase 6b
and all later phases require explicit human approval before any work begins.

## Standing Safety Contract

- **Demo-only until the human operator explicitly says otherwise.** Every
  authenticated request sends `x-simulated-trading: 1` to a strict
  regional-hostname allowlist. Production mode, `x-simulated-trading: 0`,
  withdrawals/transfers, leverage, margin, derivatives, shorting,
  account-mode mutation, demo-balance reset, generic arbitrary-endpoint
  methods, and mutating HTTP routes are forbidden and must stay
  unrepresentable in code.
- **SPOT cash, long-only, leverage locked at 1.0**, BTC-USDT/ETH-USDT only.
- **An AI or LLM must never directly place, approve, modify, or cancel an
  order.** Orders flow only through the strategy engine, deterministic risk
  manager (final veto), and controlled execution module for an explicitly
  approved phase. No demo order may be submitted except under an explicitly
  armed, separately opted-in, operator-authorized smoke test.
- **Fail closed on ambiguity**: inconsistent reconciliation, ambiguous
  account selection, unknown order outcomes, stale feeds, or lost locks block
  new entries; never guess, never blind-retry a submission.
- **No real/production API keys.** Never request, store, print, log,
  screenshot, prompt, or commit secrets. Never implement withdrawals or
  request withdrawal permissions.
- **No retuning of live/running strategies.** Strategy or risk-parameter
  changes (including the 0.60 confidence floor) are scope changes requiring
  explicit owner approval; research analysis is fine, acting on it is not.
- **No martingale, doubling down, or automated loss chasing.**
- **Exchange-side protective stops are a HARD BLOCKER for any live phase.**
  The current stop is software-only (enforced only while the runtime process
  is alive), accepted for demo only. See `docs/PHASE5_DEMO_TRADING.md`.
- **No auto-commit.** Commit only when the operator asks. A passing backtest
  or test suite never authorizes paper, demo, or live execution, and no agent
  may approve its own implementation or declare a phase complete.
- **Stop and ask** before changing agreed scope, adding authenticated
  exchange access, advancing phases, or on any conflict between instructions
  and this contract.

## Operational State

- Active demo account: **`demo-seeded`** (`DEMO_ACCOUNT_NAME` in `.env`).
  Account selection must be explicit; the account-partition guard fails
  closed when several local accounts share a key fingerprint.
- **Flatness definition (official):** a position is flat when
  `floor(position, lot_size) == 0` (`is_flat()` in
  `app/execution/precision.py`). Base-currency fees are finer than the lot
  size, so exact-zero is unreachable; sub-lot residue is unsellable dust.
- Operator CLI: `scripts/run_demo_trading.py`
  (`--status/--reconcile/--arm/--disarm/--engage-kill-switch/...`).

## Deferred / Open Items (tracked)

1. Organic strategy-generated demo round-trip - deferred to the Phase 6
   shadow period.
2. Exchange-side protective stops (`slTriggerPx`/`slOrdPx` or
   `attachAlgoOrds`) - implement + independent review + demo validation
   before ANY live phase.
3. Delete the stale empty `demo` account row sharing the demo key
   fingerprint (reviewed cleanup; the partition guard fails closed until
   then).
4. Research: historical clearance rate of the current `ma_crossover` config
   vs the 0.60 confidence floor (analysis only; no retuning authorized).
5. Safety-core adoption of lot-precision flatness (driver stop check / exit
   gating still treat `position > 0` as open) - future reviewed change.
6. Position persistence across restarts requires a reviewed change before any
   live phase: today a restart rebuilds the strategy window from live candles,
   so the warm-up FLAT closes any open position via the reviewed exit path
   (accepted for demo, June 12, 2026; crash churn = real fees live).
7. Persistence uses `create_all`; no production migration workflow.

## Completion And Change Control

A phase is complete only when all of the following are true:

- the approved implementation exists;
- normal tests pass;
- adverse and safety tests pass;
- reviewer findings are resolved;
- documentation matches actual behavior;
- an independent review has occurred; and
- the human owner explicitly approves completion.

Tests alone are never phase approval. Stop and ask before changing the agreed
scope, adding authenticated exchange access, or advancing to another phase.

See `PROJECT_RULES.md`, `docs/PHASES.md`, and the per-phase review/validation
documents referenced above.
