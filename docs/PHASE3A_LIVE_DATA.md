# Phase 3A — Live Public WebSocket Market Data

**Status: Accepted on June 9, 2026.** The Codex correction/review pass and
explicit human approval are complete. See `docs/PHASES.md`.

Phase 3A adds live, **unauthenticated, public** OKX WebSocket market-data
streaming. It is **real-time observation only**.

## What it does

- Connects to OKX's **public** market-data WebSocket endpoints (no login, no
  keys, no signature).
- Observes **BTC-USDT** and **ETH-USDT** only.
- Subscribes to public **ticker**, **trades**, and **candle** (`candle1m`)
  channels.
- Validates every message (type, instrument, channel, timestamp, numeric
  fields) and rejects/ignores malformed, unsupported, duplicate, or
  out-of-order data.
- Maintains a **bounded, in-memory** "latest state" (latest ticker/candle per
  instrument + a small recent-trades window). **No persistence.**
- Tracks each required feed independently. A feed is connected only after all
  requested subscriptions are acknowledged.
- Separates transport liveness from accepted market-data freshness. Malformed
  frames, control events, heartbeat traffic, duplicates, and out-of-order data
  do not keep market data fresh.
- Reports aggregate health fail-closed: both required feeds must be connected,
  acknowledged, and fresh.
- Exposes **read-only** API endpoints and an optional dashboard status panel.

## What it explicitly does NOT do

No strategy evaluation or signals from live data, no simulated/paper/demo/live
trading, no account authentication, no private endpoints, no orders, no
leverage, no withdrawals, and no database writes. Phase 3A does not feed live
data into the Phase 2 strategy/risk/broker code.

## Architecture

```text
OKX public WS  ──►  app/exchange/okx_public_ws.py        (protocol isolated here)
                        │  normalized TickerUpdate / TradeUpdate / CandleUpdate
                        ▼
                    app/live/market_state.py  (bounded, lock-protected, in-memory)
                        │
                        ├──►  app/api/live.py        (read-only /live/* endpoints)
                        └──►  dashboard/streamlit_app.py  (optional status panel via HTTP)

scripts/run_live_market_data.py  ──► starts the stream (standalone process)
```

- `app/exchange/base.py` defines an exchange-neutral `PublicMarketDataAdapter`.
  OKX protocol details (URLs, subscribe message, ping/pong, message shapes) live
  only in `app/exchange/okx_public_ws.py`.
- The adapter writes into a `MarketState`; it is not coupled to strategies,
  risk, or brokers.
- Parsing (`parse_okx_message`) is a pure function, separate from the async run
  loop, so validation is easy to test offline.

### Connection handling

- **Heartbeat:** after subscriptions are acknowledged, if no frame arrives
  within `ping_interval` (default 20s), the adapter sends an app-level
  `"ping"`. A failed heartbeat send closes and reconnects the session.
- **Subscriptions:** acknowledgements must exactly match every requested
  channel/instrument pair. Partial acknowledgements remain unavailable; an
  error, wrong/duplicate acknowledgement, or timeout triggers reconnect.
- **Reconnect:** on connect failure or a dropped connection, the adapter waits
  with **bounded exponential backoff** (1s → 2s → 4s … capped at 30s) and
  retries, resetting backoff after a successful connect. Waiting is
  cancellation- and stop-aware.
- **Shutdown:** setting the stop event ends the loop promptly; cancelling the
  task is safe (the connection is closed and status set to `stopped`).

### Endpoints used (all public/unauthenticated)

- `wss://ws.okx.com:8443/ws/v5/public` — `tickers`, `trades`
- `wss://ws.okx.com:8443/ws/v5/business` — `candle1m`

## Run instructions

Standalone stream (its own process; prints periodic status):

```bash
source .venv/bin/activate
python scripts/run_live_market_data.py --duration 30
# or until Ctrl-C:
python scripts/run_live_market_data.py
```

Read-only API with the stream running in-process (opt-in):

```bash
LIVE_WS_AUTOSTART=true uvicorn app.api.main:app --reload
# then:
#   GET http://localhost:8000/live/health
#   GET http://localhost:8000/live/feeds
#   GET http://localhost:8000/live/state
#   GET http://localhost:8000/live/tickers
#   GET http://localhost:8000/live/trades
```

Without `LIVE_WS_AUTOSTART=true` the API still serves `/live/*` but reports a
disconnected/empty state (no WebSocket is opened). Importing the app or running
tests never opens a connection.

Optional dashboard panel (reads the API over HTTP):

```bash
LIVE_API_BASE=http://localhost:8000 streamlit run dashboard/streamlit_app.py
```

## Configuration (all public, non-secret)

| Env var | Default | Meaning |
|---|---|---|
| `OKX_PUBLIC_WS_URL` | `wss://ws.okx.com:8443/ws/v5/public` | public ticker/trades WS |
| `OKX_BUSINESS_WS_URL` | `wss://ws.okx.com:8443/ws/v5/business` | public candle WS |
| `LIVE_WS_AUTOSTART` | `false` | open the stream in-process on API startup |
| `LIVE_STALE_AFTER_SECONDS` | `30` | seconds without accepted market data before "stale" |
| `LIVE_API_BASE` | `http://localhost:8000` | dashboard → live API base URL |

## Limitations and assumptions

- In-memory only; state is lost on restart (no persistence by design in 3A).
- The standalone runner and an autostarted API are **separate processes** with
  separate in-memory state. To see live data in the API, run the API with
  `LIVE_WS_AUTOSTART=true`.
- Candle channel is `candle1m`; order book and REST gap-backfill are Phase 3B.
- Duplicate/out-of-order rejection is timestamp-based per stream (trades also
  de-duplicate by trade id within a bounded window); it is not full sequence
  validation.
- `LIVE_STALE_AFTER_SECONDS` is measured from the last valid, accepted market
  update for each feed, not from arbitrary WebSocket frames.
- A new direct dependency, `websockets==16.0`, is used for the public WS client
  (already present transitively via `uvicorn[standard]`).

## Review verification

The June 9, 2026 Codex correction/review pass verified:

- fail-closed endpoint, channel, instrument, row-identity, and numeric
  validation;
- exact subscription acknowledgement and timeout handling;
- separate per-feed transport liveness and accepted-data freshness;
- heartbeat failure, reconnect, cancellation, and sibling-task cleanup;
- bounded state and duplicate/out-of-order rejection;
- read-only API/dashboard behavior and no import-time network connection;
- 240 offline tests, clean compile/dependency/diff checks, and a 10-second
  public-only smoke test with both feeds connected, acknowledged, and fresh.

## Safety

Phase 3A acceptance covers observation only. It authorizes no trading, account
access, private endpoints, or orders. See
`CLAUDE.md`, `PROJECT_RULES.md`, and `docs/PHASES.md`.
