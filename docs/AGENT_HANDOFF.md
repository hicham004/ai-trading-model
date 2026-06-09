# Agent Handoff

## Repository And Environment

The canonical repository is:

```text
/home/aitec/ai-trading-model
```

Use the Linux-home copy for development. The WSL/Docker/Python environment is
available, and local PostgreSQL is defined in `docker-compose.yml`.

## Product Direction

The final goal is an AI-assisted automated OKX trading bot. The dashboard is
only an observability surface over the data foundation.

The intended progression is:

```text
historical public data
-> realistic strategy backtesting
-> live public WebSocket data
-> local paper trading
-> OKX demo trading
-> AI news/event research
-> long walk-forward and paper/demo evaluation
-> tiny controlled live automation
```

The AI/LLM never directly places orders. Future order authority belongs only
to the strategy/risk/control pipeline, with the risk manager holding final
veto.

## Current Status

- Phase 1 data foundation exists and is the accepted baseline.
- Claude Code created the Phase 2 strategy/backtesting implementation and
  completed the Phase 2B corrections.
- Codex independently reviewed Phase 2 and documented safety/correctness
  findings in `docs/PHASE2_REVIEW_NOTES.md`.
- Phase 2B corrections include conservative
  stop-gap fills, distinct signal-data/execution time with future/naive/stale
  rejection, simulation-only broker enforcement with strict fill/order matching,
  signal identity/alignment validation, next-bar-open execution (no look-ahead),
  and timeframe-aware signal staleness. Adverse tests were added for each, and
  the offline suite passes.
- Codex independently verified the corrections with the full offline suite and
  targeted adversarial reproductions. The human owner explicitly accepted
  Phase 2/2B on June 9, 2026.
- Phase 3A (live, public, unauthenticated WebSocket market-data observation
  only) completed the Codex correction/review pass and was explicitly accepted
  by the human owner on June 9, 2026.
- Phase 3B public-data hardening was independently reviewed (no blocker, no
  required follow-up) and explicitly accepted by the human owner on June 9,
  2026.
- Phase 4 local paper trading was begun by Claude Code and completed and
  hardened by Codex. All independent-review findings were resolved, final
  review cleared on June 10, 2026, and the phase is accepted. The human owner
  supplied explicit approval on June 9, 2026.

## Required Reading

Before any work:

1. `CLAUDE.md`
2. `PROJECT_RULES.md`
3. `README.md`
4. `docs/PHASES.md`
5. `docs/PHASE2_REVIEW_NOTES.md`
6. `docs/AGENT_WORKFLOW.md`

For long-term context:

- `docs/LIVE_TRADING_VISION.md`
- `docs/AUTOMATED_TRADING_ROADMAP.md`
- `docs/PHASE3A_LIVE_DATA.md`
- `docs/PHASE3B_LIVE_DATA_HARDENING.md`
- `docs/PHASE3B_REVIEW_NOTES.md`
- `docs/PHASE4_LOCAL_PAPER_TRADING.md`
- `docs/PHASE4_REVIEW_NOTES.md`

## Immediate Engineering Boundary

Phase 3A was accepted on June 9, 2026. It is strictly live, UNAUTHENTICATED
public OKX WebSocket market-data observation for BTC-USDT and ETH-USDT only:
ticker, trades, and candle channels feeding a bounded in-memory state, with
read-only API/dashboard status. No persistence is added. The implementation
uses separate fail-closed health for the public ticker/trade feed and business
candle feed, and does not report a feed connected until all required
subscriptions are acknowledged.

Phase 3B was accepted on June 9, 2026: public order-book sequence integrity,
bounded public REST backfill for missing confirmed candles, optional durable
public candle/order-book writes, and read-only operational observability. It
fails closed on malformed depth or a broken sequence chain and keeps
persistence outside the WebSocket receive path.

Phase 4 was accepted after final independent review on June 10, 2026. It is
the current implemented boundary: local forward paper simulation on confirmed
public `1m` candles, fresh sequence-valid public books, deterministic risk
vetoes, virtual long-only spot balances/positions/fills, atomic local
journaling, restart reconciliation, kill-switch control, and read-only API
observability.

Out of scope and still unauthorized: OKX demo trading, authenticated/private
OKX access, exchange accounts, real orders, leverage, shorting, withdrawals,
Phase 5, and every later phase. Do not begin Phase 5.

## Permanent Safety Rules

- No real trading in the current scope.
- Public OKX market data only until a later approved phase.
- No private OKX API keys or account access.
- No withdrawals ever.
- No martingale, doubling down, or loss chasing.
- No strategy profitability guarantees.
- The risk manager has final veto over every future action.
- No phase is complete solely because tests pass.
- No agent can approve its own work.
- Do not commit automatically.

## Agent Responsibilities

- Claude Code builds approved work.
- Codex reviews, tests, and challenges safety assumptions.
- ChatGPT supports architecture, research, and planning.
- The human owner approves phases and capital decisions.

See `docs/AGENT_WORKFLOW.md` for the required review loop.
