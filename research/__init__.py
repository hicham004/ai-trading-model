"""Research lab (Sprint 2): sweeps, walk-forward validation, strategy candidates.

Sandbox rules
-------------
- Reads PUBLIC data from the Parquet lake (``app/datalake``) only.
- Imports the strategy *contract* (``app.strategy.base``) and the reviewed
  event-driven simulator (``app.backtest``) for execution-faithful checks; it
  never imports ``app.execution``, ``app.risk`` internals beyond the public
  ``RiskManager`` used by the simulator, ``app.exchange`` or ``app.shadow``
  (``tests/test_research_boundaries.py`` enforces this).
- Nothing here is registered in the live strategy registry or reachable from
  the demo runtime. Promoting a candidate is a separate, reviewed PR.
- Every number produced here is a SIMULATION. It never authorizes paper, demo
  or live trading (``PROJECT_RULES.md``).

Engine: a dependency-free vectorized long-only backtester (``research.engine``)
with the same execution conventions as ``app/backtest/simulator.py``
(next-bar-open execution, intrabar stop with conservative gap handling, fees
and slippage per side). ``vectorbt`` 1.0.0 was evaluated (resolves against the
project's pandas 2.2.3 pin) but its import fails with plotly 7 and it adds
~115 packages to the audited lockfile; a thin adapter can be added later if
wanted — the harness API is the same ``from_signals`` idea.
"""
