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

### Result (2026-10-20)

32 runs (8 candidates × BTC/ETH × 4H/6H; `hold` is a passive reference):
**0 of 28 candidate configurations pass** the Sprint 2b gates with the
walk-forward-selected sizing, and 0 of 28 with the fixed policy sizing
(`docs/research/ENSEMBLE_V1B_REPORT.md`). Sizing did what it was built for on
the risk side — the median worst drawdown of the lead rules fell from 54 %
(all-in) to 19 % — but return fell in step (median CAGR 11.4 % → 4.9 %,
Calmar 0.28 → 0.31), so the risk-adjusted gates (Sharpe > 0.7, Calmar > 0.5)
are missed by 27 of 28 and the 4-of-5 positive-years gate by 25 of 28 (2022
is negative for almost every long-only rule). Best single configuration: S4
vol-compression breakout on ETH 6H (`vt25/60 ladder`, `tp2`): CAGR 7.7 %,
max DD 13.2 %, Sharpe 0.83, Calmar 0.58, 66 trades — it misses only the
yearly gate; holding ETH over the same span made 17.6 %/yr with an 80 %
drawdown (Calmar 0.22). The drawdown ladder is roughly neutral (median return
−6 points, drawdown −4 points); trailing stops cut the give-back share from
about 50 % to 25 % but lower the profit factor by 0.3 because these rules
already have exits; 6H beat 4H in 8 of 16 pairs; the S5 positioning filter
with full funding history changes little (slightly better on ETH, worse for
S1 on BTC 4H). Portfolios of the S2/S4 (and S1) sleeves across BTC+ETH reach
Calmar 0.28 at an 11 % drawdown (diversification ratio 1.4–1.9) — no gate.
The holdout stayed untouched. The report proposes Sprint 2c and lists the
owner decisions it cannot take.

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

## Sprint 2c — regime gates, portfolio sizing and turnover

Sprint 2b ended with 0 of 28 passing: sizing made the rules survivable but
added no edge. Sprint 2c (master plan, planner decisions 1–6) keeps every
entry rule untouched and changes only *when* a rule may trade and *how* the
sleeves are sized. Report: `docs/research/ENSEMBLE_V1C_REPORT.md`
(+ `ensemble_v1c_results.json`, `paper_fleet_shortlist_v1c.json`), written
by `scripts/run_research_v1c.py`. Simulation only, as before.

| Module | Purpose |
|---|---|
| `research/hmm.py` | Diagonal-Gaussian hidden Markov model in numpy (EM + a forward-only filter). Written in-repo instead of `hmmlearn` so the lockfile stays audited and, more importantly, so the regime probability of a bar is the *filtered* posterior that uses only bars up to and including it (`hmmlearn` exposes smoothed posteriors, which look into the future). Tested: EM never decreases the log-likelihood, a planted two-regime series is recovered, appending future bars never changes earlier filtered rows. |
| `research/regime_v2.py` | Regime v2: 3 states on (log return, log 7-day realized vol), fitted on each walk-forward TRAIN slice, applied forward through the test slice; states ordered by mean return (bear / chop / bull). `mode="gate"` blocks NEW entries while `P(bear) >= 0.5`; `mode="scale"` sizes them at a quarter; exits, stops and brackets never see the regime. |
| `research/events.py` + `research/strategies/s0_filters.py` | Scheduled-event windows for the S0 no-trade filter (built-in FOMC decision days 2020–2026, ±6 h around the release; a JSON calendar can be supplied). The dates were written from memory and must be verified by the owner; they block ~6–7 % of bars together with the existing vol-spike / spread / gap rules. |
| `research/strategies/turnover.py`, `s1_tsmom.py` (`S1h`) | Lower-turnover variants: `S1w` weekly clock (state sampled once a week), `S1d`/`S2d`/`S4d` 1D entry clock (entries only at the daily close, exits on every bar), `S1h` hysteresis bands on the vol-scaled momentum. Same entry rules, different clocks. |
| `research/strategies/s5_positioning.py` (`+S5s`) | S5 re-test with a 7–14-day funding z-window and an open-interest change window (1 or 3 days) on the full Binance history. |
| `research/gated_walkforward.py` | Walk-forward with the per-window regime fit, entries-only gating of the desired matrix, Sprint 2b's staged rule selection on the gated train slice, the FIXED policy sizing (`vt10/30 crash15/90dh ladder`, planner decision 2) on the test slice, an optional small train-selected sizing comparison, and fixed replays (robustness, full-size sleeve, slippage stress) that reuse the per-window regimes. `mode="none"` reproduces Sprint 2b's policy walk-forward bit for bit (tested). |
| `research/portfolio.py` (`combine_sized`) | Portfolio-level sizing: full-size sleeves, trailing inverse-vol weights (past days only), one portfolio vol target applied to the next day, one 15 % drawdown ladder (half at 7.5 %, flat at 15 %). |
| `research/report_v1c.py` | Gates with the yearly gate v2 (planner decision 1: >= 75 % of trailing 12-month windows sampled every 30 days positive AND no calendar year with >= 60 days of data worse than −10 %), holdout verdicts (confirmed = positive return, PF > 1, >= 10 trades), the ranked shortlist with the decision-6 controls written to a machine-readable file labelled "forward evidence only; nothing approved", the regime / turnover / S5 studies and the plain-English summary. |

### Running

```bash
python scripts/run_research_v1c.py --evaluate-holdout --workers 4     # BTC/ETH x 4H/6H x 13 candidates x regime modes (~22 min on 4 cores)
python scripts/run_research_v1c.py --quick --strategies S1 S2 --instruments BTC-USDT --timeframes 4H   # smoke run
python scripts/run_research_v1c.py --render-from-json docs/research/ensemble_v1c_results.json          # re-render the report without re-running
```

Defaults: costs 0.10 % + 0.05 % per side; train 540 d → purge 7 d → test
180 d; rule selection by Sharpe with >= 20 train trades among bracket-free
rules, then the bracket among siblings; brackets `none tp2 trail1 time30`
(none for the S5 variants); regime modes `none gate scale` for S1/S2/S4,
`none gate` for the variants, `none` for `hold`; policy sizing as in 2b;
S0 filter with the FOMC calendar on; positioning source `binance`; holdout
evaluated for configurations that pass walk-forward AND for the passive
controls. One process per instrument x timeframe (`--workers`).

### Result (2026-10-20)

112 runs (108 candidate configurations + 4 `hold` controls). **4 of 108 pass
the Sprint 2c walk-forward gates at the fixed policy sizing; the untouched
12-month holdout (2025-10-20 → 2026-10-20) confirms 1 and contradicts 3.**

- Confirmed: `S1+S5` on BTC-USDT 6H, no regime gate — OOS CAGR +5.3 %, max DD
  8.8 %, Sharpe 0.86, PF 1.68, Calmar 0.60, 139 trades, 78 % of rolling
  12-month windows positive; holdout +2.3 % with a 3.9 % drawdown (PF 1.48, 32
  trades). The deflated Sharpe is 0.23.
- Contradicted: the gated `S2` family on BTC-USDT 4H (`S2`, `S2+S5`, `S2+S5s`)
  — walk-forward Calmar 0.69–0.80 but holdout −4.9 % / −3.0 % / −4.4 % with PF
  0.28–0.51 over ~20 trades: a walk-forward pass that the holdout rejects is
  selection luck among 108 configurations, not edge.
- Controls: `hold` + policy sizing made +1.8 % to +3.2 %/yr at 7–10 % drawdown
  (Calmar 0.20–0.45) and lost 2.6–4.3 % on the holdout; plain buy-and-hold made
  +11 % to +31 %/yr with 77–81 % drawdowns.
- Regime v2 as an entry gate (48 rules with/without): median Calmar 0.31 →
  0.18 (gate) / 0.27 (quarter-size), median 2022 return −2.4 % → −1.9 %, median
  max DD 9.1 % → 9.0 %; the gate had the higher Calmar in 27 of 48 rules and the
  threshold (0.35 / 0.5 / 0.65) barely matters. The bear state also contains the
  recoveries these rules need: the gate is not where the missing edge is.
- Lower-turnover clocks: median fee drag 1.1 % → 0.7 %/yr, median Calmar 0.29 →
  0.22 (variant better in 20 of 40 pairs) — fees were not the problem either.
- S5 with the 7–14-day funding window: small, mixed changes versus the 30-day
  window (table in the report).
- Portfolio-level sizing: the jointly sized BTC+ETH x S1/S2/S4 portfolio with a
  15 % vol target and the 7.5/15 % ladder made +10.9 %/yr at a 13.2 % drawdown
  (Sharpe 0.82, Calmar 0.83, 83 % of rolling 12-month windows positive) and is
  the only construction that clears every gate with margin — but it is built
  from out-of-sample sleeves with a mild timeframe selection and has no holdout
  of its own, so it is a hypothesis for the paper fleet, not a result.
- Acceptance clause: fewer than two configurations survived both tests, so the
  report states, with numbers, that the edge of long-only timing on BTC/ETH spot
  is real but thin and fragile; the Phase 7/8 product stays "risk-managed
  exposure + news brake", the confirmed sleeve and the jointly sized portfolio
  go to the paper fleet next to the controls, and the Phase 9 long/short design
  study becomes the research priority. Owner decisions are listed in the report.

### Reading the v1c report honestly

- The walk-forward gates, the regime modes, the gate threshold, the clocks and
  the policy sizing were all fixed before the run; the holdout is the arbiter and
  it rejected three of the four passers. Do not re-tune any of them on these
  results — a sweep is a new, pre-registered sprint.
- The rolling-12-month gate uses overlapping windows (a smoothed statistic),
  which is why it is paired with the calendar-year floor.
- Deflated Sharpe counts the rule trials of the last train window; the regime
  modes and clocks multiply the number of things tried and are the reason the
  DSRs stay low.
- The FOMC calendar is unverified data (mechanism tested, dates not).
