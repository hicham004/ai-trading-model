# Research lab (Sprint 2) — sweeps, walk-forward, ensemble v1 candidates

Status: research tooling. Every output is a SIMULATION on historical public
data. Nothing in `research/` is registered in the live strategy registry,
reachable from the paper/demo runtimes, or able to touch an order
(`tests/test_research_boundaries.py` enforces the import boundary). Promoting
a candidate to the paper fleet or demo is a separate, reviewed PR with owner
approval (`PROJECT_RULES.md`).

## What is here

| Module | Purpose |
|---|---|
| `research/engine.py` | Vectorized long-only backtester for sweeps. Same conventions as `app/backtest/simulator.py`: decision at bar close → execution at next open; intrabar stop checked first with conservative gap fills; fees + slippage per side; stop is a price fixed at decision time; entries whose stop is not below the open are skipped. Parity with the reviewed simulator is tested to 1e-9. |
| `research/features.py` | Backward-looking features (returns, realized vol, ATR, SMA/EMA, Donchian, RSI, z-score, Bollinger, percentile rank, momentum, gaps). |
| `research/strategies/` | Candidates: `baseline` (SMA 10/30 reference), `S1` TSMOM multi-lookback vote with vol-scaled strength, `S2` Donchian breakout + volume/ATR filters, `S3` range mean-reversion (RSI/z-score, range regime only, time stop), `S4` Bollinger-squeeze breakout, `S5` positioning filter (funding z-score / OI surge) wrapped around S1 and S2, `S0` no-trade filter applied to all (vol spike, extreme bar range, data gaps, event windows). |
| `research/sweep.py` | Cartesian grids, frame building, slice simulation, metrics table, heatmaps, ±30 % robustness. |
| `research/walkforward.py` | Rolling train → purge → test windows; selection on train only; stitched out-of-sample curve; yearly breakdown. |
| `research/metrics.py` | Sharpe, Sortino, CAGR, max DD, Calmar, PF, win rate, exposure, turnover, fee share; probabilistic and deflated Sharpe (Bailey & López de Prado). |
| `research/montecarlo.py` | Trade-order bootstrap, slippage stress. |
| `research/regime.py` | Regime v1 labels (vol tercile × trend state) and per-regime OOS metrics. |
| `research/calibration.py` | Confidence = historical hit rate of the strength bucket (training data only). |
| `research/strategies/adapters.py` | Wraps a candidate into the reviewed `Strategy` contract (LONG with stop price / FLAT) for the event-driven check and, later, the paper fleet. |
| `research/report.py`, `scripts/run_research.py` | The honest report and the runner. |

## Running

```bash
python scripts/run_research.py --instruments BTC-USDT ETH-USDT --timeframes 1H 4H 1D --evaluate-holdout
python scripts/run_research.py --strategies S1 S2 --timeframes 4H --train-days 720 --test-days 180 --purge-days 14
```

Defaults: fee 0.10 % + slippage 0.05 % per side, 100 % of equity per entry
(gross edge; production sizing is smaller), train 540 d → purge 7 d → test
180 d rolling, selection by Sharpe among grid points with ≥ 20 train trades,
holdout = last 12 months evaluated once and only for candidates that pass.
Outputs: `docs/research/ENSEMBLE_V1_REPORT.md` and
`docs/research/ensemble_v1_results.json`.

Acceptance (master plan Sprint 2): OOS profit factor > 1.2 after costs,
positive in ≥ 3 of 4 yearly OOS windows, max drawdown < 20 %, ≥ 50 % of ±30 %
grid neighbours profitable, ≥ 30 OOS trades. Failing is an expected and
useful result.

## Why not vectorbt

`vectorbt` 1.0.0 resolves against the project's `pandas==2.2.3` pin, but its
import currently fails with `plotly` 7 and it adds ~115 packages (numba,
llvmlite, matplotlib, scikit-learn, ipywidgets, …) to the audited lockfile.
The sweep harness therefore ships a dependency-free vectorized engine with
the same `from_signals` idea; a vectorbt adapter can be added behind an
optional extra if the owner wants it.

## Reading the report honestly

- Walk-forward numbers are out-of-sample by construction, but the *family*
  of strategies and the grids were chosen by people who have seen the
  history; the deflated Sharpe and the untouched holdout are the guards.
- The 12-month holdout is one draw. Treat a holdout result as confirmation
  or contradiction, not as a new estimate.
- S5 only has positioning data for the months OKX serves (funding since
  2026-07, open interest since 2026-08); in earlier bars the filter passes.
- Derivatives, 1m/5m bars, multi-asset portfolios and sizing (vol targeting,
  drawdown ladder) are Sprint 5 topics, not covered here.
