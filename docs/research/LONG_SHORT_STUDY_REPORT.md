# Phase 9 design study — long and short through perpetual swaps without leverage (walk-forward, SIMULATION ONLY)

Generated 2026-10-22 02:44 UTC by `scripts/run_long_short_study.py` (plan row R9; 7.2 min). Data: PUBLIC OKX spot candles from the Parquet lake (BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); BTC-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); ETH-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); ETH-USDT 6H: 2019-12-29->2026-10-20 (9949 bars)); 6H bars resampled from 1H (UTC). Funding: binance public funding history as the proxy for OKX's swaps. Perpetual-swap prices: OKX's public BTC-/ETH-USDT-SWAP candles (diagnostic). Costs: spot fee 0.10%, swap fee 0.05%, slippage 0.05% per side. Walk-forward: train 540.0 d -> purge 7.0 d -> test 180.0 d, rule selected on the train slice by sharpe with >= 20 trades; policy sizing `vt10/30 crash15/90dh ladder` on both sides. Holdout: 2025-10-20->2026-10-20, opened only for configurations meeting the walk-forward part of the evidence rule; every opening is in the ledger below.

**Nothing here authorizes paper, demo or live trading, derivatives access or Phase 9.** Trading shorts and perpetual swaps is forbidden by the safety contract (`CLAUDE.md`, `PROJECT_RULES.md`); this is a paper study the owner asked for so that the Phase 9 decision rests on numbers. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we tested.** Whether the trend rules of Sprint 2c (S1, S2, S4 and S1+S5) earn more, for the risk they take, when they may also be SHORT through BTC- and ETH-USDT perpetual swaps with collateral at least equal to the position (no leverage). Two designs: the long leg stays on spot and only the short uses the swap (hybrid), or both legs use the swap (all-perp). 32 configurations (4 families x BTC/ETH x 4H/6H x 2 designs), the same walk-forward, sizing policy and gates as Sprint 2c, after fees, slippage and funding; everything was fixed before the first run.
- **Result.** 4 of 32 configurations passed the Sprint 2c gates and 4 met the whole walk-forward part of the pre-registered rule (S2 ETH-USDT 4H hybrid, S2 ETH-USDT 4H perp, S2 ETH-USDT 6H hybrid, S2 ETH-USDT 6H perp). The untouched 12 months then confirmed 2 and contradicted 2 (S2 ETH-USDT 4H hybrid: -4.8% / PF 0.59 / 42 tr ✗ contradicted; S2 ETH-USDT 4H perp: -4.6% / PF 0.59 / 42 tr ✗ contradicted; S2 ETH-USDT 6H hybrid: +2.3% / PF 1.29 / 28 tr ✓ confirmed; S2 ETH-USDT 6H perp: +2.3% / PF 1.29 / 28 tr ✓ confirmed).
- **Did the short side help?** Mostly not. With the short leg added (hybrid design) the risk-adjusted result (Calmar) beat the long-only rule in 3 of 16 family-and-series pairs (median Calmar 0.05 against 0.35 long-only). The short leg on its own made money (profit factor above 1 after costs and funding) in 7 of 16 configurations: on BTC it lost in 7 of 8, on ETH it won in 6 of 8. It made the 2022 bear year better than long-only in 13 of 16 pairs; the median 2022 result improved (-2.6% long-only, -1.5% with shorts), and 4 of 16 pairs ended 2022 positive. With the families' fixed default parameters over 2020-01 to the holdout start (no selection at all) the short leg lowered Calmar in 15 of 16 pairs and lost money in 15 of 16.
- **Funding and the two designs.** Funding flowed mostly from longs to shorts: on the proxy series it averaged +13.1% a year for BTC and +15.7% for ETH (2020 to the holdout start, paid by longs when positive). The hybrid's shorts received a median 0.62% of capital over the whole walk-forward; the all-perp design's longs paid a median 3.59%. The hybrid made more than the all-perp design in 13 of 16 pairs: if shorts ever come, the long side should stay on spot.
- **The risk a short carries.** BTC rose up to 138% within 30 days (from 2020-12-11) and up to 29% within one hour; ETH rose up to 151% within 30 days (from 2020-12-24) and up to 25% within one hour. A 1x short with no stop is liquidated by a rise of about 99 %; that rise came within 30 days from BTC 0.4%, ETH 1.3% of the hourly closes of the span. With the study's ATR stops no simulated short was liquidated (highest account leverage 0.84x); every short needs an exchange-side stop.
- **What it means.** Under the pre-registered rule 1 rule counts as evidence: S2 ETH-USDT 6H (hybrid and perp). It is weak evidence: 1 rule on 1 coin; the holdout contradicted S2 ETH-USDT 4H, which met the same walk-forward rule; the holdout's falling direction was known before it was opened, which flatters any rule that can be short (pre-registered); the confirmed holdout's short side traded 10 times; across all configurations the short leg made money in only 7 of 16. Not enough to advance Phase 9.

## Fixed before the first run

Pre-registration hash (with the configuration): `977162712ac4f6f846fd39964313a9360029f21c5f6a38428585e2df004d6fed`.

- **fixed_on**: 2026-10-22, before the first full run (plan row R9)
- **question**: Does a short leg through USDT-margined perpetual swaps at no leverage (collateral >= position) improve the Sprint 2c trend rules out of sample on BTC-USDT and ETH-USDT, after fees, slippage and funding?
- **families**: S1; S2; S4; S1+S5
- **series**: BTC-USDT 4H; BTC-USDT 6H; ETH-USDT 4H; ETH-USDT 6H
- **entry_rules_and_grids**: exactly Sprint 2c's (research/strategies), brackets none/tp2/trail1/time30 (none only for S1+S5)
- **short_rules**: mirror images with the same parameters: S1 >= vote lookbacks negative; S2 close below the prior entry_days low with the same volume/ATR filters, cover above the prior exit_days high; S4 close below the lower band after a squeeze, cover above the mid band; S5 mirror: no new short while the funding z-score < -funding_z_max or open interest surges; ATR stop above the entry; a short needs a finite stop
- **priority**: the long side is the long-only rule unchanged; a short may only start while it is flat and the S0 filter (and the S5 mirror) allow a new entry; one position at a time; the long side wins a tie
- **designs**: hybrid: long on spot (fee 0.10 %, no funding), short on the perpetual swap (fee 0.05 % + funding); perp: long and short on the perpetual swap (fee 0.05 % + funding); slippage: 0.05 % per side everywhere
- **funding**: Binance BTCUSDT/ETHUSDT public funding history as the proxy for OKX's swaps (OKX keeps months); each settlement charged on the position open at the close of the bar it settles in, on |quantity| x that close; longs pay positive rates, shorts receive them; OKX's own funding compared with the proxy where both exist
- **sizing**: Sprint 2c's fixed policy vt10/30 crash15/90dh ladder (rebalance threshold 0.25, ladder re-arm 30 days), the same fraction for both sides, fraction <= 1 so a short's notional at entry never exceeds the equity behind it
- **walk_forward**: train 540 d -> purge 7 d -> test 180 d; Sharpe with >= 20 train trades; entries first, then the bracket
- **gates**: the v1c gates unchanged (research/report_v1c.py GATES)
- **phase9_evidence_rule**: (1) passes the v1c gates on the walk-forward; (2) the short leg alone has a walk-forward profit factor > 1 after costs and funding; (3) walk-forward Calmar above Sprint 2c's long-only result for the same family and series; (4) the untouched holdout confirms (positive return, profit factor > 1, >= 10 trades)
- **holdout**: last 12 months (2025-10-20 -> 2026-10-20), opened once and only for configurations meeting (1)-(3); known in advance: BTC -26 %, ETH -39 % over these months (Sprint 2c, R5b), so a confirmation is weak and a contradiction strong evidence
- **configurations_judged**: 32
- **diagnostics_not_gates**: leg attribution and funding; slippage x2/x3 and funding x2 replays; the short leg replayed on OKX perpetual-swap candles; fixed default parameters 2020-01-01 -> holdout start; funding by year, spot-perp basis, the largest rises against a short

Added after the pipeline smoke run (diagnostics only; no verdict depends on them):

- 2026-10-22, after the smoke run of S1 on BTC-USDT 4H and before the full run: the shorts of every configuration replayed with the policy sizing minus its crash filter (vol target and ladder only), on the walk-forward's own per-window selections — the pre-registered policy applies Sprint 2b's crash filter to both sides; it halves exposure while the price is more than 15 % below its 90-day peak, which is the market state in which a short leg is expected to earn — the Phase 9 design has to know what that rule costs the shorts

Fixed after the first full run, from the independent code review (no gate, rule, configuration or parameter changed; the first run's holdout openings are in the ledger below):

- flips: a short that the long side needs now closes at the open before that bar's stops are checked, so the long enters where the long-only rule enters; before, a short whose stop also fired in the flip bar was booked at its stop and the long entered one bar late, against the pre-registered 'long side unchanged' (changes numbers of configurations with flips (mostly S1 and S1+S5); tested: the long side now trades exactly like the long-only rule)
- the S5 mirror and the S0 filter gate a short's start one after the other, in the long side's order (they were combined on one bar) (S1+S5 only, a fraction of a percent of short bars)
- a leg without a losing trade has profit factor 999 (Sprint 2c's convention) instead of an empty value (reporting only)
- the holdout can only be opened by the full pre-registered study (never in quick mode or on a subset), and every opening is appended to a ledger the report shows (protocol only)

Gates (unchanged from Sprint 2c): profit_factor_min 1.2; max_drawdown_max 0.2; sharpe_min 0.7; calmar_min 0.5; rolling_12m_positive_min 0.75; worst_calendar_year_min -0.1; min_trades 30; robust_share_min 0.5; min_year_days 60.

## Reproduction of Sprint 2c

Before anything long/short ran, each family's long-only rule went through the same long/short engine and walk-forward code and had to give Sprint 2c's stored walk-forward numbers (stored with 6 decimals) — otherwise the study stops.

| Family | Series | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Largest difference | Agrees |
|---|---|---|---|---|---:|---|---:|---|
| S1 | BTC-USDT 4H | 0.093620 / 0.093620 | 0.374170 / 0.374170 | 0.083135 / 0.083135 | 184 / 184 | yes | 4.9e-07 | yes |
| S2 | BTC-USDT 4H | 0.149350 / 0.149350 | 0.570857 / 0.570857 | 0.086735 / 0.086735 | 85 / 85 | yes | 3.7e-07 | yes |
| S4 | BTC-USDT 4H | 0.050366 / 0.050366 | 0.268301 / 0.268301 | 0.099307 / 0.099307 | 109 / 109 | yes | 4.6e-07 | yes |
| S1+S5 | BTC-USDT 4H | 0.121162 / 0.121162 | 0.444672 / 0.444672 | 0.083272 / 0.083272 | 179 / 179 | yes | 4.3e-07 | yes |
| S1 | BTC-USDT 6H | 0.159336 / 0.159336 | 0.584869 / 0.584869 | 0.091930 / 0.091930 | 155 / 155 | yes | 4.9e-07 | yes |
| S2 | BTC-USDT 6H | 0.029879 / 0.029879 | 0.160691 / 0.160691 | 0.099668 / 0.099668 | 69 / 69 | yes | 3.1e-07 | yes |
| S4 | BTC-USDT 6H | 0.106119 / 0.106119 | 0.519579 / 0.519579 | 0.057990 / 0.057990 | 92 / 92 | yes | 3.5e-07 | yes |
| S1+S5 | BTC-USDT 6H | 0.247165 / 0.247165 | 0.856002 / 0.856002 | 0.087603 / 0.087603 | 139 / 139 | yes | 3.2e-07 | yes |
| S1 | ETH-USDT 4H | -0.000879 / -0.000879 | 0.025942 / 0.025942 | 0.134491 / 0.134491 | 225 / 225 | yes | 3.1e-07 | yes |
| S2 | ETH-USDT 4H | 0.167322 / 0.167322 | 0.616527 / 0.616527 | 0.088169 / 0.088169 | 77 / 77 | yes | 3.8e-07 | yes |
| S4 | ETH-USDT 4H | -0.064707 / -0.064707 | -0.454670 / -0.454670 | 0.110272 / 0.110272 | 81 / 81 | yes | 4.7e-07 | yes |
| S1+S5 | ETH-USDT 4H | 0.008910 / 0.008910 | 0.064212 / 0.064212 | 0.136380 / 0.136380 | 204 / 204 | yes | 3.0e-07 | yes |
| S1 | ETH-USDT 6H | 0.155841 / 0.155841 | 0.578727 / 0.578727 | 0.082298 / 0.082298 | 165 / 165 | yes | 4.2e-07 | yes |
| S2 | ETH-USDT 6H | 0.147567 / 0.147567 | 0.570377 / 0.570377 | 0.090869 / 0.090869 | 85 / 85 | yes | 4.6e-07 | yes |
| S4 | ETH-USDT 6H | 0.146265 / 0.146265 | 0.775388 / 0.775388 | 0.095065 / 0.095065 | 88 / 88 | yes | 3.9e-07 | yes |
| S1+S5 | ETH-USDT 6H | 0.125671 / 0.125671 | 0.477462 / 0.477462 | 0.073772 / 0.073772 | 145 / 145 | yes | 4.1e-07 | yes |

## Summary (one row per family x series x design)

Calmar = CAGR / max drawdown of the stitched out-of-sample curve. 'Long-only Calmar' is Sprint 2c's stored result for the same family and series. 'Funding' is the net funding received (+) or paid (-) over all test windows, in % of window capital. Rule: the walk-forward part of the pre-registered evidence rule.

| Family | Series | Design | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Long-only Calmar | Trades (long/short) | Time short | Short-leg PF | Funding | Gates | Rule (1)(2)(3) | Holdout (12m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| S1 | BTC-USDT 4H | hybrid | +2.0% | +0.5% | 0.10 | 1.04 | 12.8% | 0.04 | 0.25 | 344 (178/166) | 40% | 0.85 | +0.78% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1 | BTC-USDT 4H | perp | -2.9% | -0.7% | -0.06 | 0.96 | 14.1% | -0.05 | 0.25 | 354 (183/171) | 40% | 0.79 | -3.71% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S2 | BTC-USDT 4H | hybrid | -2.2% | -0.5% | -0.05 | 0.98 | 12.3% | -0.04 | 0.38 | 151 (79/72) | 29% | 0.62 | +1.00% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S2 | BTC-USDT 4H | perp | -4.4% | -1.0% | -0.14 | 0.93 | 12.8% | -0.08 | 0.38 | 151 (79/72) | 29% | 0.62 | -2.60% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S4 | BTC-USDT 4H | hybrid | -2.1% | -0.5% | -0.08 | 0.98 | 12.2% | -0.04 | 0.11 | 200 (96/104) | 13% | 0.54 | +0.66% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S4 | BTC-USDT 4H | perp | -0.6% | -0.1% | -0.00 | 1.01 | 12.1% | -0.01 | 0.11 | 211 (103/108) | 13% | 0.58 | -0.69% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1+S5 | BTC-USDT 4H | hybrid | +3.5% | +0.8% | 0.15 | 1.06 | 11.6% | 0.07 | 0.32 | 320 (162/158) | 39% | 0.85 | +0.76% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1+S5 | BTC-USDT 4H | perp | -1.6% | -0.4% | -0.02 | 0.98 | 13.1% | -0.03 | 0.32 | 330 (167/163) | 40% | 0.79 | -3.74% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1 | BTC-USDT 6H | hybrid | +11.1% | +2.5% | 0.38 | 1.18 | 12.3% | 0.20 | 0.38 | 306 (155/151) | 39% | 0.93 | +0.79% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1 | BTC-USDT 6H | perp | +7.3% | +1.6% | 0.27 | 1.12 | 11.8% | 0.14 | 0.38 | 315 (164/151) | 39% | 0.92 | -3.92% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S2 | BTC-USDT 6H | hybrid | -8.2% | -2.0% | -0.30 | 0.83 | 14.6% | -0.13 | 0.07 | 113 (62/51) | 31% | 0.50 | +0.86% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S2 | BTC-USDT 6H | perp | -13.2% | -3.2% | -0.54 | 0.74 | 17.8% | -0.18 | 0.07 | 127 (73/54) | 33% | 0.57 | -2.70% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S4 | BTC-USDT 6H | hybrid | +0.7% | +0.2% | 0.06 | 1.03 | 12.5% | 0.01 | 0.41 | 144 (73/71) | 15% | 0.73 | +0.69% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S4 | BTC-USDT 6H | perp | +0.2% | +0.1% | 0.04 | 1.02 | 12.3% | 0.00 | 0.41 | 144 (73/71) | 15% | 0.73 | -1.42% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1+S5 | BTC-USDT 6H | hybrid | +13.4% | +3.0% | 0.46 | 1.25 | 11.7% | 0.25 | 0.60 | 276 (153/123) | 37% | 1.25 | +0.70% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S1+S5 | BTC-USDT 6H | perp | +11.2% | +2.5% | 0.39 | 1.22 | 11.6% | 0.21 | 0.60 | 276 (153/123) | 37% | 1.25 | -3.86% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S1 | ETH-USDT 4H | hybrid | -2.5% | -0.6% | -0.06 | 0.97 | 21.1% | -0.03 | -0.00 | 392 (208/184) | 36% | 0.82 | +0.54% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1 | ETH-USDT 4H | perp | -3.5% | -0.8% | -0.10 | 0.96 | 20.6% | -0.04 | -0.00 | 395 (210/185) | 36% | 0.82 | -2.96% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S2 | ETH-USDT 4H | hybrid | +26.0% | +5.5% | 0.81 | 1.50 | 8.3% | 0.66 | 0.41 | 143 (75/68) | 35% | 1.01 | +0.59% | **PASS** | ✓(1) ✓(2) ✓(3) | -4.8% / PF 0.59 / 42 tr ✗ contradicted |
| S2 | ETH-USDT 4H | perp | +25.0% | +5.3% | 0.78 | 1.48 | 8.3% | 0.64 | 0.41 | 147 (80/67) | 39% | 1.16 | -3.03% | **PASS** | ✓(1) ✓(2) ✓(3) | -4.6% / PF 0.59 / 42 tr ✗ contradicted |
| S4 | ETH-USDT 4H | hybrid | -6.9% | -1.6% | -0.37 | 0.86 | 12.1% | -0.13 | -0.14 | 174 (90/84) | 12% | 1.02 | +0.35% | fail | ✗(1) ✓(2) ✓(3) | untouched |
| S4 | ETH-USDT 4H | perp | -6.4% | -1.5% | -0.35 | 0.87 | 11.8% | -0.13 | -0.14 | 176 (91/85) | 12% | 1.02 | -0.71% | fail | ✗(1) ✓(2) ✓(3) | untouched |
| S1+S5 | ETH-USDT 4H | hybrid | -1.4% | -0.3% | -0.02 | 0.99 | 20.6% | -0.02 | 0.01 | 358 (182/176) | 36% | 0.80 | +0.54% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1+S5 | ETH-USDT 4H | perp | -1.6% | -0.4% | -0.03 | 0.98 | 20.1% | -0.02 | 0.01 | 361 (184/177) | 36% | 0.81 | -3.04% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1 | ETH-USDT 6H | hybrid | +18.1% | +3.9% | 0.57 | 1.28 | 10.9% | 0.36 | 0.42 | 275 (151/124) | 30% | 1.24 | +0.58% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S1 | ETH-USDT 6H | perp | +20.3% | +4.4% | 0.61 | 1.28 | 10.9% | 0.40 | 0.42 | 289 (165/124) | 30% | 1.29 | -3.68% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S2 | ETH-USDT 6H | hybrid | +21.5% | +4.6% | 0.81 | 1.49 | 7.5% | 0.61 | 0.36 | 105 (54/51) | 32% | 1.18 | +0.42% | **PASS** | ✓(1) ✓(2) ✓(3) | +2.3% / PF 1.29 / 28 tr ✓ confirmed |
| S2 | ETH-USDT 6H | perp | +19.7% | +4.3% | 0.75 | 1.45 | 7.5% | 0.56 | 0.36 | 105 (54/51) | 32% | 1.18 | -2.02% | **PASS** | ✓(1) ✓(2) ✓(3) | +2.3% / PF 1.29 / 28 tr ✓ confirmed |
| S4 | ETH-USDT 6H | hybrid | +15.8% | +3.5% | 0.69 | 1.38 | 10.8% | 0.32 | 0.34 | 143 (71/72) | 15% | 1.13 | +0.44% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S4 | ETH-USDT 6H | perp | +13.4% | +3.0% | 0.61 | 1.33 | 12.0% | 0.25 | 0.34 | 143 (72/71) | 14% | 1.00 | -1.63% | fail | ✗(1) ✗(2) ✗(3) | untouched |
| S1+S5 | ETH-USDT 6H | hybrid | +17.2% | +3.7% | 0.56 | 1.36 | 10.5% | 0.36 | 0.38 | 236 (125/111) | 32% | 1.39 | +0.57% | fail | ✗(1) ✓(2) ✗(3) | untouched |
| S1+S5 | ETH-USDT 6H | perp | +14.6% | +3.2% | 0.49 | 1.31 | 10.3% | 0.31 | 0.38 | 236 (125/111) | 32% | 1.41 | -3.54% | fail | ✗(1) ✓(2) ✗(3) | untouched |

## Did the short side help? Long-only against the two designs

| Family | Series | Long-only Calmar | Hybrid Calmar | All-perp Calmar | Long-only CAGR | Hybrid CAGR | All-perp CAGR | 2022 long-only | 2022 hybrid | 2022 all-perp |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | BTC-USDT 4H | 0.25 | 0.04 | -0.05 | +2.1% | +0.5% | -0.7% | -4.4% | -0.4% | -0.2% |
| S1 | BTC-USDT 6H | 0.38 | 0.20 | 0.14 | +3.5% | +2.5% | +1.6% | -4.9% | -3.9% | -3.7% |
| S1 | ETH-USDT 4H | -0.00 | -0.03 | -0.04 | -0.0% | -0.6% | -0.8% | -4.5% | -3.9% | -3.6% |
| S1 | ETH-USDT 6H | 0.42 | 0.36 | 0.40 | +3.4% | +3.9% | +4.4% | -2.2% | -1.7% | -1.8% |
| S1+S5 | BTC-USDT 4H | 0.32 | 0.07 | -0.03 | +2.7% | +0.8% | -0.4% | -4.4% | -0.3% | -0.1% |
| S1+S5 | BTC-USDT 6H | 0.60 | 0.25 | 0.21 | +5.3% | +3.0% | +2.5% | -5.7% | -0.7% | -0.5% |
| S1+S5 | ETH-USDT 4H | 0.01 | -0.02 | -0.02 | +0.2% | -0.3% | -0.4% | -4.6% | -4.4% | -4.1% |
| S1+S5 | ETH-USDT 6H | 0.38 | 0.36 | 0.31 | +2.8% | +3.7% | +3.2% | -2.3% | -1.3% | -1.1% |
| S2 | BTC-USDT 4H | 0.38 | -0.04 | -0.08 | +3.3% | -0.5% | -1.0% | -2.4% | -4.3% | -4.3% |
| S2 | BTC-USDT 6H | 0.07 | -0.13 | -0.18 | +0.7% | -2.0% | -3.2% | -2.8% | -2.6% | +1.9% |
| S2 | ETH-USDT 4H | 0.41 | 0.66 | 0.64 | +3.6% | +5.5% | +5.3% | -0.5% | +2.0% | +5.3% |
| S2 | ETH-USDT 6H | 0.36 | 0.61 | 0.56 | +3.2% | +4.6% | +4.3% | -2.1% | +3.0% | +3.1% |
| S4 | BTC-USDT 4H | 0.11 | -0.04 | -0.01 | +1.1% | -0.5% | -0.1% | -2.1% | -3.8% | -3.7% |
| S4 | BTC-USDT 6H | 0.41 | 0.01 | 0.00 | +2.4% | +0.2% | +0.1% | -3.4% | +0.2% | +0.2% |
| S4 | ETH-USDT 4H | -0.14 | -0.13 | -0.13 | -1.5% | -1.6% | -1.5% | -2.3% | -3.7% | -3.5% |
| S4 | ETH-USDT 6H | 0.34 | 0.32 | 0.25 | +3.2% | +3.5% | +3.0% | -0.2% | +0.7% | +0.8% |

- hybrid (long spot, short perp): Calmar above long-only in 3 of 16 pairs; 2022 better than long-only in 13 of 16 and positive in 4; short leg profitable in 7 of 16 (BTC losing in 7 of 8, ETH winning in 6 of 8); median Calmar 0.05 against 0.35 long-only.

- all-perp (long and short perp): Calmar above long-only in 3 of 16 pairs; 2022 better than long-only in 13 of 16 and positive in 5; short leg profitable in 6 of 16 (BTC losing in 7 of 8, ETH winning in 5 of 8); median Calmar -0.00 against 0.35 long-only.

The hybrid design (long on spot) made more than the all-perp design in 13 of 16 pairs.

## Where the money came from: the two legs

P&L includes fees and funding, in % of window capital summed over the test windows (each window restarts at the same capital, so these are additive contributions, not compounded returns). 'Worst short excursion' is the largest move against a short while it was open; 'max leverage' is the largest position value / account equity at any bar close.

| Family | Series | Design | Long trades | Long PF | Long P&L | Long funding | Short trades | Short PF | Short win rate | Short P&L | Short funding | Worst short trade | Worst short excursion | Max leverage |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | BTC-USDT 4H | hybrid | 178 | 1.16 | +6.4% | +0.00% | 166 | 0.85 | 32% | -4.0% | +0.78% | -8.8% | -9.4% | 0.78 |
| S1 | BTC-USDT 4H | perp | 183 | 1.08 | +3.1% | -4.53% | 171 | 0.79 | 31% | -5.6% | +0.82% | -8.8% | -9.4% | 0.78 |
| S2 | BTC-USDT 4H | hybrid | 79 | 1.33 | +8.8% | +0.00% | 72 | 0.62 | 24% | -10.0% | +1.00% | -7.3% | -6.9% | 0.58 |
| S2 | BTC-USDT 4H | perp | 79 | 1.24 | +6.4% | -3.60% | 72 | 0.62 | 24% | -10.0% | +1.00% | -7.3% | -6.9% | 0.58 |
| S4 | BTC-USDT 4H | hybrid | 96 | 1.46 | +12.9% | +0.00% | 104 | 0.54 | 26% | -14.1% | +0.66% | -6.0% | -6.4% | 0.70 |
| S4 | BTC-USDT 4H | perp | 103 | 1.48 | +13.6% | -1.36% | 108 | 0.58 | 26% | -13.3% | +0.67% | -8.9% | -7.8% | 0.70 |
| S1+S5 | BTC-USDT 4H | hybrid | 162 | 1.20 | +7.3% | +0.00% | 158 | 0.85 | 31% | -3.6% | +0.76% | -8.8% | -8.7% | 0.78 |
| S1+S5 | BTC-USDT 4H | perp | 167 | 1.10 | +3.8% | -4.53% | 163 | 0.79 | 30% | -5.1% | +0.80% | -8.8% | -8.7% | 0.78 |
| S1 | BTC-USDT 6H | hybrid | 155 | 1.35 | +13.4% | +0.00% | 151 | 0.93 | 33% | -1.8% | +0.79% | -15.0% | -14.7% | 0.70 |
| S1 | BTC-USDT 6H | perp | 164 | 1.24 | +10.0% | -4.71% | 151 | 0.92 | 33% | -2.1% | +0.80% | -15.0% | -14.7% | 0.70 |
| S2 | BTC-USDT 6H | hybrid | 62 | 1.07 | +1.8% | +0.00% | 51 | 0.50 | 25% | -9.7% | +0.86% | -8.6% | -7.6% | 0.50 |
| S2 | BTC-USDT 6H | perp | 73 | 0.83 | -5.8% | -3.54% | 54 | 0.57 | 30% | -7.9% | +0.83% | -8.6% | -7.6% | 0.50 |
| S4 | BTC-USDT 6H | hybrid | 73 | 1.29 | +8.0% | +0.00% | 71 | 0.73 | 32% | -6.6% | +0.69% | -12.6% | -8.6% | 0.70 |
| S4 | BTC-USDT 6H | perp | 73 | 1.27 | +7.5% | -2.11% | 71 | 0.73 | 32% | -6.6% | +0.69% | -12.6% | -8.6% | 0.70 |
| S1+S5 | BTC-USDT 6H | hybrid | 153 | 1.26 | +9.4% | +0.00% | 123 | 1.25 | 35% | +4.2% | +0.70% | -8.7% | -10.8% | 0.70 |
| S1+S5 | BTC-USDT 6H | perp | 153 | 1.21 | +7.3% | -4.57% | 123 | 1.25 | 35% | +4.2% | +0.70% | -8.7% | -10.8% | 0.70 |
| S1 | ETH-USDT 4H | hybrid | 208 | 1.07 | +2.9% | +0.00% | 184 | 0.82 | 32% | -4.8% | +0.54% | -9.5% | -11.1% | 0.43 |
| S1 | ETH-USDT 4H | perp | 210 | 1.04 | +1.7% | -3.50% | 185 | 0.82 | 32% | -4.7% | +0.54% | -10.7% | -10.1% | 0.43 |
| S2 | ETH-USDT 4H | hybrid | 75 | 1.87 | +23.9% | +0.00% | 68 | 1.01 | 31% | +0.2% | +0.59% | -8.1% | -7.8% | 0.69 |
| S2 | ETH-USDT 4H | perp | 80 | 1.69 | +20.2% | -3.63% | 67 | 1.16 | 30% | +3.1% | +0.61% | -8.1% | -7.8% | 0.69 |
| S4 | ETH-USDT 4H | hybrid | 90 | 0.76 | -7.2% | +0.00% | 84 | 1.02 | 35% | +0.4% | +0.35% | -8.3% | -7.9% | 0.72 |
| S4 | ETH-USDT 4H | perp | 91 | 0.77 | -6.8% | -1.06% | 85 | 1.02 | 34% | +0.5% | +0.35% | -8.3% | -7.9% | 0.72 |
| S1+S5 | ETH-USDT 4H | hybrid | 182 | 1.13 | +4.5% | +0.00% | 176 | 0.80 | 32% | -5.3% | +0.54% | -9.5% | -11.1% | 0.43 |
| S1+S5 | ETH-USDT 4H | perp | 184 | 1.12 | +4.1% | -3.58% | 177 | 0.81 | 32% | -5.1% | +0.54% | -10.7% | -10.1% | 0.43 |
| S1 | ETH-USDT 6H | hybrid | 151 | 1.30 | +13.3% | +0.00% | 124 | 1.24 | 38% | +4.3% | +0.58% | -13.2% | -18.0% | 0.84 |
| S1 | ETH-USDT 6H | perp | 165 | 1.28 | +14.6% | -4.25% | 124 | 1.29 | 38% | +4.9% | +0.58% | -11.5% | -18.0% | 0.84 |
| S2 | ETH-USDT 6H | hybrid | 54 | 1.69 | +17.2% | +0.00% | 51 | 1.18 | 24% | +2.9% | +0.42% | -15.0% | -11.2% | 0.84 |
| S2 | ETH-USDT 6H | perp | 54 | 1.63 | +15.6% | -2.44% | 51 | 1.18 | 24% | +2.9% | +0.42% | -15.0% | -11.2% | 0.84 |
| S4 | ETH-USDT 6H | hybrid | 71 | 1.55 | +14.1% | +0.00% | 72 | 1.13 | 42% | +2.3% | +0.44% | -10.7% | -9.8% | 0.84 |
| S4 | ETH-USDT 6H | perp | 72 | 1.59 | +14.3% | -2.00% | 71 | 1.00 | 39% | -0.0% | +0.36% | -10.7% | -9.8% | 0.62 |
| S1+S5 | ETH-USDT 6H | hybrid | 125 | 1.35 | +11.1% | +0.00% | 111 | 1.39 | 37% | +6.0% | +0.57% | -13.2% | -18.0% | 0.84 |
| S1+S5 | ETH-USDT 6H | perp | 125 | 1.27 | +8.6% | -4.10% | 111 | 1.41 | 37% | +6.1% | +0.57% | -13.2% | -18.0% | 0.84 |

## The untouched 12 months

Known before it was opened (pre-registered): BTC fell about 26 % and ETH about 39 % over these months (Sprint 2c, R5b), so a rule that can be short is expected to look better here than a long-only rule. A confirmation is weak evidence; a contradiction is strong evidence.

| Family | Series | Design | Return | Max DD | PF | Trades | Time short | Long leg P&L (PF) | Short leg P&L (PF) | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| S2 | ETH-USDT 4H | hybrid | -4.8% | 6.3% | 0.59 | 42 | 49% | -5.8% (0.08) | +1.0% (1.20) | contradicted |
| S2 | ETH-USDT 4H | perp | -4.6% | 6.3% | 0.59 | 42 | 49% | -5.7% (0.09) | +1.0% (1.20) | contradicted |
| S2 | ETH-USDT 6H | hybrid | +2.3% | 3.8% | 1.29 | 28 | 36% | -3.7% (0.31) | +6.0% (3.47) | confirmed |
| S2 | ETH-USDT 6H | perp | +2.3% | 3.8% | 1.29 | 28 | 36% | -3.7% (0.31) | +6.0% (3.47) | confirmed |

### Every opening of the holdout (ledger)

Each run that opened the holdout appends its openings to `docs/research/long_short_holdout_ledger.json`; earlier looks stay visible here even when a later run replaces the numbers above.

| Run | Configuration | Return | Max DD | PF | Trades | Verdict |
|---|---|---:|---:|---:|---:|---|
| 1 (2026-10-22 01:25 UTC) | S2 ETH-USDT 4H hybrid | -5.0% | 6.6% | 0.57 | 43 | contradicted |
| 1 (2026-10-22 01:25 UTC) | S2 ETH-USDT 4H perp | -4.9% | 6.4% | 0.58 | 43 | contradicted |
| 1 (2026-10-22 01:25 UTC) | S2 ETH-USDT 6H hybrid | +4.1% | 2.3% | 2.47 | 14 | confirmed |
| 1 (2026-10-22 01:25 UTC) | S2 ETH-USDT 6H perp | +4.1% | 2.3% | 2.48 | 14 | confirmed |
| 2 (2026-10-22 02:44 UTC) | S2 ETH-USDT 4H hybrid | -4.8% | 6.3% | 0.59 | 42 | contradicted |
| 2 (2026-10-22 02:44 UTC) | S2 ETH-USDT 4H perp | -4.6% | 6.3% | 0.59 | 42 | contradicted |
| 2 (2026-10-22 02:44 UTC) | S2 ETH-USDT 6H hybrid | +2.3% | 3.8% | 1.29 | 28 | confirmed |
| 2 (2026-10-22 02:44 UTC) | S2 ETH-USDT 6H perp | +2.3% | 3.8% | 1.29 | 28 | confirmed |

- Run 1: First full run. The independent code review then found that a flip (short to long or back) was delayed by one bar when the old position's stop fired in the flip bar; the engine was fixed and the study re-run (next entry). Recorded here because these four holdout results were seen before the re-run.

## The same rules with fixed default parameters (no selection), 2020-01-01 to the holdout start

Each family's default parameters (fixed in Sprint 2, before any of these studies), no exit bracket, the policy sizing, one uninterrupted run per series. No parameter was chosen on these data, so this is the plain 'what if it had always run' view; the walk-forward above is the protocol's answer.

| Family | Series | Span | Long-only CAGR / max DD / Calmar | Hybrid CAGR / max DD / Calmar | All-perp CAGR / max DD / Calmar | Short-leg PF (hybrid) | 2022 long-only / hybrid |
|---|---|---|---|---|---|---:|---|
| S1 | BTC-USDT 4H | 2020-01-01->2025-10-20 | +4.1% / 8.1% / 0.51 | +3.9% / 9.4% / 0.41 | +3.4% / 9.5% / 0.36 | 0.86 | -3.0% / -1.6% |
| S2 | BTC-USDT 4H | 2020-01-01->2025-10-20 | +6.5% / 7.1% / 0.91 | +5.5% / 10.2% / 0.54 | +4.7% / 10.1% / 0.47 | 0.64 | -0.9% / +0.4% |
| S4 | BTC-USDT 4H | 2020-01-01->2025-10-20 | +3.0% / 6.9% / 0.44 | +0.6% / 11.6% / 0.05 | +0.3% / 11.6% / 0.02 | 0.59 | -2.4% / -0.5% |
| S1+S5 | BTC-USDT 4H | 2020-01-01->2025-10-20 | +4.3% / 7.4% / 0.58 | +3.8% / 9.0% / 0.42 | +3.7% / 9.0% / 0.41 | 0.87 | -3.0% / -3.2% |
| S1 | BTC-USDT 6H | 2020-01-01->2025-10-19 | +5.2% / 7.9% / 0.66 | +4.1% / 8.5% / 0.48 | +3.4% / 8.5% / 0.39 | 0.82 | -2.9% / -1.4% |
| S2 | BTC-USDT 6H | 2020-01-01->2025-10-19 | +5.3% / 8.1% / 0.66 | +3.4% / 9.3% / 0.36 | +2.5% / 9.7% / 0.26 | 0.43 | -2.0% / -1.2% |
| S4 | BTC-USDT 6H | 2020-01-01->2025-10-19 | +2.8% / 5.3% / 0.54 | -0.1% / 7.7% / -0.01 | +0.0% / 7.7% / 0.00 | 0.60 | -3.0% / -2.4% |
| S1+S5 | BTC-USDT 6H | 2020-01-01->2025-10-19 | +5.3% / 8.0% / 0.66 | +4.4% / 8.4% / 0.52 | +3.6% / 8.4% / 0.43 | 0.86 | -3.0% / -1.6% |
| S1 | ETH-USDT 4H | 2020-01-01->2025-10-20 | +4.4% / 11.1% / 0.40 | +3.0% / 11.3% / 0.26 | +1.0% / 11.5% / 0.09 | 0.84 | -0.3% / +2.0% |
| S2 | ETH-USDT 4H | 2020-01-01->2025-10-20 | +4.8% / 7.4% / 0.65 | +4.6% / 6.2% / 0.75 | +3.6% / 6.2% / 0.58 | 0.97 | -0.8% / +2.5% |
| S4 | ETH-USDT 4H | 2020-01-01->2025-10-20 | +2.6% / 8.5% / 0.30 | +1.7% / 11.0% / 0.16 | +1.4% / 11.0% / 0.13 | 0.74 | -0.8% / +0.6% |
| S1+S5 | ETH-USDT 4H | 2020-01-01->2025-10-20 | +4.3% / 11.1% / 0.39 | +2.9% / 11.8% / 0.25 | +1.5% / 11.6% / 0.13 | 0.75 | -0.4% / +2.9% |
| S1 | ETH-USDT 6H | 2020-01-01->2025-10-19 | +6.3% / 7.9% / 0.79 | +4.3% / 9.1% / 0.47 | +3.5% / 9.7% / 0.36 | 0.82 | -0.5% / +2.1% |
| S2 | ETH-USDT 6H | 2020-01-01->2025-10-19 | +4.6% / 7.3% / 0.63 | +3.9% / 8.3% / 0.47 | +3.1% / 8.3% / 0.37 | 1.22 | +0.1% / +4.0% |
| S4 | ETH-USDT 6H | 2020-01-01->2025-10-19 | +3.4% / 6.7% / 0.51 | +3.0% / 10.9% / 0.28 | +2.7% / 10.7% / 0.26 | 0.74 | +0.3% / -0.7% |
| S1+S5 | ETH-USDT 6H | 2020-01-01->2025-10-19 | +6.3% / 7.9% / 0.79 | +4.3% / 9.3% / 0.46 | +3.5% / 9.4% / 0.38 | 0.80 | -0.5% / +1.3% |

With the short leg the Calmar was lower in 15 of 16 pairs, the short leg lost money in 15 of 16, and 2022 was better than long-only in 14 of 16.

## Diagnostics (never gates)

- **Perp-priced**: the walk-forward's own per-window selections replayed with the swap leg(s) trading OKX's perpetual-swap candles (stops and targets on the swap's prices; signals from spot). Largest Calmar change: 0.05.
- **No crash filter on shorts** (post-hoc, see above): the same selections with the shorts sized by the policy minus its crash filter. Calmar was lower in 28 of 32 configurations: halving shorts while the price is far below its peak protected them more than it cost — the sharp rebounds after a crash are where shorts get hurt.
- **Fixed rule / slippage / funding**: the most-selected rule replayed with fixed parameters over every test window (no re-selection, which is why its return differs from the walk-forward's), with slippage x2 and x3, and with funding switched off (x0) or doubled (x2).

| Family | Series | Design | Calmar (as run) | Perp-priced Calmar | No crash filter on shorts: Calmar / short PF | Fixed rule: return | slippage x2 | slippage x3 | funding x0 | funding x2 |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| S1 | BTC-USDT 4H | hybrid | 0.04 | 0.04 | -0.06 / 0.73 | +27.9% | +22.2% | +12.3% | +26.9% | +29.4% |
| S1 | BTC-USDT 4H | perp | -0.05 | -0.04 | -0.12 / 0.70 | +28.6% | +18.7% | +10.9% | +32.6% | +22.6% |
| S2 | BTC-USDT 4H | hybrid | -0.04 | -0.05 | -0.20 / 0.54 | +14.5% | +13.3% | +11.6% | +13.7% | +15.8% |
| S2 | BTC-USDT 4H | perp | -0.08 | -0.09 | -0.21 / 0.54 | +11.8% | +10.3% | +8.6% | +14.5% | +8.3% |
| S4 | BTC-USDT 4H | hybrid | -0.04 | -0.04 | -0.14 / 0.52 | -5.1% | -7.5% | -10.4% | -5.6% | -4.5% |
| S4 | BTC-USDT 4H | perp | -0.01 | -0.04 | -0.11 / 0.55 | -5.0% | -7.4% | -10.2% | -4.3% | -5.6% |
| S1+S5 | BTC-USDT 4H | hybrid | 0.07 | 0.07 | -0.04 / 0.71 | +27.7% | +22.1% | +12.1% | +26.7% | +29.1% |
| S1+S5 | BTC-USDT 4H | perp | -0.03 | -0.02 | -0.10 / 0.69 | +28.3% | +18.6% | +10.6% | +32.3% | +22.4% |
| S1 | BTC-USDT 6H | hybrid | 0.20 | 0.20 | 0.04 / 0.87 | +35.7% | +22.5% | +17.3% | +34.3% | +37.5% |
| S1 | BTC-USDT 6H | perp | 0.14 | 0.13 | 0.02 / 0.87 | +32.9% | +21.2% | +15.1% | +37.1% | +28.9% |
| S2 | BTC-USDT 6H | hybrid | -0.13 | -0.14 | -0.16 / 0.47 | +1.0% | -1.3% | -2.1% | +0.3% | +1.5% |
| S2 | BTC-USDT 6H | perp | -0.18 | -0.19 | -0.18 / 0.58 | -9.0% | -10.1% | -12.1% | -6.9% | -10.9% |
| S4 | BTC-USDT 6H | hybrid | 0.01 | 0.01 | 0.03 / 0.82 | +2.2% | -0.3% | -2.8% | +1.5% | +2.9% |
| S4 | BTC-USDT 6H | perp | 0.00 | 0.00 | 0.02 / 0.82 | +1.5% | -1.2% | -3.6% | +3.0% | +0.0% |
| S1+S5 | BTC-USDT 6H | hybrid | 0.25 | 0.25 | 0.14 / 0.93 | +36.4% | +30.1% | +24.9% | +34.9% | +38.2% |
| S1+S5 | BTC-USDT 6H | perp | 0.21 | 0.22 | 0.11 / 0.95 | +33.6% | +27.1% | +21.9% | +37.8% | +29.6% |
| S1 | ETH-USDT 4H | hybrid | -0.03 | -0.02 | -0.03 / 0.83 | +5.6% | -4.9% | -11.6% | +4.8% | +6.1% |
| S1 | ETH-USDT 4H | perp | -0.04 | -0.03 | -0.04 / 0.83 | +5.5% | -5.0% | -10.6% | +8.0% | +3.0% |
| S2 | ETH-USDT 4H | hybrid | 0.66 | 0.61 | 0.28 / 0.89 | +16.3% | +14.3% | +12.3% | +15.6% | +17.1% |
| S2 | ETH-USDT 4H | perp | 0.64 | 0.60 | 0.25 / 0.98 | +13.9% | +11.9% | +10.0% | +16.7% | +11.1% |
| S4 | ETH-USDT 4H | hybrid | -0.13 | -0.13 | -0.16 / 0.90 | +8.2% | +5.0% | +2.5% | +7.7% | +8.9% |
| S4 | ETH-USDT 4H | perp | -0.13 | -0.12 | -0.16 / 0.90 | +7.7% | +4.5% | +2.5% | +9.4% | +6.6% |
| S1+S5 | ETH-USDT 4H | hybrid | -0.02 | -0.01 | -0.02 / 0.81 | +10.1% | +4.0% | -2.7% | +9.1% | +12.2% |
| S1+S5 | ETH-USDT 4H | perp | -0.02 | -0.02 | -0.03 / 0.82 | +10.8% | +3.0% | -2.1% | +13.3% | +7.8% |
| S1 | ETH-USDT 6H | hybrid | 0.36 | 0.33 | 0.29 / 1.05 | +21.9% | +19.4% | +17.6% | +21.5% | +22.2% |
| S1 | ETH-USDT 6H | perp | 0.40 | 0.38 | 0.32 / 1.08 | +9.9% | +3.9% | -0.8% | +13.3% | +6.8% |
| S2 | ETH-USDT 6H | hybrid | 0.61 | 0.62 | 0.41 / 1.08 | +11.8% | +9.4% | +5.3% | +11.0% | +12.5% |
| S2 | ETH-USDT 6H | perp | 0.56 | 0.55 | 0.37 / 1.08 | +9.4% | +7.1% | +3.1% | +11.9% | +6.9% |
| S4 | ETH-USDT 6H | hybrid | 0.32 | 0.34 | 0.30 / 1.08 | +19.8% | +17.7% | +15.7% | +19.5% | +20.2% |
| S4 | ETH-USDT 6H | perp | 0.25 | 0.25 | 0.24 / 1.01 | +19.1% | +17.0% | +14.9% | +20.6% | +17.9% |
| S1+S5 | ETH-USDT 6H | hybrid | 0.36 | 0.35 | 0.34 / 1.16 | +11.7% | +9.0% | +3.8% | +11.3% | +12.0% |
| S1+S5 | ETH-USDT 6H | perp | 0.31 | 0.31 | 0.29 / 1.16 | +9.9% | +7.2% | +2.1% | +13.1% | +6.9% |

## Funding, 2020 to the holdout start

Proxy: Binance's public USDT-margined funding history (the rate longs pay shorts when positive), 2020-01-01->2025-10-20. 'Summed' is what a 1x long held through every settlement of the year paid, in % of its notional (a short received it).

| Coin | Year | Settlements | Annualized mean | Summed | Negative settlements | Lowest | Highest |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | 2020 | 1098 | +17.2% | +17.2% | 14.3% | -0.300% | +0.300% |
| BTC | 2021 | 1095 | +30.7% | +30.6% | 7.3% | -0.090% | +0.249% |
| BTC | 2022 | 1095 | +4.2% | +4.2% | 22.1% | -0.119% | +0.010% |
| BTC | 2023 | 1095 | +7.9% | +7.9% | 10.1% | -0.011% | +0.055% |
| BTC | 2024 | 1098 | +11.9% | +12.0% | 8.4% | -0.011% | +0.088% |
| BTC | 2025 | 876 | +5.2% | +4.1% | 12.9% | -0.012% | +0.010% |
| ETH | 2020 | 1098 | +27.5% | +27.5% | 2.6% | -0.282% | +0.367% |
| ETH | 2021 | 1095 | +37.6% | +37.5% | 4.1% | -0.356% | +0.375% |
| ETH | 2022 | 1095 | +0.8% | +0.8% | 34.2% | -0.302% | +0.010% |
| ETH | 2023 | 1095 | +8.3% | +8.3% | 9.1% | -0.017% | +0.071% |
| ETH | 2024 | 1098 | +13.0% | +13.0% | 4.2% | -0.011% | +0.102% |
| ETH | 2025 | 876 | +5.0% | +4.0% | 16.8% | -0.025% | +0.010% |

OKX's own funding against the proxy, where both exist (OKX's public history keeps only months):

| Coin | Settlements matched | Span | Correlation | Same sign | OKX annualized | Binance annualized | Difference |
|---|---:|---|---:|---:|---:|---:|---:|
| BTC | 297 | 2026-07-13 -> 2026-10-20 | 0.53 | 89% | +5.4% | +5.8% | -0.4% |
| ETH | 297 | 2026-07-13 -> 2026-10-20 | 0.55 | 84% | +4.2% | +4.5% | -0.2% |

## What a short would have faced

The largest rise a short opened at an hourly close would have faced within each horizon (the highest high of the next hours against that close), spot and perpetual swap, 2020-01-01 to the holdout start. 'Liquidation share' counts the hourly closes from which an unprotected 1x isolated short would have been liquidated (a rise of about 99 % with OKX's 0.4 % maintenance margin).

| Coin | Market | 4 hours | 1 day | 7 days | 30 days (from) | 30-day windows with >= 20 % rise | Liquidation share (30 days) | Largest 1-hour spike (at) |
|---|---|---:|---:|---:|---|---:|---:|---|
| BTC | spot | 33.3% | 44.7% | 55.4% | 137.7% (2020-12-11) | 29.2% | 0.41% | 28.6% (2020-03-13 02:00) |
| BTC | perp | 34.0% | 48.8% | 59.3% | 138.4% (2020-12-11) | 29.4% | 0.41% | 32.3% (2020-03-13 02:00) |
| ETH | spot | 43.7% | 46.1% | 79.0% | 150.6% (2020-12-24) | 42.6% | 1.35% | 25.1% (2020-03-13 03:00) |
| ETH | perp | 44.2% | 46.7% | 79.8% | 151.3% (2020-12-24) | 42.9% | 1.37% | 25.6% (2020-03-13 02:00) |

Spot-perp basis (perp close / spot close - 1 at matching hourly closes):

| Coin | Hours | Mean | Median | 1st pct | 99th pct | Lowest | Highest | Hours beyond ±0.5 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 50856 | +0.011% | +0.004% | -0.060% | +0.272% | -4.81% | +3.75% | 0.51% |
| ETH | 50856 | +0.008% | +0.003% | -0.077% | +0.217% | -2.92% | +2.25% | 0.30% |

## Per-configuration details

### S1 BTC-USDT 4H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 40%, highest account leverage 0.78x, net funding +0.78% of capital.

Calendar years: 2021 +1.0% · 2022 -0.4% · 2023 +5.9% · 2024 -4.8% · 2025 +0.6%. Rolling 12-month windows 41 sampled, 41.5% positive; worst calendar year 2024 at -4.8%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +27.9%, neighbours median +8.4%, min -4.4%, 75.0% profitable over 8. Deflated Sharpe 0.01 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 344 trades): terminal growth p05 0.81x / p50 1.02x / p95 1.30x, P(loss) 45.4%, max DD p50 13.2% / p95 24.3%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1 BTC-USDT 4H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Windows 9 (9 traded, 3 positive). Time short 40%, highest account leverage 0.78x, net funding -3.71% of capital.

Calendar years: 2021 +0.5% · 2022 -0.2% · 2023 +5.4% · 2024 -5.5% · 2025 -2.8%. Rolling 12-month windows 41 sampled, 43.9% positive; worst calendar year 2024 at -5.5%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +28.6%, neighbours median +6.2%, min -5.5%, 75.0% profitable over 8. Deflated Sharpe 0.01 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 354 trades): terminal growth p05 0.78x / p50 0.96x / p95 1.23x, P(loss) 60.2%, max DD p50 14.8% / p95 25.6%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S2 BTC-USDT 4H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 20, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 29%, highest account leverage 0.58x, net funding +1.00% of capital.

Calendar years: 2021 -2.9% · 2022 -4.3% · 2023 +9.1% · 2024 +1.4% · 2025 -4.9%. Rolling 12-month windows 41 sampled, 58.5% positive; worst calendar year 2025 at -4.9%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +14.5%, neighbours median +10.1%, min +0.6%, 100.0% profitable over 10. Deflated Sharpe 0.01 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 151 trades): terminal growth p05 0.77x / p50 0.97x / p95 1.27x, P(loss) 57.6%, max DD p50 14.1% / p95 26.0%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S2 BTC-USDT 4H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 20, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 29%, highest account leverage 0.58x, net funding -2.60% of capital.

Calendar years: 2021 -3.2% · 2022 -4.3% · 2023 +8.3% · 2024 +0.3% · 2025 -4.9%. Rolling 12-month windows 41 sampled, 58.5% positive; worst calendar year 2025 at -4.9%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +11.8%, neighbours median +7.3%, min -2.1%, 90.0% profitable over 10. Deflated Sharpe 0.00 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 151 trades): terminal growth p05 0.77x / p50 0.95x / p95 1.22x, P(loss) 63.8%, max DD p50 14.7% / p95 26.5%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S4 BTC-USDT 4H — hybrid (long spot, short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 13%, highest account leverage 0.70x, net funding +0.66% of capital.

Calendar years: 2021 -3.5% · 2022 -3.8% · 2023 +7.9% · 2024 +8.1% · 2025 -9.6%. Rolling 12-month windows 41 sampled, 58.5% positive; worst calendar year 2025 at -9.6%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected -5.1%, neighbours median -5.9%, min -9.2%, 25.0% profitable over 8. Deflated Sharpe 0.05 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 200 trades): terminal growth p05 0.80x / p50 0.98x / p95 1.21x, P(loss) 57.8%, max DD p50 13.3% / p95 23.9%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S4 BTC-USDT 4H — all-perp (long and short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 13%, highest account leverage 0.70x, net funding -0.69% of capital.

Calendar years: 2021 -2.5% · 2022 -3.7% · 2023 +8.1% · 2024 +8.2% · 2025 -9.5%. Rolling 12-month windows 41 sampled, 61.0% positive; worst calendar year 2025 at -9.5%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected -5.0%, neighbours median -5.2%, min -9.2%, 25.0% profitable over 8. Deflated Sharpe 0.07 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 211 trades): terminal growth p05 0.81x / p50 0.99x / p95 1.24x, P(loss) 53.4%, max DD p50 12.6% / p95 23.4%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1+S5 BTC-USDT 4H — hybrid (long spot, short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 39%, highest account leverage 0.78x, net funding +0.76% of capital.

Calendar years: 2021 +1.1% · 2022 -0.3% · 2023 +7.8% · 2024 -5.0% · 2025 +0.4%. Rolling 12-month windows 41 sampled, 56.1% positive; worst calendar year 2024 at -5.0%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +27.7%, neighbours median +11.4%, min -2.4%, 80.0% profitable over 10. Deflated Sharpe 0.02 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 320 trades): terminal growth p05 0.82x / p50 1.03x / p95 1.34x, P(loss) 41.9%, max DD p50 12.6% / p95 23.5%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1+S5 BTC-USDT 4H — all-perp (long and short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 40%, highest account leverage 0.78x, net funding -3.74% of capital.

Calendar years: 2021 +0.6% · 2022 -0.1% · 2023 +7.1% · 2024 -5.7% · 2025 -3.0%. Rolling 12-month windows 41 sampled, 43.9% positive; worst calendar year 2024 at -5.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +28.3%, neighbours median +9.7%, min -3.9%, 80.0% profitable over 10. Deflated Sharpe 0.01 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 330 trades): terminal growth p05 0.79x / p50 0.98x / p95 1.25x, P(loss) 56.0%, max DD p50 14.0% / p95 25.3%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1 BTC-USDT 6H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Windows 9 (9 traded, 6 positive). Time short 39%, highest account leverage 0.70x, net funding +0.79% of capital.

Calendar years: 2021 +9.5% · 2022 -3.9% · 2023 +4.0% · 2024 +2.0% · 2025 -0.4%. Rolling 12-month windows 41 sampled, 63.4% positive; worst calendar year 2022 at -3.9%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +35.7%, neighbours median +6.8%, min -1.2%, 87.5% profitable over 8. Deflated Sharpe 0.02 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 306 trades): terminal growth p05 0.85x / p50 1.10x / p95 1.50x, P(loss) 29.5%, max DD p50 12.1% / p95 22.2%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1 BTC-USDT 6H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Windows 9 (9 traded, 6 positive). Time short 39%, highest account leverage 0.70x, net funding -3.92% of capital.

Calendar years: 2021 +8.8% · 2022 -3.7% · 2023 +3.4% · 2024 -0.1% · 2025 -0.8%. Rolling 12-month windows 41 sampled, 51.2% positive; worst calendar year 2022 at -3.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +32.9%, neighbours median +6.5%, min -3.7%, 87.5% profitable over 8. Deflated Sharpe 0.02 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 315 trades): terminal growth p05 0.85x / p50 1.06x / p95 1.38x, P(loss) 32.9%, max DD p50 11.4% / p95 22.0%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S2 BTC-USDT 6H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 31%, highest account leverage 0.50x, net funding +0.86% of capital.

Calendar years: 2021 -0.9% · 2022 -2.6% · 2023 +5.3% · 2024 -0.1% · 2025 -9.6%. Rolling 12-month windows 41 sampled, 46.3% positive; worst calendar year 2025 at -9.6%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +1.0%, neighbours median -0.9%, min -6.9%, 50.0% profitable over 10. Deflated Sharpe 0.00 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 113 trades): terminal growth p05 0.74x / p50 0.91x / p95 1.16x, P(loss) 74.5%, max DD p50 16.7% / p95 27.7%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S2 BTC-USDT 6H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'time30'}`. Windows 9 (9 traded, 3 positive). Time short 33%, highest account leverage 0.50x, net funding -2.70% of capital.

Calendar years: 2021 -3.6% · 2022 +1.9% · 2023 +2.0% · 2024 -4.1% · 2025 -9.7%. Rolling 12-month windows 41 sampled, 26.8% positive; worst calendar year 2025 at -9.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected -9.0%, neighbours median -4.5%, min -9.2%, 20.0% profitable over 10. Deflated Sharpe 0.00 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 127 trades): terminal growth p05 0.71x / p50 0.86x / p95 1.07x, P(loss) 87.5%, max DD p50 19.1% / p95 30.4%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S4 BTC-USDT 6H — hybrid (long spot, short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 15%, highest account leverage 0.70x, net funding +0.69% of capital.

Calendar years: 2021 -1.0% · 2022 +0.2% · 2023 +6.7% · 2024 -1.5% · 2025 -3.3%. Rolling 12-month windows 41 sampled, 68.3% positive; worst calendar year 2025 at -3.3%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +2.2%, neighbours median +0.6%, min -7.4%, 62.5% profitable over 8. Deflated Sharpe 0.02 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 144 trades): terminal growth p05 0.81x / p50 1.00x / p95 1.27x, P(loss) 49.0%, max DD p50 12.7% / p95 23.2%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S4 BTC-USDT 6H — all-perp (long and short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 15%, highest account leverage 0.70x, net funding -1.42% of capital.

Calendar years: 2021 -1.3% · 2022 +0.2% · 2023 +6.6% · 2024 -1.9% · 2025 -3.1%. Rolling 12-month windows 41 sampled, 65.9% positive; worst calendar year 2025 at -3.1%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +1.5%, neighbours median -0.2%, min -8.0%, 50.0% profitable over 8. Deflated Sharpe 0.02 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 144 trades): terminal growth p05 0.81x / p50 1.00x / p95 1.26x, P(loss) 50.2%, max DD p50 12.6% / p95 23.1%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1+S5 BTC-USDT 6H — hybrid (long spot, short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 37%, highest account leverage 0.70x, net funding +0.70% of capital.

Calendar years: 2021 +9.5% · 2022 -0.7% · 2023 +2.4% · 2024 +2.4% · 2025 -0.6%. Rolling 12-month windows 41 sampled, 68.3% positive; worst calendar year 2022 at -0.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +36.4%, neighbours median +19.5%, min -1.1%, 90.0% profitable over 10. Deflated Sharpe 0.05 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 276 trades): terminal growth p05 0.87x / p50 1.12x / p95 1.53x, P(loss) 24.1%, max DD p50 11.1% / p95 20.4%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S1+S5 BTC-USDT 6H — all-perp (long and short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 37%, highest account leverage 0.70x, net funding -3.86% of capital.

Calendar years: 2021 +8.8% · 2022 -0.5% · 2023 +2.1% · 2024 +1.6% · 2025 -1.0%. Rolling 12-month windows 41 sampled, 68.3% positive; worst calendar year 2025 at -1.0%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +33.6%, neighbours median +17.7%, min -3.7%, 90.0% profitable over 10. Deflated Sharpe 0.07 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 276 trades): terminal growth p05 0.86x / p50 1.10x / p95 1.46x, P(loss) 27.5%, max DD p50 11.0% / p95 20.3%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S1 ETH-USDT 4H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'trail1'}`. Windows 9 (9 traded, 5 positive). Time short 36%, highest account leverage 0.43x, net funding +0.54% of capital.

Calendar years: 2021 -0.9% · 2022 -3.9% · 2023 -3.3% · 2024 -0.3% · 2025 +6.2%. Rolling 12-month windows 41 sampled, 39.0% positive; worst calendar year 2022 at -3.9%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +5.6%, neighbours median -10.9%, min -22.4%, 12.5% profitable over 8. Deflated Sharpe 0.00 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 392 trades): terminal growth p05 0.79x / p50 0.98x / p95 1.22x, P(loss) 57.3%, max DD p50 13.8% / p95 24.7%.

Checks: profit factor above 1.2=no, max drawdown under 20%=no, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1 ETH-USDT 4H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'trail1'}`. Windows 9 (9 traded, 5 positive). Time short 36%, highest account leverage 0.43x, net funding -2.96% of capital.

Calendar years: 2021 -1.2% · 2022 -3.6% · 2023 -3.3% · 2024 -1.1% · 2025 +6.0%. Rolling 12-month windows 41 sampled, 36.6% positive; worst calendar year 2022 at -3.6%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +5.5%, neighbours median -9.9%, min -20.8%, 12.5% profitable over 8. Deflated Sharpe 0.00 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 395 trades): terminal growth p05 0.78x / p50 0.96x / p95 1.19x, P(loss) 62.2%, max DD p50 14.3% / p95 26.0%.

Checks: profit factor above 1.2=no, max drawdown under 20%=no, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S2 ETH-USDT 4H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 6 positive). Time short 35%, highest account leverage 0.69x, net funding +0.59% of capital.

Calendar years: 2021 +1.5% · 2022 +2.0% · 2023 +0.5% · 2024 +10.8% · 2025 +9.3%. Rolling 12-month windows 41 sampled, 82.9% positive; worst calendar year 2023 at +0.5%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +16.3%, neighbours median +14.8%, min -0.1%, 90.0% profitable over 10. Deflated Sharpe 0.11 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 143 trades): terminal growth p05 0.96x / p50 1.25x / p95 1.70x, P(loss) 9.8%, max DD p50 8.1% / p95 15.4%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=yes, Calmar above 0.5=yes, 75% of rolling 12-month windows positive=yes, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✓(1) ✓(2) ✓(3). Holdout: -4.8% / PF 0.59 / 42 tr ✗ contradicted.

Holdout 2025-10-20->2026-10-20: return -4.8%, max DD 6.3%, PF 0.59, 42 trades, time short 49%; long leg 22 trades P&L -5.8% (PF 0.08), short leg 20 trades P&L +1.0% (PF 1.20), funding +0.07%.

### S2 ETH-USDT 4H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 6 positive). Time short 39%, highest account leverage 0.69x, net funding -3.03% of capital.

Calendar years: 2021 -0.7% · 2022 +5.3% · 2023 +0.0% · 2024 +9.7% · 2025 +9.0%. Rolling 12-month windows 41 sampled, 80.5% positive; worst calendar year 2021 at -0.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +13.9%, neighbours median +12.6%, min -0.6%, 90.0% profitable over 10. Deflated Sharpe 0.12 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 147 trades): terminal growth p05 0.96x / p50 1.22x / p95 1.70x, P(loss) 9.2%, max DD p50 8.4% / p95 15.7%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=yes, Calmar above 0.5=yes, 75% of rolling 12-month windows positive=yes, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✓(1) ✓(2) ✓(3). Holdout: -4.6% / PF 0.59 / 42 tr ✗ contradicted.

Holdout 2025-10-20->2026-10-20: return -4.6%, max DD 6.3%, PF 0.59, 42 trades, time short 49%; long leg 22 trades P&L -5.7% (PF 0.09), short leg 20 trades P&L +1.0% (PF 1.20), funding -0.01%.

### S4 ETH-USDT 4H — hybrid (long spot, short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 12%, highest account leverage 0.72x, net funding +0.35% of capital.

Calendar years: 2021 -4.1% · 2022 -3.7% · 2023 -2.6% · 2024 +4.9% · 2025 -1.4%. Rolling 12-month windows 41 sampled, 29.3% positive; worst calendar year 2021 at -4.1%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +8.2%, neighbours median +7.0%, min -1.4%, 75.0% profitable over 8. Deflated Sharpe 0.00 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 174 trades): terminal growth p05 0.79x / p50 0.93x / p95 1.11x, P(loss) 76.2%, max DD p50 13.2% / p95 23.1%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✓(3). Holdout: untouched.

### S4 ETH-USDT 4H — all-perp (long and short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 12%, highest account leverage 0.72x, net funding -0.71% of capital.

Calendar years: 2021 -4.2% · 2022 -3.5% · 2023 -2.3% · 2024 +4.9% · 2025 -1.3%. Rolling 12-month windows 41 sampled, 29.3% positive; worst calendar year 2021 at -4.2%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +7.7%, neighbours median +6.4%, min -1.4%, 75.0% profitable over 8. Deflated Sharpe 0.00 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 176 trades): terminal growth p05 0.80x / p50 0.94x / p95 1.11x, P(loss) 74.2%, max DD p50 12.9% / p95 22.6%.

Checks: profit factor above 1.2=no, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✓(3). Holdout: untouched.

### S1+S5 ETH-USDT 4H — hybrid (long spot, short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 3.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 36%, highest account leverage 0.43x, net funding +0.54% of capital.

Calendar years: 2021 -0.5% · 2022 -4.4% · 2023 -2.5% · 2024 +0.8% · 2025 +5.3%. Rolling 12-month windows 41 sampled, 36.6% positive; worst calendar year 2022 at -4.4%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +10.1%, neighbours median -4.0%, min -14.7%, 50.0% profitable over 10. Deflated Sharpe 0.01 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 358 trades): terminal growth p05 0.80x / p50 0.98x / p95 1.25x, P(loss) 56.6%, max DD p50 13.8% / p95 24.6%.

Checks: profit factor above 1.2=no, max drawdown under 20%=no, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1+S5 ETH-USDT 4H — all-perp (long and short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 3.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 36%, highest account leverage 0.43x, net funding -3.04% of capital.

Calendar years: 2021 -0.8% · 2022 -4.1% · 2023 -1.5% · 2024 +0.0% · 2025 +5.1%. Rolling 12-month windows 41 sampled, 34.1% positive; worst calendar year 2022 at -4.1%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +10.8%, neighbours median -4.9%, min -15.5%, 40.0% profitable over 10. Deflated Sharpe 0.01 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 361 trades): terminal growth p05 0.80x / p50 0.98x / p95 1.23x, P(loss) 55.7%, max DD p50 13.4% / p95 24.1%.

Checks: profit factor above 1.2=no, max drawdown under 20%=no, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1 ETH-USDT 6H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [30, 60, 90], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 30%, highest account leverage 0.84x, net funding +0.58% of capital.

Calendar years: 2021 -1.6% · 2022 -1.7% · 2023 +6.0% · 2024 +11.9% · 2025 +3.0%. Rolling 12-month windows 41 sampled, 63.4% positive; worst calendar year 2022 at -1.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +21.9%, neighbours median -2.1%, min -12.3%, 42.9% profitable over 7. Deflated Sharpe 0.09 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 275 trades): terminal growth p05 0.89x / p50 1.17x / p95 1.62x, P(loss) 17.2%, max DD p50 11.3% / p95 21.1%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=no. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S1 ETH-USDT 6H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'lookbacks_days': [30, 60, 90], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'time30'}`. Windows 9 (9 traded, 4 positive). Time short 30%, highest account leverage 0.84x, net funding -3.68% of capital.

Calendar years: 2021 -2.2% · 2022 -1.8% · 2023 +5.6% · 2024 +10.7% · 2025 +7.1%. Rolling 12-month windows 41 sampled, 61.0% positive; worst calendar year 2021 at -2.2%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +9.9%, neighbours median +8.7%, min -7.1%, 87.5% profitable over 8. Deflated Sharpe 0.14 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 289 trades): terminal growth p05 0.87x / p50 1.19x / p95 1.69x, P(loss) 17.4%, max DD p50 12.3% / p95 22.6%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S2 ETH-USDT 6H — hybrid (long spot, short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 7 positive). Time short 32%, highest account leverage 0.84x, net funding +0.42% of capital.

Calendar years: 2021 -1.5% · 2022 +3.0% · 2023 +1.7% · 2024 +9.3% · 2025 +7.7%. Rolling 12-month windows 41 sampled, 87.8% positive; worst calendar year 2021 at -1.5%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +11.8%, neighbours median +14.2%, min +8.6%, 100.0% profitable over 10. Deflated Sharpe 0.26 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 105 trades): terminal growth p05 0.93x / p50 1.20x / p95 1.66x, P(loss) 13.0%, max DD p50 8.6% / p95 16.1%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=yes, Calmar above 0.5=yes, 75% of rolling 12-month windows positive=yes, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✓(1) ✓(2) ✓(3). Holdout: +2.3% / PF 1.29 / 28 tr ✓ confirmed.

Holdout 2025-10-20->2026-10-20: return +2.3%, max DD 3.8%, PF 1.29, 28 trades, time short 36%; long leg 18 trades P&L -3.7% (PF 0.31), short leg 10 trades P&L +6.0% (PF 3.47), funding +0.08%.

### S2 ETH-USDT 6H — all-perp (long and short perp)

Rule grid 144 combinations; most-selected rule `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Windows 9 (9 traded, 7 positive). Time short 32%, highest account leverage 0.84x, net funding -2.02% of capital.

Calendar years: 2021 -1.9% · 2022 +3.1% · 2023 +1.5% · 2024 +8.4% · 2025 +7.6%. Rolling 12-month windows 41 sampled, 87.8% positive; worst calendar year 2021 at -1.9%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +9.4%, neighbours median +11.4%, min +6.3%, 100.0% profitable over 10. Deflated Sharpe 0.25 (144 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 105 trades): terminal growth p05 0.92x / p50 1.18x / p95 1.62x, P(loss) 14.7%, max DD p50 8.8% / p95 16.4%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=yes, Calmar above 0.5=yes, 75% of rolling 12-month windows positive=yes, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✓(1) ✓(2) ✓(3). Holdout: +2.3% / PF 1.29 / 28 tr ✓ confirmed.

Holdout 2025-10-20->2026-10-20: return +2.3%, max DD 3.8%, PF 1.29, 28 trades, time short 36%; long leg 18 trades P&L -3.7% (PF 0.31), short leg 10 trades P&L +6.0% (PF 3.47), funding -0.09%.

### S4 ETH-USDT 6H — hybrid (long spot, short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 15%, highest account leverage 0.84x, net funding +0.44% of capital.

Calendar years: 2021 -4.7% · 2022 +0.7% · 2023 -3.8% · 2024 +17.0% · 2025 +7.3%. Rolling 12-month windows 41 sampled, 56.1% positive; worst calendar year 2021 at -4.7%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +19.8%, neighbours median +16.3%, min +6.5%, 100.0% profitable over 8. Deflated Sharpe 0.36 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 143 trades): terminal growth p05 0.89x / p50 1.13x / p95 1.59x, P(loss) 20.7%, max DD p50 9.5% / p95 17.6%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S4 ETH-USDT 6H — all-perp (long and short perp)

Rule grid 48 combinations; most-selected rule `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Windows 9 (9 traded, 4 positive). Time short 14%, highest account leverage 0.62x, net funding -1.63% of capital.

Calendar years: 2021 -5.0% · 2022 +0.8% · 2023 -5.0% · 2024 +16.1% · 2025 +7.3%. Rolling 12-month windows 41 sampled, 56.1% positive; worst calendar year 2023 at -5.0%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +19.1%, neighbours median +15.6%, min +6.7%, 100.0% profitable over 8. Deflated Sharpe 0.30 (48 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 143 trades): terminal growth p05 0.89x / p50 1.11x / p95 1.54x, P(loss) 24.4%, max DD p50 9.8% / p95 18.1%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✗(2) ✗(3). Holdout: untouched.

### S1+S5 ETH-USDT 6H — hybrid (long spot, short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [30, 60, 90], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 32%, highest account leverage 0.84x, net funding +0.57% of capital.

Calendar years: 2021 -0.4% · 2022 -1.3% · 2023 +8.5% · 2024 +6.9% · 2025 +2.9%. Rolling 12-month windows 41 sampled, 61.0% positive; worst calendar year 2022 at -1.3%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +11.7%, neighbours median +11.0%, min -4.1%, 80.0% profitable over 10. Deflated Sharpe 0.15 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 236 trades): terminal growth p05 0.89x / p50 1.15x / p95 1.62x, P(loss) 20.5%, max DD p50 10.3% / p95 19.0%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

### S1+S5 ETH-USDT 6H — all-perp (long and short perp)

Rule grid 108 combinations; most-selected rule `{'lookbacks_days': [30, 60, 90], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Windows 9 (9 traded, 5 positive). Time short 32%, highest account leverage 0.84x, net funding -3.54% of capital.

Calendar years: 2021 -1.0% · 2022 -1.1% · 2023 +7.9% · 2024 +5.6% · 2025 +2.7%. Rolling 12-month windows 41 sampled, 61.0% positive; worst calendar year 2022 at -1.1%.

Robustness (±30 % neighbours, fixed parameters, policy sizing, every test window): selected +9.9%, neighbours median +9.3%, min -6.0%, 80.0% profitable over 10. Deflated Sharpe 0.15 (108 rule trials in the last train window). Monte Carlo (trade order, 2000 paths over 236 trades): terminal growth p05 0.88x / p50 1.13x / p95 1.57x, P(loss) 23.5%, max DD p50 10.6% / p95 19.4%.

Checks: profit factor above 1.2=yes, max drawdown under 20%=yes, Sharpe above 0.7=no, Calmar above 0.5=no, 75% of rolling 12-month windows positive=no, no calendar year worse than -10%=yes, at least 30 trades=yes, robust to ±30% parameter changes=yes. Evidence rule: ✗(1) ✓(2) ✗(3). Holdout: untouched.

## Owner decisions (nothing below is decided by this report)

- **Phase 9.** Read `docs/PHASE9_DESIGN_STUDY.md` (the design study with the safety rules and the review path). Phase 9 stays unauthorized; this report does not ask for it.
- **Forward evidence.** Whether to run any long/short configuration forward as a paper-only account (public data, simulated fills, no derivatives access) is a new scope decision.

## Method notes and caveats

- The long side of every configuration is Sprint 2c's long-only rule unchanged; shorts only use bars that rule spends flat. Every conflict falls on the short side: a short that the long side needs is closed at the open (`flip`), before that bar's stops are checked, so the long enters exactly where the long-only rule enters; a long that gives way to a short keeps the long-only stop-first rule, and if its stop fires in that bar the short starts one bar later. Without the drawdown ladder the long side's trades are the long-only engine's to the last price (tested); with it their size differs, because the ladder watches the combined equity.
- The short rules are mirror images with the same parameters; nothing about them was tuned for shorting. S2 and S4 shorts are event states: when a breakdown happened while the long side held the bars and no cover event came since, the short starts as soon as the long side lets go, with the filters checked on that bar.
- Funding comes from Binance's public history as a proxy; OKX's own funding has the same sign most of the time and a similar level where both exist (table above), but single settlements differ, and OKX settles more often (every 4, 2 or 1 hours) while a rate sits at its cap or floor. Funding is charged at the close of the bar it settles in, on that close; a stop that fires inside the bar may make one settlement too many or too few. The OKX-against-proxy comparison uses OKX's public history, which starts in July 2026 — inside the holdout window; it only calibrates the funding source, and no selection, gate or verdict uses it.
- Signals, stops and fills use spot candles for both legs in the main run (the swap tracks spot through funding); the perp-priced diagnostic moved no Calmar by more than 0.05.
- The policy sizing (10 % vol target, crash filter, ladder) was fixed in Sprint 2b for longs and applied unchanged to shorts. Positions stay small at this sizing (account leverage at most 0.84x), so the absolute returns are small too.
- The liquidation tripwire models a 1x isolated short whose margin is its entry value; a gap above the liquidation price fills at the open, which books more than the margin (conservative; on the exchange an isolated position cannot lose more than its margin).
- The deflated Sharpe counts the rule trials of the last train window only; the two designs and four families multiply the number of things tried.
- The holdout's direction was known before it was opened (see above). Hybrid and all-perp versions of one rule share their signals: they are one rule, not two independent results. Every opening of the holdout is in the ledger above.
- Every number is a simulation on historical public data and proves nothing about the future.
