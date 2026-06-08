# Project Rules

## Purpose

This repository is for crypto-market research and software development. It is
not a live trading system.

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
an explicit phase change and human security review. Live trading is outside the
current project scope.
