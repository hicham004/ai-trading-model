# Project Rules

## Purpose

This repository is for crypto-market research and software development. It is
not a live trading system in Phase 1. The long-term goal may include automated
order execution only after strict validation and explicit human phase approval.

## Trading Scope

### Phase 1

- Use public market data only.
- Do not place real orders.
- Do not request or use OKX private API keys.
- Do not add exchange account authentication.
- Do not create or enable live execution.

### Future Phases

Future phases may add capabilities in this order:

1. OKX demo trading
2. Paper trading
3. Tiny live automated trading

Each transition requires successful backtesting, walk-forward testing,
fees-and-slippage simulation, risk review, and explicit human phase approval.
No future phase is authorized by the current repository state.

## Automation Goal

The long-term goal is an automated AI-assisted trading system that can
eventually place orders by itself, but only through a controlled execution
layer. The AI model must never directly place orders. It must produce signals
or recommendations. The risk manager and execution module decide whether an
order is allowed.

## Execution Safety

- AI and LLM agents cannot directly call order endpoints.
- All order requests must pass through the risk manager.
- Live trading requires a separate phase approval.
- Demo trading must come before live trading.
- Live trading starts with tiny capital only.
- Maximum leverage, maximum daily loss, maximum position size, stop loss, and
  a kill switch are mandatory before any live phase.
- Withdrawal functionality and withdrawal permissions are never allowed.

## Security

- Keep secrets out of Git, source code, logs, tests, screenshots, and prompts.
- Use `.env.example` only as documentation. Put no real credentials in it.
- Use public, read-only market data only during Phase 1.
- Do not request or use OKX private API keys.
- Do not add exchange account authentication during Phase 1.
- Never add withdrawal functionality or request or enable withdrawal
  permissions.

## Trading Risk

- No real orders or live execution in Phase 1.
- No martingale, doubling down, or automated loss chasing.
- Every future strategy must be backtested before consideration.
- Backtests must account for fees, slippage, data quality, and look-ahead bias.
- Clearly label simulated results as simulations.
- Passing a backtest does not authorize paper trading or live trading.
- The risk manager has final veto over every future simulated, paper, or live
  trading action.

## Engineering

- Add tests for meaningful behavior.
- Keep data collection, strategy research, and execution concerns separate.
- Use reproducible configuration and structured logs.
- Pin important dependencies and document setup changes.
- Prefer official documentation and well-maintained dependencies.

## Change Control

Any future move toward paper trading or authenticated exchange access requires
an explicit phase change and human security review. Live trading remains
outside the current Phase 1 scope.
