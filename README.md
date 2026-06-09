# AI Trading Model

AI-assisted automated OKX trading-system project.

The long-term goal is a bot that can eventually place trades automatically
through a controlled strategy, risk, and execution pipeline. This is not a
dashboard-only project and it is not intended to remain a manual trading
assistant.

> **Current safety status:** real trading is not authorized. The repository
> must not access an OKX account, use private API keys, or place orders.
> Phases 1 and 2/2B are accepted research baselines. Phase 3A (live, public,
> unauthenticated WebSocket market-data observation only) was Codex-reviewed
> and explicitly accepted by the human owner on June 9, 2026. Phase 3B and
> later remain unapproved.

Read these before changing anything:

- [`CLAUDE.md`](CLAUDE.md)
- [`PROJECT_RULES.md`](PROJECT_RULES.md)
- [`docs/PHASES.md`](docs/PHASES.md)
- [`docs/PHASE2_REVIEW_NOTES.md`](docs/PHASE2_REVIEW_NOTES.md)
- [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md)

## Product Vision

```text
historical public OKX REST data
-> local database
-> realistic backtesting and strategy engine
-> live public OKX WebSocket data
-> local paper trading
-> OKX demo trading
-> AI news/event research layer
-> risk manager final veto
-> tiny controlled live OKX executor, much later
```

The AI/LLM may research, classify news, explain signals, identify regimes, and
adjust bounded confidence. It must never directly place or approve orders.
Only a strategy engine, deterministic checks, risk manager, and controlled
execution module may authorize future orders in an explicitly approved phase.

See:

- [`docs/LIVE_TRADING_VISION.md`](docs/LIVE_TRADING_VISION.md)
- [`docs/AUTOMATED_TRADING_ROADMAP.md`](docs/AUTOMATED_TRADING_ROADMAP.md)

## Current Phase Status

### Phase 1: accepted data foundation

- Public OKX REST candles for `BTC-USDT` and `ETH-USDT`.
- PostgreSQL or SQLite local storage.
- SQLAlchemy candle model and duplicate prevention.
- Read-only FastAPI API.
- Streamlit candle viewer.
- Structured JSON logs and offline tests.

The dashboard proves and displays the data pipeline. It is an observability
tool, not the final trading product.

### Phase 2: accepted research baseline

The repository contains prototype work for:

- structured strategy signals;
- moving-average, RSI/VWAP, and breakout research strategies;
- signal-driven historical backtesting;
- a risk-manager skeleton;
- a simulated paper-broker abstraction;
- fees, slippage, and funding placeholders; and
- performance metrics.

Phase 2B corrected the documented stop-gap fills, stale-signal handling,
simulation-only enforcement, signal identity/alignment, execution timing, and
adverse-test findings. Codex independently verified the corrections, and the
human owner accepted Phase 2/2B on June 9, 2026. See
[`docs/PHASE2_REVIEW_NOTES.md`](docs/PHASE2_REVIEW_NOTES.md).

Acceptance is limited to historical research and simulation. It does not
authorize live public streaming, paper trading, demo trading, account access,
or real orders.

## Safety Boundaries

- No live orders or real trades.
- No OKX private API keys or account authentication.
- No withdrawals or withdrawal permissions, ever.
- No martingale, doubling down, or automated loss chasing.
- No direct AI/LLM order authority.
- No profitability guarantees.
- A backtest never authorizes paper, demo, or live execution.
- The risk manager has final veto over every future action.
- No phase is complete solely because tests pass.
- Human approval is required for every phase transition.

## Project Layout

```text
app/
  okx/                  # public OKX REST market-data client only
  db/                   # local candle storage
  api/                  # read-only API (REST candles + /live status)
  strategy/             # accepted Phase 2 research strategies
  risk/                 # accepted Phase 2 research risk manager
  broker/               # accepted Phase 2 simulated broker
  backtest/             # accepted Phase 2 historical simulator
  exchange/             # Phase 3A public WebSocket adapters (protocol-isolated)
  live/                 # Phase 3A bounded in-memory live state + schemas
dashboard/
  streamlit_app.py      # local candle observability + live status panel
scripts/
  fetch_candles.py
  run_backtest.py
  run_strategy_backtest.py
  run_live_market_data.py   # Phase 3A: stream live PUBLIC market data
tests/
docs/
  PHASES.md
  PHASE2_REVIEW_NOTES.md
  PHASE3A_LIVE_DATA.md
  LIVE_TRADING_VISION.md
  AUTOMATED_TRADING_ROADMAP.md
  AGENT_WORKFLOW.md
  AGENT_HANDOFF.md
docker-compose.yml
```

## Local Setup

Requirements:

- Python 3.11+
- Docker and Docker Compose for PostgreSQL

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional local configuration:

```bash
cp .env.example .env
```

Never add real credentials to `.env`, `.env.example`, source code, tests,
logs, screenshots, or prompts.

## Run The Data Foundation

Start PostgreSQL:

```bash
docker compose up -d
docker compose ps
```

Fetch public candles:

```bash
python scripts/fetch_candles.py
```

This makes public, unauthenticated OKX market-data requests only.

Run the read-only API:

```bash
uvicorn app.api.main:app --reload
```

Useful local URLs:

- http://localhost:8000/docs
- http://localhost:8000/health
- http://localhost:8000/candles?instrument=BTC-USDT&timeframe=1H

Run the local dashboard:

```bash
streamlit run dashboard/streamlit_app.py
```

Open http://localhost:8501.

## Run Simulations

Phase 1 demo skeleton:

```bash
python scripts/run_backtest.py --instrument BTC-USDT --timeframe 1H
```

Phase 2 historical simulation:

```bash
python scripts/run_strategy_backtest.py --list
python scripts/run_strategy_backtest.py \
  --strategy ma_crossover \
  --instrument BTC-USDT \
  --timeframe 1H \
  --fee-rate 0.001 \
  --slippage-rate 0.0005
```

Execution model: a signal generated on one bar executes at the NEXT bar's OPEN
(not its close), so there is no look-ahead. Signal staleness is derived from
`--timeframe` by default (one bar interval), so 4H/1D candles work without extra
flags; override it with `--max-signal-age-seconds` if needed. Unknown timeframe
values are rejected.

Treat all output as historical simulation only. The review notes document the
resolved findings and remaining modelling assumptions. Phase 2 acceptance is
not evidence of profitability and does not authorize Phase 3 or any trading.

## Live Public Market Data (Phase 3A, Accepted)

Phase 3A streams live, **unauthenticated, public** OKX WebSocket market data for
`BTC-USDT` and `ETH-USDT` (ticker, trades, candle) into a bounded in-memory
state. It is **observation only**: no strategies, signals, simulation, account
access, or orders. It was Codex-reviewed and explicitly accepted by the human
owner on June 9, 2026; see
[`docs/PHASE3A_LIVE_DATA.md`](docs/PHASE3A_LIVE_DATA.md).

Standalone stream (prints periodic status):

```bash
python scripts/run_live_market_data.py --duration 30
```

Read-only API with the stream running in-process (opt-in; off by default so
imports/tests never open a socket):

```bash
LIVE_WS_AUTOSTART=true uvicorn app.api.main:app --reload
# GET /live/health · /live/feeds · /live/state · /live/tickers · /live/trades
```

The public ticker/trade feed and business candle feed have separate health,
subscription acknowledgement, transport-liveness, and market-data freshness
tracking. Aggregate health fails closed if either required feed is unavailable
or stale. No database is used in Phase 3A; the state is in memory only.

## Tests

```bash
pytest
```

The current suite runs offline. Passing it is necessary but not sufficient for
phase completion; adverse safety tests and independent review are also
required.

## Phase Approval

A phase is complete only when implementation exists, normal and adverse tests
pass, reviewer findings are resolved, documentation matches behavior, relevant
security/risk review succeeds, and the human owner explicitly approves it.

No agent may approve its own work, and no commit should be created
automatically.
