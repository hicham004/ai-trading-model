# Research round 1 — three pre-registered entry conditions on the unchanged Sprint 2c rules (walk-forward, SIMULATION ONLY)

Generated 2026-11-04 18:50 UTC by `scripts/run_research_round_1.py` (plan row R13; 4.4 min). Rules: Sprint 2c's, run by `scripts/run_research_v1c.py`'s own `run_series` (policy sizing `vt10/30 crash15/90dh ladder`, regime gate `hmm3 bear>=0.5 gate`, S0 filter S0 vol×3 spread p98 gap3 FOMC±6/6h, walk-forward train 540d → purge 7d → test 180d, fee 0.10% + slippage 0.050% per side, brackets ['none', 'tp2', 'trail1', 'time30']), with one addition: a feature context that also carries the other market's candles for the cross-asset rules. Data: the same PUBLIC OKX spot candles as Sprint 2c (1H and 4H stored, 6H resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ 2026-10-20T10:00:00+00:00). Holdout: the last 12 months (2025-10-20->2026-10-20), opened once and only for configurations that passed walk-forward.

**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy to deploy. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we did.** We tested up to three new entry conditions on top of the unchanged Sprint 2c rules (H1: a BTC-trend condition for ETH entries; H2: a volume (attention) confirmation for S1 entries; H3: dual momentum between BTC and ETH), each written down with its rule, parameters, markets, timeframes, gates and verdict rule before the first run. Everything else is Sprint 2c's: the same grids, exit brackets, no-trade filter, regime gate, fixed sizing, walk-forward windows and gates. Before any new rule was judged, the same code (with the one change: a feature context that also carries the other market's candles) re-ran hold, S1 and S2 on BTC and ETH and matched Sprint 2c's stored numbers in 20 of 20 configurations. 20 configurations were judged on 2019-12-16->2026-10-20 after fees and slippage; the last 12 months (2025-10-20->2026-10-20) stayed untouched except for configurations that passed.
- **H1 — a BTC-trend condition for ETH entries: failed walk-forward.** 0 of 8 configurations passed every gate. Best: S2+BT ETH-USDT 6H [gate] with Calmar 0.55, +4.1% a year at a 7.5% drawdown, missing 75% of rolling 12-month windows positive. Beside the base rule the condition raised Calmar in 4 of 8 configurations (median 0.36 → 0.30) and removed a median 19% of its trades.
- **H2 — a volume (attention) confirmation for S1 entries: confirmed.** 1 of 8 configurations passed every gate (S1+VC BTC-USDT 4H [gate]). Best: S1+VC BTC-USDT 4H [gate] with Calmar 0.55, +4.3% a year at a 7.8% drawdown. Beside the base rule the condition raised Calmar in 6 of 8 configurations (median 0.29 → 0.33) and removed a median 46% of its trades.
- **H3 — dual momentum between BTC and ETH: failed walk-forward.** 0 of 4 configurations passed every gate. Best: DM BTC+ETH 6H [none] with Calmar 0.20, +2.8% a year at a 14.0% drawdown, missing profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes. The one-position curve's median Calmar was 0.11 against 0.31 for the better plain S1 rule; it beat both plain S1 rules in 0 of 4 configurations.
- **Holdout.** The untouched 12 months then confirmed 1 (S1+VC BTC-USDT 4H [gate]) and contradicted 0 (none). The holdout's falling direction was known before this study (pre-registered caveat), so a confirmation here is necessary, not sufficient; the paper fleet's forward record is the judge.
- **Binding gates.** Sharpe above 0.7 (18 of 20), Calmar above 0.5 (18 of 20), 75% of rolling 12-month windows positive (16 of 20), profit factor above 1.2 (5 of 20). Sprint 2c's own pass rate was 4 of 108, so a pass or two among 20 comparisons would be expected by chance; the holdout and the forward fleet, not the pass count, carry the verdict.
- **Paper fleet.** 1 confirmed configuration(s) were appended to the fleet's shortlist with a source tag (S1+VC BTC-USDT 4H); a running fleet takes them as new accounts at its next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading. Shortlist file: docs/research/paper_fleet_shortlist_v1c.json now lists 13 configurations (23 fleet accounts).

## Fixed before the first run (the pre-registration)

Pre-registration hash (text, file and configuration): `b8d5f8ba5caa61c199e8bb8507653891af62e6beeb4ac2c2b4f00c9caa9a5eab`; file `docs/research/research_round_1_preregistration.json` written 2026-11-04T18:37:25+00:00.

- **fixed_on**: 2026-11-04, before any run (plan row R13)
- **question**: Does one new, pre-registered entry condition on top of an unchanged Sprint 2c rule give a configuration that passes the Sprint 2c gates on BTC-USDT / ETH-USDT 4H and 6H and is then confirmed by the untouched 12 months — where the Sprint 2c rules themselves passed in only 4 of 108 configurations and the holdout confirmed 1?
- **why**: From the failure analyses: Sprint 2 (0 of 42) and 2b (0 of 28) found the edge of long-only timing on BTC/ETH thin and fragile; 2c (4 of 108, 1 confirmed) found the binding gates to be Calmar, Sharpe and the rolling-12-month consistency, that the HMM regime gate cost more return than it saved, and that ETH's rules were weaker than BTC's (no ETH configuration passed); R9 found the mirrored shorts no help; R12 found the families fragile across markets and the S2 breakout's edge not carrying into 2025-26 anywhere. The three conditions below each try to buy consistency by trading less, from the literature of plan section 2.6: cross-market trend (BTC leads the market), attention and volume (Liu & Tsyvinski 2018/2021: attention surges precede gains) and dual momentum (Antonacci: relative strength among trending assets).
- **protocol**: Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), with Sprint 2c's defaults: the candidates' grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the fixed policy sizing vt10/30 crash15/90dh ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM, bear >= 0.5, fitted on every window's train slice; modes none and gate), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then bracket) and the v1c gates — checked against the stored Sprint 2c run before the study runs; the only change is a feature context that also carries the other market's candles
- **data**: the same OKX public 1H and 4H spot candles as Sprint 2c (4H stored, 6H resampled from 1H), frozen at Sprint 2c's data end (bar close <= 2026-10-20T10:00:00+00:00) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window; Binance public funding and open interest for the S0/S5 machinery as in Sprint 2c (the new rules do not use them)
- **reproduction**: before any new rule is judged, the same patched code path re-runs hold, S1 and S2 on BTC-USDT and ETH-USDT (4H and 6H, modes none and gate) and must give Sprint 2c's stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts; otherwise the study stops
- **gates**: the v1c gates unchanged (research/report_v1c.py GATES): PF > 1.2, max DD < 20 %, Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, no calendar year below -10 %, >= 30 trades, >= 50 % of +-30 % neighbours profitable
- **verdicts**: a configuration passes when it passes every gate on the walk-forward; a hypothesis is 'confirmed' when at least one of its configurations passes and is confirmed by its holdout, 'contradicted by the holdout' when some pass and none is confirmed, and 'failed walk-forward' when none passes; every failing hypothesis gets a failure analysis computed from the numbers beside its base rule
- **holdout**: the last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward gate (for H3, the combined curve: then both legs' holdouts are simulated and combined the same way), only by the full pre-registered study (every hypothesis, timeframe and mode, with the reproduction, never --quick); the v1c verdict (positive return, PF > 1, >= 10 trades); every opening goes into an append-only ledger the report shows. CAVEAT, stated before the run: the holdout's falling direction is already known from the R5b and R9 reports (BTC about -26 %, ETH about -39 % over those months, hold + policy negative on every series), and all three conditions reduce time in the market, which flatters them there; a confirmation is therefore necessary but not sufficient, and the paper fleet's forward record is the judge
- **fleet**: a confirmed configuration is appended to the paper fleet's shortlist as a new account with a source tag (existing entries and running accounts untouched; a walk-forward pass alone adds nothing); a confirmed H3 adds both legs, which together are the one position; the fleet must be able to load the amended shortlist, otherwise the file is restored and the report says so (the R12 rule)
- **no_changes_after_results**: no gate, parameter, condition, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so

### H1 — a BTC-trend condition for ETH entries

- **rule**: ETH-USDT's S1 (time-series momentum) and S2 (Donchian breakout) rules, exactly Sprint 2c's parameters, grids and brackets, with new entries allowed only while BTC-USDT's S1 trend is up — S1 with its Sprint 2 defaults on BTC's candles of the same timeframe (lookbacks 7/14/30 days, at least 2 of 3 positive), aligned bar for bar. Entries only: an open ETH position is left to the base rule's own exits and stop, as the regime gate and the S5 filter do. The condition's parameters are fixed and never in a grid.
- **candidates**: ['S1+BT', 'S2+BT']
- **markets**: ['ETH-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **reference_trend**: {'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0}
- **comparison**: the same S1 / S2 configuration on ETH-USDT without the condition (Sprint 2c's stored numbers, reproduced in this run)
- **why**: no ETH configuration passed in Sprint 2c; BTC's trend is the market's trend, and ETH's rules may be entering against it

### H2 — a volume (attention) confirmation for S1 entries

- **rule**: S1, exactly Sprint 2c's parameters, grid and brackets, on BTC-USDT and ETH-USDT, with new entries allowed only on bars whose volume z-score over the trailing 30 days (the bar's own volume against the trailing mean and standard deviation of the bars of that window) is above 1. Entries only, as above; a run of desired bars that never sees such a bar is skipped. The window and the threshold are fixed and never in a grid.
- **candidates**: ['S1+VC']
- **markets**: ['BTC-USDT', 'ETH-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **comparison**: the same S1 configuration without the condition (Sprint 2c's stored numbers, reproduced in this run)
- **why**: attention surges precede gains in the crypto literature; S1's losses in 2c came from many small whipsaw entries

### H3 — dual momentum between BTC and ETH

- **rule**: One position in the stronger 90-day performer of BTC-USDT and ETH-USDT, only while BOTH markets' S1 trends are up, as two mutually exclusive legs: DM-BTC on BTC-USDT is long only while BTC's and ETH's S1 trends (the leg's own S1 parameters, from S1's grid, applied to both markets) are up AND BTC's simple return over the lookback is at least ETH's; DM-ETH on ETH-USDT is the mirror with a strict comparison, so an exact tie goes to BTC. Each leg carries S1's ATR stop on its own market and S1's brackets; a leg exits when its condition ends (the position moves to the other leg at the next open) or on its stop. The lookback is fixed and never in a grid.
- **candidates**: ['DM-BTC', 'DM-ETH']
- **markets**: ['BTC-USDT', 'ETH-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **judged_as**: the combined one-position curve per timeframe and regime mode: the legs' stitched out-of-sample bar returns r_b and r_e (identical windows, as the two markets' bar indices are identical) give the combined return (1 + r_b)(1 + r_e) - 1, exact for a fraction-of-equity sizing because at most one leg is in the market at a bar close; the v1c gates on that curve with the profit factor and trade count pooled over the legs' trades and the robustness share taken as the smaller of the legs' shares; the legs are shown as components and are not judged on their own
- **comparison**: S1 on BTC-USDT and S1 on ETH-USDT without the condition (Sprint 2c's stored numbers, reproduced in this run), and the hold + policy controls
- **why**: relative strength among trending assets is the one momentum variant the literature finds robust; it concentrates the one position where the trend is strongest

Protocol check against the stored Sprint 2c run: every parameter the same (checked: brackets, fee, holdout_months, ladder_recovery_days, min_trades, no_trade_label, policy_sizing, positioning_source, purge_days, quick, rebalance_threshold, regime, regime_modes, select_by, slippage, strategies, test_days, timeframes, train_days; new candidates, not in Sprint 2c by design: S1+BT, S2+BT, S1+VC, DM-BTC, DM-ETH).

Gates (unchanged from Sprint 2c): profit_factor_min 1.2; max_drawdown_max 0.2; sharpe_min 0.7; calmar_min 0.5; rolling_12m_positive_min 0.75; worst_calendar_year_min -0.1; min_trades 30; robust_share_min 0.5; min_year_days 60.

## Reproduction of Sprint 2c

Before any new rule ran, hold, S1 and S2 on BTC-USDT and ETH-USDT went through the same loaded runner with the cross-asset context and had to give Sprint 2c's stored walk-forward numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — otherwise the study stops.

| Candidate | Series | Regime | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |
|---|---|---|---|---|---|---:|---|---|---:|---|
| hold | BTC-USDT 4H | none | 0.147823 / 0.147823 | 0.594651 / 0.594651 | 0.072057 / 0.072057 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 4H | none | 0.093620 / 0.093620 | 0.374170 / 0.374170 | 0.083135 / 0.083135 | 184 / 184 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 4H | gate | 0.069956 / 0.069956 | 0.290839 / 0.290839 | 0.105133 / 0.105133 | 151 / 151 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 4H | none | 0.149350 / 0.149350 | 0.570857 / 0.570857 | 0.086735 / 0.086735 | 85 / 85 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 4H | gate | 0.246926 / 0.246926 | 0.863110 / 0.863110 | 0.065190 / 0.065190 | 69 / 69 | yes | yes | 0.0e+00 | yes |
| hold | ETH-USDT 4H | none | 0.078472 / 0.078472 | 0.377167 / 0.377167 | 0.086111 / 0.086111 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 4H | none | -0.000879 / -0.000879 | 0.025942 / 0.025942 | 0.134491 / 0.134491 | 225 / 225 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 4H | gate | 0.055714 / 0.055714 | 0.254772 / 0.254772 | 0.115195 / 0.115195 | 150 / 150 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 4H | none | 0.167322 / 0.167322 | 0.616527 / 0.616527 | 0.088169 / 0.088169 | 77 / 77 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 4H | gate | 0.031911 / 0.031911 | 0.159041 / 0.159041 | 0.108802 / 0.108802 | 86 / 86 | yes | yes | 0.0e+00 | yes |
| hold | BTC-USDT 6H | none | 0.118166 / 0.118166 | 0.486633 / 0.486633 | 0.079653 / 0.079653 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 6H | none | 0.159336 / 0.159336 | 0.584869 / 0.584869 | 0.091930 / 0.091930 | 155 / 155 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 6H | gate | 0.175086 / 0.175086 | 0.625968 / 0.625968 | 0.114153 / 0.114153 | 146 / 146 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 6H | none | 0.029879 / 0.029879 | 0.160691 / 0.160691 | 0.099668 / 0.099668 | 69 / 69 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 6H | gate | 0.050630 / 0.050630 | 0.282661 / 0.282661 | 0.098563 / 0.098563 | 48 / 48 | yes | yes | 0.0e+00 | yes |
| hold | ETH-USDT 6H | none | 0.110168 / 0.110168 | 0.496014 / 0.496014 | 0.095781 / 0.095781 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 6H | none | 0.155841 / 0.155841 | 0.578727 / 0.578727 | 0.082298 / 0.082298 | 165 / 165 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 6H | gate | 0.123779 / 0.123779 | 0.509298 / 0.509298 | 0.075121 / 0.075121 | 113 / 113 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 6H | none | 0.147567 / 0.147567 | 0.570377 / 0.570377 | 0.090869 / 0.090869 | 85 / 85 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 6H | gate | 0.240615 / 0.240615 | 0.916072 / 0.916072 | 0.083290 / 0.083290 | 52 / 52 | yes | yes | 0.0e+00 | yes |

20 of 20 reproduced.

## H1 — a BTC-trend condition for ETH entries: **failed walk-forward**

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| S1+BT ETH-USDT 4H [none] | none | +5.1% | +1.2% | 0.23 | 1.14 | 8.8% | 0.13 | 155 | 53% | 1.1% | 41.5% | -3.3% | 100.0% | 0.10 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+BT ETH-USDT 4H [gate] | none | +12.0% | +2.6% | 0.49 | 1.36 | 8.4% | 0.31 | 140 | 50% | 1.1% | 56.1% | -1.8% | 87.5% | 0.25 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+BT ETH-USDT 4H [none] | none | +14.3% | +3.1% | 0.53 | 1.60 | 9.9% | 0.32 | 72 | 41% | 0.5% | 58.5% | -0.6% | 100.0% | 0.09 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+BT ETH-USDT 4H [gate] | time30 | +8.2% | +1.8% | 0.35 | 1.28 | 9.7% | 0.19 | 69 | 39% | 0.5% | 70.7% | -2.4% | 80.0% | 0.06 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+BT ETH-USDT 6H [none] | none | +11.1% | +2.5% | 0.45 | 1.26 | 8.8% | 0.28 | 136 | 56% | 0.9% | 51.2% | -4.9% | 100.0% | 0.12 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+BT ETH-USDT 6H [gate] | none | +7.3% | +1.6% | 0.33 | 1.26 | 8.2% | 0.20 | 106 | 39% | 0.8% | 75.6% | -5.9% | 100.0% | 0.11 | Sharpe above 0.7, Calmar above 0.5 | fail | untouched |
| S2+BT ETH-USDT 6H [none] | none | +16.6% | +3.6% | 0.66 | 1.63 | 8.2% | 0.44 | 55 | 37% | 0.4% | 63.4% | -2.2% | 100.0% | 0.17 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+BT ETH-USDT 6H [gate] | none | +18.9% | +4.1% | 0.88 | 2.03 | 7.5% | 0.55 | 41 | 23% | 0.3% | 68.3% | -1.0% | 100.0% | 0.23 | 75% of rolling 12-month windows positive | fail | untouched |

Beside the base rule (same instrument, timeframe and mode; Sprint 2c's stored numbers, reproduced in this run):

| Configuration | Base | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1+BT ETH-USDT 4H [none] | S1 ETH-USDT 4H [none] | -0.00 → 0.13 | -0.0% → +1.2% | 13.4% → 8.8% | 0.03 → 0.23 | 1.01 → 1.14 | 225 → 155 | 58% → 53% | 31.7% → 41.5% | -4.5% → -3.3% | -4.5% → -3.3% | no / no |
| S1+BT ETH-USDT 4H [gate] | S1 ETH-USDT 4H [gate] | 0.11 → 0.31 | +1.3% → +2.6% | 11.5% → 8.4% | 0.25 → 0.49 | 1.18 → 1.36 | 150 → 140 | 47% → 50% | 39.0% → 56.1% | -3.0% → -1.8% | -3.0% → -1.8% | no / no |
| S2+BT ETH-USDT 4H [none] | S2 ETH-USDT 4H [none] | 0.41 → 0.32 | +3.6% → +3.1% | 8.8% → 9.9% | 0.62 → 0.53 | 1.63 → 1.60 | 77 → 72 | 42% → 41% | 63.4% → 58.5% | -0.6% → -0.6% | -0.5% → -0.1% | no / no |
| S2+BT ETH-USDT 4H [gate] | S2 ETH-USDT 4H [gate] | 0.07 → 0.19 | +0.7% → +1.8% | 10.9% → 9.7% | 0.16 → 0.35 | 1.10 → 1.28 | 86 → 69 | 40% → 39% | 70.7% → 70.7% | -0.8% → -2.4% | +0.5% → +2.1% | no / no |
| S1+BT ETH-USDT 6H [none] | S1 ETH-USDT 6H [none] | 0.42 → 0.28 | +3.4% → +2.5% | 8.2% → 8.8% | 0.58 → 0.45 | 1.31 → 1.26 | 165 → 136 | 54% → 56% | 68.3% → 51.2% | -2.2% → -4.9% | -2.2% → -4.9% | no / no |
| S1+BT ETH-USDT 6H [gate] | S1 ETH-USDT 6H [gate] | 0.37 → 0.20 | +2.7% → +1.6% | 7.5% → 8.2% | 0.51 → 0.33 | 1.38 → 1.26 | 113 → 106 | 41% → 39% | 80.5% → 75.6% | -1.8% → -5.9% | -1.8% → +0.6% | no / no |
| S2+BT ETH-USDT 6H [none] | S2 ETH-USDT 6H [none] | 0.36 → 0.44 | +3.2% → +3.6% | 9.1% → 8.2% | 0.57 → 0.66 | 1.39 → 1.63 | 85 → 55 | 36% → 37% | 61.0% → 63.4% | -2.1% → -2.2% | -2.1% → +0.5% | no / no |
| S2+BT ETH-USDT 6H [gate] | S2 ETH-USDT 6H [gate] | 0.62 → 0.55 | +5.1% → +4.1% | 8.3% → 7.5% | 0.92 → 0.88 | 2.01 → 2.03 | 52 → 41 | 41% → 23% | 70.7% → 68.3% | +0.7% → -1.0% | +0.7% → +0.3% | no / no |

**Failure analysis** (computed from the numbers above):

- Across its 8 configurations the condition raised the risk-adjusted result (Calmar) in 4 and lowered it in 4: the median Calmar went from 0.36 to 0.30 (+0.01), the median yearly return from +3.0% to +2.6%, the median worst drawdown from 9.0% to 8.6%, and the median share of positive rolling 12-month windows from 65.9% to 61.0%.
- It removed a median 19% of the base rule's trades (median 100 → 89), changed the time in the market by -1.0% and the fees per year by -0.06%; the drawdown fell in 5 of 8 configurations and the return fell in 4 of 8.
- In the 2022 bear year the median result moved from -1.9% to +0.1%.
- With the HMM regime gate already on, the condition still raised Calmar in 2 of 4 configurations (without the gate: 2 of 4).
- Gates missed most often: Sharpe above 0.7 (7 of 8), Calmar above 0.5 (7 of 8), 75% of rolling 12-month windows positive (7 of 8), profit factor above 1.2 (1 of 8).
- Reading: the condition changed little — it rarely binds where the base rule's losses are, so the losses that break the Calmar and consistency gates remain. A stricter version would be a new, pre-registered test, not an edit of this one.

## H2 — a volume (attention) confirmation for S1 entries: **confirmed**

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| S1+VC BTC-USDT 4H [none] | none | +11.5% | +2.5% | 0.44 | 1.36 | 8.5% | 0.30 | 98 | 43% | 0.9% | 68.3% | -6.8% | 75.0% | 0.08 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC BTC-USDT 4H [gate] | none | +20.2% | +4.3% | 0.71 | 1.72 | 7.8% | 0.55 | 83 | 48% | 0.8% | 82.9% | -1.5% | 100.0% | 0.22 | - | **PASS** | +2.0% / PF 1.41 / 25 tr ✓ |
| S1+VC ETH-USDT 4H [none] | none | +7.8% | +1.8% | 0.34 | 1.26 | 8.9% | 0.20 | 100 | 44% | 0.7% | 56.1% | +0.2% | 100.0% | 0.09 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ETH-USDT 4H [gate] | none | +13.9% | +3.0% | 0.54 | 1.37 | 7.9% | 0.38 | 108 | 51% | 0.8% | 85.4% | -0.4% | 100.0% | 0.19 | Sharpe above 0.7, Calmar above 0.5 | fail | untouched |
| S1+VC BTC-USDT 6H [none] | time30 | +14.7% | +3.2% | 0.57 | 1.42 | 8.4% | 0.38 | 93 | 41% | 0.8% | 63.4% | -4.9% | 100.0% | 0.12 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC BTC-USDT 6H [gate] | none | +13.3% | +2.9% | 0.51 | 1.40 | 8.3% | 0.35 | 84 | 42% | 0.8% | 78.0% | -2.6% | 75.0% | 0.14 | Sharpe above 0.7, Calmar above 0.5 | fail | untouched |
| S1+VC ETH-USDT 6H [none] | tp2 | +9.1% | +2.0% | 0.39 | 1.36 | 8.8% | 0.23 | 74 | 51% | 0.4% | 53.7% | -3.8% | 100.0% | 0.11 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ETH-USDT 6H [gate] | none | +6.3% | +1.4% | 0.32 | 1.37 | 7.3% | 0.19 | 43 | 33% | 0.3% | 34.1% | -4.2% | 100.0% | 0.06 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |

Beside the base rule (same instrument, timeframe and mode; Sprint 2c's stored numbers, reproduced in this run):

| Configuration | Base | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1+VC BTC-USDT 4H [none] | S1 BTC-USDT 4H [none] | 0.25 → 0.30 | +2.1% → +2.5% | 8.3% → 8.5% | 0.37 → 0.44 | 1.23 → 1.36 | 184 → 98 | 52% → 43% | 61.0% → 68.3% | -4.4% → -6.8% | -4.4% → -6.8% | no / no |
| S1+VC BTC-USDT 4H [gate] | S1 BTC-USDT 4H [gate] | 0.15 → 0.55 | +1.6% → +4.3% | 10.5% → 7.8% | 0.29 → 0.71 | 1.18 → 1.72 | 151 → 83 | 49% → 48% | 65.9% → 82.9% | -2.7% → -1.5% | -2.7% → -1.5% | no / yes |
| S1+VC ETH-USDT 4H [none] | S1 ETH-USDT 4H [none] | -0.00 → 0.20 | -0.0% → +1.8% | 13.4% → 8.9% | 0.03 → 0.34 | 1.01 → 1.26 | 225 → 100 | 58% → 44% | 31.7% → 56.1% | -4.5% → +0.2% | -4.5% → +0.8% | no / no |
| S1+VC ETH-USDT 4H [gate] | S1 ETH-USDT 4H [gate] | 0.11 → 0.38 | +1.3% → +3.0% | 11.5% → 7.9% | 0.25 → 0.54 | 1.18 → 1.37 | 150 → 108 | 47% → 51% | 39.0% → 85.4% | -3.0% → -0.4% | -3.0% → -0.4% | no / no |
| S1+VC BTC-USDT 6H [none] | S1 BTC-USDT 6H [none] | 0.38 → 0.38 | +3.5% → +3.2% | 9.2% → 8.4% | 0.58 → 0.57 | 1.40 → 1.42 | 155 → 93 | 50% → 41% | 68.3% → 63.4% | -4.9% → -4.9% | -4.9% → -4.9% | no / no |
| S1+VC BTC-USDT 6H [gate] | S1 BTC-USDT 6H [gate] | 0.33 → 0.35 | +3.8% → +2.9% | 11.4% → 8.3% | 0.63 → 0.51 | 1.42 → 1.40 | 146 → 84 | 53% → 42% | 73.2% → 78.0% | -4.2% → -2.6% | -4.2% → -2.6% | no / no |
| S1+VC ETH-USDT 6H [none] | S1 ETH-USDT 6H [none] | 0.42 → 0.23 | +3.4% → +2.0% | 8.2% → 8.8% | 0.58 → 0.39 | 1.31 → 1.36 | 165 → 74 | 54% → 51% | 68.3% → 53.7% | -2.2% → -3.8% | -2.2% → -1.0% | no / no |
| S1+VC ETH-USDT 6H [gate] | S1 ETH-USDT 6H [gate] | 0.37 → 0.19 | +2.7% → +1.4% | 7.5% → 7.3% | 0.51 → 0.32 | 1.38 → 1.37 | 113 → 43 | 41% → 33% | 80.5% → 34.1% | -1.8% → -4.2% | -1.8% → -0.5% | no / no |

**Confirmed.** S1+VC BTC-USDT 4H [gate] passed every walk-forward gate and the untouched 12 months confirmed it; it joins the paper fleet's shortlist (below). The holdout's falling direction was known before this study, so the forward fleet, not this confirmation, is the judge.

## H3 — dual momentum between BTC and ETH: **failed walk-forward**

The combined one-position curve per timeframe and regime mode (judged), built bar by bar from the two legs' stitched out-of-sample returns:

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| DM BTC+ETH 4H [none] | none/none | +1.9% | +0.4% | 0.10 | 1.03 | 15.0% | 0.03 | 301 | 58% | 2.5% | 43.9% | -6.9% | 71.4% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| DM BTC+ETH 4H [gate] | time30/tp2 | +1.7% | +0.4% | 0.09 | 1.03 | 12.8% | 0.03 | 238 | 54% | 2.2% | 46.3% | -4.5% | 0.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| DM BTC+ETH 6H [none] | tp2/tp2 | +12.9% | +2.8% | 0.44 | 1.19 | 14.0% | 0.20 | 258 | 54% | 2.2% | 53.7% | -1.3% | 37.5% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| DM BTC+ETH 6H [gate] | time30/tp2 | +10.5% | +2.3% | 0.37 | 1.18 | 12.9% | 0.18 | 223 | 50% | 1.9% | 48.8% | -4.5% | 0.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |

The legs on their own (components, not judged):

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| DM-BTC BTC-USDT 4H [none] | none | +2.1% | +0.5% | 0.12 | 1.06 | 11.4% | 0.04 | 170 | 36% | 1.6% | 43.9% | -3.2% | 71.4% | 0.00 | - | leg (not judged) | untouched |
| DM-BTC BTC-USDT 4H [gate] | time30 | +1.3% | +0.3% | 0.08 | 1.05 | 10.4% | 0.03 | 132 | 33% | 1.4% | 46.3% | -1.7% | 0.0% | 0.01 | - | leg (not judged) | untouched |
| DM-ETH ETH-USDT 4H [none] | none | -0.1% | -0.0% | 0.01 | 1.00 | 9.9% | -0.00 | 131 | 21% | 0.9% | 51.2% | -3.8% | 75.0% | 0.03 | - | leg (not judged) | untouched |
| DM-ETH ETH-USDT 4H [gate] | tp2 | +0.4% | +0.1% | 0.04 | 1.02 | 10.1% | 0.01 | 106 | 21% | 0.8% | 51.2% | -3.7% | 42.9% | 0.04 | - | leg (not judged) | untouched |
| DM-BTC BTC-USDT 6H [none] | tp2 | -1.9% | -0.4% | -0.06 | 0.96 | 9.6% | -0.05 | 171 | 34% | 1.6% | 41.5% | -2.4% | 37.5% | 0.00 | - | leg (not judged) | untouched |
| DM-BTC BTC-USDT 6H [gate] | time30 | +2.9% | +0.7% | 0.15 | 1.08 | 10.2% | 0.06 | 131 | 31% | 1.3% | 46.3% | -1.7% | 0.0% | 0.00 | - | leg (not judged) | untouched |
| DM-ETH ETH-USDT 6H [none] | tp2 | +15.0% | +3.3% | 0.73 | 1.72 | 8.3% | 0.40 | 87 | 20% | 0.6% | 53.7% | -1.1% | 87.5% | 0.23 | - | leg (not judged) | untouched |
| DM-ETH ETH-USDT 6H [gate] | tp2 | +7.4% | +1.7% | 0.40 | 1.35 | 11.1% | 0.15 | 92 | 18% | 0.6% | 39.0% | -4.6% | 75.0% | 0.07 | - | leg (not judged) | untouched |

Beside the plain S1 rule on each market and the hold + policy controls (same timeframe and mode; Sprint 2c's stored numbers, reproduced in this run):

| Combined configuration | Combined Calmar / CAGR / max DD / trades / exposure | S1 BTC Calmar / CAGR / max DD | S1 ETH Calmar / CAGR / max DD | Hold+policy BTC / ETH Calmar | Leg BTC Calmar / trades | Leg ETH Calmar / trades | 2022 combined / S1 BTC / S1 ETH |
|---|---|---|---|---|---|---|---|
| DM BTC+ETH 4H [none] | 0.03 / +0.4% / 15.0% / 301 / 58% | 0.25 / +2.1% / 8.3% | -0.00 / -0.0% / 13.4% | 0.45 / 0.20 | 0.04 / 170 | -0.00 / 131 | -6.9% / -4.4% / -4.5% |
| DM BTC+ETH 4H [gate] | 0.03 / +0.4% / 12.8% / 238 / 54% | 0.15 / +1.6% / 10.5% | 0.11 / +1.3% / 11.5% | 0.45 / 0.20 | 0.03 / 132 | 0.01 / 106 | -4.5% / -2.7% / -3.0% |
| DM BTC+ETH 6H [none] | 0.20 / +2.8% / 14.0% / 258 / 54% | 0.38 / +3.5% / 9.2% | 0.42 / +3.4% / 8.2% | 0.33 / 0.26 | -0.05 / 171 | 0.40 / 87 | -1.3% / -4.9% / -2.2% |
| DM BTC+ETH 6H [gate] | 0.18 / +2.3% / 12.9% / 223 / 50% | 0.33 / +3.8% / 11.4% | 0.37 / +2.7% / 7.5% | 0.33 / 0.26 | 0.06 / 131 | 0.15 / 92 | -4.5% / -4.2% / -1.8% |

**Failure analysis** (computed from the numbers above):

- The one-position curve's median Calmar was 0.11 against 0.31 for the better of the two plain S1 rules on the same bars: it beat both plain S1 rules in 0 of 4 configurations and the hold + policy controls of both markets in 0 of 4.
- It traded a median 57 times a year against 35 for plain S1 on one market, and was in the market 54% of the time against 51% for plain S1: the switches between the two markets are extra trades at full cost, and the 'both trends up' condition keeps the position out whenever one market lags.
- In the 2022 bear year the median result was -4.5% against -3.6% for plain S1.
- The legs on their own: DM-BTC BTC-USDT 4H [none] Calmar 0.04, 170 trades, PF 1.06; DM-BTC BTC-USDT 4H [gate] Calmar 0.03, 132 trades, PF 1.05; DM-ETH ETH-USDT 4H [none] Calmar -0.00, 131 trades, PF 1.00; DM-ETH ETH-USDT 4H [gate] Calmar 0.01, 106 trades, PF 1.02; DM-BTC BTC-USDT 6H [none] Calmar -0.05, 171 trades, PF 0.96; DM-BTC BTC-USDT 6H [gate] Calmar 0.06, 131 trades, PF 1.08; DM-ETH ETH-USDT 6H [none] Calmar 0.40, 87 trades, PF 1.72; DM-ETH ETH-USDT 6H [gate] Calmar 0.15, 92 trades, PF 1.35.
- Gates missed most often: profit factor above 1.2 (4 of 4), Sharpe above 0.7 (4 of 4), Calmar above 0.5 (4 of 4), 75% of rolling 12-month windows positive (4 of 4).
- Reading: concentrating the one position in the stronger market did not beat simply running the plain trend rule on each market — the relative-strength switches added trades and fees without adding return, and requiring both trends to be up removed exposure in the months the trend rules earn their return. The idea is not where the missing edge is.

## The comparison lines — hold + policy controls and the plain S1 / S2 rules (Sprint 2c's numbers, reproduced here)

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| hold BTC-USDT 4H [none] | none | +14.8% | +3.2% | 0.59 | 2.88 | 7.2% | 0.45 | 9 | 100% | 0.1% | 70.7% | -4.7% | - | 0.89 | - | control | -4.3% / PF 0.00 / 1 tr ✗ |
| S1 BTC-USDT 4H [none] | none | +9.4% | +2.1% | 0.37 | 1.23 | 8.3% | 0.25 | 184 | 52% | 1.4% | 61.0% | -4.4% | 75.0% | 0.04 | - | comparison line | untouched |
| S1 BTC-USDT 4H [gate] | none | +7.0% | +1.6% | 0.29 | 1.18 | 10.5% | 0.15 | 151 | 49% | 1.2% | 65.9% | -2.7% | 100.0% | 0.06 | - | comparison line | untouched |
| S2 BTC-USDT 4H [none] | none | +14.9% | +3.3% | 0.57 | 1.46 | 8.7% | 0.38 | 85 | 46% | 0.8% | 61.0% | -4.6% | 100.0% | 0.11 | - | comparison line | untouched |
| S2 BTC-USDT 4H [gate] | none | +24.7% | +5.2% | 0.86 | 1.94 | 6.5% | 0.80 | 69 | 43% | 0.7% | 80.5% | -3.2% | 100.0% | 0.19 | - | comparison line | -4.9% / PF 0.28 / 21 tr ✗ |
| hold ETH-USDT 4H [none] | none | +7.8% | +1.8% | 0.38 | 1.83 | 8.6% | 0.20 | 9 | 100% | 0.1% | 63.4% | -4.1% | - | 0.78 | - | control | -2.6% / PF 0.00 / 1 tr ✗ |
| S1 ETH-USDT 4H [none] | tp2 | -0.1% | -0.0% | 0.03 | 1.01 | 13.4% | -0.00 | 225 | 58% | 1.4% | 31.7% | -4.5% | 25.0% | 0.02 | - | comparison line | untouched |
| S1 ETH-USDT 4H [gate] | none | +5.6% | +1.3% | 0.25 | 1.18 | 11.5% | 0.11 | 150 | 47% | 1.1% | 39.0% | -3.0% | 87.5% | 0.10 | - | comparison line | untouched |
| S2 ETH-USDT 4H [none] | none | +16.7% | +3.6% | 0.62 | 1.63 | 8.8% | 0.41 | 77 | 42% | 0.5% | 63.4% | -0.6% | 100.0% | 0.11 | - | comparison line | untouched |
| S2 ETH-USDT 4H [gate] | time30 | +3.2% | +0.7% | 0.16 | 1.10 | 10.9% | 0.07 | 86 | 40% | 0.6% | 70.7% | -0.8% | 80.0% | 0.02 | - | comparison line | untouched |
| hold BTC-USDT 6H [none] | none | +11.8% | +2.6% | 0.49 | 2.37 | 8.0% | 0.33 | 9 | 100% | 0.1% | 73.2% | -4.8% | - | 0.84 | - | control | -4.0% / PF 0.00 / 1 tr ✗ |
| S1 BTC-USDT 6H [none] | none | +15.9% | +3.5% | 0.58 | 1.40 | 9.2% | 0.38 | 155 | 50% | 1.3% | 68.3% | -4.9% | 100.0% | 0.05 | - | comparison line | untouched |
| S1 BTC-USDT 6H [gate] | none | +17.5% | +3.8% | 0.63 | 1.42 | 11.4% | 0.33 | 146 | 53% | 1.2% | 73.2% | -4.2% | 100.0% | 0.06 | - | comparison line | untouched |
| S2 BTC-USDT 6H [none] | none | +3.0% | +0.7% | 0.16 | 1.10 | 10.0% | 0.07 | 69 | 35% | 0.7% | 58.5% | -3.5% | 100.0% | 0.02 | - | comparison line | untouched |
| S2 BTC-USDT 6H [gate] | none | +5.1% | +1.2% | 0.28 | 1.22 | 9.9% | 0.12 | 48 | 30% | 0.4% | 56.1% | -1.7% | 100.0% | 0.01 | - | comparison line | untouched |
| hold ETH-USDT 6H [none] | none | +11.0% | +2.5% | 0.50 | 2.04 | 9.6% | 0.26 | 9 | 100% | 0.1% | 65.9% | -3.5% | - | 0.85 | - | control | -2.9% / PF 0.00 / 1 tr ✗ |
| S1 ETH-USDT 6H [none] | none | +15.6% | +3.4% | 0.58 | 1.31 | 8.2% | 0.42 | 165 | 54% | 1.1% | 68.3% | -2.2% | 100.0% | 0.19 | - | comparison line | untouched |
| S1 ETH-USDT 6H [gate] | none | +12.4% | +2.7% | 0.51 | 1.38 | 7.5% | 0.37 | 113 | 41% | 0.9% | 80.5% | -1.8% | 100.0% | 0.21 | - | comparison line | untouched |
| S2 ETH-USDT 6H [none] | none | +14.8% | +3.2% | 0.57 | 1.39 | 9.1% | 0.36 | 85 | 36% | 0.6% | 61.0% | -2.1% | 100.0% | 0.14 | - | comparison line | untouched |
| S2 ETH-USDT 6H [gate] | none | +24.1% | +5.1% | 0.92 | 2.01 | 8.3% | 0.62 | 52 | 41% | 0.3% | 70.7% | +0.7% | 100.0% | 0.26 | - | comparison line | untouched |

Data spans: BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); ETH-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); BTC-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); ETH-USDT 6H: 2019-12-29->2026-10-20 (9949 bars).

## The untouched 12 months

Opened once, only for configurations that passed every walk-forward gate (and the hold + policy controls as the comparison line). Verdict ✓ = positive return, PF > 1 and ≥ 10 trades. The holdout's falling direction was known before the run (see the pre-registration).

| Configuration | Return | Max DD | PF | Trades | Verdict |
|---|---:|---:|---:|---:|---|
| hold BTC-USDT 4H [none] | -4.3% | 5.2% | 0.00 | 1 | control (comparison line) |
| S2 BTC-USDT 4H [gate] | -4.9% | 6.3% | 0.28 | 21 | comparison line |
| S1+VC BTC-USDT 4H [gate] | +2.0% | 4.4% | 1.41 | 25 | confirmed |
| hold ETH-USDT 4H [none] | -2.6% | 4.0% | 0.00 | 1 | control (comparison line) |
| hold BTC-USDT 6H [none] | -4.0% | 5.5% | 0.00 | 1 | control (comparison line) |
| hold ETH-USDT 6H [none] | -2.9% | 4.0% | 0.00 | 1 | control (comparison line) |

### Every opening of the holdout (ledger)

Each run that opened a holdout appends its openings to `docs/research/research_round_1_holdout_ledger.json`; earlier looks stay visible here even when a later run replaces the numbers above.

| Run | Configuration | Role | Return | Max DD | PF | Trades | Verdict |
|---|---|---|---:|---:|---:|---:|---|
| 1 (2026-11-04 18:50 UTC) | hold BTC-USDT 4H [none] | control | -4.3% | 5.2% | 0.00 | 1 | comparison |
| 1 (2026-11-04 18:50 UTC) | S2 BTC-USDT 4H [gate] | reproduction | -4.9% | 6.3% | 0.28 | 21 | comparison |
| 1 (2026-11-04 18:50 UTC) | S1+VC BTC-USDT 4H [gate] | configuration | +2.0% | 4.4% | 1.41 | 25 | confirmed |
| 1 (2026-11-04 18:50 UTC) | hold ETH-USDT 4H [none] | control | -2.6% | 4.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 18:50 UTC) | hold BTC-USDT 6H [none] | control | -4.0% | 5.5% | 0.00 | 1 | comparison |
| 1 (2026-11-04 18:50 UTC) | hold ETH-USDT 6H [none] | control | -2.9% | 4.0% | 0.00 | 1 | comparison |

## Paper-fleet shortlist

Confirmed passers appended to `docs/research/paper_fleet_shortlist_v1c.json` with a `source` tag (existing entries and running accounts untouched):

- S1+VC BTC-USDT 4H (hmm3 bear>=0.5 gate): walk-forward Calmar 0.55, holdout +2.0%

Shortlist file: docs/research/paper_fleet_shortlist_v1c.json now lists 13 configurations (23 fleet accounts).

## Owner decisions (nothing below is decided by this report)

- **Fleet.** 1 new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). Recommended: let them run; judge them at G7 with the rest.
- **What the verdicts mean.** H1: failed walk-forward; H2: confirmed; H3: failed walk-forward. No gate, parameter, condition or verdict rule changed after the results. If a gate looks wrong, that is a note for the next pre-registered round (R16), not an edit of this one.
- **Next round.** Plan row R16 draws its hypotheses from the failure analyses above and R12's; the readings there say which ideas are not worth another test.

## Method notes and caveats

- The rules were not re-implemented: Sprint 2c's runner module ran them; the reproduction table shows the same code with the cross-asset context gives the stored numbers for hold, S1 and S2.
- The new conditions gate entries only (an open position is left to the base rule's own exits and stop), exactly as the regime gate and the S5 filter do; H3's legs are states (a leg exits when its condition ends, so the position moves to the other market at the next open).
- A cross-asset rule sees the other market's bar that closed at the same instant, never a later one; where that bar is missing it does not enter.
- H3's combined curve multiplies the legs' bar returns, which is exact for a fraction-of-equity sizing while at most one leg is in the market; the drawdown ladder acted on each leg's own equity, so a ladder on the combined account would differ slightly. Its DSR is a probabilistic Sharpe against the larger of the legs' expected maximum Sharpe; its robustness share is the smaller leg's.
- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed policy sizing is Sprint 2b's; none of them was adapted to the new rules.
- The reproduction re-runs Sprint 2c's own passers through the same holdout code path (S2 BTC-USDT 4H [gate]), so their already-opened 12 months appear again in the ledger as comparison lines with Sprint 2c's numbers; that is a repeat of a known result, not a new look.
- 20 judged configurations are 20 more comparisons on the same six years; a pass or two among them at the Sprint 2c pass rate would be expected by chance, which is why the holdout and the forward fleet, not single passes, carry the verdict.
- The holdout's falling direction was known before this study; every one of the three conditions reduces time in the market. Confirmation there is necessary, not sufficient.
- Every number is a simulation on historical public data and proves nothing about the future.
