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

## Sprint 5a — the paper fleet (plan row R5a)

The shortlist (`docs/research/paper_fleet_shortlist_v1c.json`) runs forward on
live PUBLIC OKX data as 19 local paper accounts: the 10 shortlisted
configurations, the jointly sized BTC+ETH × S1/S2/S4 portfolio (15 % vol
target, 7.5/15 % ladder) as one account, and the 8 controls (always long with
the policy sizing, plain buy-and-hold; BTC and ETH, 4H and 6H). Simulation
only: virtual fills, no keys, no demo account, no database, no order path.
Operator steps: `docs/runbooks/PAPER_FLEET.md` (plan row G6).

| Module | Purpose |
|---|---|
| `research/paper_fleet/config.py` | The manifest: one account per shortlist row and control, the portfolio's six full-size sleeves from `ensemble_v1c_results.json`, the walk-forward and holdout expectations of each account; fails loudly when the two files disagree. Fingerprints of the shared rules and of every account's rules are stored with the fleet: a changed rule refuses to resume, an account added to the shortlist joins from that moment, a removed one is retired (journal kept). |
| `research/paper_fleet/data.py` | Public data: OKX 1H candles (`market/candles`, `market/history-candles`) and the swaps' funding rate and open interest, through the GET-only allowlisted `OKXPublicRest`; the fleet's own small lake (seeded once by copying the research lake, read only); 4H/6H bars rebuilt from confirmed 1H candles on the UTC clock, complete bars only. |
| `research/paper_fleet/signals.py` | One decision per closed bar through the reviewed `Strategy` contract (`ResearchStrategyAdapter`: the candidate, its S5 filter, the S0 filter with the FOMC calendar), plus the research overlays: the regime-v2 entries-only gate, the policy sizing fraction, the exit bracket. `frame_decisions` is the same in one vectorized pass (portfolio warm-up). |
| `research/paper_fleet/engine.py` | The bar-by-bar engine: a transcription of `research.engine.run_vectorized` for one column with JSON state between bars (stops on the bar's low with gap fills, targets, time and trailing stops, sizing × ladder, reduce-only rebalancing), plus the walk-forward's 180-day test windows: every sleeve restarts flat at each window, closing at the last close with costs (the research's `end_of_data` exit). Plain buy-and-hold never restarts, as in the research. A missing decision keeps the stops working and makes no entry. |
| `research/paper_fleet/regime.py` | The regime model forward with the walk-forward geometry: fitted on the 540 days ending 7 days before each 180-day period (when the sleeves restart), filtered forward from its train start, stored so a restart reuses it; a failed fit blocks entries. |
| `research/paper_fleet/portfolio.py` | The portfolio account: six full-size sleeves compounded into UTC-day returns, trailing inverse-vol weights and the 15 % vol target over 120 days of warm-up plus the forward days, the 7.5/15 % ladder from the forward start (`combine_sized` semantics). |
| `research/paper_fleet/runner.py`, `store.py` | The cycle (refresh, every new bar of every series in one time order, portfolio days, journals, atomic state), the file lock, the journals (append-only JSONL per account, sequence-numbered so a crash never duplicates a record). |
| `research/paper_fleet/report.py` | The weekly ranking report: controls first, forward metrics per account, and the bands fixed before the first forward bar (return ± 2σ of the walk-forward volatility, Sharpe ± 2 standard errors from 90 days, drawdown against the walk-forward worst with an alarm at 1.5×, a Poisson band on trades, the holdout pace); verdicts from 30 days. |
| `research/paper_fleet/replay.py`, `scripts/run_paper_fleet.py` | The offline dry run (recorded lake data or a synthetic market replayed with a simulated clock, invariants checked) and the CLI: `--loop`, `--once`, `--dry-run`, `--report`, `--status`. |
| `research/paper_fleet/digest.py` | Read-only facts for the daily ops digest (plan row R6, `docs/runbooks/OPS_DIGEST.md`): the saved state through the same `status_from_state` view as `--status` (last cycle, stale prices, day count and "too early" before day 30, positions, best and worst account, the holdout-confirmed sleeve next to its always-long control, allocator v2), the weekly report's own verdicts and drawdown alarms (`build_report_data`), and the newest weekly report. No lock, no write, no network. |

Why not `app/paper`: the reviewed Phase 4 engine trades 1-minute candles only,
sizes by risk per trade, prices fills from a live order book and keeps its
ledger in the database. None of the research sizing (vol target, crash
filter, ladder, reduce-only rebalancing), the regime gate or the brackets
exists there, so its forward numbers could not be compared with the research's
expectations. `app/paper` is unchanged; the fleet reuses the research code and
the `Strategy` contract instead.

Parity is tested, not assumed: the engine against `run_vectorized` on long
random paths (every exit path, sizing, ladder, rebalancing, brackets), and with
the 180-day restarts against the research run separately on every window; the
contract decisions against `build_frames` + the gated walk-forward's gate +
`fraction_series`; a gated, policy-sized sleeve end to end against
`simulate_sizing`; the portfolio booking against `combine_sized`; restarts and
crashes against an uninterrupted run (byte-identical journals).

Known differences from the research (stated in every report): the S5 filter
reads OKX's own swap funding and open interest (timely) instead of Binance's
files (a day late); an account added to the fleet later has its own 180-day
windows, so a regime refit can recompute the gate while it holds a position and
close it (the research started every window flat at a refit); 4H bars are
rebuilt from 1H candles (identical to OKX's stored 4H bars on 99.97 % of the
history); the portfolio's
estimates start from 120 days of simulated sleeve history and moving money
between its sleeves is free, as in the research.

## Sprint 5b — portfolio allocator v2 (plan row R5b)

Master plan Sprint 5 item 2: the portfolio vol target, a correlation cap, the
portfolio drawdown ladder, a weekly loss limit and cooldowns, as an optional
allocator configuration in `research/` and in the paper fleet. Not in
`app/risk`: the demo and live risk manager stays the reviewed core until a
separately approved review. Report: `docs/research/ALLOCATOR_V2_REPORT.md`
(numbers in `allocator_v2_results.json`).

| Module | Purpose |
|---|---|
| `research/allocator.py` | Allocator v2. The v1 sizing of `combine_sized` (trailing inverse-vol weights, one portfolio vol target measured on the v1 weights, one drawdown ladder on v2's own equity) times brakes in [0, 1]: the correlation cap (sleeves on one coin, or coins whose trailing 60-day correlation is ≥ 0.70 — unknown counts as correlated — are one bet; the equity invested in one bet, from the sleeves long at the previous close, is capped at 50 %; sleeves entering during a day count from the next close), the weekly loss limit (−5 % over 7 days → cash) and its 7-day cooldown, after which the loss window restarts. "Only lowers" is relative to v2's own sizing: its ladder can leave v2 larger than v1 on days only v1's ladder halved. `step_day` sizes one day from the previous close and advances a JSON state that also carries the v1 rules on the same sleeves as a paired reference; `allocate_v2` runs it over a daily history (with a warm-up `start`); `brake_stats` counts what each brake did and estimates the re-weighting cost both allocators leave out. `DEFAULT_ALLOCATOR_V2` was fixed before the first run. |
| `research/allocator_study.py`, `scripts/run_allocator_v2.py` | The study: the six sleeves of the v1c jointly sized portfolio replayed at full size in the same walk-forward windows (with the long/flat state after every bar); a reproduction check that stops unless v1 gives Sprint 2c's stored numbers; v2 and two ablations (each new brake alone, diagnostics only); the v1c portfolio gates unchanged; the 12-month holdout only after a walk-forward pass, with the estimators warmed up on the walk-forward history and v1 as the paired reference; the report and results JSON (the paper fleet reads the v2 account's expectations from it, checking that they describe its sleeves and brakes). |
| `research/paper_fleet/` (changes) | `PortfolioSpec.allocator` (None = v1: rules and fingerprint unchanged); a second portfolio account `pf-s1s2s4-btceth-vt15-alloc2` with its own six sleeves; the book also keeps each sleeve's close position and one close per coin per day; the runner holds several portfolio accounts (state version 2, an R5a state is migrated when opened, also one whose portfolio was retired); shared sleeves decide once per bar; a portfolio account's sleeves continue from their warm-up (no bar skipped or doubled); a fleet is created and an account joins only once its series are ready (the bar that closed last is complete, no earlier bar still waits for a late candle); a journal of an interrupted start is set aside; the weekly report's allocator section; dry-run invariants that v2's brakes only lower its own sizing. |

Result (walk-forward 2021-06 → 2025-10, after fees and slippage): v2 +10.5 %/yr,
max DD 12.3 %, Sharpe 0.86, Calmar 0.85; v1 on the same sleeves +10.9 %, 13.2 %,
0.82, 0.83. Both pass the v1c gates. Almost all of the difference is the
correlation cap, which trimmed the book on 87 days (5.5 %: 5 in 2021, none in 2022,
22, 36 and 24 in 2023–2025). It cost most in the 2024 rally (+34.7 % → +21.9 %) and
helped in 2025 (+0.1 % → +5.8 %). Because it is checked at the previous close, a bet
stood above 50 % at a day's close on 29 days (at most 87 %) until the next day's cap.
The loss limit tripped once, on 2025-10-13.
The untouched holdout (364 full days, 2025-10-21 → 2026-10-19, BTC −26 %, ETH −39 %)
contradicts both: v2 −9.2 %, v1 −15.0 %, pooled sleeve profit factor 0.59. The jointly sized
portfolio's walk-forward pass therefore did not survive its holdout, like three of
Sprint 2c's four passes. The study's report says why the portfolio gates were too
easy (no robustness gate at portfolio level, PF pooled from sleeves that did not
pass on their own, OOS-picked timeframes, a bull-dominated span) and recommends a
stricter, pre-registered portfolio rule for the next study.

Parity is tested, not assumed: with its brakes off v2 equals `combine_sized` to
floating-point rounding (and its paired reference always does); the fleet's
day-by-day booking equals the research driver (including days on which a sleeve
has no bar); a fleet started with both portfolio accounts has v2's in-journal
reference equal to the v1 account on every day; a fleet written by the real R5a
code (`tests/fixtures/paper_fleet_r5a`, two accounts) resumes with its records
untouched and continues byte for byte as an uninterrupted run, while the
allocator account joins from its own start; an account that joins on lagging data
ends with the same forward record as one that joined on complete data.
