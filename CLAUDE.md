# AI Agent Rules

These rules apply to Claude Code, Codex, ChatGPT, and every other AI agent
working on this repository.

## Product Goal

This is an AI-assisted automated OKX trading-system project. The long-term
goal is a controlled system that can eventually place trades automatically.
It is not merely a dashboard and it is not a manual trading assistant.

Live automation is a future capability only. The current repository is not
authorized to place real trades, access an exchange account, or use private
OKX APIs.

## Agent Authority

- AI agents may build approved code, tests, documentation, research tooling,
  public-data collectors, databases, backtests, simulations, and dashboards.
- AI agents may use public OKX market-data endpoints for approved research.
- AI and LLM components may research markets, classify news, explain signals,
  identify regimes, and adjust a bounded confidence input.
- An AI or LLM must never directly place, approve, modify, or cancel an order.
- Future orders may be authorized only by the strategy engine, risk manager,
  and controlled execution module for an explicitly approved phase.
- No agent may approve its own implementation or declare its phase complete.

## Absolute Restrictions

- Do not place real trades.
- Do not add or enable live order execution without explicit human phase
  approval and a separate security review.
- Do not request or use OKX private API keys in the current approved scope.
- Do not request, store, print, log, screenshot, prompt, or commit secrets.
- Never implement withdrawals or request withdrawal permissions.
- Do not implement martingale, doubling down, or automated loss chasing.
- Do not claim that a strategy or backtest guarantees future performance.
- A passing backtest never authorizes paper, demo, or live execution.
- The risk manager has final veto over every future simulated, paper, demo, or
  live trading action.

## Current Phase Boundary

- Phase 1 data-foundation work exists and is accepted as the current baseline.
- Phase 2 strategy/backtesting and the Phase 2B safety corrections were
  independently reviewed by Codex and explicitly accepted by the human owner
  on June 9, 2026.
- Phase 2 acceptance covers historical simulation and research only.
- Phase 3A (live, UNAUTHENTICATED public OKX WebSocket market-data observation
  for BTC-USDT and ETH-USDT only) was reviewed by Codex and explicitly accepted
  by the human owner on June 9, 2026. Acceptance covers real-time public-data
  observation only: no strategy evaluation or signals from live data, no
  paper/demo/live trading, no account access, no private endpoints, and no
  orders.
- Phase 3B public-data hardening was independently reviewed and explicitly
  accepted by the human owner on June 9, 2026.
- Phase 4 local paper trading received final independent review on June 10,
  2026 and is accepted; the human owner supplied explicit approval on June 9,
  2026. Its scope is forward strategy evaluation on public data, virtual
  fills/balances/positions, deterministic risk vetoes, local
  journaling/reconciliation, and read-only observability.
- Phase 5 and all later phases are NOT authorized. Do not begin them without
  explicit human approval.

See `PROJECT_RULES.md`, `docs/PHASES.md`,
`docs/PHASE2_REVIEW_NOTES.md`, and
`docs/PHASE3B_LIVE_DATA_HARDENING.md`. Phase 4 implementation boundaries are
in `docs/PHASE4_LOCAL_PAPER_TRADING.md`, and its review is recorded in
`docs/PHASE4_REVIEW_NOTES.md`.

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
