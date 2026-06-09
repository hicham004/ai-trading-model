Bro I did the research and I’m going to be very direct: **we are not building a candle viewer. We are building an automated OKX trading system, but the candle viewer is the first sensor.**

The final product is:

```text
AI-assisted automated OKX trading bot
= live market data + strategy engine + AI/news research + risk manager + OKX executor
```

The best version is **not** “Claude sees chart and clicks buy.” It is an automated system where the **AI helps analyze**, but the **risk engine and execution engine control the real orders**. This matches the project source: the plan already says the system should be hybrid — OKX data, feature engineering, ML/regime detection, news/X sentiment, risk manager, OKX executor, dashboard/logs — and that real money comes only after backtesting, paper/demo trading, fees, slippage, and bad-market testing. 

---

# The ultimate vision

## Final architecture

```text
OKX REST historical data
        ↓
Historical database / candles / funding / OI / trades
        ↓
Backtesting + feature engineering + model training

OKX WebSocket live data
        ↓
Live tickers / trades / order book / live candles
        ↓
Real-time signal engine
        ↓
Regime filter
        ↓
Strategy ensemble
        ↓
AI news/event reasoning agent
        ↓
Risk manager
        ↓
Paper/demo broker
        ↓
OKX live executor later
        ↓
Dashboard + Telegram alerts + full logs
```

OKX is suitable because it provides REST and WebSocket APIs; OKX’s docs specifically recommend WebSocket for market data and order book depth because it avoids repeated REST polling and gives continuous updates. ([OKX][1]) OKX also has demo trading/paper trading, and its API FAQ explains that simulated calls use simulated API keys with the `x-simulated-trading` request header set to `1`, so we can test automated execution before touching real money. ([OKX][2])

---

# The best “strategy” is not one strategy

Bro there is no single magic OKX strategy. The best serious approach is an **adaptive multi-regime strategy ensemble**.

That means the bot first asks:

```text
What market regime are we in?
```

Then it chooses the correct strategy.

## Core strategy: adaptive regime ensemble

### Regime 1 — Trending market

Use:

```text
breakout + moving average trend + volume confirmation + order-book filter
```

Best for:

```text
BTC/ETH when market is moving strongly
```

Example:

```text
ETH above 200 EMA
+ 20-period high breakout
+ volume above average
+ funding not too crowded
+ order book not showing extreme sell pressure
= possible long signal
```

### Regime 2 — Ranging market

Use:

```text
RSI / z-score / VWAP mean reversion
```

Best for:

```text
sideways BTC/ETH
```

Example:

```text
ETH near lower range
+ RSI oversold
+ price below VWAP band
+ no bearish news shock
= possible long mean-reversion signal
```

### Regime 3 — High-volatility danger

Use:

```text
no trade / reduce size / only breakout after confirmation
```

Best for:

```text
CPI, war headlines, liquidation cascades, extreme candles
```

The risk manager should be allowed to say:

```text
No trade. Volatility too high.
```

### Regime 4 — News/event momentum

Use:

```text
confirmed news + price confirmation + volume confirmation
```

Best for:

```text
ETF news, Fed news, Trump/war/tariff headlines, hacks, exchange issues
```

The AI agent should not say “buy.” It should say:

```json
{
  "event": "confirmed ETF approval news",
  "asset_impact": "BTC bullish",
  "confidence": 0.76,
  "action": "increase long confidence, do not execute alone"
}
```

This is important because your project source already says the LLM should analyze news and events, while the strategy/risk engine keeps final control. 

---

# The real trading brain

## 1. Market data engine

Current dashboard = historical candle layer.

Good, but not enough.

We need:

```text
REST historical candles
WebSocket live candles
WebSocket trades
WebSocket order book
funding rates
open interest
liquidation/proxy data if available
spread/slippage estimator
```

REST is for history and backfills. WebSocket is for live trading. OKX’s API overview separates Trading API and Data API and lists market data, public data, order book trading, and historical candlesticks as available API areas. ([OKX][3])

## 2. Feature engine

Every candle/live tick becomes features:

```text
returns
volatility
ATR
RSI
MACD
EMA slope
VWAP distance
volume spike
breakout distance
funding rate
open interest change
spread
order-book imbalance
BTC trend
ETH/BTC trend
news score
social score
```

## 3. Regime detector

Start simple:

```text
trend regime
range regime
high-volatility regime
low-liquidity regime
news-shock regime
```

Later:

```text
HMM
KMeans clustering
LightGBM/XGBoost classifier
volatility model/GARCH-style risk estimator
```

Do **not** start with reinforcement learning. It is too easy to overfit and look amazing in backtest but fail live. Research on backtest overfitting and walk-forward validation repeatedly warns that in-sample performance can collapse out of sample; one large Quantopian study used 888 algorithms and found backtest-overfitting is a serious problem. ([quantpedia.com][4])

## 4. Strategy engine

Each strategy outputs the same object:

```json
{
  "instrument": "ETH-USDT-SWAP",
  "timeframe": "1H",
  "direction": "long",
  "confidence": 0.68,
  "entry_price": 1684.50,
  "stop_loss": 1648.00,
  "take_profit": 1758.00,
  "max_risk_pct": 0.005,
  "reason": "trend breakout + volume confirmation + neutral funding",
  "expires_at": "2026-06-08T18:00:00Z"
}
```

Strategies to build:

```text
Strategy A: trend breakout
Strategy B: RSI/VWAP mean reversion
Strategy C: volatility expansion breakout
Strategy D: funding/open-interest filter
Strategy E: news-confirmed momentum
Strategy F: no-trade filter
```

## 5. AI research/news agent

This is where Claude/GPT is useful.

It watches:

```text
official OKX/Binance/Coinbase accounts
Fed/FOMC/central-bank news
Trump/geopolitical headlines
ETF/SEC news
major crypto founders
hacks/exploits
Iran/Lebanon/Middle East escalation
macro data: CPI, PPI, jobs, rates
```

For X, the official X API now uses pay-per-usage pricing, so we should start with a tiny watchlist, not scrape huge feeds. ([docs.x.com][5]) For broader crypto market data, CoinGecko’s Demo API currently offers 10,000 monthly calls at 100 calls/minute, and paid plans start at $35/month, so CoinGecko can be a low-cost secondary data source. ([CoinGecko][6]) For real news, NewsAPI.ai’s 5K plan is listed at $90/month and includes current data from the last 30 days. ([newsapi.ai][7])

The AI output should be structured, not vibes:

```json
{
  "event_type": "geopolitical",
  "source_quality": "high",
  "asset": "ETH",
  "impact": "risk_off",
  "confidence": 0.74,
  "trade_effect": "block_new_longs_for_30m",
  "summary": "Confirmed escalation headline increased short-term risk."
}
```

## 6. Risk manager

This is the most important module.

The risk manager controls:

```text
position size
max leverage
max daily loss
max weekly loss
max open positions
stop loss required
spread/slippage allowed
market regime allowed
news danger filter
cooldown after losses
kill switch
```

For your “moderate risk” goal:

```text
Backtest/paper phase:
risk per trade: 0.25%–0.5%
max daily loss: 1.5%–2%
max weekly loss: 4%–5%
leverage: simulated 1x–3x

Tiny live phase:
capital: $100–$300 first
risk per trade: 0.25%–0.5%
max leverage: 1x–2x
daily kill switch: mandatory
```

OKX perpetual trading costs matter a lot. OKX’s futures/perpetual explainer says the lowest-tier perpetual fees are commonly maker/taker style around 0.02%/0.05%, with funding payments exchanged periodically, while the official fee schedule should always be checked because fee tiers vary. ([OKX][8])

## 7. Execution engine

This is where automation finally happens.

But it must be dumb and controlled.

```text
Signal engine says: possible long
Risk manager says: approved size 0.03 ETH
Execution engine says: place limit order + stop loss + take profit
```

Not:

```text
Claude says buy → order placed
```

OKX supports order placement through REST and WebSocket private endpoints, but those require authentication and must only be added after demo/paper validation. OKX docs show order placement endpoints and rate limits, so execution is technically possible later; the issue is safety, not possibility. ([OKX United States][9])

---

# Best tech stack

## Current local phase

```text
Backend: Python + FastAPI
Database: PostgreSQL
Dashboard: Streamlit first
Backtesting: custom simple engine now
Data: OKX REST candles
Agents: Claude Code + Codex + ChatGPT
```

FastAPI is a strong fit because it is a modern Python web framework based on type hints and is designed to be fast and production-ready. ([FastAPI][10])

## Serious phase

```text
Backend: Python FastAPI
Live workers: asyncio services
Database: PostgreSQL + TimescaleDB
Queue: Redis + Celery/RQ
Backtesting: vectorbt first, custom event-driven simulator later
ML: pandas, numpy, scikit-learn, LightGBM/XGBoost
Live data: native OKX WebSocket
Execution: native OKX API, not LLM
Dashboard: React/Tailwind later
Alerts: Telegram/Discord
Deployment: VPS or Render/Railway first, then dedicated VPS
```

Vectorbt is good for fast research because it works on pandas/NumPy and can test many strategies quickly. ([VectorBT][11]) Backtrader is also a solid framework for reusable strategies/indicators and more event-style simulation. ([backtrader.com][12]) TimescaleDB is useful later because it is a PostgreSQL extension built for high-performance time-series/event data. ([GitHub][13])

---

# Agent workflow

Use the agents like this:

```text
Claude Code = main builder
Codex = tester/reviewer/refactor checker
ChatGPT = architect/research/decision support
OpenClaw = future command center only
```

Claude Code is useful because Anthropic describes it as an agentic coding tool that works in your codebase, edits files, runs commands, and helps ship from terminal/IDE. ([Claude][14]) Codex CLI is useful as a second agent because OpenAI describes it as a local coding agent that can read, change, and run code on your machine in the selected directory. ([OpenAI Developers][15])

Agent loop:

```text
1. Claude builds feature
2. Codex tests and tries to break it
3. Claude fixes bugs
4. ChatGPT reviews architecture
5. You approve phase change
6. Git commit
```

Never let one agent build, review, and approve everything alone.

---

# Build roadmap from today

## Phase 1 — Data foundation — mostly done

Status:

```text
OKX candles
PostgreSQL
Streamlit dashboard
read-only data
tests passing
```

Action now:

```bash
git status
git add .
git commit -m "feat: add phase 1 OKX candle research foundation"
```

But first inspect `.claude/scheduled_tasks.lock`. If it is generated junk, add `.claude/` or that lock file to `.gitignore`.

## Phase 2 — Strategy engine and real backtesting

Build:

```text
Signal model
Strategy interface
Moving average crossover
RSI/VWAP mean reversion
Breakout strategy
Backtest runner
Fees/slippage/funding placeholders
Performance report
Risk manager skeleton
```

Metrics:

```text
total return
win rate
profit factor
max drawdown
Sharpe/Sortino
average win/loss
number of trades
exposure time
fees paid
slippage cost
```

Important: no strategy is allowed to be “good” only because one backtest looked good. A 2026 paper on walk-forward validation says rigorous validation is designed to mitigate overfitting and lookahead bias; another proposes in-sample, walk-forward, and out-of-sample stages with purge gaps and veto rules. ([arXiv][16])

## Phase 3 — Live public WebSocket data

Build:

```text
OKX WebSocket client
ticker stream
trades stream
candle stream
order book stream
heartbeat/reconnect
sequence validation
database writer
live dashboard
```

This phase makes the bot feel “alive.”

## Phase 4 — Paper trading engine

Build:

```text
virtual account balance
virtual orders
virtual fills
virtual positions
virtual PnL
virtual fees
virtual slippage
trade journal
daily report
```

This is still not OKX private API.

## Phase 5 — OKX demo trading

Add:

```text
simulated OKX API keys
x-simulated-trading: 1
private account read
demo order placement
demo order updates
demo position sync
cancel/replace logic
```

This is where automation becomes real, but still fake money.

## Phase 6 — AI news/event agent

Add:

```text
X API watchlist
news API
event classifier
source credibility scoring
asset impact scoring
fake-news/unconfirmed filter
AI reasoning summary
trade-confidence adjustment
```

The AI agent should only adjust confidence or block trades. It should not place orders.

## Phase 7 — Walk-forward validation

For each strategy:

```text
train window
validation window
out-of-sample holdout
walk-forward rolling tests
different regimes
fees/slippage/funding
Monte Carlo/randomized slippage
stress tests
```

Pass conditions:

```text
profit factor > 1.2 after costs
max drawdown acceptable
not one lucky trade
works across multiple periods
does not collapse out of sample
paper trading roughly matches backtest
```

## Phase 8 — Tiny live automated trading

Only then:

```text
$100–$300 capital
1x–2x max leverage
read + trade API key only
no withdrawal permission
IP whitelist if possible
daily kill switch
manual emergency button
all trades logged
```

OKX API FAQ says API key permissions include Read, Trade, and Withdraw, so the live key should never have Withdraw permission. ([OKX][2]) OKX also supports IP whitelisting features to restrict where API keys can be used, which matters because stolen keys become much harder to exploit if requests must come from whitelisted servers. ([OKX][17])

---

# The best strategy setup for OKX specifically

Start with **BTC-USDT-SWAP and ETH-USDT-SWAP only**.

Why:

```text
highest liquidity
tightest spreads
less random than small alts
enough volatility
more reliable news impact
```

Avoid at first:

```text
low-liquidity alts
meme coins
100x leverage
scalping with weak infrastructure
AI-only decisions
copying YouTube win-rate strategies
```

## Strategy ensemble v1

### Strategy 1: ETH/BTC trend breakout

Use on:

```text
1H and 4H
```

Long rules:

```text
price above 200 EMA
20-bar breakout
volume > 1.3x rolling average
ATR not extreme
spread below threshold
funding not too positive
BTC not dumping
```

Exit:

```text
ATR stop
take profit 1.5R–2.5R
trailing stop after 1R
time stop if no movement
```

### Strategy 2: RSI/VWAP mean reversion

Use on:

```text
15m and 1H
```

Long rules:

```text
range regime detected
RSI < 30
price below VWAP band
no bearish news shock
order book not heavily bearish
```

Exit:

```text
return to VWAP
fixed stop below local low
time stop
```

### Strategy 3: volatility expansion breakout

Use when:

```text
low volatility compresses then expands
```

Rules:

```text
Bollinger/ATR compression
breakout candle closes outside range
volume expansion
no spread/slippage warning
```

### Strategy 4: news momentum overlay

This is not a standalone strategy at first.

It modifies signals:

```text
confirmed bullish news: +confidence
confirmed bearish news: block longs / reduce long size
unconfirmed news: no trade
high-impact macro event soon: reduce size
```

### Strategy 5: no-trade strategy

This sounds stupid but is powerful.

Block trades when:

```text
spread too wide
liquidity too thin
funding too crowded
price moved too far too fast
API data stale
WebSocket disconnected
major event incoming
daily loss hit
strategy confidence low
```

---

# Reliability plan

Automated trading fails from boring technical problems.

Build protection:

```text
heartbeat checker
WebSocket reconnect
REST fallback
data staleness detection
duplicate candle protection
order idempotency with clOrdId
position reconciliation
open-order reconciliation
exchange error handler
rate-limit handler
clock sync
kill switch
manual close-all button
```

For OKX order-book streaming, pay attention to sequence continuity. OKX’s changelog says order book integrity should use `seqId/prevSeqId` continuity in affected updates rather than relying on checksum behavior after upcoming changes. ([OKX][18])

---

# Cost plan

## Cheap/local version

```text
OKX public API: free
local PostgreSQL: free
Streamlit/FastAPI local: free
Claude/Codex subscriptions: what you already pay
CoinGecko demo: free
X API: optional later
```

## Serious paper version

```text
VPS/hosting: ~$25–$85/month
database/backup: ~$20–$100/month
X/news/social: variable
Claude/OpenAI API: ~$50–$250/month
monitoring: $0–$50/month
```

## Production version

```text
reliable VPS/server: ~$85–$250/month
database/backups: ~$55–$200/month
X/news/social: ~$300–$1500+
AI APIs: ~$100–$500
monitoring/alerts: ~$20–$100
```

These numbers match the earlier project source direction: start cheap, then only pay for serious data sources when the bot proves the basic engine. 

---

# Immediate next move

Do **not** keep arguing with the dashboard. It did its job.

Your next agent task should be:

```text
Phase 2: strategy engine + backtesting + risk manager skeleton
```

Use this prompt:

```text
We finished Phase 1. The dashboard is only the historical data foundation, not the final product.

The long-term goal is an automated OKX trading bot that can eventually place orders by itself after strict validation. Do not build live trading yet, but make the architecture clearly point toward automated execution later.

Build Phase 2:

1. Create a strategy engine:
   - Strategy base class/interface
   - Signal model
   - Trade model
   - Backtest result model

2. Add baseline strategies:
   - Moving average crossover
   - RSI/VWAP mean reversion
   - Breakout strategy

3. Add a backtest runner that uses stored candles.

4. Add fee/slippage/funding placeholders.

5. Add performance metrics:
   - total return
   - win rate
   - profit factor
   - max drawdown
   - average win
   - average loss
   - number of trades
   - fees paid
   - slippage cost

6. Add a risk manager skeleton:
   - max risk per trade
   - max daily loss
   - max position size
   - max leverage placeholder
   - stop-loss required
   - no trade if confidence too low
   - no trade if data stale

7. Add a paper broker interface:
   - no real OKX private API
   - no account access
   - no order placement
   - simulated fills only

8. Add docs explaining:
   - Phase 1 = data foundation
   - Phase 2 = strategy/backtest
   - Phase 3 = live WebSocket data
   - Phase 4 = paper trading
   - Phase 5 = OKX demo trading
   - Phase 6 = tiny live automated trading

Hard restrictions:
- no real API keys
- no live orders
- no private OKX endpoints
- no leverage in real exchange
- no withdrawals
- no profitability claims
- no martingale
- no doubling down

Run all tests before finishing.
Do not commit automatically.
Report changed files, how to run backtests, test results, and final git status.
```

---

# Final answer, bro

The current screen is **not the vision**.

The vision is:

```text
A bot that automatically trades on OKX,
but only after:
historical research
→ live market stream
→ backtesting
→ walk-forward validation
→ paper trading
→ OKX demo trading
→ strict risk control
→ tiny live automation
```

The best strategy is not “MACD” or “RSI.”
The best strategy is:

```text
adaptive regime-based strategy ensemble
+ live OKX WebSocket data
+ AI news/event intelligence
+ strict risk manager
+ controlled OKX executor
```

That is the serious version.

[1]: https://www.okx.com/docs-v5/en/?utm_source=chatgpt.com "OKX API guide | OKX technical support"
[2]: https://www.okx.com/help/api-faq?utm_source=chatgpt.com "OKX API FAQ"
[3]: https://www.okx.com/en-us/okx-api?utm_source=chatgpt.com "Free Crypto Price API | OKX REST & WebSocket API"
[4]: https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/?utm_source=chatgpt.com "Quantopian's Academic Paper About In vs. Out-of-Sample ..."
[5]: https://docs.x.com/x-api/getting-started/pricing?utm_source=chatgpt.com "Pricing"
[6]: https://www.coingecko.com/en/api/pricing?utm_source=chatgpt.com "Crypto API Pricing Plans"
[7]: https://newsapi.ai/plans?utm_source=chatgpt.com "API Pricing"
[8]: https://www.okx.com/en-eu/learn/what-is-okx-perpetual-futures?utm_source=chatgpt.com "What is OKX Perpetual Futures: Fees, Trading, Features"
[9]: https://my.okx.com/docs-v5/en/?utm_source=chatgpt.com "Overview – OKX API guide | OKX technical support"
[10]: https://fastapi.tiangolo.com/?utm_source=chatgpt.com "FastAPI - FastAPI"
[11]: https://vectorbt.dev/?utm_source=chatgpt.com "VectorBT: Getting started"
[12]: https://www.backtrader.com/docu/?utm_source=chatgpt.com "Introduction"
[13]: https://github.com/timescale/timescaledb?utm_source=chatgpt.com "timescale/timescaledb: A time-series database for high- ..."
[14]: https://claude.com/product/claude-code?utm_source=chatgpt.com "Claude Code by Anthropic | AI Coding Agent, Terminal, IDE"
[15]: https://developers.openai.com/codex/cli?utm_source=chatgpt.com "Codex CLI"
[16]: https://arxiv.org/html/2512.12924v1?utm_source=chatgpt.com "A Rigorous Walk-Forward Validation Framework for Market ..."
[17]: https://www.okx.com/help/third-party-app-ip-whitelist-launch?utm_source=chatgpt.com "Third Party App IP Whitelist Launch"
[18]: https://www.okx.com/docs-v5/log_en/?utm_source=chatgpt.com "Upcoming Changes – OKX API guide | OKX technical support"
