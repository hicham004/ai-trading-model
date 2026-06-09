# Live Trading Vision

## Product Definition

The long-term product is an AI-assisted automated OKX trading system that can
eventually place trades without a human clicking each order.

This is not a dashboard project. The dashboard is for visibility.
This is not a manual trading assistant. Research reports and signals are
inputs to an automated, controlled decision pipeline.

Real trading is not currently authorized.

## Target Architecture

```text
historical public OKX REST data
-> database and data-quality checks
-> feature engineering and realistic backtesting
-> strategy and market-regime engine
-> live public OKX WebSocket data
-> local paper broker and forward testing
-> OKX demo trading
-> AI news/event research layer
-> deterministic risk manager final veto
-> controlled tiny live OKX executor
-> logs, alerts, monitoring, and dashboard
```

Historical REST data supports backfills, research, and validation. Public
WebSocket data later supports live candles, trades, tickers, and order-book
state. Private exchange access is reserved for separately approved demo and
live phases.

## Decision Boundary

The AI/LLM is a research component, not an execution authority.

It may output structured information such as:

```json
{
  "event_type": "macro",
  "source_quality": "high",
  "asset": "BTC",
  "impact": "risk_off",
  "confidence": 0.74,
  "trade_effect": "reduce_or_block_new_longs",
  "summary": "Confirmed event may increase short-term downside risk."
}
```

It may research, classify events, explain signals, identify regimes, and adjust
confidence within deterministic limits. It must never call order endpoints.

Future order authority must follow:

```text
validated market data
-> strategy signal
-> deterministic eligibility checks
-> risk manager final veto and position limit
-> controlled execution module
-> exchange
```

## Strategy Direction

The intended approach is not one "magic" indicator. Research should move
toward an adaptive ensemble with explicit no-trade behavior:

- trend/breakout logic in trending regimes;
- RSI/VWAP or statistical mean reversion in ranges;
- volatility-expansion logic after compression;
- reduced size or no trade in high-volatility and low-liquidity regimes;
- funding, open-interest, spread, and order-book filters later;
- news/event overlays that adjust confidence or block trades; and
- a first-class no-trade filter.

These are research directions, not profitability claims.

## Live Safety Requirements

Tiny live automation may be considered only after all earlier phases are
accepted. It requires:

- explicitly limited capital;
- least-privilege read/trade access with no withdrawal permission;
- strict risk per trade and position limits;
- leverage, daily-loss, and weekly-loss limits;
- stop-loss and exit handling that accounts for gaps;
- spread/slippage limits;
- stale-data, disconnected-feed, and exchange-health blocks;
- idempotent orders and account/order/position reconciliation;
- complete logs, monitoring, and alerts;
- an automatic kill switch and manual emergency stop; and
- human approval of capital and deployment.

The risk manager must always be able to say "no trade."
