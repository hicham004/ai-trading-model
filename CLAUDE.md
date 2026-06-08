# AI Agent Rules

These rules apply to Claude Code, Codex, and every other AI agent working in
this repository.

## Allowed Work

- AI agents may write code, tests, documentation, and development scripts.
- AI agents may use public OKX market-data endpoints for research.
- AI agents may build local databases, backtesting foundations, logs, and
  dashboards.

## Absolute Restrictions

- AI agents must not place real trades.
- Do not create or enable live order execution in Phase 1.
- Use public market data only in Phase 1.
- Do not request or use OKX private API keys.
- Do not request, store, print, log, or commit API keys or other secrets.
- Do not put API keys or credentials in source code.
- Never implement withdrawals or request or enable withdrawal permissions.
- Do not implement martingale strategies.
- Do not implement doubling down or loss-chasing position sizing.
- Do not claim that backtest results guarantee future performance.
- Every future strategy must be backtested before it can be considered.
- Backtest results never authorize paper or live execution.
- The risk manager has final veto over every future simulated, paper, or live
  trading action.

## Phase 1 Boundary

Phase 1 is limited to:

- Public OKX data collection
- Local database foundations
- Backtesting skeleton
- Structured logs
- Local research dashboard

Stop and ask for explicit human review before expanding beyond this boundary.
