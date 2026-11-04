# Research round 2 — three pre-registered hypotheses from the R12 and R13 failure analyses (walk-forward, SIMULATION ONLY)

Generated 2026-11-04 21:33 UTC by `scripts/run_research_round_2.py` (plan row R16; 11.9 min). Rules: Sprint 2c's, run by `scripts/run_research_v1c.py`'s own `run_series`, unchanged (policy sizing `vt10/30 crash15/90dh ladder`, regime gate `hmm3 bear>=0.5 gate`, S0 filter S0 vol×3 spread p98 gap3 FOMC±6/6h, walk-forward train 540d → purge 7d → test 180d, fee 0.10% + slippage 0.050% per side, brackets ['none', 'tp2', 'trail1', 'time30']). Data: PUBLIC OKX spot candles of nine markets (1H and 4H stored, 6H resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ 2026-10-20T10:00:00+00:00). Holdout: the last 12 months (2025-10-20->2026-10-20), opened once and only for configurations that passed walk-forward.

**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy to deploy. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we did.** We tested up to three more pre-registered hypotheses drawn from the failure analyses of the replication study (R12) and research round 1 (R13) — H4: the volume (attention) confirmation on the replication markets; H5: a slow trend filter for the breakout rule; H6: the slow trend filter as the exposure rule — each written down with its rule, parameters, markets, timeframes, gates, readings and verdict rule before the first run. Everything else is Sprint 2c's: the same grids, exit brackets, no-trade filter, regime gate, fixed sizing, walk-forward windows and gates. Before any new rule was judged, the same unchanged code re-ran hold, S1 and S2 on every market of the round and matched the stored numbers — Sprint 2c's for BTC/ETH, the replication study's for the other seven markets — in 90 of 90 configurations. 68 configurations on 9 markets were judged on 2019-12-16->2026-10-20 after fees and slippage; the last 12 months (2025-10-20->2026-10-20) stayed untouched except for configurations that passed.
- **H4 — the volume (attention) confirmation on the replication markets: confirmed.** 5 of 28 configurations passed every gate (S1+VC DOGE-USDT 4H [none], S1+VC DOGE-USDT 4H [gate], S1+VC SOL-USDT 4H [none], S1+VC DOGE-USDT 6H [gate], S1+VC SOL-USDT 6H [none]). Best: S1+VC SOL-USDT 6H [none] with Calmar 1.54, +9.1% a year at a 5.9% drawdown. Beside S1 it raised Calmar in 25 of 28 configurations (median 0.15 → 0.41) and removed a median 55% of its trades. Directional reading: replicates in direction (25 of 28; the 5% level needs 19). Round 1's pattern (the gain in the gated 4H configurations) is consistent here: Calmar rose in 6 of 7 markets' 4H [gate] configurations (needs 5).
- **H5 — a slow trend filter for the breakout rule: failed walk-forward.** 0 of 20 configurations passed every gate. Best: S2+TF TRX-USDT 6H [gate] with Calmar 0.95, +4.9% a year at a 5.2% drawdown, missing 75% of rolling 12-month windows positive, at least 30 trades. Beside S2 it raised Calmar in 4 of 20 configurations (median 0.43 → 0.00) and removed a median 87% of its trades. Directional reading: does not replicate in direction (4 of 20; the 5% level needs 15). The protocol's selection rule (20 train trades) let it trade in only 53 of 180 walk-forward windows, so the result measures the selection rule more than the idea: untested here rather than refuted.
- **H6 — the slow trend filter as the exposure rule: failed walk-forward.** 0 of 20 configurations passed every gate. Best: TF DOGE-USDT 6H [gate] with Calmar 0.38, +1.2% a year at a 3.3% drawdown, missing Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades. Beside hold + policy it raised Calmar in 3 of 20 configurations (median 0.23 → 0.00) and beat the control by more than 0.1 Calmar in 3. Directional reading: does not replicate in direction (3 of 20; the 5% level needs 15). The protocol's selection rule (20 train trades) let it trade in only 13 of 180 walk-forward windows, so the result measures the selection rule more than the idea: untested here rather than refuted.
- **Holdout.** The untouched 12 months then confirmed 1 (S1+VC DOGE-USDT 4H [gate]) and contradicted 4 (S1+VC DOGE-USDT 4H [none], S1+VC SOL-USDT 4H [none], S1+VC DOGE-USDT 6H [gate], S1+VC SOL-USDT 6H [none]). The holdout's falling direction was known for every market before this study (pre-registered caveat), and a slow trend filter is expected to sit out a bear year, so a confirmation here is necessary, not sufficient; the paper fleet's forward record is the judge. The ledger below names, beside every opening, the earlier look at the same months by the comparison line.
- **Binding gates.** 75% of rolling 12-month windows positive (62 of 68), Sharpe above 0.7 (56 of 68), Calmar above 0.5 (52 of 68), at least 30 trades (37 of 68). Sprint 2c's own pass rate was 4 of 108, so two or three passes among 68 comparisons would be expected by chance; the holdout and the forward fleet, not the pass count, carry the verdict.
- **Paper fleet.** 1 confirmed configuration(s) were appended to the fleet's shortlist with a source tag (S1+VC DOGE-USDT 4H); a running fleet takes them as new accounts at its next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading. Shortlist file: docs/research/paper_fleet_shortlist_v1c.json now lists 14 configurations (24 fleet accounts).

## Fixed before the first run (the pre-registration)

Pre-registration hash (text, file and configuration): `eb017c5b15db266c8da9b0e3d1739e1a4735783fc58dc1d4f5fd903140350fa5`; file `docs/research/research_round_2_preregistration.json` written 2026-11-04T21:20:59+00:00.

- **fixed_on**: 2026-11-04, before any run (plan row R16)
- **question**: Do the two ideas the replication study (R12) and research round 1 (R13) left as the credible next tests — the volume (attention) confirmation on the seven replication markets, and a SLOW own-market trend filter (the close above its 200-day moving average) for the breakout rule and for the risk-managed exposure itself — give configurations that pass the Sprint 2c gates on the walk-forward and are then confirmed by the untouched 12 months?
- **why**: From the failure analyses. R13: the volume confirmation (H2 there) was confirmed once, on BTC-USDT 4H with the regime gate; it gained most where the base rule was weakest (the gated 4H rules) and lost on 6H, and the report named 'the attention idea on R12's markets, pre-registered and fixed a priori, never swept' as the candidate for this round — a test on seven markets the idea has never seen is the cleanest check of whether that one pass was luck. R12: the breakout family (S2) passed walk-forward on BTC in Sprint 2c and on ADA, DOGE and TRX, and the untouched 12 months — a bear year — contradicted it on every one of them; the HMM regime gate (a volatility-regime detector) did not keep it out, and R13's H1 showed a FAST trend condition (BTC's 7/14/30-day momentum vote) changes little. Untested so far is the SLOW trend condition the literature has used since Faber (2007) — the close above its 200-day moving average — the plain answer to 'buy breakouts only in uptrends' (plan section 2.6: trend is the one robust family; drawdown control is the problem to solve). R12 and 2c also found hold + policy sizing the strongest control (beaten by more than 0.1 Calmar on only 4 of 14 series) yet a loser on every market's untouched 12 months; the Phase 7/8 product candidate is that risk-managed exposure, and the slow trend filter applied to it is the standard remedy for its bear-year losses and the benchmark that says whether the breakout adds anything to the filter. Not retested, per the R13 readings: the fast BTC-trend condition for ETH (changed little), dual momentum (churned), and the strictness of the volume confirmation on BTC/ETH (deferred: it would be a second look at the same months on the same markets with a near-identical rule; the forward fleet judges the z > 1 version first).
- **protocol**: Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), unchanged, with Sprint 2c's defaults: the candidates' grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the fixed policy sizing vt10/30 crash15/90dh ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM, bear >= 0.5, fitted on every window's train slice; modes none and gate), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then bracket) and the v1c gates — checked against the stored Sprint 2c run before the study runs; the new rules need no runner change (they use only the market's own candles)
- **data**: OKX public 1H and 4H spot candles of the nine markets (4H stored, 6H resampled from 1H), frozen in a study lake at Sprint 2c's data end (bar close <= 2026-10-20T10:00:00+00:00) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window as in Sprint 2c, R12 and R13; Binance public funding and open interest for the S0/S5 machinery as before (the new rules do not use them). The seven replication markets are exactly those the R12 pre-registration fixed (checked against that file); the five trend-filter markets are the Sprint 2c pair plus the three where the breakout rule was contradicted (ADA, DOGE, TRX).
- **reproduction**: before any new rule is judged, the same code path re-runs hold, S1 and S2 on every market of the round (4H and 6H, modes none and gate) and must give the stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts — Sprint 2c's for BTC-USDT and ETH-USDT, the replication study's for the seven other markets; otherwise the study stops
- **gates**: the v1c gates unchanged (research/report_v1c.py GATES): PF > 1.2, max DD < 20 %, Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, no calendar year below -10 %, >= 30 trades, >= 50 % of +-30 % neighbours profitable
- **verdicts**: a configuration passes when it passes every gate on the walk-forward; a hypothesis is 'confirmed' when at least one of its configurations passes and is confirmed by its holdout, 'passed walk-forward, contradicted by the holdout' when some pass and none is confirmed, and 'failed walk-forward' when none passes; the directional and pattern readings are reported beside the label and never replace it; every failing hypothesis gets a failure analysis computed from the numbers beside its comparison line
- **holdout**: the last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward gate, only by the full pre-registered study (every hypothesis, market, timeframe and mode, with the reproduction, never --quick); the v1c verdict (positive return, PF > 1, >= 10 trades); every opening goes into an append-only ledger the report shows, and beside every opening the report names the earlier look at the same months by the configuration's comparison line (Sprint 2c's or the replication study's stored holdout), because a new rule on a market whose base rule already opened its holdout is a near-second look. CAVEAT, stated before the run: the holdout's falling direction is known for every market (hold + policy lost on all nine over those months, R12 and R5b/R9), every condition here reduces time in the market, and a slow trend filter in particular is expected to sit out a bear year; a confirmation is therefore necessary but not sufficient, and the paper fleet's forward record is the judge
- **fleet**: a confirmed configuration is appended to the paper fleet's shortlist as a new account with a source tag (existing entries and running accounts untouched; a walk-forward pass alone adds nothing); the fleet must be able to load the amended shortlist, otherwise the file is restored and the report says so (the R12 rule); S1+VC on a replication market needs only that market's public candles, which the fleet already fetches; TF and S2+TF are registered candidates that use the market's own candles
- **no_changes_after_results**: no gate, parameter, condition, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so

### H4 — the volume (attention) confirmation on the replication markets

- **rule**: S1+VC exactly as research round 1 registered it: S1 with Sprint 2c's parameters, grid and brackets, new entries allowed only on bars whose volume z-score over the trailing 30 days is above 1 (the bar's own volume against the trailing mean and standard deviation of the bars of that window); entries only, an open position is left to the base rule's own exits and stop. The window and the threshold are fixed and never in a grid.
- **candidates**: ['S1+VC']
- **markets**: ['XRP-USDT', 'DOGE-USDT', 'LINK-USDT', 'TRX-USDT', 'ADA-USDT', 'LTC-USDT', 'SOL-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **comparison**: the same S1 configuration on the same market without the condition (the replication study's stored numbers, reproduced in this run)
- **readings**: (a) per configuration, the v1c gates and the holdout rule; (b) a pre-registered directional reading: the attention effect 'replicates in direction' when the condition raises Calmar beside S1 in at least k of the n judged configurations, k being the smallest count whose one-sided binomial(n, 1/2) tail is at most 0.05 (19 of 28 when every configuration runs; 14 would be expected by chance) — the configurations share markets across two timeframes and two modes, so this is indicative, not a test of independent trials; (c) the pattern check: round 1's gain was concentrated in the gated 4H configurations, so the same reading is 'consistent with round 1' when the condition raises Calmar in at least 5 of the 7 markets' 4H [gate] configurations, otherwise 'not consistent'
- **why**: one confirmation among 20 comparisons on BTC/ETH; seven markets the idea has never seen are the honest replication

### H5 — a slow trend filter for the breakout rule

- **rule**: S2+TF: the Donchian breakout rule (S2) exactly as in Sprint 2c — parameters, grid and brackets — with new entries allowed only while the market's close is above its 200-day simple moving average (200 days in bars of the timeframe: 1200 at 4H, 800 at 6H; the average needs that much history, so no entry is possible before it). Entries only: an open position is left to the base rule's own exits and stop. The length is fixed and never in a grid.
- **candidates**: ['S2+TF']
- **markets**: ['BTC-USDT', 'ETH-USDT', 'ADA-USDT', 'DOGE-USDT', 'TRX-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **comparison**: the same S2 configuration on the same market without the filter (Sprint 2c's stored numbers for BTC/ETH, the replication study's for ADA, DOGE and TRX, reproduced in this run)
- **readings**: (a) per configuration, the v1c gates and the holdout rule; (b) the directional reading as for H4 (Calmar beside S2 in at least k of n, k at the 5 % tail); (c) for every S2 configuration that passed walk-forward and was contradicted by the untouched 12 months in Sprint 2c or the replication study (taken from the stored results), whether S2+TF passes walk-forward on that series and, if it does, what its holdout says — shown with the warning that the base rule's holdout loss in a bear year is already known and a trend filter is expected to sit that year out, so this comparison carries no verdict weight; (d) beside TF alone (H6) on the same series and mode: 'the breakout adds to the filter' where S2+TF's Calmar exceeds TF's
- **why**: the breakout family's walk-forward passes were contradicted everywhere by a bear year the volatility gate did not detect; the slow trend is the untested regime definition

### H6 — the slow trend filter as the exposure rule

- **rule**: TF: long while the close is above its 200-day simple moving average, flat otherwise (Faber 2007's rule on a 24/7 market, evaluated at every bar close); no stop — the rule's exit is the cross back below the average — under the same fixed policy sizing, S0 no-trade filter and regime gate as every candidate, and the protocol's exit brackets (none / tp2 / trail1 / time30: without a stop the take-profit and trailing brackets are inert, so the walk-forward's only choice is between no bracket and the 30-day time stop). The average's length is the rule's one parameter, fixed at 200 days and never selected (a single grid value), but perturbed by +-30 % (140 and 260 days) by the protocol's robustness replay like every rule's numeric parameters. The protocol's selection rule (a bracket variant needs 20 train trades) applies unchanged: a window in which no variant reaches 20 trades stays flat, and the report shows how many windows traded.
- **candidates**: ['TF']
- **markets**: ['BTC-USDT', 'ETH-USDT', 'ADA-USDT', 'DOGE-USDT', 'TRX-USDT']
- **timeframes**: ['4H', '6H']
- **regime_modes**: ['none', 'gate']
- **comparison**: hold + policy sizing on the same market and timeframe (the control; its one mode is 'none', so TF [gate] is compared with the same control), and S2+TF (H5) on the same series and mode
- **readings**: (a) per configuration, the v1c gates and the holdout rule; (b) Sprint 2c's acceptance-clause statistic: TF 'beats hold + policy' on a series when its Calmar exceeds the control's by more than 0.1; (c) the directional reading as for H4, against the control's Calmar
- **why**: hold + policy is the product candidate and the strongest control, and it lost on every market's untouched 12 months; the slow trend filter is the standard remedy and the benchmark for H5

Protocol check against the stored Sprint 2c run: every parameter the same (checked: brackets, fee, holdout_months, ladder_recovery_days, min_trades, no_trade_label, policy_sizing, positioning_source, purge_days, quick, rebalance_threshold, regime, regime_modes, select_by, slippage, strategies, test_days, timeframes, train_days; new candidates, not in Sprint 2c by design: S1+VC, S2+TF, TF).

Gates (unchanged from Sprint 2c): profit_factor_min 1.2; max_drawdown_max 0.2; sharpe_min 0.7; calmar_min 0.5; rolling_12m_positive_min 0.75; worst_calendar_year_min -0.1; min_trades 30; robust_share_min 0.5; min_year_days 60.

## Reproduction of the stored studies

Before any new rule ran, hold, S1 and S2 on every market of the round went through the same loaded runner and had to give the stored walk-forward numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — Sprint 2c's for BTC-USDT and ETH-USDT, the replication study's for the other seven markets — otherwise the study stops.

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
| hold | XRP-USDT 4H | none | 0.123225 / 0.123225 | 0.549850 / 0.549850 | 0.058370 / 0.058370 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | XRP-USDT 4H | none | -0.094352 / -0.094352 | -0.362590 / -0.362590 | 0.222661 / 0.222661 | 209 / 209 | yes | yes | 0.0e+00 | yes |
| S1 | XRP-USDT 4H | gate | 0.011649 / 0.011649 | 0.075668 / 0.075668 | 0.167107 / 0.167107 | 184 / 184 | yes | yes | 0.0e+00 | yes |
| S2 | XRP-USDT 4H | none | -0.002930 / -0.002930 | 0.012950 / 0.012950 | 0.168466 / 0.168466 | 92 / 92 | yes | yes | 0.0e+00 | yes |
| S2 | XRP-USDT 4H | gate | 0.061278 / 0.061278 | 0.277161 / 0.277161 | 0.122880 / 0.122880 | 110 / 110 | yes | yes | 0.0e+00 | yes |
| hold | DOGE-USDT 4H | none | 0.030347 / 0.030347 | 0.188892 / 0.188892 | 0.068967 / 0.068967 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | DOGE-USDT 4H | none | 0.161999 / 0.161999 | 0.670494 / 0.670494 | 0.063145 / 0.063145 | 252 / 252 | yes | yes | 0.0e+00 | yes |
| S1 | DOGE-USDT 4H | gate | 0.034398 / 0.034398 | 0.199003 / 0.199003 | 0.058151 / 0.058151 | 132 / 132 | yes | yes | 0.0e+00 | yes |
| S2 | DOGE-USDT 4H | none | 0.082571 / 0.082571 | 0.435228 / 0.435228 | 0.062815 / 0.062815 | 59 / 59 | yes | yes | 0.0e+00 | yes |
| S2 | DOGE-USDT 4H | gate | 0.167252 / 0.167252 | 0.806322 / 0.806322 | 0.041935 / 0.041935 | 46 / 46 | yes | yes | 0.0e+00 | yes |
| hold | LINK-USDT 4H | none | 0.070548 / 0.070548 | 0.365437 / 0.365437 | 0.056159 / 0.056159 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | LINK-USDT 4H | none | -0.005712 / -0.005712 | 0.002491 / 0.002491 | 0.128016 / 0.128016 | 219 / 219 | yes | yes | 0.0e+00 | yes |
| S1 | LINK-USDT 4H | gate | 0.073422 / 0.073422 | 0.334953 / 0.334953 | 0.087483 / 0.087483 | 186 / 186 | yes | yes | 0.0e+00 | yes |
| S2 | LINK-USDT 4H | none | -0.039942 / -0.039942 | -0.171570 / -0.171570 | 0.115881 / 0.115881 | 96 / 96 | yes | yes | 0.0e+00 | yes |
| S2 | LINK-USDT 4H | gate | -0.050075 / -0.050075 | -0.229071 / -0.229071 | 0.110998 / 0.110998 | 97 / 97 | yes | yes | 0.0e+00 | yes |
| hold | TRX-USDT 4H | none | 0.363799 / 0.363799 | 1.299326 / 1.299326 | 0.055756 / 0.055756 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | TRX-USDT 4H | none | 0.226087 / 0.226087 | 0.675301 / 0.675301 | 0.153358 / 0.153358 | 282 / 282 | yes | yes | 0.0e+00 | yes |
| S1 | TRX-USDT 4H | gate | 0.188561 / 0.188561 | 0.589395 / 0.589395 | 0.126790 / 0.126790 | 177 / 177 | yes | yes | 0.0e+00 | yes |
| S2 | TRX-USDT 4H | none | 0.240958 / 0.240958 | 0.822637 / 0.822637 | 0.086703 / 0.086703 | 95 / 95 | yes | yes | 0.0e+00 | yes |
| S2 | TRX-USDT 4H | gate | 0.163331 / 0.163331 | 0.631848 / 0.631848 | 0.076365 / 0.076365 | 68 / 68 | yes | yes | 0.0e+00 | yes |
| hold | ADA-USDT 4H | none | 0.055449 / 0.055449 | 0.293413 / 0.293413 | 0.077463 / 0.077463 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ADA-USDT 4H | none | 0.054577 / 0.054577 | 0.258586 / 0.258586 | 0.096417 / 0.096417 | 237 / 237 | yes | yes | 0.0e+00 | yes |
| S1 | ADA-USDT 4H | gate | 0.080907 / 0.080907 | 0.408996 / 0.408996 | 0.112009 / 0.112009 | 161 / 161 | yes | yes | 0.0e+00 | yes |
| S2 | ADA-USDT 4H | none | 0.061862 / 0.061862 | 0.321475 / 0.321475 | 0.081093 / 0.081093 | 80 / 80 | yes | yes | 0.0e+00 | yes |
| S2 | ADA-USDT 4H | gate | 0.044688 / 0.044688 | 0.269155 / 0.269155 | 0.071267 / 0.071267 | 58 / 58 | yes | yes | 0.0e+00 | yes |
| hold | LTC-USDT 4H | none | -0.017866 / -0.017866 | -0.075674 / -0.075674 | 0.075968 / 0.075968 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | LTC-USDT 4H | none | -0.149013 / -0.149013 | -0.614183 / -0.614183 | 0.219263 / 0.219263 | 288 / 288 | yes | yes | 0.0e+00 | yes |
| S1 | LTC-USDT 4H | gate | -0.143234 / -0.143234 | -0.577829 / -0.577829 | 0.219467 / 0.219467 | 203 / 203 | yes | yes | 0.0e+00 | yes |
| S2 | LTC-USDT 4H | none | -0.022255 / -0.022255 | -0.059931 / -0.059931 | 0.120379 / 0.120379 | 118 / 118 | yes | yes | 0.0e+00 | yes |
| S2 | LTC-USDT 4H | gate | -0.124775 / -0.124775 | -0.546291 / -0.546291 | 0.165849 / 0.165849 | 145 / 145 | yes | yes | 0.0e+00 | yes |
| hold | SOL-USDT 4H | none | 0.239317 / 0.239317 | 1.067911 / 1.067911 | 0.067153 / 0.067153 | 7 / 7 | yes | yes | 0.0e+00 | yes |
| S1 | SOL-USDT 4H | none | 0.180933 / 0.180933 | 0.916732 / 0.916732 | 0.075482 / 0.075482 | 141 / 141 | yes | yes | 0.0e+00 | yes |
| S1 | SOL-USDT 4H | gate | 0.060242 / 0.060242 | 0.390331 / 0.390331 | 0.062431 / 0.062431 | 134 / 134 | yes | yes | 0.0e+00 | yes |
| S2 | SOL-USDT 4H | none | 0.117004 / 0.117004 | 0.604717 / 0.604717 | 0.071626 / 0.071626 | 73 / 73 | yes | yes | 0.0e+00 | yes |
| S2 | SOL-USDT 4H | gate | 0.178524 / 0.178524 | 0.909177 / 0.909177 | 0.078044 / 0.078044 | 70 / 70 | yes | yes | 0.0e+00 | yes |
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
| hold | XRP-USDT 6H | none | 0.210649 / 0.210649 | 0.794576 / 0.794576 | 0.057811 / 0.057811 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | XRP-USDT 6H | none | 0.073369 / 0.073369 | 0.293722 / 0.293722 | 0.166738 / 0.166738 | 192 / 192 | yes | yes | 0.0e+00 | yes |
| S1 | XRP-USDT 6H | gate | 0.183353 / 0.183353 | 0.668181 / 0.668181 | 0.108759 / 0.108759 | 137 / 137 | yes | yes | 0.0e+00 | yes |
| S2 | XRP-USDT 6H | none | 0.041108 / 0.041108 | 0.179405 / 0.179405 | 0.140613 / 0.140613 | 100 / 100 | yes | yes | 0.0e+00 | yes |
| S2 | XRP-USDT 6H | gate | -0.020052 / -0.020052 | -0.107254 / -0.107254 | 0.074903 / 0.074903 | 47 / 47 | yes | yes | 0.0e+00 | yes |
| hold | DOGE-USDT 6H | none | 0.051758 / 0.051758 | 0.277023 / 0.277023 | 0.071945 / 0.071945 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | DOGE-USDT 6H | none | 0.034363 / 0.034363 | 0.165238 / 0.165238 | 0.091462 / 0.091462 | 181 / 181 | yes | yes | 0.0e+00 | yes |
| S1 | DOGE-USDT 6H | gate | 0.141864 / 0.141864 | 0.605662 / 0.605662 | 0.058850 / 0.058850 | 109 / 109 | yes | yes | 0.0e+00 | yes |
| S2 | DOGE-USDT 6H | none | 0.105386 / 0.105386 | 0.523867 / 0.523867 | 0.067672 / 0.067672 | 45 / 45 | yes | yes | 0.0e+00 | yes |
| S2 | DOGE-USDT 6H | gate | 0.203179 / 0.203179 | 0.900177 / 0.900177 | 0.055905 / 0.055905 | 46 / 46 | yes | yes | 0.0e+00 | yes |
| hold | LINK-USDT 6H | none | 0.088959 / 0.088959 | 0.424386 / 0.424386 | 0.055310 / 0.055310 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | LINK-USDT 6H | none | 0.088412 / 0.088412 | 0.371315 / 0.371315 | 0.091420 / 0.091420 | 173 / 173 | yes | yes | 0.0e+00 | yes |
| S1 | LINK-USDT 6H | gate | 0.050422 / 0.050422 | 0.228595 / 0.228595 | 0.113454 / 0.113454 | 164 / 164 | yes | yes | 0.0e+00 | yes |
| S2 | LINK-USDT 6H | none | 0.007806 / 0.007806 | 0.060339 / 0.060339 | 0.107892 / 0.107892 | 79 / 79 | yes | yes | 0.0e+00 | yes |
| S2 | LINK-USDT 6H | gate | -0.000843 / -0.000843 | 0.016600 / 0.016600 | 0.100319 / 0.100319 | 57 / 57 | yes | yes | 0.0e+00 | yes |
| hold | TRX-USDT 6H | none | 0.363317 / 0.363317 | 1.128940 / 1.128940 | 0.065519 / 0.065519 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | TRX-USDT 6H | none | 0.291543 / 0.291543 | 0.760765 / 0.760765 | 0.125823 / 0.125823 | 198 / 198 | yes | yes | 0.0e+00 | yes |
| S1 | TRX-USDT 6H | gate | 0.282401 / 0.282401 | 0.735735 / 0.735735 | 0.151123 / 0.151123 | 199 / 199 | yes | yes | 0.0e+00 | yes |
| S2 | TRX-USDT 6H | none | 0.322405 / 0.322405 | 0.838261 / 0.838261 | 0.126124 / 0.126124 | 119 / 119 | yes | yes | 0.0e+00 | yes |
| S2 | TRX-USDT 6H | gate | 0.320858 / 0.320858 | 0.902757 / 0.902757 | 0.120726 / 0.120726 | 98 / 98 | yes | yes | 0.0e+00 | yes |
| hold | ADA-USDT 6H | none | 0.058929 / 0.058929 | 0.295889 / 0.295889 | 0.079989 / 0.079989 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ADA-USDT 6H | none | 0.041160 / 0.041160 | 0.201652 / 0.201652 | 0.109547 / 0.109547 | 155 / 155 | yes | yes | 0.0e+00 | yes |
| S1 | ADA-USDT 6H | gate | 0.038847 / 0.038847 | 0.198074 / 0.198074 | 0.104010 / 0.104010 | 147 / 147 | yes | yes | 0.0e+00 | yes |
| S2 | ADA-USDT 6H | none | 0.205563 / 0.205563 | 0.870472 / 0.870472 | 0.069078 / 0.069078 | 65 / 65 | yes | yes | 0.0e+00 | yes |
| S2 | ADA-USDT 6H | gate | 0.212139 / 0.212139 | 0.936411 / 0.936411 | 0.047272 / 0.047272 | 44 / 44 | yes | yes | 0.0e+00 | yes |
| hold | LTC-USDT 6H | none | -0.006553 / -0.006553 | -0.009767 / -0.009767 | 0.076059 / 0.076059 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | LTC-USDT 6H | none | -0.134604 / -0.134604 | -0.497720 / -0.497720 | 0.198856 / 0.198856 | 221 / 221 | yes | yes | 0.0e+00 | yes |
| S1 | LTC-USDT 6H | gate | -0.148616 / -0.148616 | -0.611216 / -0.611216 | 0.220006 / 0.220006 | 187 / 187 | yes | yes | 0.0e+00 | yes |
| S2 | LTC-USDT 6H | none | -0.118287 / -0.118287 | -0.516635 / -0.516635 | 0.156137 / 0.156137 | 87 / 87 | yes | yes | 0.0e+00 | yes |
| S2 | LTC-USDT 6H | gate | -0.102973 / -0.102973 | -0.458061 / -0.458061 | 0.151878 / 0.151878 | 78 / 78 | yes | yes | 0.0e+00 | yes |
| hold | SOL-USDT 6H | none | 0.285279 / 0.285279 | 1.134204 / 1.134204 | 0.069845 / 0.069845 | 7 / 7 | yes | yes | 0.0e+00 | yes |
| S1 | SOL-USDT 6H | none | 0.222609 / 0.222609 | 1.079467 / 1.079467 | 0.056399 / 0.056399 | 107 / 107 | yes | yes | 0.0e+00 | yes |
| S1 | SOL-USDT 6H | gate | 0.188548 / 0.188548 | 0.924108 / 0.924108 | 0.069353 / 0.069353 | 105 / 105 | yes | yes | 0.0e+00 | yes |
| S2 | SOL-USDT 6H | none | 0.091352 / 0.091352 | 0.508576 / 0.508576 | 0.073004 / 0.073004 | 67 / 67 | yes | yes | 0.0e+00 | yes |
| S2 | SOL-USDT 6H | gate | 0.160398 / 0.160398 | 0.825215 / 0.825215 | 0.091108 / 0.091108 | 37 / 37 | yes | yes | 0.0e+00 | yes |

90 of 90 reproduced.

## H4 — the volume (attention) confirmation on the replication markets: **confirmed**

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Windows traded | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| S1+VC XRP-USDT 4H [none] | none | +7.0% | +1.5% | 0.33 | 1.27 | 9.0% | 0.17 | 104 | 9/9 | 26% | 0.5% | 33.3% | -4.2% | 87.5% | 0.00 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC XRP-USDT 4H [gate] | trail1 | +8.5% | +1.9% | 0.40 | 1.38 | 12.9% | 0.14 | 84 | 9/9 | 25% | 0.5% | 33.3% | -5.2% | 100.0% | 0.00 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC DOGE-USDT 4H [none] | none | +16.9% | +3.6% | 0.77 | 1.79 | 4.8% | 0.75 | 98 | 9/9 | 32% | 0.3% | 85.7% | -2.0% | 100.0% | 0.41 | - | **PASS** | -3.1% / PF 0.43 / 27 tr ✗ |
| S1+VC DOGE-USDT 4H [gate] | none | +18.7% | +4.0% | 0.88 | 2.24 | 4.8% | 0.83 | 67 | 9/9 | 29% | 0.3% | 85.7% | -0.8% | 100.0% | 0.43 | - | **PASS** | +1.8% / PF 1.65 / 18 tr ✓ |
| S1+VC LINK-USDT 4H [none] | none | +2.7% | +0.6% | 0.14 | 1.12 | 14.5% | 0.04 | 99 | 9/9 | 46% | 0.4% | 54.8% | -4.8% | 100.0% | 0.10 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC LINK-USDT 4H [gate] | none | +4.9% | +1.1% | 0.23 | 1.15 | 13.7% | 0.08 | 120 | 9/9 | 47% | 0.5% | 54.8% | -5.1% | 100.0% | 0.12 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC TRX-USDT 4H [none] | none | +36.7% | +7.4% | 1.01 | 1.74 | 10.3% | 0.72 | 129 | 9/9 | 52% | 1.5% | 73.8% | -4.6% | 100.0% | 0.58 | 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC TRX-USDT 4H [gate] | none | +26.4% | +5.5% | 0.87 | 1.90 | 10.8% | 0.51 | 80 | 9/9 | 45% | 1.0% | 73.8% | -3.7% | 100.0% | 0.60 | 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ADA-USDT 4H [none] | time30 | +8.7% | +1.9% | 0.43 | 1.33 | 9.2% | 0.21 | 89 | 9/9 | 27% | 0.4% | 61.9% | -1.7% | 100.0% | 0.01 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ADA-USDT 4H [gate] | none | +7.4% | +1.6% | 0.38 | 1.30 | 8.2% | 0.20 | 81 | 9/9 | 29% | 0.4% | 66.7% | -3.6% | 87.5% | 0.00 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC LTC-USDT 4H [none] | none | -7.9% | -1.9% | -0.32 | 0.74 | 17.0% | -0.11 | 92 | 9/9 | 47% | 0.5% | 21.4% | -8.8% | 0.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| S1+VC LTC-USDT 4H [gate] | none | -6.3% | -1.5% | -0.25 | 0.80 | 16.1% | -0.09 | 85 | 9/9 | 43% | 0.4% | 26.2% | -8.9% | 42.9% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| S1+VC SOL-USDT 4H [none] | none | +27.5% | +7.3% | 1.15 | 2.89 | 5.3% | 1.38 | 64 | 7/7 | 46% | 0.3% | 83.3% | -1.9% | 100.0% | 0.41 | - | **PASS** | -2.4% / PF 0.56 / 25 tr ✗ |
| S1+VC SOL-USDT 4H [gate] | none | +24.7% | +6.6% | 1.08 | 2.79 | 9.6% | 0.69 | 62 | 7/7 | 50% | 0.3% | 73.3% | -4.1% | 100.0% | 0.43 | 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC XRP-USDT 6H [none] | trail1 | +22.3% | +4.7% | 0.77 | 1.76 | 8.5% | 0.55 | 82 | 9/9 | 28% | 0.5% | 45.2% | -3.6% | 100.0% | 0.06 | 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC XRP-USDT 6H [gate] | time30 | +12.5% | +2.7% | 0.59 | 1.76 | 7.5% | 0.36 | 56 | 8/9 | 26% | 0.3% | 57.1% | -2.0% | 100.0% | 0.01 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC DOGE-USDT 6H [none] | tp2 | +16.0% | +3.4% | 0.64 | 1.58 | 6.6% | 0.52 | 93 | 9/9 | 38% | 0.4% | 71.4% | -3.1% | 100.0% | 0.22 | Sharpe above 0.7, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC DOGE-USDT 6H [gate] | none | +20.5% | +4.3% | 0.93 | 2.12 | 5.1% | 0.84 | 61 | 6/9 | 31% | 0.3% | 85.7% | -2.7% | 100.0% | 0.48 | - | **PASS** | -2.2% / PF 0.35 / 16 tr ✗ |
| S1+VC LINK-USDT 6H [none] | none | +5.3% | +1.2% | 0.24 | 1.22 | 9.6% | 0.12 | 91 | 9/9 | 45% | 0.4% | 54.8% | -4.9% | 100.0% | 0.15 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC LINK-USDT 6H [gate] | none | +15.4% | +3.3% | 0.68 | 2.14 | 4.6% | 0.72 | 56 | 8/9 | 37% | 0.2% | 61.9% | -1.7% | 100.0% | 0.29 | Sharpe above 0.7, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC TRX-USDT 6H [none] | tp2 | +34.1% | +6.9% | 0.87 | 1.64 | 12.9% | 0.54 | 129 | 9/9 | 47% | 1.5% | 69.0% | -5.3% | 87.5% | 0.34 | 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC TRX-USDT 6H [gate] | trail1 | +18.6% | +4.0% | 0.59 | 1.39 | 11.7% | 0.34 | 125 | 9/9 | 41% | 1.6% | 69.0% | -5.2% | 100.0% | 0.26 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ADA-USDT 6H [none] | tp2 | +14.0% | +3.0% | 0.65 | 1.59 | 8.6% | 0.35 | 90 | 9/9 | 28% | 0.4% | 69.0% | -2.8% | 100.0% | 0.11 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S1+VC ADA-USDT 6H [gate] | none | +12.8% | +2.8% | 0.65 | 1.74 | 6.1% | 0.45 | 52 | 8/9 | 28% | 0.2% | 78.6% | -4.7% | 100.0% | 0.12 | Sharpe above 0.7, Calmar above 0.5 | fail | untouched |
| S1+VC LTC-USDT 6H [none] | none | -9.2% | -2.2% | -0.35 | 0.68 | 14.9% | -0.15 | 80 | 9/9 | 43% | 0.4% | 38.1% | -5.1% | 0.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| S1+VC LTC-USDT 6H [gate] | none | -3.1% | -0.7% | -0.10 | 0.90 | 12.5% | -0.06 | 74 | 9/9 | 36% | 0.4% | 38.1% | -3.8% | 14.3% | 0.02 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | fail | untouched |
| S1+VC SOL-USDT 6H [none] | none | +34.9% | +9.1% | 1.31 | 3.72 | 5.9% | 1.54 | 41 | 6/7 | 46% | 0.2% | 76.7% | -1.9% | 100.0% | 0.53 | - | **PASS** | -1.6% / PF 0.68 / 23 tr ✗ |
| S1+VC SOL-USDT 6H [gate] | none | +31.2% | +8.2% | 1.34 | 5.70 | 5.6% | 1.45 | 27 | 4/7 | 36% | 0.1% | 73.3% | -1.3% | 100.0% | 0.77 | 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |

Beside the plain S1 rule (same market, timeframe and mode — the control has one mode; stored numbers reproduced in this run):

| Configuration | Comparison line | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1+VC XRP-USDT 4H [none] | S1 XRP-USDT 4H [none] | -0.10 → 0.17 | -2.2% → +1.5% | 22.3% → 9.0% | -0.36 → 0.33 | 0.80 → 1.27 | 209 → 104 | 43% → 26% | 26.2% → 33.3% | -8.4% → -4.2% | -4.3% → -4.2% | no / no |
| S1+VC XRP-USDT 4H [gate] | S1 XRP-USDT 4H [gate] | 0.02 → 0.14 | +0.3% → +1.9% | 16.7% → 12.9% | 0.08 → 0.40 | 1.06 → 1.38 | 184 → 84 | 39% → 25% | 33.3% → 33.3% | -5.7% → -5.2% | -3.6% → -2.5% | no / no |
| S1+VC DOGE-USDT 4H [none] | S1 DOGE-USDT 4H [none] | 0.55 → 0.75 | +3.5% → +3.6% | 6.3% → 4.8% | 0.67 → 0.77 | 1.42 → 1.79 | 252 → 98 | 36% → 32% | 85.7% → 85.7% | -2.9% → -2.0% | +1.7% → +0.7% | no / yes |
| S1+VC DOGE-USDT 4H [gate] | S1 DOGE-USDT 4H [gate] | 0.13 → 0.83 | +0.8% → +4.0% | 5.8% → 4.8% | 0.20 → 0.88 | 1.14 → 2.24 | 132 → 67 | 21% → 29% | 57.1% → 85.7% | -2.7% → -0.8% | -2.7% → +0.4% | no / yes |
| S1+VC LINK-USDT 4H [none] | S1 LINK-USDT 4H [none] | -0.01 → 0.04 | -0.1% → +0.6% | 12.8% → 14.5% | 0.00 → 0.14 | 1.00 → 1.12 | 219 → 99 | 56% → 46% | 54.8% → 54.8% | -5.3% → -4.8% | -5.3% → -4.8% | no / no |
| S1+VC LINK-USDT 4H [gate] | S1 LINK-USDT 4H [gate] | 0.19 → 0.08 | +1.6% → +1.1% | 8.7% → 13.7% | 0.33 → 0.23 | 1.23 → 1.15 | 186 → 120 | 48% → 47% | 61.9% → 54.8% | -4.1% → -5.1% | -4.1% → -5.1% | no / no |
| S1+VC TRX-USDT 4H [none] | S1 TRX-USDT 4H [none] | 0.31 → 0.72 | +4.7% → +7.4% | 15.3% → 10.3% | 0.68 → 1.01 | 1.36 → 1.74 | 282 → 129 | 71% → 52% | 54.8% → 73.8% | -5.1% → -4.6% | -5.1% → -4.6% | no / no |
| S1+VC TRX-USDT 4H [gate] | S1 TRX-USDT 4H [gate] | 0.32 → 0.51 | +4.0% → +5.5% | 12.7% → 10.8% | 0.59 → 0.87 | 1.33 → 1.90 | 177 → 80 | 59% → 45% | 57.1% → 73.8% | -4.6% → -3.7% | -4.6% → -3.7% | no / no |
| S1+VC ADA-USDT 4H [none] | S1 ADA-USDT 4H [none] | 0.13 → 0.21 | +1.2% → +1.9% | 9.6% → 9.2% | 0.26 → 0.43 | 1.13 → 1.33 | 237 → 89 | 43% → 27% | 64.3% → 61.9% | -3.9% → -1.7% | -3.9% → -0.2% | no / no |
| S1+VC ADA-USDT 4H [gate] | S1 ADA-USDT 4H [gate] | 0.16 → 0.20 | +1.8% → +1.6% | 11.2% → 8.2% | 0.41 → 0.38 | 1.30 → 1.30 | 161 → 81 | 30% → 29% | 64.3% → 66.7% | -4.0% → -3.6% | -3.2% → -3.0% | no / no |
| S1+VC LTC-USDT 4H [none] | S1 LTC-USDT 4H [none] | -0.16 → -0.11 | -3.6% → -1.9% | 21.9% → 17.0% | -0.61 → -0.32 | 0.74 → 0.74 | 288 → 92 | 63% → 47% | 14.3% → 21.4% | -7.9% → -8.8% | -4.0% → -8.8% | no / no |
| S1+VC LTC-USDT 4H [gate] | S1 LTC-USDT 4H [gate] | -0.16 → -0.09 | -3.5% → -1.5% | 21.9% → 16.1% | -0.58 → -0.25 | 0.65 → 0.80 | 203 → 85 | 54% → 43% | 14.3% → 26.2% | -6.8% → -8.9% | -3.5% → -8.9% | no / no |
| S1+VC SOL-USDT 4H [none] | S1 SOL-USDT 4H [none] | 0.65 → 1.38 | +4.9% → +7.3% | 7.5% → 5.3% | 0.92 → 1.15 | 1.85 → 2.89 | 141 → 64 | 43% → 46% | 70.0% → 83.3% | -3.2% → -1.9% | -3.2% → -1.9% | no / yes |
| S1+VC SOL-USDT 4H [gate] | S1 SOL-USDT 4H [gate] | 0.27 → 0.69 | +1.7% → +6.6% | 6.2% → 9.6% | 0.39 → 1.08 | 1.25 → 2.79 | 134 → 62 | 31% → 50% | 53.3% → 73.3% | -3.3% → -4.1% | -3.3% → -4.1% | no / no |
| S1+VC XRP-USDT 6H [none] | S1 XRP-USDT 6H [none] | 0.10 → 0.55 | +1.6% → +4.7% | 16.7% → 8.5% | 0.29 → 0.77 | 1.23 → 1.76 | 192 → 82 | 47% → 28% | 35.7% → 45.2% | -8.8% → -3.6% | -0.9% → -3.6% | no / no |
| S1+VC XRP-USDT 6H [gate] | S1 XRP-USDT 6H [gate] | 0.36 → 0.36 | +3.9% → +2.7% | 10.9% → 7.5% | 0.67 → 0.59 | 1.55 → 1.76 | 137 → 56 | 29% → 26% | 33.3% → 57.1% | -3.3% → -2.0% | -1.4% → -0.4% | no / no |
| S1+VC DOGE-USDT 6H [none] | S1 DOGE-USDT 6H [none] | 0.08 → 0.52 | +0.8% → +3.4% | 9.1% → 6.6% | 0.17 → 0.64 | 1.09 → 1.58 | 181 → 93 | 30% → 38% | 54.8% → 71.4% | -5.0% → -3.1% | +1.1% → +2.3% | no / no |
| S1+VC DOGE-USDT 6H [gate] | S1 DOGE-USDT 6H [gate] | 0.52 → 0.84 | +3.1% → +4.3% | 5.9% → 5.1% | 0.61 → 0.93 | 1.53 → 2.12 | 109 → 61 | 21% → 31% | 78.6% → 85.7% | -0.4% → -2.7% | -0.4% → +2.1% | no / yes |
| S1+VC LINK-USDT 6H [none] | S1 LINK-USDT 6H [none] | 0.21 → 0.12 | +1.9% → +1.2% | 9.1% → 9.6% | 0.37 → 0.24 | 1.28 → 1.22 | 173 → 91 | 57% → 45% | 54.8% → 54.8% | -3.5% → -4.9% | -3.5% → -4.9% | no / no |
| S1+VC LINK-USDT 6H [gate] | S1 LINK-USDT 6H [gate] | 0.10 → 0.72 | +1.1% → +3.3% | 11.3% → 4.6% | 0.23 → 0.68 | 1.17 → 2.14 | 164 → 56 | 49% → 37% | 54.8% → 61.9% | -5.1% → -1.7% | -5.1% → -1.7% | no / no |
| S1+VC TRX-USDT 6H [none] | S1 TRX-USDT 6H [none] | 0.48 → 0.54 | +6.0% → +6.9% | 12.6% → 12.9% | 0.76 → 0.87 | 1.56 → 1.64 | 198 → 129 | 70% → 47% | 64.3% → 69.0% | -5.7% → -5.3% | -5.7% → -5.3% | no / no |
| S1+VC TRX-USDT 6H [gate] | S1 TRX-USDT 6H [gate] | 0.39 → 0.34 | +5.8% → +4.0% | 15.1% → 11.7% | 0.74 → 0.59 | 1.54 → 1.39 | 199 → 125 | 56% → 41% | 66.7% → 69.0% | -7.7% → -5.2% | -7.7% → -5.2% | no / no |
| S1+VC ADA-USDT 6H [none] | S1 ADA-USDT 6H [none] | 0.08 → 0.35 | +0.9% → +3.0% | 11.0% → 8.6% | 0.20 → 0.65 | 1.13 → 1.59 | 155 → 90 | 41% → 28% | 57.1% → 69.0% | -3.7% → -2.8% | -2.1% → -2.8% | no / no |
| S1+VC ADA-USDT 6H [gate] | S1 ADA-USDT 6H [gate] | 0.08 → 0.45 | +0.9% → +2.8% | 10.4% → 6.1% | 0.20 → 0.65 | 1.12 → 1.74 | 147 → 52 | 40% → 28% | 52.4% → 78.6% | -4.1% → -4.7% | -4.1% → -0.5% | no / no |
| S1+VC LTC-USDT 6H [none] | S1 LTC-USDT 6H [none] | -0.16 → -0.15 | -3.2% → -2.2% | 19.9% → 14.9% | -0.50 → -0.35 | 0.71 → 0.68 | 221 → 80 | 64% → 43% | 14.3% → 38.1% | -6.3% → -5.1% | -5.3% → -3.5% | no / no |
| S1+VC LTC-USDT 6H [gate] | S1 LTC-USDT 6H [gate] | -0.16 → -0.06 | -3.6% → -0.7% | 22.0% → 12.5% | -0.61 → -0.10 | 0.66 → 0.90 | 187 → 74 | 49% → 36% | 11.9% → 38.1% | -7.0% → -3.8% | -7.0% → -3.8% | no / no |
| S1+VC SOL-USDT 6H [none] | S1 SOL-USDT 6H [none] | 1.06 → 1.54 | +6.0% → +9.1% | 5.6% → 5.9% | 1.08 → 1.31 | 2.08 → 3.72 | 107 → 41 | 33% → 46% | 90.0% → 76.7% | -1.7% → -1.9% | -1.7% → -1.9% | yes / yes |
| S1+VC SOL-USDT 6H [gate] | S1 SOL-USDT 6H [gate] | 0.74 → 1.45 | +5.1% → +8.2% | 6.9% → 5.6% | 0.92 → 1.34 | 1.99 → 5.70 | 105 → 27 | 35% → 36% | 60.0% → 73.3% | -2.7% → -1.3% | -2.7% → -1.3% | no / no |

Directional reading (pre-registered): Calmar rose beside the plain S1 rule in 25 of 28 configurations (14 expected by chance; the one-sided sign test needs at least 19 of 28 at the 5% level; P(at least this many by chance) = 0.000): the effect **replicates in direction**. The configurations share markets across two timeframes and two modes, so this is indicative, not a test of independent trials.
Pattern check (pre-registered): round 1 found the gain concentrated in the gated 4H configurations; here Calmar rose in 6 of 7 markets' 4H [gate] configurations (XRP-USDT, DOGE-USDT, TRX-USDT, ADA-USDT, LTC-USDT, SOL-USDT), against the pre-registered 5 of 7: **consistent with round 1**.

**Confirmed.** S1+VC DOGE-USDT 4H [gate] passed every walk-forward gate and the untouched 12 months confirmed it; it joins the paper fleet's shortlist (below). The holdout's falling direction was known before this study, so the forward fleet, not this confirmation, is the judge.
The other passers were not confirmed: S1+VC DOGE-USDT 4H [none], S1+VC SOL-USDT 4H [none], S1+VC DOGE-USDT 6H [gate], S1+VC SOL-USDT 6H [none]. That is 1 confirmation among 5 walk-forward passers — the same order as Sprint 2c (1 of 4) and the replication study (2 of 10), so the condition's strong walk-forward direction did not make its passers more durable than the base rules' were.
On SOL-USDT the comparison line's own holdout was confirmed (S1 SOL-USDT 6H [none]: +9.5%, PF 5.49, 12 trades) while S1+VC SOL-USDT 6H [none] was contradicted (-1.6%): there the condition changed the selected rule and removed the entries that made the base rule's year.

## H5 — a slow trend filter for the breakout rule: **failed walk-forward**

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Windows traded | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| S2+TF BTC-USDT 4H [none] | none | -7.0% | -1.6% | -0.48 | 0.65 | 7.8% | -0.21 | 45 | 5/9 | 13% | 0.6% | 2.4% | -5.3% | 100.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+TF BTC-USDT 4H [gate] | none | -3.2% | -0.7% | -0.19 | 0.78 | 5.4% | -0.14 | 31 | 4/9 | 14% | 0.4% | 12.2% | -2.5% | 100.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+TF ETH-USDT 4H [none] | none | -0.1% | -0.0% | 0.01 | 1.00 | 10.0% | -0.00 | 23 | 5/9 | 11% | 0.2% | 9.8% | -1.4% | 70.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ETH-USDT 4H [gate] | none | -2.2% | -0.5% | -0.27 | 0.64 | 5.8% | -0.09 | 12 | 4/9 | 7% | 0.1% | 2.4% | -1.4% | 80.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF DOGE-USDT 4H [none] | none | -1.1% | -0.3% | -0.18 | 0.00 | 3.0% | -0.09 | 4 | 1/9 | 5% | 0.0% | 7.1% | -1.1% | 80.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF DOGE-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 70.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF TRX-USDT 4H [none] | none | +9.4% | +2.1% | 0.50 | 1.62 | 6.8% | 0.30 | 40 | 5/9 | 21% | 0.5% | 33.3% | -3.5% | 100.0% | 0.07 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | fail | untouched |
| S2+TF TRX-USDT 4H [gate] | none | +12.5% | +2.7% | 0.67 | 2.06 | 4.5% | 0.60 | 26 | 3/9 | 15% | 0.4% | 33.3% | +0.0% | 100.0% | 0.20 | Sharpe above 0.7, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ADA-USDT 4H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 2/9 | 0% | 0.0% | 0.0% | +0.0% | 90.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ADA-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 1/9 | 0% | 0.0% | 0.0% | +0.0% | 90.0% | 0.01 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF BTC-USDT 6H [none] | none | -1.9% | -0.4% | -0.15 | 0.76 | 5.5% | -0.08 | 14 | 2/9 | 7% | 0.2% | 4.9% | -1.2% | 100.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF BTC-USDT 6H [gate] | none | -1.0% | -0.2% | -0.48 | 0.00 | 1.0% | -0.23 | 1 | 1/9 | 0% | 0.0% | 0.0% | -1.0% | 80.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ETH-USDT 6H [none] | none | +9.2% | +2.1% | 0.60 | 2.69 | 4.5% | 0.46 | 9 | 4/9 | 8% | 0.1% | 29.3% | -1.2% | 100.0% | 0.17 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ETH-USDT 6H [gate] | time30 | +2.4% | +0.6% | 0.22 | 1.38 | 6.1% | 0.09 | 13 | 3/9 | 6% | 0.1% | 29.3% | -1.6% | 100.0% | 0.03 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF DOGE-USDT 6H [none] | time30 | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 1/9 | 0% | 0.0% | 0.0% | +0.0% | 50.0% | 0.00 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF DOGE-USDT 6H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.04 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF TRX-USDT 6H [none] | none | +16.4% | +3.5% | 0.64 | 1.74 | 6.0% | 0.59 | 44 | 4/9 | 14% | 0.7% | 33.3% | -0.6% | 100.0% | 0.03 | Sharpe above 0.7, 75% of rolling 12-month windows positive | fail | untouched |
| S2+TF TRX-USDT 6H [gate] | none | +23.6% | +4.9% | 0.99 | 4.95 | 5.2% | 0.95 | 11 | 3/9 | 10% | 0.2% | 57.1% | +0.0% | 100.0% | 0.20 | 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ADA-USDT 6H [none] | none | +1.5% | +0.3% | 0.26 | 1.54 | 3.5% | 0.10 | 8 | 3/9 | 5% | 0.0% | 7.1% | +0.0% | 100.0% | 0.05 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| S2+TF ADA-USDT 6H [gate] | none | +1.5% | +0.3% | 0.26 | 1.54 | 3.5% | 0.10 | 8 | 2/9 | 5% | 0.0% | 7.1% | +0.0% | 100.0% | 0.02 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |

Beside the plain S2 rule (same market, timeframe and mode — the control has one mode; stored numbers reproduced in this run):

| Configuration | Comparison line | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S2+TF BTC-USDT 4H [none] | S2 BTC-USDT 4H [none] | 0.38 → -0.21 | +3.3% → -1.6% | 8.7% → 7.8% | 0.57 → -0.48 | 1.46 → 0.65 | 85 → 45 | 46% → 13% | 61.0% → 2.4% | -4.6% → -5.3% | -2.4% → +0.0% | no / no |
| S2+TF BTC-USDT 4H [gate] | S2 BTC-USDT 4H [gate] | 0.80 → -0.14 | +5.2% → -0.7% | 6.5% → 5.4% | 0.86 → -0.19 | 1.94 → 0.78 | 69 → 31 | 43% → 14% | 80.5% → 12.2% | -3.2% → -2.5% | -3.2% → +0.0% | yes / no |
| S2+TF ETH-USDT 4H [none] | S2 ETH-USDT 4H [none] | 0.41 → -0.00 | +3.6% → -0.0% | 8.8% → 10.0% | 0.62 → 0.01 | 1.63 → 1.00 | 77 → 23 | 42% → 11% | 63.4% → 9.8% | -0.6% → -1.4% | -0.5% → -1.4% | no / no |
| S2+TF ETH-USDT 4H [gate] | S2 ETH-USDT 4H [gate] | 0.07 → -0.09 | +0.7% → -0.5% | 10.9% → 5.8% | 0.16 → -0.27 | 1.10 → 0.64 | 86 → 12 | 40% → 7% | 70.7% → 2.4% | -0.8% → -1.4% | +0.5% → -1.4% | no / no |
| S2+TF DOGE-USDT 4H [none] | S2 DOGE-USDT 4H [none] | 0.29 → -0.09 | +1.8% → -0.3% | 6.3% → 3.0% | 0.44 → -0.18 | 1.50 → 0.00 | 59 → 4 | 27% → 5% | 66.7% → 7.1% | -2.3% → -1.1% | +2.5% → +0.0% | no / no |
| S2+TF DOGE-USDT 4H [gate] | S2 DOGE-USDT 4H [gate] | 0.85 → 0.00 | +3.6% → +0.0% | 4.2% → -0.0% | 0.81 → 0.00 | 2.29 → 0.00 | 46 → 0 | 29% → 0% | 85.7% → 0.0% | -0.1% → +0.0% | +1.7% → +0.0% | yes / no |
| S2+TF TRX-USDT 4H [none] | S2 TRX-USDT 4H [none] | 0.58 → 0.30 | +5.0% → +2.1% | 8.7% → 6.8% | 0.82 → 0.50 | 1.63 → 1.62 | 95 → 40 | 44% → 21% | 76.2% → 33.3% | -4.8% → -3.5% | -4.8% → -0.6% | yes / no |
| S2+TF TRX-USDT 4H [gate] | S2 TRX-USDT 4H [gate] | 0.46 → 0.60 | +3.5% → +2.7% | 7.6% → 4.5% | 0.63 → 0.67 | 1.51 → 2.06 | 68 → 26 | 39% → 15% | 66.7% → 33.3% | -3.2% → +0.0% | -3.2% → +0.0% | no / no |
| S2+TF ADA-USDT 4H [none] | S2 ADA-USDT 4H [none] | 0.17 → 0.00 | +1.4% → +0.0% | 8.1% → -0.0% | 0.32 → 0.00 | 1.26 → 0.00 | 80 → 0 | 36% → 0% | 57.1% → 0.0% | -3.3% → +0.0% | -2.8% → +0.0% | no / no |
| S2+TF ADA-USDT 4H [gate] | S2 ADA-USDT 4H [gate] | 0.14 → 0.00 | +1.0% → +0.0% | 7.1% → -0.0% | 0.27 → 0.00 | 1.23 → 0.00 | 58 → 0 | 25% → 0% | 45.2% → 0.0% | -3.6% → +0.0% | -0.0% → +0.0% | no / no |
| S2+TF BTC-USDT 6H [none] | S2 BTC-USDT 6H [none] | 0.07 → -0.08 | +0.7% → -0.4% | 10.0% → 5.5% | 0.16 → -0.15 | 1.10 → 0.76 | 69 → 14 | 35% → 7% | 58.5% → 4.9% | -3.5% → -1.2% | -2.8% → +0.0% | no / no |
| S2+TF BTC-USDT 6H [gate] | S2 BTC-USDT 6H [gate] | 0.12 → -0.23 | +1.2% → -0.2% | 9.9% → 1.0% | 0.28 → -0.48 | 1.22 → 0.00 | 48 → 1 | 30% → 0% | 56.1% → 0.0% | -1.7% → -1.0% | -1.4% → +0.0% | no / no |
| S2+TF ETH-USDT 6H [none] | S2 ETH-USDT 6H [none] | 0.36 → 0.46 | +3.2% → +2.1% | 9.1% → 4.5% | 0.57 → 0.60 | 1.39 → 2.69 | 85 → 9 | 36% → 8% | 61.0% → 29.3% | -2.1% → -1.2% | -2.1% → -1.2% | no / no |
| S2+TF ETH-USDT 6H [gate] | S2 ETH-USDT 6H [gate] | 0.62 → 0.09 | +5.1% → +0.6% | 8.3% → 6.1% | 0.92 → 0.22 | 2.01 → 1.38 | 52 → 13 | 41% → 6% | 70.7% → 29.3% | +0.7% → -1.6% | +0.7% → -1.6% | no / no |
| S2+TF DOGE-USDT 6H [none] | S2 DOGE-USDT 6H [none] | 0.34 → 0.00 | +2.3% → +0.0% | 6.8% → -0.0% | 0.52 → 0.00 | 1.76 → 0.00 | 45 → 0 | 25% → 0% | 66.7% → 0.0% | -0.1% → +0.0% | +2.0% → +0.0% | no / no |
| S2+TF DOGE-USDT 6H [gate] | S2 DOGE-USDT 6H [gate] | 0.77 → 0.00 | +4.3% → +0.0% | 5.6% → -0.0% | 0.90 → 0.00 | 2.50 → 0.00 | 46 → 0 | 26% → 0% | 85.7% → 0.0% | +0.0% → +0.0% | +1.4% → +0.0% | yes / no |
| S2+TF TRX-USDT 6H [none] | S2 TRX-USDT 6H [none] | 0.52 → 0.59 | +6.6% → +3.5% | 12.6% → 6.0% | 0.84 → 0.64 | 1.64 → 1.74 | 119 → 44 | 43% → 14% | 64.3% → 33.3% | -7.2% → -0.6% | -7.2% → -0.6% | no / no |
| S2+TF TRX-USDT 6H [gate] | S2 TRX-USDT 6H [gate] | 0.54 → 0.95 | +6.5% → +4.9% | 12.1% → 5.2% | 0.90 → 0.99 | 1.75 → 4.95 | 98 → 11 | 38% → 10% | 61.9% → 57.1% | -7.2% → +0.0% | -7.2% → +0.1% | no / no |
| S2+TF ADA-USDT 6H [none] | S2 ADA-USDT 6H [none] | 0.63 → 0.10 | +4.3% → +0.3% | 6.9% → 3.5% | 0.87 → 0.26 | 1.99 → 1.54 | 65 → 8 | 40% → 5% | 83.3% → 7.1% | -1.7% → +0.0% | -1.7% → +0.0% | yes / no |
| S2+TF ADA-USDT 6H [gate] | S2 ADA-USDT 6H [gate] | 0.95 → 0.10 | +4.5% → +0.3% | 4.7% → 3.5% | 0.94 → 0.26 | 2.37 → 1.54 | 44 → 8 | 34% → 5% | 88.1% → 7.1% | -2.3% → +0.0% | -0.6% → +0.0% | yes / no |

Directional reading (pre-registered): Calmar rose beside the plain S2 rule in 4 of 20 configurations (10 expected by chance; the one-sided sign test needs at least 15 of 20 at the 5% level; P(at least this many by chance) = 0.999): the effect **does not replicate in direction**. The configurations share markets across two timeframes and two modes, so this is indicative, not a test of independent trials.

The breakout configurations that passed walk-forward and were contradicted by the untouched 12 months (Sprint 2c, the replication study), and what the same rule with the slow trend filter did on those series. The base rule's holdout loss in a bear year is known, and a trend filter is expected to sit that year out, so the last column carries no verdict weight:

| Breakout configuration (stored) | Study | Its walk-forward Calmar | Its holdout (contradicted) | With the filter: walk-forward | With the filter: Calmar / trades | With the filter: holdout |
|---|---|---:|---|---|---|---|
| S2 ADA-USDT 6H [gate] | R12 replication | 0.95 | -6.0% / PF 0.07 / 20 tr | fail (Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades) | 0.10 / 8 | untouched |
| S2 ADA-USDT 6H [none] | R12 replication | 0.63 | -4.6% / PF 0.28 / 20 tr | fail (Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades) | 0.10 / 8 | untouched |
| S2 BTC-USDT 4H [gate] | Sprint 2c | 0.80 | -4.9% / PF 0.28 / 21 tr | fail (profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive) | -0.14 / 31 | untouched |
| S2 DOGE-USDT 4H [gate] | R12 replication | 0.85 | +1.7% / PF 1.70 / 8 tr | fail (profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades) | 0.00 / 0 | untouched |
| S2 DOGE-USDT 6H [gate] | R12 replication | 0.77 | -0.6% / PF 0.87 / 10 tr | fail (profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades) | 0.00 / 0 | untouched |
| S2 TRX-USDT 4H [none] | R12 replication | 0.58 | -5.6% / PF 0.47 / 26 tr | fail (Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive) | 0.30 / 40 | untouched |

**Failure analysis** (computed from the numbers above):

- Across its 20 configurations the condition raised the risk-adjusted result (Calmar) beside the plain S2 rule in 4 and lowered it in 16: the median Calmar went from 0.43 to 0.00 (-0.35), the median yearly return from +3.5% to +0.0%, the median worst drawdown from 8.2% to 4.5%, and the median share of positive rolling 12-month windows from 66.7% to 7.1%.
- It removed a median 87% of the base rule's trades (median 68 → 10), changed the time in the market by -29.0% and the fees per year by -0.31%; the drawdown fell in 19 of 20 configurations and the return fell in 20 of 20.
- The protocol's selection rule (a bracket variant needs 20 train trades) let the condition trade in 53 of 180 walk-forward windows across the configurations; a window without a qualified variant stays flat.
- In the 2022 bear year the median result moved from -1.6% to +0.0%.
- With the HMM regime gate already on, Calmar still rose in 2 of 10 configurations (without the gate: 2 of 10).
- By timeframe: 4H: Calmar rose in 1 of 10; 6H: Calmar rose in 3 of 10.
- By market: ADA-USDT 0 of 4; BTC-USDT 0 of 4; DOGE-USDT 0 of 4; ETH-USDT 1 of 4; TRX-USDT 3 of 4.
- Gates missed most often: 75% of rolling 12-month windows positive (20 of 20), Sharpe above 0.7 (19 of 20), Calmar above 0.5 (17 of 20), at least 30 trades (16 of 20).
- Reading: the condition removed so many entries (a median 87% of the base rule's trades) that in 127 of 180 windows no variant reached the 20 train trades the selection step requires, so most configurations sat flat; where it did trade, Calmar rose beside the base rule in 4 of 20 configurations. The base rule's entries mostly come below the 200-day average — rallies and recoveries — so 'only in uptrends' leaves too little of the rule to judge: untested by this protocol rather than refuted, and the 4 of 20 says the idea is not where the missing edge is either.

## H6 — the slow trend filter as the exposure rule: **failed walk-forward**

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Windows traded | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| TF BTC-USDT 4H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.48 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF BTC-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.50 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ETH-USDT 4H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.49 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ETH-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.49 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF DOGE-USDT 4H [none] | none | +8.4% | +1.8% | 0.60 | 2.93 | 5.6% | 0.33 | 13 | 3/9 | 15% | 0.1% | 52.4% | +0.0% | 0.0% | 0.89 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades, robust to ±30% parameter changes | fail | untouched |
| TF DOGE-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 50.0% | 0.48 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF TRX-USDT 4H [none] | time30 | +3.9% | +0.9% | 0.31 | 1.74 | 6.0% | 0.14 | 8 | 2/9 | 18% | 0.1% | 45.2% | +0.0% | 100.0% | 0.73 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF TRX-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.46 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ADA-USDT 4H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 1/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.46 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ADA-USDT 4H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 50.0% | 0.49 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF BTC-USDT 6H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.46 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF BTC-USDT 6H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.49 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ETH-USDT 6H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.48 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ETH-USDT 6H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 100.0% | 0.49 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF DOGE-USDT 6H [none] | none | +6.8% | +1.5% | 0.53 | 4.33 | 4.6% | 0.32 | 9 | 3/9 | 15% | 0.0% | 54.8% | +0.0% | 100.0% | 0.86 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF DOGE-USDT 6H [gate] | none | +5.5% | +1.2% | 0.54 | ∞ | 3.3% | 0.38 | 1 | 1/9 | 11% | 0.0% | 38.1% | +0.0% | 100.0% | 0.87 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF TRX-USDT 6H [none] | none | +3.1% | +0.7% | 0.25 | 2.39 | 5.6% | 0.12 | 6 | 2/9 | 18% | 0.0% | 45.2% | +0.0% | 100.0% | 0.69 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF TRX-USDT 6H [gate] | none | -1.8% | -0.4% | -0.19 | 0.25 | 5.7% | -0.07 | 5 | 1/9 | 7% | 0.0% | 4.8% | -1.8% | 100.0% | 0.34 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ADA-USDT 6H [none] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 50.0% | 0.50 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |
| TF ADA-USDT 6H [gate] | none | +0.0% | +0.0% | 0.00 | 0.00 | -0.0% | 0.00 | 0 | 0/9 | 0% | 0.0% | 0.0% | +0.0% | 50.0% | 0.48 | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, at least 30 trades | fail | untouched |

Beside hold + policy sizing (same market, timeframe and mode — the control has one mode; stored numbers reproduced in this run):

| Configuration | Comparison line | Calmar base → new | CAGR base → new | Max DD base → new | Sharpe base → new | PF base → new | Trades base → new | Exposure base → new | Rolling 12m + base → new | Worst year base → new | 2022 base → new | Base passes / new passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TF BTC-USDT 4H [none] | hold BTC-USDT 4H [none] | 0.45 → 0.00 | +3.2% → +0.0% | 7.2% → -0.0% | 0.59 → 0.00 | 2.88 → 0.00 | 9 → 0 | 100% → 0% | 70.7% → 0.0% | -4.7% → +0.0% | -4.7% → +0.0% | no / no |
| TF BTC-USDT 4H [gate] | hold BTC-USDT 4H [none] | 0.45 → 0.00 | +3.2% → +0.0% | 7.2% → -0.0% | 0.59 → 0.00 | 2.88 → 0.00 | 9 → 0 | 100% → 0% | 70.7% → 0.0% | -4.7% → +0.0% | -4.7% → +0.0% | no / no |
| TF ETH-USDT 4H [none] | hold ETH-USDT 4H [none] | 0.20 → 0.00 | +1.8% → +0.0% | 8.6% → -0.0% | 0.38 → 0.00 | 1.83 → 0.00 | 9 → 0 | 100% → 0% | 63.4% → 0.0% | -4.1% → +0.0% | -4.1% → +0.0% | no / no |
| TF ETH-USDT 4H [gate] | hold ETH-USDT 4H [none] | 0.20 → 0.00 | +1.8% → +0.0% | 8.6% → -0.0% | 0.38 → 0.00 | 1.83 → 0.00 | 9 → 0 | 100% → 0% | 63.4% → 0.0% | -4.1% → +0.0% | -4.1% → +0.0% | no / no |
| TF DOGE-USDT 4H [none] | hold DOGE-USDT 4H [none] | 0.10 → 0.33 | +0.7% → +1.8% | 6.9% → 5.6% | 0.19 → 0.60 | 1.58 → 2.93 | 9 → 13 | 100% → 15% | 47.6% → 52.4% | -2.5% → +0.0% | -2.5% → +0.0% | no / no |
| TF DOGE-USDT 4H [gate] | hold DOGE-USDT 4H [none] | 0.10 → 0.00 | +0.7% → +0.0% | 6.9% → -0.0% | 0.19 → 0.00 | 1.58 → 0.00 | 9 → 0 | 100% → 0% | 47.6% → 0.0% | -2.5% → +0.0% | -2.5% → +0.0% | no / no |
| TF TRX-USDT 4H [none] | hold TRX-USDT 4H [none] | 1.31 → 0.14 | +7.3% → +0.9% | 5.6% → 6.0% | 1.30 → 0.31 | 11.67 → 1.74 | 9 → 8 | 100% → 18% | 78.6% → 45.2% | -1.5% → +0.0% | -1.5% → +0.0% | no / no |
| TF TRX-USDT 4H [gate] | hold TRX-USDT 4H [none] | 1.31 → 0.00 | +7.3% → +0.0% | 5.6% → -0.0% | 1.30 → 0.00 | 11.67 → 0.00 | 9 → 0 | 100% → 0% | 78.6% → 0.0% | -1.5% → +0.0% | -1.5% → +0.0% | no / no |
| TF ADA-USDT 4H [none] | hold ADA-USDT 4H [none] | 0.16 → 0.00 | +1.2% → +0.0% | 7.7% → -0.0% | 0.29 → 0.00 | 1.86 → 0.00 | 9 → 0 | 100% → 0% | 54.8% → 0.0% | -4.0% → +0.0% | -4.0% → +0.0% | no / no |
| TF ADA-USDT 4H [gate] | hold ADA-USDT 4H [none] | 0.16 → 0.00 | +1.2% → +0.0% | 7.7% → -0.0% | 0.29 → 0.00 | 1.86 → 0.00 | 9 → 0 | 100% → 0% | 54.8% → 0.0% | -4.0% → +0.0% | -4.0% → +0.0% | no / no |
| TF BTC-USDT 6H [none] | hold BTC-USDT 6H [none] | 0.33 → 0.00 | +2.6% → +0.0% | 8.0% → -0.0% | 0.49 → 0.00 | 2.37 → 0.00 | 9 → 0 | 100% → 0% | 73.2% → 0.0% | -4.8% → +0.0% | -4.8% → +0.0% | no / no |
| TF BTC-USDT 6H [gate] | hold BTC-USDT 6H [none] | 0.33 → 0.00 | +2.6% → +0.0% | 8.0% → -0.0% | 0.49 → 0.00 | 2.37 → 0.00 | 9 → 0 | 100% → 0% | 73.2% → 0.0% | -4.8% → +0.0% | -4.8% → +0.0% | no / no |
| TF ETH-USDT 6H [none] | hold ETH-USDT 6H [none] | 0.26 → 0.00 | +2.5% → +0.0% | 9.6% → -0.0% | 0.50 → 0.00 | 2.04 → 0.00 | 9 → 0 | 100% → 0% | 65.9% → 0.0% | -3.5% → +0.0% | -3.5% → +0.0% | no / no |
| TF ETH-USDT 6H [gate] | hold ETH-USDT 6H [none] | 0.26 → 0.00 | +2.5% → +0.0% | 9.6% → -0.0% | 0.50 → 0.00 | 2.04 → 0.00 | 9 → 0 | 100% → 0% | 65.9% → 0.0% | -3.5% → +0.0% | -3.5% → +0.0% | no / no |
| TF DOGE-USDT 6H [none] | hold DOGE-USDT 6H [none] | 0.16 → 0.32 | +1.2% → +1.5% | 7.2% → 4.6% | 0.28 → 0.53 | 1.94 → 4.33 | 9 → 9 | 100% → 15% | 52.4% → 54.8% | -2.6% → +0.0% | -2.6% → +0.0% | no / no |
| TF DOGE-USDT 6H [gate] | hold DOGE-USDT 6H [none] | 0.16 → 0.38 | +1.2% → +1.2% | 7.2% → 3.3% | 0.28 → 0.54 | 1.94 → ∞ | 9 → 1 | 100% → 11% | 52.4% → 38.1% | -2.6% → +0.0% | -2.6% → +0.0% | no / no |
| TF TRX-USDT 6H [none] | hold TRX-USDT 6H [none] | 1.11 → 0.12 | +7.3% → +0.7% | 6.6% → 5.6% | 1.13 → 0.25 | 8.79 → 2.39 | 9 → 6 | 100% → 18% | 71.4% → 45.2% | -2.7% → +0.0% | -2.7% → +0.0% | no / no |
| TF TRX-USDT 6H [gate] | hold TRX-USDT 6H [none] | 1.11 → -0.07 | +7.3% → -0.4% | 6.6% → 5.7% | 1.13 → -0.19 | 8.79 → 0.25 | 9 → 5 | 100% → 7% | 71.4% → 4.8% | -2.7% → -1.8% | -2.7% → +0.0% | no / no |
| TF ADA-USDT 6H [none] | hold ADA-USDT 6H [none] | 0.16 → 0.00 | +1.3% → +0.0% | 8.0% → -0.0% | 0.30 → 0.00 | 1.93 → 0.00 | 9 → 0 | 100% → 0% | 54.8% → 0.0% | -4.6% → +0.0% | -4.6% → +0.0% | no / no |
| TF ADA-USDT 6H [gate] | hold ADA-USDT 6H [none] | 0.16 → 0.00 | +1.3% → +0.0% | 8.0% → -0.0% | 0.30 → 0.00 | 1.93 → 0.00 | 9 → 0 | 100% → 0% | 54.8% → 0.0% | -4.6% → +0.0% | -4.6% → +0.0% | no / no |

Directional reading (pre-registered): Calmar rose beside hold + policy sizing in 3 of 20 configurations (10 expected by chance; the one-sided sign test needs at least 15 of 20 at the 5% level; P(at least this many by chance) = 1.000): the effect **does not replicate in direction**. The configurations share markets across two timeframes and two modes, so this is indicative, not a test of independent trials.

The filter as the exposure rule beside the always-long control with the same policy sizing, and beside the filtered breakout rule (H5) on the same series and mode:

| TF configuration | TF Calmar / CAGR / max DD / exposure / trades | Hold + policy Calmar / CAGR / max DD | Beats hold by 0.1 Calmar | S2+TF Calmar / CAGR / max DD | S2 Calmar | Breakout adds to the filter | 2022 TF / hold |
|---|---|---|---|---|---:|---|---|
| TF ADA-USDT 4H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.16 / +1.2% / 7.7% | no | 0.00 / +0.0% / -0.0% | 0.14 | no | +0.0% / -4.0% |
| TF ADA-USDT 4H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.16 / +1.2% / 7.7% | no | 0.00 / +0.0% / -0.0% | 0.17 | no | +0.0% / -4.0% |
| TF ADA-USDT 6H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.16 / +1.3% / 8.0% | no | 0.10 / +0.3% / 3.5% | 0.95 | yes | +0.0% / -4.6% |
| TF ADA-USDT 6H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.16 / +1.3% / 8.0% | no | 0.10 / +0.3% / 3.5% | 0.63 | yes | +0.0% / -4.6% |
| TF BTC-USDT 4H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.45 / +3.2% / 7.2% | no | -0.14 / -0.7% / 5.4% | 0.80 | no | +0.0% / -4.7% |
| TF BTC-USDT 4H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.45 / +3.2% / 7.2% | no | -0.21 / -1.6% / 7.8% | 0.38 | no | +0.0% / -4.7% |
| TF BTC-USDT 6H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.33 / +2.6% / 8.0% | no | -0.23 / -0.2% / 1.0% | 0.12 | no | +0.0% / -4.8% |
| TF BTC-USDT 6H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.33 / +2.6% / 8.0% | no | -0.08 / -0.4% / 5.5% | 0.07 | no | +0.0% / -4.8% |
| TF DOGE-USDT 4H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.10 / +0.7% / 6.9% | no | 0.00 / +0.0% / -0.0% | 0.85 | no | +0.0% / -2.5% |
| TF DOGE-USDT 4H [none] | 0.33 / +1.8% / 5.6% / 15% / 13 | 0.10 / +0.7% / 6.9% | yes | -0.09 / -0.3% / 3.0% | 0.29 | no | +0.0% / -2.5% |
| TF DOGE-USDT 6H [gate] | 0.38 / +1.2% / 3.3% / 11% / 1 | 0.16 / +1.2% / 7.2% | yes | 0.00 / +0.0% / -0.0% | 0.77 | no | +0.0% / -2.6% |
| TF DOGE-USDT 6H [none] | 0.32 / +1.5% / 4.6% / 15% / 9 | 0.16 / +1.2% / 7.2% | yes | 0.00 / +0.0% / -0.0% | 0.34 | no | +0.0% / -2.6% |
| TF ETH-USDT 4H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.20 / +1.8% / 8.6% | no | -0.09 / -0.5% / 5.8% | 0.07 | no | +0.0% / -4.1% |
| TF ETH-USDT 4H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.20 / +1.8% / 8.6% | no | -0.00 / -0.0% / 10.0% | 0.41 | no | +0.0% / -4.1% |
| TF ETH-USDT 6H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.26 / +2.5% / 9.6% | no | 0.09 / +0.6% / 6.1% | 0.62 | yes | +0.0% / -3.5% |
| TF ETH-USDT 6H [none] | 0.00 / +0.0% / -0.0% / 0% / 0 | 0.26 / +2.5% / 9.6% | no | 0.46 / +2.1% / 4.5% | 0.36 | yes | +0.0% / -3.5% |
| TF TRX-USDT 4H [gate] | 0.00 / +0.0% / -0.0% / 0% / 0 | 1.31 / +7.3% / 5.6% | no | 0.60 / +2.7% / 4.5% | 0.46 | yes | +0.0% / -1.5% |
| TF TRX-USDT 4H [none] | 0.14 / +0.9% / 6.0% / 18% / 8 | 1.31 / +7.3% / 5.6% | no | 0.30 / +2.1% / 6.8% | 0.58 | yes | +0.0% / -1.5% |
| TF TRX-USDT 6H [gate] | -0.07 / -0.4% / 5.7% / 7% / 5 | 1.11 / +7.3% / 6.6% | no | 0.95 / +4.9% / 5.2% | 0.54 | yes | +0.0% / -2.7% |
| TF TRX-USDT 6H [none] | 0.12 / +0.7% / 5.6% / 18% / 6 | 1.11 / +7.3% / 6.6% | no | 0.59 / +3.5% / 6.0% | 0.52 | yes | +0.0% / -2.7% |
The breakout rule added to the filter (S2+TF's Calmar above TF's) on 8 of 20 series; TF beat hold + policy by more than 0.1 Calmar on 3 of 20.

**Failure analysis** (computed from the numbers above):

- Across its 20 configurations the rule raised the risk-adjusted result (Calmar) beside hold + policy sizing in 3 and lowered it in 17: the median Calmar went from 0.23 to 0.00 (-0.23), the median yearly return from +2.1% to +0.0%, the median worst drawdown from 7.5% to -0.0%, and the median share of positive rolling 12-month windows from 64.6% to 0.0%.
- It was in the market 0% of the time against 100% for the always-long control, with a median 0 trades over the out-of-sample years; it beat the control by more than 0.1 Calmar (Sprint 2c's acceptance-clause yardstick) in 3 of 20 configurations; the drawdown fell in 19 of 20 and the return fell in 17 of 20.
- The protocol's selection rule (a bracket variant needs 20 train trades) let the rule trade in 13 of 180 walk-forward windows across the configurations; a window without a qualified variant stays flat.
- In the 2022 bear year the median result moved from -3.7% to +0.0%.
- With the HMM regime gate already on, Calmar still rose in 1 of 10 configurations (without the gate: 2 of 10).
- By timeframe: 4H: Calmar rose in 1 of 10; 6H: Calmar rose in 2 of 10.
- By market: ADA-USDT 0 of 4; BTC-USDT 0 of 4; DOGE-USDT 3 of 4; ETH-USDT 0 of 4; TRX-USDT 0 of 4.
- Gates missed most often: Sharpe above 0.7 (20 of 20), Calmar above 0.5 (20 of 20), 75% of rolling 12-month windows positive (20 of 20), at least 30 trades (20 of 20).
- Reading: the rule traded too rarely for the protocol. In 167 of 180 windows no bracket variant reached the 20 train trades the selection step requires, so the configurations sat flat and their numbers measure the selection rule, not the idea; where it did trade it beat the control by more than 0.1 Calmar in 3 of 20 configurations. The idea is untested here, not refuted: a rule that trades a few times a year needs a pre-registered protocol of its own (a lower qualification threshold for a fixed rule, or a forward control account in the paper fleet), which is an owner decision, not an edit of this round.

## The comparison lines — hold + policy controls and the plain S1 / S2 rules (stored numbers, reproduced here)

| Configuration | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Windows traded | Exposure | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Gates missed | Verdict | Holdout (12m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| hold BTC-USDT 4H [none] | none | +14.8% | +3.2% | 0.59 | 2.88 | 7.2% | 0.45 | 9 | 9/9 | 100% | 0.1% | 70.7% | -4.7% | - | 0.89 | - | control | -4.3% / PF 0.00 / 1 tr ✗ |
| S1 BTC-USDT 4H [none] | none | +9.4% | +2.1% | 0.37 | 1.23 | 8.3% | 0.25 | 184 | 9/9 | 52% | 1.4% | 61.0% | -4.4% | 75.0% | 0.04 | - | comparison line | untouched |
| S1 BTC-USDT 4H [gate] | none | +7.0% | +1.6% | 0.29 | 1.18 | 10.5% | 0.15 | 151 | 9/9 | 49% | 1.2% | 65.9% | -2.7% | 100.0% | 0.06 | - | comparison line | untouched |
| S2 BTC-USDT 4H [none] | none | +14.9% | +3.3% | 0.57 | 1.46 | 8.7% | 0.38 | 85 | 9/9 | 46% | 0.8% | 61.0% | -4.6% | 100.0% | 0.11 | - | comparison line | untouched |
| S2 BTC-USDT 4H [gate] | none | +24.7% | +5.2% | 0.86 | 1.94 | 6.5% | 0.80 | 69 | 8/9 | 43% | 0.7% | 80.5% | -3.2% | 100.0% | 0.19 | - | comparison line | -4.9% / PF 0.28 / 21 tr ✗ |
| hold ETH-USDT 4H [none] | none | +7.8% | +1.8% | 0.38 | 1.83 | 8.6% | 0.20 | 9 | 9/9 | 100% | 0.1% | 63.4% | -4.1% | - | 0.78 | - | control | -2.6% / PF 0.00 / 1 tr ✗ |
| S1 ETH-USDT 4H [none] | tp2 | -0.1% | -0.0% | 0.03 | 1.01 | 13.4% | -0.00 | 225 | 9/9 | 58% | 1.4% | 31.7% | -4.5% | 25.0% | 0.02 | - | comparison line | untouched |
| S1 ETH-USDT 4H [gate] | none | +5.6% | +1.3% | 0.25 | 1.18 | 11.5% | 0.11 | 150 | 9/9 | 47% | 1.1% | 39.0% | -3.0% | 87.5% | 0.10 | - | comparison line | untouched |
| S2 ETH-USDT 4H [none] | none | +16.7% | +3.6% | 0.62 | 1.63 | 8.8% | 0.41 | 77 | 9/9 | 42% | 0.5% | 63.4% | -0.6% | 100.0% | 0.11 | - | comparison line | untouched |
| S2 ETH-USDT 4H [gate] | time30 | +3.2% | +0.7% | 0.16 | 1.10 | 10.9% | 0.07 | 86 | 9/9 | 40% | 0.6% | 70.7% | -0.8% | 80.0% | 0.02 | - | comparison line | untouched |
| hold XRP-USDT 4H [none] | none | +12.3% | +2.7% | 0.55 | 2.97 | 5.8% | 0.46 | 9 | 9/9 | 100% | 0.0% | 52.4% | -3.0% | - | 0.88 | - | control | -2.2% / PF 0.00 / 1 tr ✗ |
| S1 XRP-USDT 4H [none] | none | -9.4% | -2.2% | -0.36 | 0.80 | 22.3% | -0.10 | 209 | 9/9 | 43% | 1.1% | 26.2% | -8.4% | 28.6% | 0.00 | - | comparison line | untouched |
| S1 XRP-USDT 4H [gate] | none | +1.2% | +0.3% | 0.08 | 1.06 | 16.7% | 0.02 | 184 | 9/9 | 39% | 1.0% | 33.3% | -5.7% | 42.9% | 0.00 | - | comparison line | untouched |
| S2 XRP-USDT 4H [none] | none | -0.3% | -0.1% | 0.01 | 1.02 | 16.8% | -0.00 | 92 | 9/9 | 42% | 0.4% | 26.2% | -6.3% | 100.0% | 0.00 | - | comparison line | untouched |
| S2 XRP-USDT 4H [gate] | none | +6.1% | +1.4% | 0.28 | 1.20 | 12.3% | 0.11 | 110 | 9/9 | 48% | 0.5% | 45.2% | -5.1% | 100.0% | 0.00 | - | comparison line | untouched |
| hold DOGE-USDT 4H [none] | none | +3.0% | +0.7% | 0.19 | 1.58 | 6.9% | 0.10 | 9 | 9/9 | 100% | 0.0% | 47.6% | -2.5% | - | 0.65 | - | control | -2.7% / PF 0.00 / 1 tr ✗ |
| S1 DOGE-USDT 4H [none] | none | +16.2% | +3.5% | 0.67 | 1.42 | 6.3% | 0.55 | 252 | 9/9 | 36% | 1.0% | 85.7% | -2.9% | 100.0% | 0.38 | - | comparison line | untouched |
| S1 DOGE-USDT 4H [gate] | trail1 | +3.4% | +0.8% | 0.20 | 1.14 | 5.8% | 0.13 | 132 | 9/9 | 21% | 0.5% | 57.1% | -2.7% | 100.0% | 0.02 | - | comparison line | untouched |
| S2 DOGE-USDT 4H [none] | none | +8.3% | +1.8% | 0.44 | 1.50 | 6.3% | 0.29 | 59 | 7/9 | 27% | 0.2% | 66.7% | -2.3% | 100.0% | 0.01 | - | comparison line | untouched |
| S2 DOGE-USDT 4H [gate] | none | +16.7% | +3.6% | 0.81 | 2.29 | 4.2% | 0.85 | 46 | 7/9 | 29% | 0.2% | 85.7% | -0.1% | 100.0% | 0.14 | - | comparison line | +1.7% / PF 1.70 / 8 tr ✗ |
| hold LINK-USDT 4H [none] | none | +7.1% | +1.6% | 0.37 | 2.90 | 5.6% | 0.28 | 9 | 9/9 | 100% | 0.0% | 54.8% | -2.2% | - | 0.78 | - | control | -1.7% / PF 0.00 / 1 tr ✗ |
| S1 LINK-USDT 4H [none] | time30 | -0.6% | -0.1% | 0.00 | 1.00 | 12.8% | -0.01 | 219 | 9/9 | 56% | 0.9% | 54.8% | -5.3% | 100.0% | 0.04 | - | comparison line | untouched |
| S1 LINK-USDT 4H [gate] | time30 | +7.3% | +1.6% | 0.33 | 1.23 | 8.7% | 0.19 | 186 | 9/9 | 48% | 0.8% | 61.9% | -4.1% | 100.0% | 0.10 | - | comparison line | untouched |
| S2 LINK-USDT 4H [none] | none | -4.0% | -0.9% | -0.17 | 0.87 | 11.6% | -0.08 | 96 | 9/9 | 47% | 0.4% | 40.5% | -5.0% | 100.0% | 0.01 | - | comparison line | untouched |
| S2 LINK-USDT 4H [gate] | none | -5.0% | -1.2% | -0.23 | 0.84 | 11.1% | -0.10 | 97 | 9/9 | 44% | 0.4% | 35.7% | -4.3% | 0.0% | 0.00 | - | comparison line | untouched |
| hold TRX-USDT 4H [none] | none | +36.4% | +7.3% | 1.30 | 11.67 | 5.6% | 1.31 | 9 | 9/9 | 100% | 0.1% | 78.6% | -1.5% | - | 1.00 | - | control | -0.8% / PF 0.00 / 1 tr ✗ |
| S1 TRX-USDT 4H [none] | none | +22.6% | +4.7% | 0.68 | 1.36 | 15.3% | 0.31 | 282 | 9/9 | 71% | 2.3% | 54.8% | -5.1% | 100.0% | 0.27 | - | comparison line | untouched |
| S1 TRX-USDT 4H [gate] | none | +18.9% | +4.0% | 0.59 | 1.33 | 12.7% | 0.32 | 177 | 9/9 | 59% | 2.0% | 57.1% | -4.6% | 100.0% | 0.31 | - | comparison line | untouched |
| S2 TRX-USDT 4H [none] | none | +24.1% | +5.0% | 0.82 | 1.63 | 8.7% | 0.58 | 95 | 9/9 | 44% | 1.2% | 76.2% | -4.8% | 100.0% | 0.22 | - | comparison line | -5.6% / PF 0.47 / 26 tr ✗ |
| S2 TRX-USDT 4H [gate] | none | +16.3% | +3.5% | 0.63 | 1.51 | 7.6% | 0.46 | 68 | 8/9 | 39% | 1.0% | 66.7% | -3.2% | 100.0% | 0.18 | - | comparison line | untouched |
| hold ADA-USDT 4H [none] | none | +5.5% | +1.2% | 0.29 | 1.86 | 7.7% | 0.16 | 9 | 9/9 | 100% | 0.0% | 54.8% | -4.0% | - | 0.73 | - | control | -3.0% / PF 0.00 / 1 tr ✗ |
| S1 ADA-USDT 4H [none] | none | +5.5% | +1.2% | 0.26 | 1.13 | 9.6% | 0.13 | 237 | 9/9 | 43% | 1.0% | 64.3% | -3.9% | 100.0% | 0.01 | - | comparison line | untouched |
| S1 ADA-USDT 4H [gate] | none | +8.1% | +1.8% | 0.41 | 1.30 | 11.2% | 0.16 | 161 | 9/9 | 30% | 0.7% | 64.3% | -4.0% | 100.0% | 0.01 | - | comparison line | untouched |
| S2 ADA-USDT 4H [none] | none | +6.2% | +1.4% | 0.32 | 1.26 | 8.1% | 0.17 | 80 | 9/9 | 36% | 0.3% | 57.1% | -3.3% | 90.0% | 0.00 | - | comparison line | untouched |
| S2 ADA-USDT 4H [gate] | none | +4.5% | +1.0% | 0.27 | 1.23 | 7.1% | 0.14 | 58 | 7/9 | 25% | 0.3% | 45.2% | -3.6% | 90.0% | 0.00 | - | comparison line | untouched |
| hold LTC-USDT 4H [none] | none | -1.8% | -0.4% | -0.08 | 0.79 | 7.6% | -0.05 | 9 | 9/9 | 100% | 0.0% | 38.1% | -2.1% | - | 0.44 | - | control | -1.4% / PF 0.00 / 1 tr ✗ |
| S1 LTC-USDT 4H [none] | none | -14.9% | -3.6% | -0.61 | 0.74 | 21.9% | -0.16 | 288 | 9/9 | 63% | 1.2% | 14.3% | -7.9% | 0.0% | 0.00 | - | comparison line | untouched |
| S1 LTC-USDT 4H [gate] | none | -14.3% | -3.5% | -0.58 | 0.65 | 21.9% | -0.16 | 203 | 9/9 | 54% | 0.9% | 14.3% | -6.8% | 0.0% | 0.00 | - | comparison line | untouched |
| S2 LTC-USDT 4H [none] | none | -2.2% | -0.5% | -0.06 | 0.96 | 12.0% | -0.04 | 118 | 9/9 | 46% | 0.6% | 31.0% | -5.9% | 0.0% | 0.00 | - | comparison line | untouched |
| S2 LTC-USDT 4H [gate] | none | -12.5% | -3.0% | -0.55 | 0.75 | 16.6% | -0.18 | 145 | 8/9 | 35% | 0.9% | 9.5% | -5.9% | 0.0% | 0.00 | - | comparison line | untouched |
| hold SOL-USDT 4H [none] | none | +23.9% | +6.4% | 1.07 | 4.84 | 6.7% | 0.96 | 7 | 7/7 | 100% | 0.0% | 76.7% | -5.3% | - | 0.98 | - | control | -2.3% / PF 0.00 / 1 tr ✗ |
| S1 SOL-USDT 4H [none] | none | +18.1% | +4.9% | 0.92 | 1.85 | 7.5% | 0.65 | 141 | 7/7 | 43% | 0.7% | 70.0% | -3.2% | 100.0% | 0.35 | - | comparison line | untouched |
| S1 SOL-USDT 4H [gate] | none | +6.0% | +1.7% | 0.39 | 1.25 | 6.2% | 0.27 | 134 | 7/7 | 31% | 0.7% | 53.3% | -3.3% | 100.0% | 0.18 | - | comparison line | untouched |
| S2 SOL-USDT 4H [none] | none | +11.7% | +3.3% | 0.60 | 1.62 | 7.2% | 0.46 | 73 | 7/7 | 54% | 0.3% | 60.0% | -4.4% | 100.0% | 0.32 | - | comparison line | untouched |
| S2 SOL-USDT 4H [gate] | none | +17.9% | +4.9% | 0.91 | 1.86 | 7.8% | 0.62 | 70 | 7/7 | 52% | 0.3% | 70.0% | -4.4% | 100.0% | 0.57 | - | comparison line | untouched |
| hold BTC-USDT 6H [none] | none | +11.8% | +2.6% | 0.49 | 2.37 | 8.0% | 0.33 | 9 | 9/9 | 100% | 0.1% | 73.2% | -4.8% | - | 0.84 | - | control | -4.0% / PF 0.00 / 1 tr ✗ |
| S1 BTC-USDT 6H [none] | none | +15.9% | +3.5% | 0.58 | 1.40 | 9.2% | 0.38 | 155 | 9/9 | 50% | 1.3% | 68.3% | -4.9% | 100.0% | 0.05 | - | comparison line | untouched |
| S1 BTC-USDT 6H [gate] | none | +17.5% | +3.8% | 0.63 | 1.42 | 11.4% | 0.33 | 146 | 9/9 | 53% | 1.2% | 73.2% | -4.2% | 100.0% | 0.06 | - | comparison line | untouched |
| S2 BTC-USDT 6H [none] | none | +3.0% | +0.7% | 0.16 | 1.10 | 10.0% | 0.07 | 69 | 7/9 | 35% | 0.7% | 58.5% | -3.5% | 100.0% | 0.02 | - | comparison line | untouched |
| S2 BTC-USDT 6H [gate] | none | +5.1% | +1.2% | 0.28 | 1.22 | 9.9% | 0.12 | 48 | 6/9 | 30% | 0.4% | 56.1% | -1.7% | 100.0% | 0.01 | - | comparison line | untouched |
| hold ETH-USDT 6H [none] | none | +11.0% | +2.5% | 0.50 | 2.04 | 9.6% | 0.26 | 9 | 9/9 | 100% | 0.1% | 65.9% | -3.5% | - | 0.85 | - | control | -2.9% / PF 0.00 / 1 tr ✗ |
| S1 ETH-USDT 6H [none] | none | +15.6% | +3.4% | 0.58 | 1.31 | 8.2% | 0.42 | 165 | 9/9 | 54% | 1.1% | 68.3% | -2.2% | 100.0% | 0.19 | - | comparison line | untouched |
| S1 ETH-USDT 6H [gate] | none | +12.4% | +2.7% | 0.51 | 1.38 | 7.5% | 0.37 | 113 | 9/9 | 41% | 0.9% | 80.5% | -1.8% | 100.0% | 0.21 | - | comparison line | untouched |
| S2 ETH-USDT 6H [none] | none | +14.8% | +3.2% | 0.57 | 1.39 | 9.1% | 0.36 | 85 | 9/9 | 36% | 0.6% | 61.0% | -2.1% | 100.0% | 0.14 | - | comparison line | untouched |
| S2 ETH-USDT 6H [gate] | none | +24.1% | +5.1% | 0.92 | 2.01 | 8.3% | 0.62 | 52 | 8/9 | 41% | 0.3% | 70.7% | +0.7% | 100.0% | 0.26 | - | comparison line | untouched |
| hold XRP-USDT 6H [none] | none | +21.1% | +4.4% | 0.79 | 4.72 | 5.8% | 0.77 | 9 | 9/9 | 100% | 0.0% | 61.9% | -2.8% | - | 0.96 | - | control | -2.7% / PF 0.00 / 1 tr ✗ |
| S1 XRP-USDT 6H [none] | none | +7.3% | +1.6% | 0.29 | 1.23 | 16.7% | 0.10 | 192 | 9/9 | 47% | 1.0% | 35.7% | -8.8% | 85.7% | 0.04 | - | comparison line | untouched |
| S1 XRP-USDT 6H [gate] | trail1 | +18.3% | +3.9% | 0.67 | 1.55 | 10.9% | 0.36 | 137 | 9/9 | 29% | 0.7% | 33.3% | -3.3% | 87.5% | 0.06 | - | comparison line | untouched |
| S2 XRP-USDT 6H [none] | time30 | +4.1% | +0.9% | 0.18 | 1.15 | 14.1% | 0.07 | 100 | 9/9 | 46% | 0.5% | 33.3% | -3.5% | 100.0% | 0.00 | - | comparison line | untouched |
| S2 XRP-USDT 6H [gate] | none | -2.0% | -0.5% | -0.11 | 0.91 | 7.5% | -0.06 | 47 | 7/9 | 28% | 0.2% | 28.6% | -1.7% | 100.0% | 0.00 | - | comparison line | untouched |
| hold DOGE-USDT 6H [none] | none | +5.2% | +1.2% | 0.28 | 1.94 | 7.2% | 0.16 | 9 | 9/9 | 100% | 0.0% | 52.4% | -2.6% | - | 0.72 | - | control | -3.1% / PF 0.00 / 1 tr ✗ |
| S1 DOGE-USDT 6H [none] | trail1 | +3.4% | +0.8% | 0.17 | 1.09 | 9.1% | 0.08 | 181 | 9/9 | 30% | 0.7% | 54.8% | -5.0% | 87.5% | 0.07 | - | comparison line | untouched |
| S1 DOGE-USDT 6H [gate] | trail1 | +14.2% | +3.1% | 0.61 | 1.53 | 5.9% | 0.52 | 109 | 9/9 | 21% | 0.5% | 78.6% | -0.4% | 100.0% | 0.33 | - | comparison line | untouched |
| S2 DOGE-USDT 6H [none] | none | +10.5% | +2.3% | 0.52 | 1.76 | 6.8% | 0.34 | 45 | 7/9 | 25% | 0.2% | 66.7% | -0.1% | 100.0% | 0.00 | - | comparison line | untouched |
| S2 DOGE-USDT 6H [gate] | none | +20.3% | +4.3% | 0.90 | 2.50 | 5.6% | 0.77 | 46 | 6/9 | 26% | 0.2% | 85.7% | +0.0% | 100.0% | 0.13 | - | comparison line | -0.6% / PF 0.87 / 10 tr ✗ |
| hold LINK-USDT 6H [none] | none | +8.9% | +2.0% | 0.42 | 3.52 | 5.5% | 0.35 | 9 | 9/9 | 100% | 0.0% | 54.8% | -2.4% | - | 0.81 | - | control | -1.7% / PF 0.00 / 1 tr ✗ |
| S1 LINK-USDT 6H [none] | none | +8.8% | +1.9% | 0.37 | 1.28 | 9.1% | 0.21 | 173 | 9/9 | 57% | 0.7% | 54.8% | -3.5% | 100.0% | 0.15 | - | comparison line | untouched |
| S1 LINK-USDT 6H [gate] | none | +5.0% | +1.1% | 0.23 | 1.17 | 11.3% | 0.10 | 164 | 9/9 | 49% | 0.6% | 54.8% | -5.1% | 57.1% | 0.20 | - | comparison line | untouched |
| S2 LINK-USDT 6H [none] | none | +0.8% | +0.2% | 0.06 | 1.05 | 10.8% | 0.02 | 79 | 9/9 | 40% | 0.3% | 40.5% | -4.1% | 50.0% | 0.08 | - | comparison line | untouched |
| S2 LINK-USDT 6H [gate] | none | -0.1% | -0.0% | 0.02 | 1.02 | 10.0% | -0.00 | 57 | 8/9 | 32% | 0.2% | 45.2% | -3.4% | 20.0% | 0.00 | - | comparison line | untouched |
| hold TRX-USDT 6H [none] | none | +36.3% | +7.3% | 1.13 | 8.79 | 6.6% | 1.11 | 9 | 9/9 | 100% | 0.1% | 71.4% | -2.7% | - | 1.00 | - | control | -0.1% / PF 0.00 / 1 tr ✗ |
| S1 TRX-USDT 6H [none] | none | +29.2% | +6.0% | 0.76 | 1.56 | 12.6% | 0.48 | 198 | 9/9 | 70% | 1.7% | 64.3% | -5.7% | 100.0% | 0.44 | - | comparison line | untouched |
| S1 TRX-USDT 6H [gate] | none | +28.2% | +5.8% | 0.74 | 1.54 | 15.1% | 0.39 | 199 | 9/9 | 56% | 1.9% | 66.7% | -7.7% | 100.0% | 0.40 | - | comparison line | untouched |
| S2 TRX-USDT 6H [none] | none | +32.2% | +6.6% | 0.84 | 1.64 | 12.6% | 0.52 | 119 | 9/9 | 43% | 1.5% | 64.3% | -7.2% | 100.0% | 0.09 | - | comparison line | untouched |
| S2 TRX-USDT 6H [gate] | none | +32.1% | +6.5% | 0.90 | 1.75 | 12.1% | 0.54 | 98 | 7/9 | 38% | 1.3% | 61.9% | -7.2% | 100.0% | 0.18 | - | comparison line | untouched |
| hold ADA-USDT 6H [none] | none | +5.9% | +1.3% | 0.30 | 1.93 | 8.0% | 0.16 | 9 | 9/9 | 100% | 0.0% | 54.8% | -4.6% | - | 0.73 | - | control | -3.7% / PF 0.00 / 1 tr ✗ |
| S1 ADA-USDT 6H [none] | none | +4.1% | +0.9% | 0.20 | 1.13 | 11.0% | 0.08 | 155 | 9/9 | 41% | 0.6% | 57.1% | -3.7% | 100.0% | 0.01 | - | comparison line | untouched |
| S1 ADA-USDT 6H [gate] | none | +3.9% | +0.9% | 0.20 | 1.12 | 10.4% | 0.08 | 147 | 9/9 | 40% | 0.6% | 52.4% | -4.1% | 100.0% | 0.00 | - | comparison line | untouched |
| S2 ADA-USDT 6H [none] | none | +20.6% | +4.3% | 0.87 | 1.99 | 6.9% | 0.63 | 65 | 9/9 | 40% | 0.3% | 83.3% | -1.7% | 100.0% | 0.03 | - | comparison line | -4.6% / PF 0.28 / 20 tr ✗ |
| S2 ADA-USDT 6H [gate] | none | +21.2% | +4.5% | 0.94 | 2.37 | 4.7% | 0.95 | 44 | 7/9 | 34% | 0.2% | 88.1% | -2.3% | 100.0% | 0.08 | - | comparison line | -6.0% / PF 0.07 / 20 tr ✗ |
| hold LTC-USDT 6H [none] | none | -0.7% | -0.1% | -0.01 | 0.94 | 7.6% | -0.02 | 9 | 9/9 | 100% | 0.0% | 47.6% | -2.0% | - | 0.49 | - | control | -1.1% / PF 0.00 / 1 tr ✗ |
| S1 LTC-USDT 6H [none] | none | -13.5% | -3.2% | -0.50 | 0.71 | 19.9% | -0.16 | 221 | 9/9 | 64% | 0.9% | 14.3% | -6.3% | 0.0% | 0.00 | - | comparison line | untouched |
| S1 LTC-USDT 6H [gate] | none | -14.9% | -3.6% | -0.61 | 0.66 | 22.0% | -0.16 | 187 | 9/9 | 49% | 0.8% | 11.9% | -7.0% | 0.0% | 0.00 | - | comparison line | untouched |
| S2 LTC-USDT 6H [none] | none | -11.8% | -2.8% | -0.52 | 0.67 | 15.6% | -0.18 | 87 | 8/9 | 41% | 0.4% | 23.8% | -6.8% | 0.0% | 0.00 | - | comparison line | untouched |
| S2 LTC-USDT 6H [gate] | none | -10.3% | -2.4% | -0.46 | 0.69 | 15.2% | -0.16 | 78 | 8/9 | 37% | 0.4% | 26.2% | -6.3% | 0.0% | 0.00 | - | comparison line | untouched |
| hold SOL-USDT 6H [none] | none | +28.5% | +7.5% | 1.13 | 5.40 | 7.0% | 1.08 | 7 | 7/7 | 100% | 0.0% | 76.7% | -5.0% | - | 0.98 | - | control | -2.5% / PF 0.00 / 1 tr ✗ |
| S1 SOL-USDT 6H [none] | time30 | +22.3% | +6.0% | 1.08 | 2.08 | 5.6% | 1.06 | 107 | 7/7 | 33% | 0.6% | 90.0% | -1.7% | 100.0% | 0.52 | - | comparison line | +9.5% / PF 5.49 / 12 tr ✓ |
| S1 SOL-USDT 6H [gate] | none | +18.9% | +5.1% | 0.92 | 1.99 | 6.9% | 0.74 | 105 | 7/7 | 35% | 0.5% | 60.0% | -2.7% | 100.0% | 0.49 | - | comparison line | untouched |
| S2 SOL-USDT 6H [none] | none | +9.1% | +2.6% | 0.51 | 1.46 | 7.3% | 0.35 | 67 | 7/7 | 44% | 0.3% | 73.3% | -5.9% | 100.0% | 0.23 | - | comparison line | untouched |
| S2 SOL-USDT 6H [gate] | none | +16.0% | +4.4% | 0.83 | 2.33 | 9.1% | 0.48 | 37 | 5/7 | 35% | 0.2% | 50.0% | -4.7% | 100.0% | 0.48 | - | comparison line | untouched |

Data spans: BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); ETH-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); XRP-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); DOGE-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); LINK-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); TRX-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); ADA-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); LTC-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); SOL-USDT 4H: 2020-09-30->2026-10-20 (13266 bars); BTC-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); ETH-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); XRP-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); DOGE-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); LINK-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); TRX-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); ADA-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); LTC-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); SOL-USDT 6H: 2020-09-30->2026-10-20 (8843 bars).

## The untouched 12 months

Opened once, only for configurations that passed every walk-forward gate (and the hold + policy controls as the comparison line). Verdict ✓ = positive return, PF > 1 and ≥ 10 trades. The holdout's falling direction was known before the run (see the pre-registration).

| Configuration | Return | Max DD | PF | Trades | Verdict |
|---|---:|---:|---:|---:|---|
| hold BTC-USDT 4H [none] | -4.3% | 5.2% | 0.00 | 1 | control (comparison line) |
| S2 BTC-USDT 4H [gate] | -4.9% | 6.3% | 0.28 | 21 | comparison line |
| hold ETH-USDT 4H [none] | -2.6% | 4.0% | 0.00 | 1 | control (comparison line) |
| hold XRP-USDT 4H [none] | -2.2% | 3.1% | 0.00 | 1 | control (comparison line) |
| hold DOGE-USDT 4H [none] | -2.7% | 3.0% | 0.00 | 1 | control (comparison line) |
| S2 DOGE-USDT 4H [gate] | +1.7% | 2.1% | 1.70 | 8 | comparison line |
| S1+VC DOGE-USDT 4H [none] | -3.1% | 5.7% | 0.43 | 27 | contradicted |
| S1+VC DOGE-USDT 4H [gate] | +1.8% | 2.3% | 1.65 | 18 | confirmed |
| hold LINK-USDT 4H [none] | -1.7% | 3.0% | 0.00 | 1 | control (comparison line) |
| hold TRX-USDT 4H [none] | -0.8% | 3.3% | 0.00 | 1 | control (comparison line) |
| S2 TRX-USDT 4H [none] | -5.6% | 7.5% | 0.47 | 26 | comparison line |
| hold ADA-USDT 4H [none] | -3.0% | 3.6% | 0.00 | 1 | control (comparison line) |
| hold LTC-USDT 4H [none] | -1.4% | 2.8% | 0.00 | 1 | control (comparison line) |
| hold SOL-USDT 4H [none] | -2.3% | 3.6% | 0.00 | 1 | control (comparison line) |
| S1+VC SOL-USDT 4H [none] | -2.4% | 5.2% | 0.56 | 25 | contradicted |
| hold BTC-USDT 6H [none] | -4.0% | 5.5% | 0.00 | 1 | control (comparison line) |
| hold ETH-USDT 6H [none] | -2.9% | 4.0% | 0.00 | 1 | control (comparison line) |
| hold XRP-USDT 6H [none] | -2.7% | 3.9% | 0.00 | 1 | control (comparison line) |
| hold DOGE-USDT 6H [none] | -3.1% | 3.6% | 0.00 | 1 | control (comparison line) |
| S2 DOGE-USDT 6H [gate] | -0.6% | 3.0% | 0.87 | 10 | comparison line |
| S1+VC DOGE-USDT 6H [gate] | -2.2% | 5.0% | 0.35 | 16 | contradicted |
| hold LINK-USDT 6H [none] | -1.7% | 3.4% | 0.00 | 1 | control (comparison line) |
| hold TRX-USDT 6H [none] | -0.1% | 3.4% | 0.00 | 1 | control (comparison line) |
| hold ADA-USDT 6H [none] | -3.7% | 4.4% | 0.00 | 1 | control (comparison line) |
| S2 ADA-USDT 6H [none] | -4.6% | 5.4% | 0.28 | 20 | comparison line |
| S2 ADA-USDT 6H [gate] | -6.0% | 6.4% | 0.07 | 20 | comparison line |
| hold LTC-USDT 6H [none] | -1.1% | 2.6% | 0.00 | 1 | control (comparison line) |
| hold SOL-USDT 6H [none] | -2.5% | 3.8% | 0.00 | 1 | control (comparison line) |
| S1 SOL-USDT 6H [none] | +9.5% | 2.1% | 5.49 | 12 | comparison line |
| S1+VC SOL-USDT 6H [none] | -1.6% | 5.1% | 0.68 | 23 | contradicted |

### Earlier looks at the same months by the comparison lines

A new rule on a series whose base rule already opened its holdout is a near-second look at those months; the base rule's stored result is shown beside it.

| Configuration opened in this run | Comparison line | Study | Its holdout then |
|---|---|---|---|
| S1+VC DOGE-USDT 4H [none] | S1 DOGE-USDT 4H [none] | R12 replication | never opened |
| S1+VC DOGE-USDT 4H [gate] | S1 DOGE-USDT 4H [gate] | R12 replication | never opened |
| S1+VC SOL-USDT 4H [none] | S1 SOL-USDT 4H [none] | R12 replication | never opened |
| S1+VC DOGE-USDT 6H [gate] | S1 DOGE-USDT 6H [gate] | R12 replication | never opened |
| S1+VC SOL-USDT 6H [none] | S1 SOL-USDT 6H [none] | R12 replication | +9.5% / PF 5.49 / 12 tr ✓ |

### Every opening of the holdout (ledger)

Each run that opened a holdout appends its openings to `docs/research/research_round_2_holdout_ledger.json`; earlier looks stay visible here even when a later run replaces the numbers above.

| Run | Configuration | Role | Return | Max DD | PF | Trades | Verdict |
|---|---|---|---:|---:|---:|---:|---|
| 1 (2026-11-04 21:33 UTC) | hold BTC-USDT 4H [none] | control | -4.3% | 5.2% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 BTC-USDT 4H [gate] | reproduction | -4.9% | 6.3% | 0.28 | 21 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold ETH-USDT 4H [none] | control | -2.6% | 4.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold XRP-USDT 4H [none] | control | -2.2% | 3.1% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold DOGE-USDT 4H [none] | control | -2.7% | 3.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 DOGE-USDT 4H [gate] | reproduction | +1.7% | 2.1% | 1.70 | 8 | comparison |
| 1 (2026-11-04 21:33 UTC) | S1+VC DOGE-USDT 4H [none] | configuration | -3.1% | 5.7% | 0.43 | 27 | contradicted |
| 1 (2026-11-04 21:33 UTC) | S1+VC DOGE-USDT 4H [gate] | configuration | +1.8% | 2.3% | 1.65 | 18 | confirmed |
| 1 (2026-11-04 21:33 UTC) | hold LINK-USDT 4H [none] | control | -1.7% | 3.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold TRX-USDT 4H [none] | control | -0.8% | 3.3% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 TRX-USDT 4H [none] | reproduction | -5.6% | 7.5% | 0.47 | 26 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold ADA-USDT 4H [none] | control | -3.0% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold LTC-USDT 4H [none] | control | -1.4% | 2.8% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold SOL-USDT 4H [none] | control | -2.3% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S1+VC SOL-USDT 4H [none] | configuration | -2.4% | 5.2% | 0.56 | 25 | contradicted |
| 1 (2026-11-04 21:33 UTC) | hold BTC-USDT 6H [none] | control | -4.0% | 5.5% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold ETH-USDT 6H [none] | control | -2.9% | 4.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold XRP-USDT 6H [none] | control | -2.7% | 3.9% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold DOGE-USDT 6H [none] | control | -3.1% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 DOGE-USDT 6H [gate] | reproduction | -0.6% | 3.0% | 0.87 | 10 | comparison |
| 1 (2026-11-04 21:33 UTC) | S1+VC DOGE-USDT 6H [gate] | configuration | -2.2% | 5.0% | 0.35 | 16 | contradicted |
| 1 (2026-11-04 21:33 UTC) | hold LINK-USDT 6H [none] | control | -1.7% | 3.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold TRX-USDT 6H [none] | control | -0.1% | 3.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold ADA-USDT 6H [none] | control | -3.7% | 4.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 ADA-USDT 6H [none] | reproduction | -4.6% | 5.4% | 0.28 | 20 | comparison |
| 1 (2026-11-04 21:33 UTC) | S2 ADA-USDT 6H [gate] | reproduction | -6.0% | 6.4% | 0.07 | 20 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold LTC-USDT 6H [none] | control | -1.1% | 2.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | hold SOL-USDT 6H [none] | control | -2.5% | 3.8% | 0.00 | 1 | comparison |
| 1 (2026-11-04 21:33 UTC) | S1 SOL-USDT 6H [none] | reproduction | +9.5% | 2.1% | 5.49 | 12 | comparison |
| 1 (2026-11-04 21:33 UTC) | S1+VC SOL-USDT 6H [none] | configuration | -1.6% | 5.1% | 0.68 | 23 | contradicted |

## Paper-fleet shortlist

Confirmed passers appended to `docs/research/paper_fleet_shortlist_v1c.json` with a `source` tag (existing entries and running accounts untouched):

- S1+VC DOGE-USDT 4H (hmm3 bear>=0.5 gate): walk-forward Calmar 0.83, holdout +1.8%

Shortlist file: docs/research/paper_fleet_shortlist_v1c.json now lists 14 configurations (24 fleet accounts).

## Owner decisions (nothing below is decided by this report)

- **Fleet.** 1 new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). Recommended: let them run; judge them at G7 with the rest.
- **What the verdicts mean.** H4: confirmed; H5: failed walk-forward; H6: failed walk-forward. No gate, parameter, condition, market or verdict rule changed after the results. If a gate looks wrong, that is a note for the next pre-registered round, not an edit of this one.
- **Slow rules.** H5 traded in 53 of 180 windows; H6 traded in 13 of 180 windows: the protocol's 20-train-trade qualification, built for rules that trade weekly, cannot judge a rule that trades a few times a year. Whether to evaluate such rules another way — a forward control account in the paper fleet, or a pre-registered protocol variant with a lower qualification threshold for fixed rules — is a decision for the owner (`docs/PLAN_STATUS.md`, section 2); nothing here is retuned.
- **Next round.** The failure analyses above say which ideas are not worth another test; anything left credible is a decision for the owner, as a new plan row.

## Method notes and caveats

- The rules were not re-implemented and the runner was not changed: Sprint 2c's runner module ran them; the reproduction table shows the same code gives the stored numbers for hold, S1 and S2 on every market of the round.
- The conditions gate entries only (an open position is left to the base rule's own exits and stop), exactly as the regime gate, the S5 filter and the round-1 conditions do; TF is a rule, not a condition: it exits when the close crosses back below its average and carries no stop, so the protocol's take-profit and trailing brackets are inert for it and its walk-forward selects only between no bracket and the 30-day time stop.
- TF's one parameter is a single grid value; the protocol's robustness replay perturbs it by ±30 % (140 and 260 days) like every rule's numeric parameters. The protocol's selection rule (20 train trades) applies to it unchanged; the 'Windows traded' column shows where it bound.
- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed policy sizing is Sprint 2b's; none of them was adapted to the new rules or the new markets.
- The reproduction re-runs stored passers through the same holdout code path (S2 BTC-USDT 4H [gate], S1 SOL-USDT 6H [none], the contradicted S2 rows on ADA, DOGE and TRX), so their already-opened 12 months appear again in the ledger as comparison lines with their stored numbers; that is a repeat of a known result, not a new look. A new rule's opening on a series whose base rule already opened its holdout is listed as an earlier look above.
- 68 judged configurations are 68 more comparisons on the same six years; two or three passes among them at the Sprint 2c pass rate would be expected by chance, which is why the holdout and the forward fleet, not single passes, carry the verdict. The directional sign tests treat configurations as trials although they share markets, so they are indicative only.
- The holdout's falling direction was known for every market before this study; every condition reduces time in the market and a slow trend filter is built to sit out a bear year. Confirmation there is necessary, not sufficient.
- Every number is a simulation on historical public data and proves nothing about the future.
