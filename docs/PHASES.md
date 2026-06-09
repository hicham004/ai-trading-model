# Project Phases And Approval Status

This roadmap describes the intended path toward an AI-assisted automated OKX
trading system. Each phase is a hard boundary. Building code for a phase does
not approve it, and passing tests does not make it complete.

## Status Legend

- **Accepted:** implementation, review, documentation, and human approval are
  complete.
- **WIP:** implementation or review is incomplete.
- **Planned:** no implementation is authorized yet.

## Phase 1 - Historical Data Foundation

**Status: Accepted baseline**

- Public OKX REST candle collection for approved instruments.
- Local PostgreSQL/SQLite storage.
- Duplicate prevention and UTC timestamps.
- Read-only FastAPI access.
- Local Streamlit research view.
- Structured logs and offline tests.

The dashboard is an observability tool and first data sensor. It is not the
product goal.

## Phase 2 - Strategy Engine And Backtesting

**Status: Accepted research baseline on June 9, 2026**

A prototype currently includes:

- structured strategy signals;
- baseline moving-average, RSI/VWAP, and breakout strategies;
- a risk-manager skeleton;
- a simulated paper-broker abstraction;
- a signal-driven backtest runner;
- fees, slippage, and funding placeholders;
- performance metrics and tests.

The implementation and Phase 2B corrections passed independent Codex review
and explicit human approval. Acceptance applies only to historical research
and simulation. See `docs/PHASE2_REVIEW_NOTES.md`.

## Phase 2B - Safety And Realism Corrections

**Status: Accepted on June 9, 2026**

Phase 2B completed the required work to:

- model stop-loss gaps without optimistic fills;
- wire stale-data and stale-signal checks correctly;
- enforce simulation-only broker behavior in simulations;
- validate signal instrument, timeframe, timestamp, and candle alignment;
- add adverse tests covering those failures;
- validate spread, fees, slippage, and funding accounting;
- confirm no look-ahead behavior;
- reconcile documentation with actual behavior; and
- receive independent review and explicit human approval.

Phase 2/2B acceptance does not itself authorize Phase 3. Phase 3 remains a
separate scope requiring explicit human approval before implementation.

## Phase 3 - Live Public OKX WebSocket Data

### Phase 3A - Live Public WebSocket Market-Data Observation

**Status: Accepted on June 9, 2026**

Real-time market observation only. Explicitly in scope:

- live, UNAUTHENTICATED public OKX WebSocket streaming for BTC-USDT and
  ETH-USDT only;
- public ticker, trades, and candle channels;
- protocol heartbeat/ping-pong and cancellation-safe reconnect with bounded
  backoff;
- message validation (type, instrument, channel, timestamp, numeric fields)
  with rejection of malformed, unsupported, duplicate, or out-of-order data;
- bounded, async/thread-safe in-memory latest-market state (no persistence);
- connection/staleness tracking; read-only API and optional dashboard status;
- structured logging and offline tests with fake connections.

Explicitly OUT of scope for Phase 3A (still unauthorized): strategy evaluation
or signals from live data, simulated/paper/demo/live trading, any account
authentication, private endpoints, orders, leverage, or withdrawals. Phase 3A
completed its Codex correction/review pass and was explicitly accepted by the
human owner on June 9, 2026.

### Phase 3B - Remaining Live-Data Hardening

**Status: Accepted on June 9, 2026**

- Public order-book streams and sequence validation.
- REST backfill after gaps and missing-bar detection.
- Durable writes and longer-running observability.

The implementation passed an independent adversarial review (Claude) that found
no blocker and no required follow-up: the reviewer's order-book checksum
question was resolved as a deliberate, documented design choice (OKX is
deprecating the JSON checksum on June 23, 2026 and recommends `seqId`/`prevSeqId`
continuity, which is implemented). The review is recorded in
`docs/PHASE3B_REVIEW_NOTES.md`, and implementation detail and limitations are in
`docs/PHASE3B_LIVE_DATA_HARDENING.md`. The human owner explicitly accepted
Phase 3B on June 9, 2026.

Phase 3B remains public-data-only. It authorizes no live strategy evaluation,
signals, paper/demo/live trading, authentication, accounts, private endpoints,
orders, leverage, or withdrawals. Its acceptance did not by itself authorize
Phase 4; the human owner separately authorized Phase 4 on June 9, 2026.

## Phase 4 - Local Paper Trading Loop

**Status: Accepted after final independent review on June 10, 2026**

- Forward-time strategy evaluation on confirmed public `1m` candles.
- Fresh synchronized bid/ask virtual fills with fees, spread, and slippage.
- Long-only spot simulation with virtual balances and positions.
- Deterministic risk vetoes, exposure limits, daily-loss lockout, and a local
  kill switch.
- Atomic trade journal, idempotency, restart reconciliation, and daily reports.
- Read-only `/paper` observability.
- No private OKX APIs, credentials, exchange account, demo orders, real orders,
  leverage, shorting, or withdrawals.

Implementation details and limitations are documented in
`docs/PHASE4_LOCAL_PAPER_TRADING.md`. The independent review and resolved
findings are recorded in `docs/PHASE4_REVIEW_NOTES.md`. The human owner
supplied explicit approval on June 9, 2026; the final review cleared and the
phase gate completed on June 10, 2026.

## Phase 5 - OKX Demo Trading

**Status: Planned, not authorized**

- Authenticated access to OKX's simulated trading environment only.
- Demo account reads, demo orders, updates, cancel/replace, and reconciliation.
- Least-privilege simulated credentials and a security review.
- Mandatory kill switch, limits, idempotency, and audit logs.
- No real funds and no withdrawal permission.

## Phase 6 - AI News And Event Research Agent

**Status: Planned, not authorized**

- Ingest approved news, macro, official-source, and social-watchlist data.
- Classify event type, source quality, asset impact, and confidence.
- Produce structured research outputs.
- Adjust bounded strategy confidence or block trades under defined rules.
- Never place, approve, modify, or cancel orders.

## Phase 7 - Walk-Forward And Long Evaluation

**Status: Planned, not authorized**

- In-sample development separated from validation and holdout data.
- Rolling walk-forward testing with purge gaps where appropriate.
- Multiple market regimes and adverse periods.
- Randomized costs, spread, slippage, gaps, and failure stress tests.
- Long-running paper and demo evaluation.
- Compare simulated assumptions with observed paper/demo behavior.

No fixed profitability threshold alone can approve progression.

## Phase 8 - Tiny Live Automated Trading

**Status: Future vision, not authorized**

This phase may be considered only after every prior phase is accepted and a
separate security, operational, and capital review succeeds.

Required controls include:

- tiny, explicitly approved capital;
- least-privilege read/trade key with no withdrawal permission;
- IP restrictions where available;
- strict position, leverage, daily-loss, and weekly-loss limits;
- required protective exits;
- order idempotency and account/order/position reconciliation;
- stale-data and disconnected-feed blocks;
- automated kill switch and manual emergency stop;
- complete audit logs, monitoring, and alerts; and
- risk-manager final veto over every order.

The AI/LLM remains outside the execution authority path.

## Phase Completion Gate

A phase is complete only when:

1. The approved implementation exists.
2. Normal tests pass.
3. Adverse safety tests pass.
4. Reviewer findings are resolved.
5. Documentation matches implementation.
6. The relevant security and risk review passes.
7. The human owner explicitly approves completion.

No agent may approve its own work.
