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
- 1m/5m bars are not covered. Sizing, portfolios and long-history positioning
  data are Sprint 2b (next section).

## Sprint 2b — sizing, risk, timeframe and positioning data

Sprint 2 ended with 0 of 42 candidate runs passing because drawdown at all-in
sizing was the binding constraint. Sprint 2b keeps the entry rules untouched
and engineers the risk side (master plan Sprint 2b, items 1–10). Report:
`docs/research/ENSEMBLE_V1B_REPORT.md` (+ `ensemble_v1b_results.json`),
written by `scripts/run_research_v1b.py`. Simulation only, as before.

| Module | Purpose |
|---|---|
| `research/sizing.py` | Vol-targeted entry fraction `clamp(target_vol / realized_vol, 0, 1)`; crash-state de-risking (half or zero exposure while the close is more than X % below its rolling N-day peak); drawdown ladder on the strategy's own equity (−5 % → half, −10 % → flat; released by a new equity high or, for flat, after a cooling-off that resets the reference peak); the 390-variant sizing grid. Every series uses past bars only (tested). |
| `research/bracket.py` | Mechanical exit brackets layered on a candidate: take-profit at 2R/3R, trailing stop after 1R (1R or 2R behind the running high, effective from the next bar), 30-day time stop; `none` keeps the strategy's own exits. |
| `research/engine.py` | Extended: per-bar/per-combo size matrices, reduce-only mid-trade de-risking (a position is sold down when the decision-bar fraction drops by more than the threshold or the ladder steps; it is never added to), ladder inside the loop, trailing stop, per-column time stops, MFE/MAE per trade. With every overlay off it is bit-for-bit the Sprint 2 engine (parity test unchanged). |
| `research/resample.py` | 1H → 6H bars on the UTC grid (complete bars only, prefix-stable). The runner resamples when the lake has no stored 6H series. |
| `research/sized_walkforward.py` | Staged walk-forward: per window the entry rule is selected among bracket-free rules on the train slice at full size by Sharpe, then the exit bracket among that rule's siblings, then the sizing variant by Calmar among variants with train max drawdown ≤ 10 % (half the gate — a 540-day train window understates a multi-year stitched drawdown); the test slice is simulated once. A fixed a-priori "policy" sizing (10 % vol target, 15 %/90-day crash filter, ladder) is run next to it so sizing-selection noise is visible. Fixed replays for robustness, the sizing sweep, ladder/bracket effects and slippage stress. |
| `research/portfolio.py` | Sleeves (one configuration's OOS bar returns, possibly on different bar clocks) compounded into daily returns; bucketed or daily-rebalanced combination; equal-capital / equal-risk weights; correlation and diversification ratio; portfolio-level ladder. |
| `research/report_v1b.py` | Risk-adjusted gates, ranked paper-fleet shortlist, plain-English executive summary, Markdown report. |
| `research/strategies/hold.py` | `hold`: always long, no stop — a passive reference that isolates what the sizing overlays alone do; reported, never shortlisted. |
| `app/datalake/binance_public.py` | Long-history positioning features (Binance public funding since 2019, open interest since 2020-09 / 2021-12) for S5; see `docs/DATA_LAKE.md`. |

Gates (master plan Sprint 2b item 8, applied to the stitched out-of-sample
curve at the proposed sizing): profit factor > 1.2 after costs; max drawdown
< 20 %; Sharpe > 0.7; Calmar > 0.5; positive in ≥ 4 of 5 yearly OOS windows;
≥ 30 OOS trades; ≥ 50 % of ±30 % parameter neighbours profitable (replayed
with the proposed sizing); deflated Sharpe reported. Acceptance: ≥ 2
configurations pass; otherwise the report proposes Sprint 2c. Nothing goes to
demo either way.

### Running

```bash
python scripts/collect_binance_positioning.py                  # once; resumable (funding ~1 min, open interest ~1.5 h)
python scripts/run_research_v1b.py --evaluate-holdout           # BTC/ETH × 4H/6H × hold baseline S1 S2 S3 S4 S1+S5 S2+S5 (~35 min)
python scripts/run_research_v1b.py --quick --strategies S2 --instruments BTC-USDT --timeframes 4H   # smoke run
```

Defaults: costs 0.10 % + 0.05 % per side; train 540 d → purge 7 d → test
180 d; entry-rule selection by Sharpe with ≥ 20 train trades among
bracket-free rules, then the bracket among siblings; sizing selection by
Calmar with train max DD ≤ 10 % (`--sizing-dd-cap`) and ≥ 10 train trades;
policy sizing `vt10/30 crash15/90dh ladder` (`--policy-*` flags);
reduce-only threshold 0.25 (`--rebalance-threshold -1` = entry-sized only);
ladder re-arm after 30 days. Sizing grid: vol targets {10, 15, 20, 25} % ×
lookbacks {20, 30, 60} bars + fixed {25, 50, 100} % (100 % is the Sprint 2
reference), × {no crash filter, crash {10, 15, 20} % × {90, 180} days × {half,
zero}}, × {ladder off, on} = 390 variants. Brackets: `none tp2 tp3 trail1
trail2 trail1_tp3 time30`. Positioning source: `binance` (`--positioning-source
okx|none`).

### Reading the v1b report honestly

- The summary table re-selects the rule and the sizing every window; the
  sizing study, the robustness and the ladder/bracket comparisons replay ONE
  fixed choice over the same test windows, so their numbers differ from the
  summary by construction.
- The sizing stage picks among 390 near-equivalent variants, so its choice
  is noisy from window to window; compare the summary with the fixed-policy
  table before reading anything into a particular sizing label.
- The sizing stage selects on the TRAIN drawdown; out-of-sample drawdowns are
  regularly larger. The gate is applied to the stitched OOS curve.
- Brackets and sizing variants multiply the number of things tried; the
  deflated Sharpe uses all of them, which is why it is low.
- The `hold` reference shows what vol targeting + crash filter + ladder do to
  plain buy-and-hold; a timing rule has to beat it to be worth running.
- Portfolios use, per (family, instrument), the timeframe with the higher OOS
  Calmar — a mild selection on OOS data; treat portfolio numbers as slightly
  optimistic.
