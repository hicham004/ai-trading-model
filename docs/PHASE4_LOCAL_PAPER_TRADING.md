# Phase 4 - Local Paper Trading

## Status And Boundary

The human owner explicitly authorized Phase 4 implementation on June 9, 2026.
The human owner also supplied explicit acceptance on June 9, 2026. After three
finding-and-correction rounds, final independent review found no remaining
blocker on June 10, 2026, completing the phase gate. See
`docs/PHASE4_REVIEW_NOTES.md`.

Phase 4 is local simulation only. It uses public, unauthenticated OKX market
data and cannot access an exchange account or place demo/real orders.

## Data Flow

```text
confirmed public candle + synchronized public book
-> candle/time/continuity validation
-> incremental strategy evaluation
-> signal validation and deterministic identity
-> risk-manager final veto
-> virtual order and simulated fill
-> staged virtual account mutation
-> atomic ledger transaction
-> in-memory commit after persistence succeeds
```

The runtime is opt-in through `scripts/run_paper_trading.py`. Imports, API
startup, and tests do not start it.

## Timing And Fills

- The approved live feed currently supports `1m` candles only.
- A strategy sees only history through the newly confirmed candle.
- A quote-priced fill requires a connected, fresh feed and a synchronized,
  coherent order book.
- The quote timestamp must be at or after the candle close that made the signal
  actionable.
- Buys cross the ask; sells cross the bid. Configured adverse slippage and fees
  are then applied.
- Protective long stops use the stop price, or the worse candle open when a bar
  gaps below the stop, plus adverse slippage and fees.
- Missing candle continuity halts the paper loop. Stale/future/malformed,
  duplicate, out-of-order, wrong-instrument, and wrong-timeframe data cannot
  create a fill.
- Stale confirmed candles are persisted as recovery bars. They cannot open
  retrospective trades, but they remain in indicator history and can enforce
  a protective stop that was already active.

## Account And Risk

The account is virtual USDT plus long-only spot positions. It prohibits:

- negative cash and borrowing;
- leverage and short selling;
- partial oversells;
- duplicate entries and averaging down;
- martingale, doubling, and loss chasing; and
- non-finite prices, quantities, fees, or balances.

Every entry passes the deterministic risk manager. Gates include feed/book/
quote health, signal freshness and confidence, a required stop, risk-based
sizing, maximum position and total exposure, maximum open positions, daily
realized-loss lockout, and the local kill switch. Protective exits are not
blocked by entry vetoes.

Risk sizing includes modeled entry and non-gap stop-exit fees and adverse
slippage. A market gap through the stop can still exceed the configured risk,
because the stop price may never be available.

## Persistence And Restart

The `paper_*` tables store:

- account configuration;
- processed-candle identities and OHLCV restart history;
- immutable UTC-day starting-equity baselines;
- signals and risk decisions;
- virtual orders and simulated fills;
- completed trades;
- equity/position snapshots;
- runtime health and lock state; and
- append-only operational events.

One transaction persists a candle marker and its entire outcome. The engine
adopts staged account state only after that transaction commits.

On restart, reconciliation independently replays fills and compares cash,
position quantities, entry cost basis, fees, stop metadata, completed trades,
realized PnL, the immutable daily-loss baseline, and the latest account
snapshot. Corrupt, impossible, or inconsistent state blocks startup. The
paper ledger rebuilds the bounded strategy window and latest marks even when
separate public-data persistence is disabled. Persisted candles accumulated
during downtime cannot open retrospective trades, but they are replayed to
enforce protective stops that were already active.

Every processed candle must be interval-contiguous and have exactly one equity
snapshot. A missing middle candle or orphan snapshot makes reconciliation fail.

The complete paper-account configuration is immutable under one account name,
so a restart cannot silently strand an open position under a different
instrument or strategy. Lock acquisition is atomic and an active lock is never
stolen automatically. Releasing a heartbeat-expired lock requires an explicit
local operator command.

## Commands

```bash
python scripts/run_paper_trading.py --list
python scripts/run_paper_trading.py \
  --account default \
  --strategy ma_crossover \
  --instruments BTC-USDT \
  --timeframe 1m \
  --duration 300

python scripts/run_paper_trading.py --account default --engage-kill-switch
python scripts/run_paper_trading.py --account default --release-kill-switch
python scripts/run_paper_trading.py --account default --release-stale-lock
```

The API exposes read-only `/paper` endpoints for health, account, balances,
positions, signals, risk decisions, virtual orders/fills, trades, events, and
daily reports. It exposes no order-placement, modification, or cancellation
operation.

## Tests

The offline suite covers normal entries, spread/fees/slippage, stop gaps,
duplicate and gap handling, stale/future/malformed data, quote timing, feed and
book failures, kill-switch and risk vetoes, insufficient/invalid account
operations, simulation-only enforcement, atomic duplicate rollback,
fill-derived reconciliation and corruption, incompatible restart
configuration, concurrent lock acquisition, explicit stale-lock release,
cost-aware stop sizing, immutable daily-loss baselines, paper-ledger strategy
window reconstruction, processed-candle/snapshot continuity, stale-candle
recovery, authoritative kill-switch API state, stale runtime health, and
read-only API methods.

## Known Limitations

- Only the existing public `candle1m` feed is supported.
- Virtual fills use top-of-book plus configured slippage; they do not model
  queue position, partial fills, or full depth consumption.
- Protective stops are evaluated from confirmed OHLC candles, not tick by tick.
- Persistence uses SQLAlchemy `create_all`; a production migration workflow is
  not yet present.
- Historical warmup is context only and is never retrospectively traded.
- Results are simulations and make no profitability claim.

## Explicit Prohibitions

Phase 4 adds no API key fields, authentication, private endpoint client,
exchange account access, OKX demo mode, real order path, leverage, shorting, or
withdrawal functionality. Phase 5 and later remain unauthorized.
