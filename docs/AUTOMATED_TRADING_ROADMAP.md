# Automated Trading Technical Roadmap

This document describes technical direction. It does not authorize work beyond
the current phase status in `docs/PHASES.md`.

## Data Foundation

Use public OKX REST data for history and backfills. Expand data quality before
expanding execution:

- candle continuity and duplicate detection;
- timestamps and clock consistency;
- funding and open interest where approved;
- trades and order-book snapshots later;
- spread and liquidity measurements; and
- reproducible datasets for backtests.

## Research And Backtesting

Build a common structured signal contract containing at least:

- instrument and timeframe;
- direction/action;
- signal and source-data timestamps;
- confidence and reason;
- entry assumptions;
- stop and exit assumptions;
- expiration; and
- risk metadata.

Backtests must model:

- fees, spread, slippage, and applicable funding;
- gaps through stops and conservative fill assumptions;
- stale, expired, duplicate, future, and misaligned signals;
- missing/out-of-order market data;
- no look-ahead behavior;
- exposure and drawdown; and
- later walk-forward and holdout validation.

## Live Public Data

Phase 3 should add public WebSocket workers only:

- candles, trades, tickers, and order book;
- heartbeat and reconnect;
- subscription and sequence validation;
- REST backfill after gaps;
- data freshness and clock monitoring; and
- durable writes and observability.

No account or order access belongs in this phase.

## Paper And Demo Progression

Local paper trading must run forward in time with virtual balances, positions,
orders, fills, and reconciliation.

OKX demo trading comes later and requires separate approval for authenticated
simulated access. It must include:

- least-privilege demo credentials;
- explicit simulated-trading mode;
- order idempotency;
- order/position/account reconciliation;
- cancel/replace and exchange-error handling;
- rate-limit and clock handling; and
- kill-switch testing.

## AI Research Layer

The AI news/event agent should consume approved, attributable sources and emit
structured classifications. It may adjust confidence or block trades through
defined policy. It may not place orders or bypass risk controls.

Potential inputs later include:

- official exchange and project announcements;
- macro and central-bank events;
- regulatory and ETF news;
- security incidents and exploits;
- geopolitical events;
- a small approved social-source watchlist; and
- market confirmation from price, volume, spread, and liquidity.

## Validation Before Live

Phase 7 should combine:

- rolling walk-forward tests;
- untouched holdouts;
- regime-separated analysis;
- randomized costs and execution stress;
- outage and stale-data drills;
- long paper/demo observation;
- comparison of expected versus observed fills; and
- review of operational failure modes.

No single metric or favorable period is sufficient.

## Tiny Live Executor

The eventual live executor should be deliberately narrow and deterministic. It
receives only risk-approved orders, applies idempotency and exchange checks,
submits to OKX, reconciles state, and emits audit logs.

It must not interpret news, invent strategy decisions, or accept direct LLM
commands. Live implementation remains unapproved until Phase 8.
