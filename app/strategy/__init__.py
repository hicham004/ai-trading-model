"""Phase 2 strategy engine (research only).

A *strategy* looks at market candles and emits *signals* (LONG / FLAT / HOLD)
with a confidence score and a required stop-loss. Signals are only
recommendations: the risk manager (``app.risk``) has final veto, and the paper
broker (``app.broker``) produces simulated fills only.

Safety (see CLAUDE.md / PROJECT_RULES.md):
- Strategies never place real or live orders.
- Signals never authorise live trading on their own.
- No strategy here claims or guarantees profitability.
"""
