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
| `research/events.py` + `research/strategies/s0_filters.py` | Scheduled-event windows for the S0 no-trade filter (built-in FOMC decision days 2020–2027, ±6 h around 18:00 UTC on the statement day, which holds the 2:00 p.m. New York release in winter and in daylight time; a JSON calendar can be supplied). Written from memory in Sprint 2c and checked against the Federal Reserve's published calendar in plan row R7 (2026-10-22): all 57 dates of 2020–2026 were right, the 2027 dates were added, and `tests/test_fomc_calendar.py` compares the calendar with the Fed's, recorded in `tests/fixtures/fomc_calendar/`. Together with the vol-spike / spread / gap rules they block ~6–7 % of bars. |
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
- The FOMC calendar was written from memory; plan row R7 (2026-10-22) found all
  57 dates of 2020–2026 right against the Federal Reserve's published calendar,
  so no Sprint 2c number depends on a wrong date. The Fed calls each date
  tentative until the meeting before it confirms it; the built-in calendar ends
  2027-12-08 (refreshing it: `tests/fixtures/fomc_calendar/README.md`).

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

## Phase 9 design study — long and short through perpetual swaps (plan row R9)

The owner's go of 2026-10-21 for a paper-only study: would the trend rules earn
their keep if they could also be short — through BTC- and ETH-USDT perpetual
swaps with collateral at least equal to the position (no leverage) — after fees,
slippage and funding? Phase 9 itself, trading shorts and derivatives access stay
unauthorized. Report: `docs/research/LONG_SHORT_STUDY_REPORT.md` (numbers in
`docs/research/long_short_results.json`); the design study with the extra safety
rules and the review path: `docs/PHASE9_DESIGN_STUDY.md`. Simulation only.

| Module | Purpose |
|---|---|
| `research/longshort.py` | `run_long_short`: `run_vectorized` with a second, short side. With no shorts and no funding it is the long-only engine operation for operation (parity-tested bit for bit on every overlay). A short sells at the next open (slippage against it), its stop sits `stop_distance` ABOVE the decision close and fills on the bar's high (a gap fills at the worse open), targets below, a trailing stop that follows the running low and only moves down, reduce-only buy-backs, time stops, end of data; the long side wins a tie, so it is the long-only rule unchanged; one position per column. Funding: per-bar settled rates, charged at the bar's close on the open position (longs pay positive rates, shorts receive them), per leg. A 1x isolated liquidation tripwire (`entry x 2 / (1 + mmr)`, OKX tier-1 mmr 0.4 %) and a leverage trace. Every short exit path is tested against the long engine on the price path reflected around the entry. |
| `research/strategies/shorts.py` | The mirror images of S1, S2, S4 and the S5 filter with the same parameters (S1 and S2 are tested to equal the reviewed long rules on the reflected market); `build_ls_frames` keeps the long frames of Sprint 2c unchanged and lets a short START only while the long rule is flat and the S0 filter (and the S5 mirror) allow an entry. |
| `research/longshort_data.py` | Binance's public funding history as the proxy for OKX's swaps (OKX keeps months; the two are compared where both exist), settlement-to-bar assignment (a settlement at `s` belongs to the bar with `open < s <= next open`; time-unit safe), OKX's public BTC-/ETH-USDT-SWAP 1H candles collected through the GET-only `OKXPublicRest` into `data/lake/candles/<SWAP>/1H` (resumable), the perp aligned onto spot bars, spot-perp basis. |
| `research/longshort_study.py`, `scripts/run_long_short_study.py` | The pre-registered study (`PREREGISTRATION`, hashed with the configuration into the results): S1, S2, S4, S1+S5 x BTC/ETH x 4H/6H x two designs — hybrid (long on spot 0.10 %, short on the swap 0.05 % + funding) and all-perp (both on the swap) — under Sprint 2c's walk-forward, policy sizing (both sides) and gates. The long-only path is run first and must reproduce Sprint 2c's stored numbers or the study stops. The evidence rule: the v1c gates, a profitable short leg on its own and a Calmar above Sprint 2c's long-only result on the walk-forward, then a confirming holdout — opened only for configurations meeting the walk-forward part (`holdout_step`). Diagnostics: leg attribution, funding x0/x2 and slippage x2/x3 replays, the swap legs replayed on the perp's own candles, the shorts without the crash filter (post-hoc, recorded as such), the families' default parameters over 2020-01-01 to the holdout start, funding by year, the largest rises against a short, basis. |
| `research/report_longshort.py` | The report; every plain-English sentence is computed from the run. |

### Running

```bash
python scripts/run_long_short_study.py --collect-perp-candles            # once: OKX public swap candles (resumable, ~10 min)
python scripts/run_long_short_study.py --evaluate-holdout --workers 4    # the study (~9 min on 4 cores)
python scripts/run_long_short_study.py --quick --families S1 --instruments BTC-USDT --timeframes 4H --report - --json -   # smoke run
python scripts/run_long_short_study.py --render-from-json docs/research/long_short_results.json                         # re-render
```

The holdout is opened only by the full pre-registered study (never with `--quick` or a subset)
and every opening is appended to `docs/research/long_short_holdout_ledger.json`, which the report
shows.

### Result (2026-10-22)

32 configurations; all 16 long-only reproductions matched Sprint 2c. **4 of 32 met the
walk-forward part of the evidence rule — S2 (Donchian breakout) on ETH-USDT 4H and 6H, each in
both designs; the untouched 12 months (2025-10-20 → 2026-10-20) confirmed ETH 6H (+2.3 %, 28
trades, PF 1.29; its short side +6.0 % from 10 trades, its long side −3.7 %) and contradicted
ETH 4H (−4.8 %, 42 trades, PF 0.59).** The holdout's falling direction was known before it was
opened (pre-registered caveat), so the confirmation is weak.

- Adding the mirrored shorts made the rules worse in most cases: hybrid Calmar above long-only
  in 3 of 16 family-and-series pairs (median 0.05 against 0.35); the short leg profitable in 7
  of 16 — BTC losing in 7 of 8, ETH winning in 6 of 8 (most of the gain went to fees); 2022
  better than long-only in 13 of 16 pairs but positive in 4 (median −2.6 % → −1.5 %). With the
  fixed default parameters over 2020-01-01 to the holdout start (no selection) the shorts lowered
  Calmar in 15 of 16 pairs.
- Funding flowed from longs to shorts (Binance proxy, 2020 to the holdout start: +13.1 %/yr BTC,
  +15.7 %/yr ETH): the hybrid's shorts received 0.3–1.0 % of capital, the all-perp design's
  longs paid 1.1–4.7 %; the hybrid beat the all-perp design in 13 of 16 pairs.
- Diagnostics: the swap legs on OKX's own perpetual candles moved no Calmar by more than 0.05;
  the shorts without the crash filter (post-hoc) were worse in 28 of 32; no liquidation, account
  leverage at most 0.84x, the worst move against an open short 18 %.
- BTC rose up to 138 % and ETH up to 151 % within 30 days (December 2020 – January 2021): an
  unprotected 1x short would have been liquidated from 0.4 % (BTC) and 1.3 % (ETH) of the hourly
  closes of 2020 – October 2025.
- An independent review found one real defect before the final run: a short-to-long switch could
  start the long one bar late when the short's stop fired in that bar. Fixed and re-run; the first
  run's holdout openings (the same verdicts) are the ledger's first entry.

### Reading the R9 report honestly

- The long side is Sprint 2c's long-only rule unchanged and the shorts are mirror images with the
  same parameters: nothing was tuned for shorting, which is the point of the test and also why a
  dedicated short rule might do better — that would be a new, pre-registered study.
- Hybrid and all-perp versions of one rule share their signals: four passing configurations are
  two rules, and the holdout split them one each.
- Funding comes from Binance's public history; OKX's own (since 2026-07, inside the holdout window)
  only calibrates it. OKX settles more often when a rate sits at its cap, which the proxy cannot
  show for OKX.
- Positions are small at the policy sizing (10 % vol target), so returns are small in absolute
  terms on both sides of the comparison.

## Replication v1d — the Sprint 2c rule families on markets they were never tuned on (plan row R12)

The question: do the Sprint 2c rules hold on other large OKX spot USDT markets, or are they
BTC-specific? Research only, public data only, pre-registered; nothing under `app/` or `config/`
changed, and the app's instrument allowlist (`ALLOWED_INSTRUMENTS` in `app/okx/client.py`, which
also bounds demo and paper trading) was not widened. Report:
`docs/research/REPLICATION_V1D_REPORT.md` (numbers in `docs/research/replication_v1d_results.json`;
the market snapshot in `docs/research/replication_v1d_preregistration.json`; every holdout opening
in `docs/research/replication_v1d_holdout_ledger.json`). Simulation only.

| Module | Purpose |
|---|---|
| `research/markets.py` | Tables only: the candidate markets (public 1H history from before 2020-01-01, plus SOL-USDT), the Binance perpetual symbol of each (the research-side counterpart of the app's BTC/ETH-only table) and its OKX swap. |
| `research/replication_data.py` | Two bounded, resumable, GET-only collectors: OKX 1H and 4H spot candles through the lake's public client into `candles/<inst>/<bar>` (4H stored and 6H resampled from 1H, exactly Sprint 2c's data path for BTC/ETH), and Binance public funding for the markets' perpetuals into the same external layout through the app's writer (the app's collector stays BTC/ETH-only). `candle_history_start` probes the history condition with one GET. |
| `research/data.py` | `positioning_context` looks a market up in the research symbol table only when the app's table does not know it, so nothing changes for BTC/ETH (the reproduction proves it). |
| `research/replication.py` | The pre-registration (`PREREGISTRATION`, hashed with the market snapshot and the configuration), the ranked market selection, the frozen study lake (every candle series cut at Sprint 2c's data end, so the untouched 12 months are the same calendar window), the Sprint 2c runner loaded as a module (`load_v1c_runner`; its `run_series` runs every market — nothing is copied), the protocol check of its defaults against the stored Sprint 2c run, the BTC/ETH reproduction check (6 decimals, trade counts, selected rules, gate verdicts), the pre-registered verdict rules (the three BTC passers replicated, family labels, the overall label), the holdout ledger and the fleet shortlist additions with a `source` tag. |
| `research/report_replication.py` | The report; every plain-English sentence is computed from the run. |
| `scripts/run_replication_v1d.py` | `--preregister` (once), `--collect` (resumable), `--freeze`, the study (`--evaluate-holdout` only for the full pre-registered study), `--render-from-json`. A shortlist amendment the paper fleet cannot load is rolled back. |

### Running

```bash
python scripts/run_replication_v1d.py --preregister                    # once: the public ticker snapshot fixes the markets
python scripts/run_replication_v1d.py --collect                        # ~45 min, resumable: 7 markets x (1H, 4H, funding)
python scripts/run_replication_v1d.py --freeze                         # the study lake, cut at Sprint 2c's data end
python scripts/run_replication_v1d.py --evaluate-holdout --workers 8   # the study (BTC/ETH reproduction first; stops on any difference)
python scripts/run_replication_v1d.py --quick --markets XRP-USDT --timeframes 4H --families S1 --skip-reproduction --holdout-ledger - --shortlist - --report - --json -   # smoke run
python scripts/run_replication_v1d.py --render-from-json docs/research/replication_v1d_results.json
```

The holdout is opened only by the full pre-registered study (every chosen market, family,
timeframe and mode, the control, never with `--quick` or `--skip-reproduction`), and every opening
is appended to the ledger, which the report shows.

### Result (2026-11-04)

Markets, fixed from one public ticker snapshot (16:32 UTC) before any candle was collected:
XRP, DOGE, LINK, TRX, ADA, LTC (the top 6 of the eleven pre-2020 candidates by 24-hour quote
volume) and SOL. Data: OKX 1H and 4H candles from 2019-11-28 (SOL: 2020-09-30) cut at Sprint 2c's
data end, Binance funding per market; DOGE's funding covers 89.5 % of its in-sample bars, under
the 90 % threshold, so its 8 S5 configurations were reported as "run without S5" and not judged.
All 36 BTC/ETH reproductions matched Sprint 2c's stored numbers (largest difference 5e-7, every
trade count, rule and verdict the same). **Verdict: fragile.** 10 of 104 judged configurations
passed every gate on a new market — S2 (Donchian breakout) on DOGE (4H and 6H, gated), TRX (4H,
S2 and S2+S5) and ADA (6H, all four S2 variants), S1 and S1+S5 on SOL 6H without the gate — and
none of the three BTC passers of Sprint 2c replicated (S2 4H gate on 1 of 7 markets, S2+S5 4H gate
on 0 of 6, S1+S5 6H on 1 of 6; replication needed 4). The untouched 12 months confirmed the two SOL
configurations (+9.5 %, PF 5.5, 12 trades; the S5 filter changed nothing there), contradicted
seven (TRX and ADA lost 4.6–6.0 % with PF 0.07–0.47; DOGE 6H −0.6 %) and left DOGE S2 4H gate
unconfirmed for lack of trades (+1.7 % from 8 trades). Median Calmar on the new markets stayed
below BTC's for every family (S1 0.15 vs 0.29, S1+S5 0.19 vs 0.41, S2 0.23 vs 0.25, S2+S5 0.16 vs
0.29); LTC was negative for every rule. The best rule beat hold + policy sizing by more than 0.1
Calmar on 4 of 14 series (Sprint 2c: 4 of 4), and hold + policy itself lost 0.1–3.7 % on every
market's untouched 12 months. The two SOL accounts (`c11-s1s5-sol-6h-none`, `c12-s1-sol-6h-none`)
were appended to the fleet shortlist with a `source` tag; the fleet loads 22 accounts.

### Reading the R12 report honestly

- Ten passes out of 104 is about the Sprint 2c pass rate (4 of 108): a few passes among many
  comparisons are expected by chance, which is why the primary test asked for replication on half
  the markets and why the holdout, not the pass count, carries the verdict.
- The two confirmations are one signal: S1 and S1+S5 on SOL 6H traded identically over the 12
  months (the funding filter removed no entry), and SOL has the shortest history (first test
  window 2022-03), so fewer walk-forward windows judged it. Forward evidence in the fleet is the
  right next test, which is why they join it.
- The 12 months were a losing period for simply holding every one of the seven markets, as for
  BTC and ETH in Sprint 2c; a long-only rule that stayed mostly out was the only way to confirm.
- The S2 family passed walk-forward on three new markets and failed its holdout on all of them:
  the breakout rule's 2021–2025 out-of-sample edge did not carry into 2025–26 anywhere, which is
  the failure analysis plan rows R13 and R16 should start from.
- The hold + policy control is evaluated on every market's holdout as the comparison line (Sprint
  2c's practice); its openings are in the ledger too. Nothing here authorizes trading.

## Research round 1 — three pre-registered entry conditions on the unchanged Sprint 2c rules (plan row R13)

Plan section 5.3's research loop with the Sprint 2c discipline: up to three new rules — not
retunes of old ones — each written down with its rule, parameters, markets, timeframes, gates and
verdict rule before the first run, then judged forward (walk-forward at the fixed policy sizing; the
untouched 12 months once, only for passers, through an append-only ledger; confirmed passers to the
paper fleet as new accounts, as in R12). Research only, public data only; nothing under `app/` or
`config/` changed. Report: `docs/research/RESEARCH_ROUND_1_REPORT.md` (numbers in
`docs/research/research_round_1_results.json`; the pre-registration in
`docs/research/research_round_1_preregistration.json`; every holdout opening in
`docs/research/research_round_1_holdout_ledger.json`). Simulation only.

| Module | Purpose |
|---|---|
| `research/strategies/round1.py` | The three rules and the cross-asset context. H1 `S1+BT` / `S2+BT`: ETH's S1 / S2 (Sprint 2c grids and brackets) with new entries only while BTC's S1 trend (Sprint 2 defaults: 7/14/30 days, 2 of 3) is up. H2 `S1+VC`: S1 with new entries only on bars whose 30-day volume z-score is above 1. H3 `DM-BTC` / `DM-ETH`: dual-momentum legs, long their own market only while both S1 trends are up and it is the stronger 90-day performer (ties to BTC), mutually exclusive by construction. The conditions gate entries only (open positions are left to the base rule's exits and stop), their parameters are fixed and never in a grid. `CrossAssetContext` carries the other market's candles; a rule aligns them by exact timestamp (no look-ahead), fails closed where a bar is missing, and raises when the context lacks its reference. Registered in `research/strategies/__init__.py` (`ROUND1_BASES` names each rule's base). |
| `research/round1.py` | The pre-registration (`PREREGISTRATION`, written once to a hashed file the study checks against the module's text), the Sprint 2c runner loaded as a module with its `positioning_context` replaced by the cross-asset one (`patched_runner`; nothing else is copied), the protocol check (the replication study's, with the new candidates set aside and listed), one job per series and strategy group for a process pool, the H3 combination (`combine_legs`: the legs' stitched out-of-sample returns multiplied bar by bar, pooled trades, the smaller robustness share, a probabilistic Sharpe against the larger expected maximum), `leg_holdout` (the runner's own holdout steps, checked against it in the tests), the comparison of every new configuration with its base rule, the pre-registered verdict labels, the failure facts, the ledger and the shortlist additions (a confirmed H3 adds both legs). |
| `research/report_round1.py` | The report; every sentence, including each failure analysis's reading, is computed from the numbers. |
| `scripts/run_research_round_1.py` | `--preregister` (once), the study (`--evaluate-holdout` only for the full pre-registered study: every hypothesis, timeframe and mode, with the hold/S1/S2 reproduction, never `--quick`), `--render-from-json`, `--apply-shortlist-from-json`. A shortlist amendment the paper fleet cannot load is rolled back. |

### Running

```bash
python scripts/run_research_round_1.py --preregister                   # once: the fixed text, hashed
python scripts/run_research_round_1.py --evaluate-holdout --workers 12  # the study (~5 min on 12 workers; the study lake is frozen first)
python scripts/run_research_round_1.py --quick --hypotheses H2 --timeframes 4H --regime-modes none --skip-reproduction --report - --json - --holdout-ledger - --shortlist -   # smoke run
python scripts/run_research_round_1.py --render-from-json docs/research/research_round_1_results.json
```

The study lake (`data/lake_research_round_1`) is the research lake's BTC/ETH candles cut at Sprint 2c's
data end, so the walk-forward and the untouched 12 months are Sprint 2c's calendar windows. Before any
new rule is judged, hold, S1 and S2 on BTC-USDT and ETH-USDT must reproduce Sprint 2c's stored numbers
to 6 decimals through the patched context — the proof that the context change moves nothing for the
existing rules.

### Result (2026-11-04)

Pre-registered 18:37 UTC, official run 18:50 UTC (4.4 min on 12 workers; a holdout-free dry run minutes
earlier gave identical walk-forward numbers). The reproduction matched Sprint 2c's stored numbers in
20 of 20 configurations (largest difference 5e-7, every trade count, rule and verdict the same), so the
cross-asset context moves nothing for the existing rules. 20 configurations were judged.

- **H1 — a BTC-trend condition for ETH entries: failed walk-forward** (0 of 8). Beside the base
  rules the condition changed little: median Calmar 0.36 → 0.30, a median 19 % of trades removed,
  Calmar up in 4 of 8 and down in 4; the binding gates (Sharpe, Calmar, rolling consistency: 7 of 8
  each) are the ones the plain ETH rules miss. The HMM regime gate already stands aside in most of
  the bars a BTC-trend condition would block.
- **H2 — a volume (attention) confirmation for S1 entries: confirmed** (1 of 8). S1+VC on BTC-USDT
  4H with the regime gate: Calmar 0.55, Sharpe 0.71, +4.3 %/yr at a 7.8 % drawdown, PF 1.72, 83
  trades, 82.9 % of rolling 12-month windows positive, worst year −1.5 %, robust to ±30 % changes;
  the untouched 12 months gave +2.0 % with PF 1.41 from 25 trades. Beside plain S1 the condition
  raised Calmar in 6 of 8 configurations (median 0.29 → 0.33) and removed a median 46 % of trades;
  it did not pass on 6H or on ETH. The configuration is row 13 of the fleet shortlist
  (`c13-s1vc-btc-4h-gate`); the fleet loads 23 accounts.
- **H3 — dual momentum between BTC and ETH: failed walk-forward** (0 of 4). The one-position curve's
  median Calmar was 0.11 against 0.31 for the better plain S1 rule, with 57 trades a year against 35
  and a 2022 of −4.5 % against −3.6 %: the relative-strength switches added trades and fees without
  return, and "both trends up" removed exposure where the trend rules earn it.

### Reading the R13 report honestly

- One pass among 20 comparisons is what the Sprint 2c pass rate (4 of 108) predicts by chance; the
  pass clears two gates by a hair (Calmar 0.55 against 0.5, Sharpe 0.71 against 0.7), and the rule
  used for its holdout was selected in only 2 of 9 walk-forward windows (seven different rules over
  nine windows), which is the signature of a thin, unstable edge rather than a robust one.
- The holdout's falling direction was known before the study (pre-registered caveat): all three
  conditions trade less, which flatters them on a bear year. Confirmation there was necessary, not
  sufficient; the fleet's forward record is the judge, which is why the account joins it.
- The reproduction re-runs Sprint 2c's own passer S2 BTC 4H [gate] through the holdout path, so its
  already-opened 12 months appear in the ledger again as a comparison line with the same numbers
  (−4.9 %, PF 0.28): a repeat of a known result, not a new look.
- H1 and H3 are not worth a retest in this form; the failure analyses say why with numbers. The one
  idea with a signal — the volume confirmation — gained most where the base rule was weakest (the
  gated 4H rules) and lost on 6H, so a next round (R16) could pre-register its strictness or the
  attention idea on R12's markets, fixed a priori rather than swept. Nothing here authorizes trading.

## Paper-fleet hygiene — positioning data for the replication markets (plan row R17)

Found 2026-11-05 in the running laptop fleet: the S5 positioning filter's data came through the
app's collector, which is bounded to `BTC-USDT-SWAP` and `ETH-USDT-SWAP`, so the SOL S1+S5
account (`c11`, from R12) ran without its funding and open-interest series — the filter passes
where data is missing, as in the research — and the only sign was `not allowed` in the cycle
lines and `funding_rate: None` in its journal. Fleet and research code only; the app's bounds
are not widened. Runbook: `docs/runbooks/PAPER_FLEET.md`, "Positioning data for the S5 filter on
the replication markets".

| Module | Purpose |
|---|---|
| `research/positioning_data.py` | GET-only fetch of OKX's public funding-rate and open-interest history for the replication markets' swaps (`RESEARCH_SWAP_FOR`) through the path-allowlisted `OKXPublicRest`, with the app's path constants and row parsers but without its BTC/ETH bound; refuses BTC/ETH and anything unknown before any request (the R12 precedent applied to positioning data). |
| `research/paper_fleet/` (changes) | The feed routes BTC/ETH through the app's collector, unchanged, and every other fleet market through the research fetch. `positioning_status` labels each bar's S5 data (`current` / `stale` / `missing` per series, against the series' own period plus the 30-minute refresh window) with a plain-words note; the runner writes it into every S5 bar record (`positioning_data`) and the state; `--status` and the weekly report say it ("S5 running without data: the filter passes"). No rule, fingerprint or `positioning_source` check changed, so a running fleet resumes and the fix takes effect at its next restart. |


## Trader Policy v1 — three fixed risk budgets, entry brakes, position-management variants (plan row R18a)

The research half of plan row R18 (`docs/TRADER_PLAN_2026-11-05.md`, sections 4 and 9; the
paper-fleet half is row R18b). The five configurations the earlier studies confirmed are
re-judged at three fixed risk budgets, with the section 4.3 brakes on and off and each section
4.2 variant on alone, under the Sprint 2c walk-forward and the section 4.6 gates. The tier is a
policy overlay: the per-window selection of the rule variants never sees it, so every
configuration keeps the ATR multiple and exit bracket its walk-forward selected, and only the
size of the same trades changes. Nothing here changes the demo shadow run, its caps or the
0.60 floor; no tier reaches demo or live.

| Module | Purpose |
|---|---|
| `research/sizing.py` (changes) | `risk_cap` (allocation <= cap / (stop distance / close), read from the candidate's stop at the decision bar), `kind="risk"` (Kovner's rule), `rule_fraction_matrix` (one policy column per rule column), `fraction_components`, `SIZING_TIERS` (Reference unchanged; Trader `vt20/30 crash15/90dh cap2`; Aggressive `vt25/30 crash15/90dh cap2.5`; `risk1.5` for information). A spec without the new fields serialises exactly as before. |
| `research/brakes.py` | Entries-only circuit breakers: the Turtle ladder (x0.8 at -10 %, x0.64 at -20 %, restored on a new high), the -30 % hard stop, the entry caps (1/market/day, 3/day, none on the bar after an exit), the rolling 24 h / weekly / monthly loss limits (3 / 6 / 10 %), the heat cap (6 %, variant 8 %) with the R5b correlation grouping and equal size-down; `EntryBrakes` is the per-column state machine the engine consults before its entries; `BarCalendar` is unit-independent (stored Parquet candles carry millisecond timestamps). |
| `research/engine.py` (changes) | The optional `brakes` hook and `EngineVariants` (one add of half the initial quantity at +1 R with its own stop; a half scale-out at +2 R through the reduce-only path); off is bit-for-bit the old engine; the extra trade columns `stop_price`, `risk`, `risk_pct`, `adds`, `add_worst_case_r`, `scale_outs`. |
| `research/trader_policy.py` | The tiers (`TIERS`, the comparison tiers, `tier_for`), the variants, the section 4.6 gates (`acceptance_check_r18`), the size-neutral variant rule, the brake-cost flag, the per-trade statistics (expectancy in R, payoff, gaps, re-entries, cap binding, the conviction test). |
| `research/trader_policy_study.py`, `research/report_trader_policy.py`, `scripts/run_trader_policy_v1.py` | The pre-registered study: 15 runs (5 configurations, 6 hold controls, 4 TF forward controls) x 11 core cells (+ 7 variant cells for the configurations) = 150 cells through Sprint 2c's own runner (`scripts/run_research_v1c.py`, which took the tier / brakes / variant / cost-replay arguments with Sprint 2c defaults); reproduction of every stored number first; the protocol check per cell; the holdout through an append-only ledger; the report, the results JSON and the fleet rows recorded for R18b. |

### Running

```bash
python scripts/run_trader_policy_v1.py --preregister                  # once; refuses a second write
python scripts/run_trader_policy_v1.py --evaluate-holdout --workers 12 # the full study (about 10 minutes on 12 workers)
python scripts/run_trader_policy_v1.py --quick --runs C1 H2 --cells "reference|nobrakes|none" "trader|brakes|none" --skip-reproduction --report - --json - --holdout-ledger -
python scripts/run_trader_policy_v1.py --render-from-json docs/research/trader_policy_v1_results.json
```

The study lake (`data/lake_trader_policy_v1`) is the research lake's BTC, ETH, SOL and DOGE
candles cut at Sprint 2c's data end, built on first use. `--evaluate-holdout` needs the full
pre-registered study (every run and cell, with the reproduction, never `--quick`).

### Result (2026-11-05)

Report: `docs/research/TRADER_POLICY_V1_REPORT.md`; results `trader_policy_v1_results.json`;
pre-registration `trader_policy_v1_preregistration.json`; ledger `trader_policy_v1_holdout_ledger.json`.

- Reproduction: 11 of 11 stored results exact at the Reference cell (Sprint 2c's, the replication
  study's, round 1's and round 2's numbers; same trades, rules and verdicts).
- All five confirmed configurations pass the section 4.6 gates at the Trader tier with the
  brakes on and their 12 months confirm at that tier (near-second looks). Trader tier: +6.3 % to
  +13.6 % a year at 8.0-14.1 % worst drawdowns, realized volatility 7.9-10.5 %, 1.6-1.8 x the
  Reference exposure, a stop costing 1.2-1.7 % of the account on average, average win 2.7-4.7 x
  average loss, expectancy 0.16-0.27 R, no gap past a stop in 4.3 years, a bootstrap chance of
  touching -30 % of at most 0.6 %. Aggressive passes on all five with the brakes on (drawdowns
  9.9-17.2 %, -30 % chance up to 2.9 %); `risk1.5` lands between Reference and Trader.
- Brakes (Trader, five sleeves): the bar-after-exit cap acted 131 times, the daily entry cap 26,
  the Turtle ladder 7, the 24-hour loss limit once; the weekly and monthly limits and the heat
  cap never (as pre-registered for one sleeve). Cost -0.18 to +0.10 Calmar; flagged above 0.1
  only on DOGE 4H at the Reference and Aggressive tiers. The Turtle ladder cost at most 0.02 Calmar.
- Variants: the +1 R add counted on BTC 6H only (0.74 to 0.95 Calmar; worst case at the stops
  1.73 R at most); the +2 R half scale-out on the two SOL sleeves only; trailing exits lost
  everywhere; the wider stop on DOGE only; dropping the time stop on three sleeves; the
  conviction split failed its pre-registered test (0.12 R against 0.25 R, pooled). No account changes.
- Fleet rows recorded for R18b: the five Trader-tier configurations and the TF forward control
  (BTC-USDT and ETH-USDT 6H). The first run's calendar bug and the TF control's unplanned holdout
  look are written in the report's method notes and the ledger.

### Reading the R18 report honestly

- A tier changes the size of the same trades: a holdout opened at a tier is a near-second look
  at months the Reference tier already opened, and its falling direction was known. The tier
  runs confirm the plumbing of the budget, not the edge; the paper fleet's forward record is
  the judge (row R18b adds the accounts, G7 reads them after 60+ days).
- The walk-forward restarts flat every 180 days, so the ladder's peak, the hard stop and the
  loss windows restart with it; a -30 % drawdown inside one window is rare by construction and
  the stitched curve's drawdown can exceed any window's.
- The brakes act on entries only. "No entry on the bar after an exit" is the brake that acts
  most on the trend rules, whose vote often flips back the bar after an exit; it changes the
  trade count, and the report shows its cost.
- The study's first run had a timestamp-unit bug in the brake calendar on 4H series (every 4H
  bar on one day, so the one-entry-per-day cap blocked almost everything); its own brake counts
  exposed it, the calendar was fixed and the whole study re-run with the pre-registration
  unchanged; both runs' holdout openings are in the ledger.

## Research round 3 — asymmetric setups: trend-pullback continuation, the slow breakout, the bar size after costs (plan row R19)

The Trader Plan's section 5 (`docs/TRADER_PLAN_2026-11-05.md`): two new rule families written
as FIXED rules (one pre-registered parameter set each, nothing for the walk-forward to select)
and judged under a pre-registered fixed-rule protocol variant — the 20-train-trade qualification
that silenced round 2's slow rules is skipped (`--min-trades 0`: every window runs the rule's
test slice) and the exit bracket is fixed (`none`, or `trail3` for the S7 trail variant) — at the
Trader Policy's Trader tier with its brakes (the paper fleet's cell `trader|brakes|none`), under
the plan's section 4.6 gates; the Reference cell runs beside it for information. BTC-USDT and
ETH-USDT are the primary markets, the seven R12 markets the replication, on 1D and 6H bars.
Plus the bar-size comparison: the S1 and S2 families (Sprint 2c's grids and selection) on 1D,
6H and 4H bars at the Trader tier, at the 0.30 % gate cost and the measured 0.20 % replay.
Nothing here changes the demo shadow run, its caps or the 0.60 floor; nothing reaches demo or live.

| Module | Purpose |
|---|---|
| `research/strategies/round3.py` | `TrendPullback` (S7: uptrend = close above its 100-day SMA and the 50-day above the 100-day; pullback = a close below the 20-day SMA, variant `S7e` the 10-day EMA; entry = a close above the previous bar's high while the uptrend holds; stop = under the pullback low floored at 2 x ATR(14), variant `S7w` 3 x; exit = a close below the 50-day SMA or the stop; `S7t` = the same rule under the `trail3` bracket, which the runner and the fleet apply through the `bracket` parameter) and `SlowBreakout` (S8: Turtle System 2, 55-day high entry, 20-day low exit, 5 x ATR(14) stop, no adds, no filters; `S8g` Garner's 90/45 channels). Registered as `FIXED_RULES`; `VARIANT_OF` names each variant's base. |
| `research/round3.py` | The pre-registration (`PREREGISTRATION`, written once with a hash; the committed file must match the module, the rules' numbers, the cell and the brakes), the jobs (control / fixed / fixed_trail / barsize per series and cell), Sprint 2c's command line per job (`job_argv`), the per-job protocol check with its explained deviations (a tier, the fixed-rule protocol, 1D bars), the reproduction targets (Sprint 2c, the replication study, the Trader Policy study's judged cell), the bookkeeping (comparisons with hold + policy at the same cell, with the variant's base, with the Reference cell), the readings (sign tests, the R12 replication reading, the variants, H8's pooled reading), the bar-size table and its reading, the holdout openings, earlier looks, ledger, the shortlist rows (applied / recorded only). |
| `research/report_round3.py` | The report, every sentence computed from the numbers (also renders the pre-registration-only stub before the first run). |
| `scripts/run_research_round_3.py` | The command line: `--preregister`, the study, `--render-from-json`, `--apply-shortlist-from-json` (the R12 restore rule). |
| `research/paper_fleet/config.py` (change) | A candidate row may name the fixed-rule protocol variant — only for a rule in `FIXED_RULES`, only when the study's recorded check of that cell names the same variant, with the same two explained deviations (`brackets`, `min_trades`) the slow-trend control already has. Existing accounts and fingerprints unchanged. |

### Running

```bash
python scripts/run_research_round_3.py --preregister                   # once; writes the JSON and the report stub; refuses a second write
python scripts/run_research_round_3.py --evaluate-holdout --workers 12  # the full study
python scripts/run_research_round_3.py --hypotheses H8 --markets BTC-USDT --timeframes 6H --regime-modes none --no-barsize --skip-reproduction --report - --json - --holdout-ledger - --shortlist -
python scripts/run_research_round_3.py --render-from-json docs/research/research_round_3_results.json
```

The study lake (`data/lake_research_round_3`) is the research lake's nine markets cut at Sprint
2c's data end, built on first use; 6H and 1D bars are resampled from the stored 1H candles at
UTC midnight. `--evaluate-holdout` needs the full pre-registered study (every hypothesis,
market, timeframe, mode and cell, the bar-size comparison, with the reproduction, never `--quick`).

### Result (2026-11-05)

Report: `docs/research/RESEARCH_ROUND_3_REPORT.md`; results `research_round_3_results.json`;
pre-registration `research_round_3_preregistration.json` (written 05:14 UTC, before the first run);
ledger `research_round_3_holdout_ledger.json`. 124 jobs, 568 results, 216 judged configurations,
18.7 minutes on 12 workers.

- Reproduction: 49 of 49 stored results exact (Sprint 2c's and the replication study's at the
  Reference cell; the Trader Policy study's at the judged cell; same trades, rules and verdicts).
- **H7, trend-pullback continuation (S7 and its three variants): failed walk-forward** on the primary
  markets (0 of 32) and on the replication markets (0 of 112). Beside hold + policy sizing at the
  same Trader budget it ended with a higher Calmar in 5 of 144 configurations (all on SOL-USDT 1D):
  median Calmar -0.11 against 0.34, median yearly return -1.2 % against +5.0 %, a median average
  win of 1.86 x the average loss, expectancy -0.07 R, 30 % winners, in the market 17 % of the time,
  10.9 trades a year (6.6 on daily bars, 18.4 on 6H; the plan guessed fewer on 6H). The EMA-10
  pullback and the 3-ATR floor raised Calmar beside the base rule in 57 and 50 of 72 series
  (+0.06 and +0.01 median), the trail-3R exit lowered it (18 of 72), and none of it lifts the family
  above holding: refuted on these markets under this protocol, not merely untested.
- **H8, the slow breakout (S8 and Garner's 90/45 variant): failed walk-forward** everywhere (0 of 16
  and 0 of 56), and the 'at least 30 trades' gate bound in 72 of 72: the rule fires a median 3.2
  times a year, so one market cannot produce 30 trades over 4.3 out-of-sample years. Its shape is
  the asymmetric one the plan asked for - pooled over the nine markets S8 on 6H made 167 trades
  with profit factor 1.62, an average win 2.74 x the average loss, 37 % winners and +0.24 R a trade
  (S8g on daily bars: 85 trades, PF 1.93, 2.51 x, +0.29 R) - but beside hold + policy at the same
  budget its Calmar was higher in only 11 of 72 configurations (median 0.20 against 0.34; it is in
  the market a third of the time and misses the rest of the trend). Best single configuration:
  S8 BTC-USDT 6H without a gate, Calmar 0.44, +3.9 % a year at an 8.8 % drawdown, Sharpe 0.78,
  17 trades.
- **Bar size:** the claim '6H is the cost-adjusted sweet spot' does not hold under the
  pre-registered reading (6H best in 7 of 16 comparisons at the 0.30 % gate cost and 6 of 16 at the
  measured 0.20 %; 8 needed). Clarified after the run with the verdict unchanged: the S2 family
  produced no trade on daily bars at either cell because the 20-train-trade qualification silenced
  every window there (untested, not beaten), which gives 7 of 16 and 7 of 16; by family, 6H is the
  best bar size for the S1 family at the gate cost (5 of 8) but not at the measured cost (3 of 8),
  and 4H beats 6H for the S2 family (6 of 8). Median Calmar at the Trader budget: 1D 0.02, 6H 0.39,
  4H 0.46 at 0.30 %, with 6, 20 and 24 trades a year and 0.2, 1.3 and 1.6 % of fees a year.
- Holdout: nothing passed, so the untouched 12 months were opened only for the hold + policy controls
  at the judged cell (18 comparison lines, all negative: -0.2 % to -8.4 %). No fleet row applied; the
  fleet loader's fixed-rule path is built and tested but unused.
- Honesty notes (in the report's method notes): the first full run crashed before writing anything
  because the runner's regime-threshold sensitivity replay sized a gated S1/S2 bar-size job with a
  per-trade-cap tier but no stop; fixed in `scripts/run_research_v1c.py` (stop-aware; Sprint 2c's own
  policy takes the path it always did, the reproduction proves it) and the study re-run with the
  pre-registration unchanged.

### Reading the R19 report honestly

- A fixed rule under the fixed-rule protocol is judged exactly once per window with no selection,
  so a failure is a failure of the rule as written, not of the selection step; the 20-train-trade
  qualification still applies to the swept bar-size families, which is why the S2 family is untested
  on daily bars here.
- The 30-trade gate cannot be met by a rule that fires three times a year on one market; the gate
  stayed as the plan fixed it and the report says where it binds. S8's pooled nine-market numbers are
  information, never a verdict and never a fleet ticket.
- The 0.20 % column of the bar-size table is a replay of the most-often-selected rule over every
  window (the Trader Policy study's construction); for a swept family that also removes the
  per-window selection, so read the 0.30 % column as the protocol's number.
- The tier's volatility window is 30 bars (30 days at 1D, 5 days at 4H): the bar-size comparison
  also compares volatility estimators, as pre-registered.
- 216 judged configurations at Sprint 2c's own pass rate would give about 8 passes by chance; the
  study found none, which is the strongest statement a backtest can make about these two setups.
