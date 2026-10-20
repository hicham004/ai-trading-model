# Ensemble v1b — sizing, risk, timeframe and positioning (walk-forward, SIMULATION ONLY)

Generated 2026-10-20 13:50 UTC by `scripts/run_research_v1b.py`. Data: PUBLIC OKX spot candles from the Parquet lake (BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); BTC-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); ETH-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); ETH-USDT 6H: 2019-12-29->2026-10-20 (9949 bars)); 6H bars resampled from 1H (UTC-aligned). Positioning features: binance (public, research only). Costs: fee 0.10% per side + slippage 0.050% per side. Long-only spot, no leverage. Walk-forward: train 540d → purge 7d → test 180d, rolling; stage 1 selects the trading rule (entries × exit bracket) by sharpe with ≥20 train trades at full size; stage 2 selects the sizing rule for that rule by calmar among variants whose TRAIN max drawdown is ≤ 10% (390 variants: vol targets [0.1, 0.15, 0.2, 0.25] × lookbacks [20, 30, 60] bars, fixed fractions [0.25, 0.5, 1.0], crash filter [(0.1, 90.0), (0.1, 180.0), (0.15, 90.0), (0.15, 180.0), (0.2, 90.0), (0.2, 180.0)] × {half, zero}, drawdown ladder −5% → half / −10% → flat, re-arm after 30.0 days). Mid-trade adjustments are reduce-only (threshold 0.25). Holdout: last 12 months (2025-10-20->2026-10-20), evaluated once and only for candidates that passed walk-forward.

**Nothing here authorizes paper, demo or live trading.** A passing candidate is a hypothesis for the forward paper fleet (Sprint 5), not a strategy to deploy. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we did.** We took the Sprint 2 strategies and, instead of betting the whole account on every trade, let the computer choose how much to risk: 390 sizing rules (volatility targeting, fixed fractions, a crash filter that cuts exposure when the market is far below its recent high, and a drawdown ladder that halves and then stops trading after losses) and 7 exit rules (take-profit, trailing stop, time stop). Every choice was made only on past data, then tested on the following months, over 28 strategy/market/timeframe combinations from 2019-12-16->2026-10-20 after fees and slippage.
- **Result.** None of the 28 configurations passed all seven gates with the walk-forward-selected sizing. The gates most often missed were: Sharpe above 0.7 (27 of 28), Calmar above 0.5 (27 of 28), positive in 4 of 5 years (25 of 28). With the fixed policy sizing `vt10/30 crash15/90dh ladder` (no sizing selection), 0 of 28 passed. Nothing goes to demo or paper trading from this report.
- **Best so far.** S4 on ETH-USDT 6H with sizing `vt25/60 ladder` and exit `tp2`: out-of-sample +7.7% per year with a worst drawdown of 13.2% (Sharpe 0.83, Calmar 0.58, 66 trades). Simply holding ETH over the same months made +17.6% per year but with a 80.4% drawdown (Calmar 0.22). It still misses: positive in 4 of 5 years.
- **What sizing bought us.** Across the 28 runs with a lead rule, replaying the same rule all-in versus with the chosen sizing moved the median worst drawdown from 54.2% to 19.3%, the median yearly return from +11.4% to +4.9% and the median Calmar from 0.28 to 0.31. In other words, sizing scaled risk and return down together; it made the strategies survivable but did not add edge. For comparison, simply staying long BTC (4H) with the same sizing machinery and no timing rule made +7.5% per year with a 19.3% drawdown (Sharpe 0.60, Calmar 0.39) — a timing rule has to beat that to earn its place.
- **Portfolio and next step.** The best portfolio (S2+S4 x BTC+ETH, equal capital) made +3.1% per year with a 11.3% drawdown (Sharpe 0.49, Calmar 0.28) — not better than the best single configuration. Proposed Sprint 2c (research only): 0 configuration(s) passed, so the ensemble is not ready for the paper fleet. Binding gates: sharpe_gt_0_7 (27/28), calmar_gt_0_5 (27/28), positive_in_4_of_5_years (25/28). Proposed work: (1) regime v2 (HMM on returns+vol) and the S0 filter as entry gates so the trend rules stand aside in 2022-style bear markets, which drive the failed yearly-consistency and Calmar gates; (2) portfolio-level sizing — size the BTC+ETH, S1/S2/S4 sleeves jointly against one drawdown budget instead of per sleeve; (3) lower-turnover variants (weekly rebalanced TSMOM, 1D entries with 4H exits) to cut fee drag; (4) keep collecting Binance/OKX positioning for an S5 re-test with a shorter funding z-window; (5) no entry-rule retuning beyond that — the evidence says the edge is small and the risk side is where the gates are won.

## Gates (master plan, Sprint 2b item 8 — at the proposed sizing)

- Out-of-sample profit factor > 1.2 after costs
- Max drawdown < 20% at the proposed sizing
- Sharpe > 0.7
- Calmar (CAGR / max drawdown) > 0.5
- Positive in ≥ 4 of 5 yearly out-of-sample windows
- At least 30 out-of-sample trades
- ≥ 50% of ±30% parameter neighbours stay profitable (replayed with the proposed sizing)
- Deflated Sharpe reported (no threshold)

## Summary

| Candidate | Series | Sizing | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Fees/yr | Pos. years | Robust ±30% | DSR | Verdict |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| hold | BTC-USDT 4H | vt10/60 crash20/90dz ladder | none | +36.8% | +7.5% | 0.60 | 1.82 | 19.3% | 0.39 | 40 | 23.2% | 0.8% | 3/5 | - | 0.24 | fail |
| baseline | BTC-USDT 4H | vt25/60 ladder | none | +5.9% | +1.3% | 0.18 | 1.10 | 16.5% | 0.08 | 159 | 14.4% | 2.1% | 2/5 | 87.5% | 0.00 | fail |
| S1 | BTC-USDT 4H | fixed50 | none | +38.9% | +7.9% | 0.61 | 1.37 | 20.1% | 0.39 | 184 | 17.5% | 3.1% | 4/5 | 62.5% | 0.05 | fail |
| S2 | BTC-USDT 4H | vt10/60 crash15/90dh ladder | none | +9.3% | +2.1% | 0.29 | 1.23 | 11.4% | 0.18 | 84 | 10.4% | 1.1% | 2/5 | 100.0% | 0.01 | fail |
| S3 | BTC-USDT 4H | vt10/20 crash20/90dz | none | -5.9% | -1.4% | -0.30 | 0.82 | 9.9% | -0.14 | 85 | 1.8% | 1.3% | 1/5 | 20.0% | 0.00 | fail |
| S4 | BTC-USDT 4H | fixed100 crash10/90dz ladder | none | +11.6% | +2.6% | 0.30 | 1.18 | 17.9% | 0.14 | 96 | 7.2% | 2.4% | 2/5 | 62.5% | 0.11 | fail |
| S1+S5 | BTC-USDT 4H | vt20/60 | none | +23.7% | +5.0% | 0.41 | 1.23 | 20.5% | 0.25 | 193 | 20.0% | 3.3% | 3/5 | 70.0% | 0.01 | fail |
| S2+S5 | BTC-USDT 4H | vt10/60 crash15/90dh ladder | none | +11.0% | +2.4% | 0.33 | 1.27 | 11.4% | 0.21 | 83 | 10.5% | 1.0% | 2/5 | 100.0% | 0.00 | fail |
| hold | BTC-USDT 6H | vt20/20 crash10/180dz ladder | none | +34.7% | +7.2% | 0.63 | 1.95 | 27.0% | 0.26 | 36 | 20.3% | 0.7% | 3/5 | - | 0.37 | fail |
| baseline | BTC-USDT 6H | vt25/60 ladder | none | +15.2% | +3.3% | 0.38 | 1.23 | 17.6% | 0.19 | 114 | 11.6% | 1.5% | 3/5 | 100.0% | 0.00 | fail |
| S1 | BTC-USDT 6H | vt25/60 ladder | tp2 | +41.6% | +8.4% | 0.66 | 1.40 | 21.6% | 0.39 | 162 | 15.6% | 2.9% | 4/5 | 87.5% | 0.02 | fail |
| S2 | BTC-USDT 6H | vt15/20 crash20/180dz ladder | none | -2.2% | -0.5% | -0.04 | 0.96 | 13.6% | -0.04 | 73 | 8.1% | 1.0% | 1/5 | 100.0% | 0.00 | fail |
| S3 | BTC-USDT 6H | vt10/60 crash20/90dz | none | -4.3% | -1.0% | -0.22 | 0.86 | 8.1% | -0.12 | 64 | 1.9% | 1.2% | 1/5 | 10.0% | 0.00 | fail |
| S4 | BTC-USDT 6H | vt20/60 crash10/180dh | none | +4.1% | +0.9% | 0.15 | 1.08 | 12.4% | 0.08 | 97 | 7.7% | 2.0% | 2/5 | 100.0% | 0.03 | fail |
| S1+S5 | BTC-USDT 6H | vt25/60 ladder | tp2 | +41.1% | +8.3% | 0.66 | 1.42 | 22.0% | 0.38 | 153 | 15.0% | 2.7% | 4/5 | 100.0% | 0.01 | fail |
| S2+S5 | BTC-USDT 6H | vt15/20 crash20/180dz ladder | none | -2.2% | -0.5% | -0.04 | 0.96 | 13.6% | -0.04 | 73 | 8.1% | 1.0% | 1/5 | 100.0% | 0.00 | fail |
| hold | ETH-USDT 4H | vt10/20 crash15/180dz | none | +5.2% | +1.2% | 0.18 | 1.17 | 20.2% | 0.06 | 79 | 9.1% | 0.8% | 2/5 | - | 0.01 | fail |
| baseline | ETH-USDT 4H | vt15/60 | none | +12.8% | +2.8% | 0.31 | 1.16 | 22.9% | 0.12 | 194 | 10.1% | 2.0% | 2/5 | 100.0% | 0.00 | fail |
| S1 | ETH-USDT 4H | vt25/30 crash15/90dz ladder | none | -4.6% | -1.1% | -0.05 | 0.96 | 22.1% | -0.05 | 221 | 10.1% | 2.8% | 2/5 | 62.5% | 0.00 | fail |
| S2 | ETH-USDT 4H | vt20/60 crash20/90dh | none | -2.5% | -0.6% | -0.00 | 0.99 | 28.8% | -0.02 | 103 | 8.8% | 1.3% | 2/5 | 100.0% | 0.00 | fail |
| S3 | ETH-USDT 4H | vt25/20 | trail2 | -30.8% | -8.1% | -0.58 | 0.62 | 43.5% | -0.19 | 64 | 1.9% | 1.5% | 0/5 | 60.0% | 0.00 | fail |
| S4 | ETH-USDT 4H | vt25/20 crash10/180dz | none | -16.9% | -4.2% | -0.64 | 0.66 | 28.1% | -0.15 | 66 | 2.7% | 1.1% | 1/5 | 0.0% | 0.00 | fail |
| S1+S5 | ETH-USDT 4H | vt25/60 | none | -5.4% | -1.3% | -0.05 | 0.95 | 27.2% | -0.05 | 219 | 11.3% | 3.2% | 3/5 | 90.0% | 0.00 | fail |
| S2+S5 | ETH-USDT 4H | fixed25 | none | +7.0% | +1.6% | 0.19 | 1.16 | 26.9% | 0.06 | 85 | 10.0% | 1.2% | 2/5 | 100.0% | 0.00 | fail |
| hold | ETH-USDT 6H | vt25/60 crash15/90dz | none | +1.0% | +0.2% | 0.08 | 1.08 | 19.1% | 0.01 | 55 | 11.0% | 0.6% | 2/5 | - | 0.00 | fail |
| baseline | ETH-USDT 6H | vt25/30 crash10/90dh | time30 | +7.1% | +1.6% | 0.21 | 1.10 | 24.2% | 0.07 | 215 | 9.3% | 1.8% | 2/5 | 100.0% | 0.00 | fail |
| S1 | ETH-USDT 6H | vt25/60 crash10/180dz | none | -3.3% | -0.8% | -0.01 | 0.98 | 19.1% | -0.04 | 168 | 10.3% | 2.2% | 2/5 | 0.0% | 0.00 | fail |
| S2 | ETH-USDT 6H | vt15/60 | none | -1.0% | -0.2% | 0.03 | 1.02 | 20.0% | -0.01 | 96 | 7.3% | 1.3% | 3/5 | 100.0% | 0.00 | fail |
| S3 | ETH-USDT 6H | vt25/20 crash20/90dh | tp3 | -2.0% | -0.5% | -0.04 | 0.95 | 15.1% | -0.03 | 48 | 1.5% | 1.1% | 1/5 | 70.0% | 0.00 | fail |
| S4 | ETH-USDT 6H | vt25/60 ladder | tp2 | +37.7% | +7.7% | 0.83 | 1.83 | 13.2% | 0.58 | 66 | 5.7% | 1.1% | 3/5 | 87.5% | 0.13 | fail |
| S1+S5 | ETH-USDT 6H | vt25/60 crash10/180dz | none | +2.8% | +0.6% | 0.11 | 1.05 | 19.0% | 0.03 | 168 | 11.0% | 2.3% | 3/5 | 20.0% | 0.00 | fail |
| S2+S5 | ETH-USDT 6H | vt15/60 | time30 | +4.0% | +0.9% | 0.14 | 1.08 | 19.8% | 0.05 | 87 | 7.4% | 1.3% | 3/5 | 100.0% | 0.00 | fail |

Configurations passing all gates: **0** of 28 (the `hold` rows are passive always-long references with the same sizing machinery, not candidates).

Buy-and-hold over the same out-of-sample span (after costs, all-in):

| Series | Total | CAGR | Sharpe | Max DD | Calmar |
|---|---:|---:|---:|---:|---:|
| BTC-USDT 4H | +176.1% | +26.2% | 0.70 | 77.0% | 0.34 |
| BTC-USDT 6H | +212.6% | +30.5% | 0.77 | 77.0% | 0.40 |
| ETH-USDT 4H | +56.0% | +11.1% | 0.50 | 81.1% | 0.14 |
| ETH-USDT 6H | +100.6% | +17.6% | 0.58 | 80.4% | 0.22 |

## Fixed policy sizing (no sizing selection) — `vt10/30 crash15/90dh ladder`

Same rule selection as above, but one a-priori sizing rule for every candidate instead of the train-selected one (a 20% drawdown budget with a modest-Sharpe strategy implies roughly a 10% vol target; the crash filter and ladder are the defensive defaults). The gap between this table and the summary table is selection noise in the sizing stage.

| Candidate | Series | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Pos. years | Robust ±30% | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| hold | BTC-USDT 4H | none | +14.8% | +3.2% | 0.59 | 2.88 | 7.2% | 0.45 | 9 | 9.6% | 3/5 | - | fail |
| baseline | BTC-USDT 4H | none | +7.9% | +1.8% | 0.33 | 1.19 | 8.5% | 0.21 | 154 | 8.2% | 2/5 | 87.5% | fail |
| S1 | BTC-USDT 4H | none | +9.8% | +2.2% | 0.39 | 1.24 | 8.3% | 0.26 | 185 | 8.5% | 3/5 | 75.0% | fail |
| S2 | BTC-USDT 4H | none | +15.4% | +3.4% | 0.59 | 1.48 | 8.6% | 0.39 | 84 | 7.7% | 2/5 | 100.0% | fail |
| S3 | BTC-USDT 4H | none | -4.5% | -1.0% | -0.40 | 0.81 | 8.6% | -0.12 | 100 | 1.3% | 2/5 | 30.0% | fail |
| S4 | BTC-USDT 4H | none | +7.4% | +1.6% | 0.38 | 1.21 | 9.9% | 0.17 | 113 | 3.8% | 2/5 | 100.0% | fail |
| S1+S5 | BTC-USDT 4H | none | +7.2% | +1.6% | 0.29 | 1.17 | 8.1% | 0.20 | 193 | 8.8% | 3/5 | 80.0% | fail |
| S2+S5 | BTC-USDT 4H | none | +16.1% | +3.5% | 0.61 | 1.51 | 8.6% | 0.41 | 83 | 7.7% | 2/5 | 100.0% | fail |
| hold | BTC-USDT 6H | none | +11.8% | +2.6% | 0.49 | 2.37 | 8.0% | 0.33 | 9 | 9.8% | 4/5 | - | fail |
| baseline | BTC-USDT 6H | none | +8.1% | +1.8% | 0.33 | 1.18 | 9.9% | 0.18 | 144 | 8.3% | 3/5 | 100.0% | fail |
| S1 | BTC-USDT 6H | tp2 | +14.5% | +3.2% | 0.54 | 1.32 | 10.4% | 0.31 | 173 | 8.5% | 3/5 | 87.5% | fail |
| S2 | BTC-USDT 6H | none | +1.5% | +0.3% | 0.09 | 1.05 | 10.0% | 0.03 | 82 | 6.1% | 2/5 | 100.0% | fail |
| S3 | BTC-USDT 6H | none | -6.7% | -1.6% | -0.62 | 0.71 | 7.3% | -0.22 | 78 | 1.2% | 0/5 | 10.0% | fail |
| S4 | BTC-USDT 6H | none | +7.8% | +1.8% | 0.40 | 1.25 | 5.8% | 0.30 | 98 | 4.1% | 3/5 | 100.0% | fail |
| S1+S5 | BTC-USDT 6H | tp2 | +11.3% | +2.5% | 0.43 | 1.26 | 9.9% | 0.25 | 164 | 8.5% | 3/5 | 90.0% | fail |
| S2+S5 | BTC-USDT 6H | none | +1.5% | +0.3% | 0.09 | 1.05 | 10.0% | 0.03 | 82 | 6.1% | 2/5 | 100.0% | fail |
| hold | ETH-USDT 4H | none | +7.8% | +1.8% | 0.38 | 1.83 | 8.6% | 0.20 | 9 | 6.2% | 4/5 | - | fail |
| baseline | ETH-USDT 4H | none | -6.2% | -1.5% | -0.24 | 0.88 | 14.0% | -0.10 | 194 | 5.2% | 2/5 | 50.0% | fail |
| S1 | ETH-USDT 4H | none | +1.5% | +0.3% | 0.09 | 1.04 | 13.5% | 0.02 | 220 | 5.7% | 3/5 | 75.0% | fail |
| S2 | ETH-USDT 4H | none | +16.7% | +3.6% | 0.62 | 1.63 | 8.8% | 0.41 | 77 | 5.1% | 3/5 | 100.0% | fail |
| S3 | ETH-USDT 4H | trail2 | -3.5% | -0.8% | -0.42 | 0.82 | 6.9% | -0.12 | 97 | 0.5% | 2/5 | 60.0% | fail |
| S4 | ETH-USDT 4H | none | -6.4% | -1.5% | -0.47 | 0.78 | 9.8% | -0.16 | 96 | 1.9% | 0/5 | 37.5% | fail |
| S1+S5 | ETH-USDT 4H | none | +0.7% | +0.2% | 0.06 | 1.03 | 13.6% | 0.01 | 218 | 5.7% | 3/5 | 80.0% | fail |
| S2+S5 | ETH-USDT 4H | none | +12.0% | +2.6% | 0.49 | 1.44 | 8.4% | 0.31 | 78 | 4.8% | 3/5 | 100.0% | fail |
| hold | ETH-USDT 6H | none | +11.0% | +2.5% | 0.50 | 2.04 | 9.6% | 0.26 | 9 | 6.5% | 3/5 | - | fail |
| baseline | ETH-USDT 6H | time30 | +0.3% | +0.1% | 0.04 | 1.02 | 13.7% | 0.01 | 215 | 5.5% | 3/5 | 100.0% | fail |
| S1 | ETH-USDT 6H | none | +4.7% | +1.1% | 0.20 | 1.10 | 8.7% | 0.12 | 170 | 5.9% | 3/5 | 100.0% | fail |
| S2 | ETH-USDT 6H | none | +8.4% | +1.9% | 0.38 | 1.21 | 9.0% | 0.21 | 94 | 4.3% | 4/5 | 100.0% | fail |
| S3 | ETH-USDT 6H | tp3 | -0.6% | -0.1% | -0.05 | 0.96 | 6.0% | -0.02 | 60 | 0.5% | 2/5 | 50.0% | fail |
| S4 | ETH-USDT 6H | tp2 | +16.3% | +3.6% | 0.87 | 1.66 | 8.7% | 0.41 | 82 | 2.8% | 3/5 | 87.5% | fail |
| S1+S5 | ETH-USDT 6H | none | +6.7% | +1.5% | 0.28 | 1.15 | 8.7% | 0.17 | 170 | 5.9% | 3/5 | 40.0% | fail |
| S2+S5 | ETH-USDT 6H | time30 | +9.5% | +2.1% | 0.44 | 1.26 | 8.8% | 0.24 | 86 | 4.3% | 4/5 | 100.0% | fail |

## Paper-fleet shortlist (ranked)

Ranked by: passed all gates first, then Calmar, then Sharpe; only configurations with OOS profit factor > 1 and ≥ 30 trades. These are the configurations Sprint 5's paper fleet should run forward on live public data; none is approved for demo.

| # | Candidate | Series | Sizing | Bracket | CAGR | Sharpe | Calmar | Max DD | PF | Trades | DSR | Gates missed |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | S4 | ETH-USDT 6H | vt25/60 ladder | tp2 | +7.7% | 0.83 | 0.58 | 13.2% | 1.83 | 66 | 0.13 | positive in 4 of 5 years |
| 2 | S2 | ETH-USDT 4H | policy vt10/30 crash15/90dh ladder | none | +3.6% | 0.62 | 0.41 | 8.8% | 1.63 | 77 | - | Sharpe above 0.7, Calmar above 0.5, positive in 4 of 5 years |
| 3 | S4 | ETH-USDT 6H | policy vt10/30 crash15/90dh ladder | tp2 | +3.6% | 0.87 | 0.41 | 8.7% | 1.66 | 82 | - | Calmar above 0.5, positive in 4 of 5 years |
| 4 | S2+S5 | BTC-USDT 4H | policy vt10/30 crash15/90dh ladder | none | +3.5% | 0.61 | 0.41 | 8.6% | 1.51 | 83 | - | Sharpe above 0.7, Calmar above 0.5, positive in 4 of 5 years |
| 5 | S2 | BTC-USDT 4H | policy vt10/30 crash15/90dh ladder | none | +3.4% | 0.59 | 0.39 | 8.6% | 1.48 | 84 | - | Sharpe above 0.7, Calmar above 0.5, positive in 4 of 5 years |
| 6 | S1 | BTC-USDT 4H | fixed50 | none | +7.9% | 0.61 | 0.39 | 20.1% | 1.37 | 184 | 0.05 | max drawdown under 20%, Sharpe above 0.7, Calmar above 0.5 |
| 7 | S1 | BTC-USDT 6H | vt25/60 ladder | tp2 | +8.4% | 0.66 | 0.39 | 21.6% | 1.40 | 162 | 0.02 | max drawdown under 20%, Sharpe above 0.7, Calmar above 0.5 |
| 8 | S1+S5 | BTC-USDT 6H | vt25/60 ladder | tp2 | +8.3% | 0.66 | 0.38 | 22.0% | 1.42 | 153 | 0.01 | max drawdown under 20%, Sharpe above 0.7, Calmar above 0.5 |
| 9 | S2+S5 | ETH-USDT 4H | policy vt10/30 crash15/90dh ladder | none | +2.6% | 0.49 | 0.31 | 8.4% | 1.44 | 78 | - | Sharpe above 0.7, Calmar above 0.5, positive in 4 of 5 years |
| 10 | S1 | BTC-USDT 6H | policy vt10/30 crash15/90dh ladder | tp2 | +3.2% | 0.54 | 0.31 | 10.4% | 1.32 | 173 | - | Sharpe above 0.7, Calmar above 0.5, positive in 4 of 5 years |

## Sizing study — all-in vs the chosen sizing (same rule, fixed replay over the test windows)

| Candidate | Series | Rule bracket | All-in CAGR | All-in max DD | All-in Calmar | Chosen sizing | CAGR | Max DD | Calmar | Best sweep by Calmar (informational) |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---|
| baseline | BTC-USDT 4H | none | +16.7% | 56.9% | 0.29 | vt25/60 ladder | +7.0% | 20.2% | 0.35 | fixed100 crash15/180dz ladder |
| S1 | BTC-USDT 4H | none | +7.2% | 65.6% | 0.11 | fixed50 | +5.8% | 41.4% | 0.14 | vt25/60 crash20/180dz ladder |
| S2 | BTC-USDT 4H | none | +2.7% | 64.3% | 0.04 | vt10/60 crash15/90dh ladder | +2.7% | 10.2% | 0.27 | vt20/60 crash20/180dz |
| S3 | BTC-USDT 4H | none | +0.3% | 23.3% | 0.01 | vt10/20 crash20/90dz | -0.6% | 5.9% | -0.09 | fixed25 crash15/90dh |
| S4 | BTC-USDT 4H | none | +14.1% | 31.6% | 0.45 | fixed100 crash10/90dz ladder | +3.8% | 22.7% | 0.17 | vt25/60 ladder |
| S1+S5 | BTC-USDT 4H | none | +6.9% | 65.6% | 0.11 | vt20/60 | +11.3% | 29.9% | 0.38 | vt25/60 crash20/180dz ladder |
| S2+S5 | BTC-USDT 4H | none | +3.0% | 64.2% | 0.05 | vt10/60 crash15/90dh ladder | +2.7% | 10.2% | 0.27 | vt20/60 crash20/180dz |
| baseline | BTC-USDT 6H | none | +19.2% | 51.9% | 0.37 | vt25/60 ladder | +8.7% | 22.6% | 0.38 | vt10/60 crash10/90dh ladder |
| S1 | BTC-USDT 6H | tp2 | +31.8% | 51.0% | 0.62 | vt25/60 ladder | +14.4% | 20.1% | 0.72 | fixed100 crash20/180dh |
| S2 | BTC-USDT 6H | none | +2.4% | 60.6% | 0.04 | vt15/20 crash20/180dz ladder | +2.9% | 9.1% | 0.32 | fixed100 crash15/90dz ladder |
| S3 | BTC-USDT 6H | none | +0.1% | 27.6% | 0.00 | vt10/60 crash20/90dz | -0.8% | 9.3% | -0.09 | fixed25 |
| S4 | BTC-USDT 6H | none | +12.8% | 41.4% | 0.31 | vt20/60 crash10/180dh | +8.1% | 12.4% | 0.66 | vt15/60 crash15/90dz |
| S1+S5 | BTC-USDT 6H | tp2 | +30.5% | 53.2% | 0.57 | vt25/60 ladder | +14.4% | 20.9% | 0.69 | vt15/60 crash20/90dz |
| S2+S5 | BTC-USDT 6H | none | +2.4% | 60.6% | 0.04 | vt15/20 crash20/180dz ladder | +2.9% | 9.1% | 0.32 | fixed100 crash15/90dz ladder |
| baseline | ETH-USDT 4H | none | +1.8% | 62.3% | 0.03 | vt15/60 | +4.3% | 21.6% | 0.20 | fixed100 crash15/90dz ladder |
| S1 | ETH-USDT 4H | none | +27.7% | 55.1% | 0.50 | vt25/30 crash15/90dz ladder | +1.3% | 23.1% | 0.06 | vt25/20 |
| S2 | ETH-USDT 4H | none | +17.6% | 51.8% | 0.34 | vt20/60 crash20/90dh | +6.2% | 20.4% | 0.30 | fixed100 crash20/90dh ladder |
| S3 | ETH-USDT 4H | trail2 | +7.8% | 14.1% | 0.56 | vt25/20 | +3.4% | 6.7% | 0.50 | vt10/60 crash15/180dh |
| S4 | ETH-USDT 4H | none | -2.2% | 30.9% | -0.07 | vt25/20 crash10/180dz | -4.0% | 16.4% | -0.24 | vt20/60 ladder |
| S1+S5 | ETH-USDT 4H | none | +24.5% | 55.1% | 0.45 | vt25/60 | +14.1% | 25.0% | 0.57 | vt25/20 |
| S2+S5 | ETH-USDT 4H | none | +20.3% | 49.9% | 0.41 | fixed25 | +6.7% | 15.9% | 0.42 | fixed100 crash20/90dh ladder |
| baseline | ETH-USDT 6H | time30 | +4.6% | 62.3% | 0.07 | vt25/30 crash10/90dh | +5.5% | 21.8% | 0.25 | vt25/60 ladder |
| S1 | ETH-USDT 6H | none | +30.4% | 65.9% | 0.46 | vt25/60 crash10/180dz | -0.9% | 28.2% | -0.03 | vt20/60 ladder |
| S2 | ETH-USDT 6H | none | +12.7% | 48.4% | 0.26 | vt15/60 | +7.5% | 15.5% | 0.48 | vt25/60 ladder |
| S3 | ETH-USDT 6H | tp3 | +11.8% | 19.1% | 0.62 | vt25/20 crash20/90dh | +2.8% | 11.3% | 0.25 | fixed25 crash10/180dh |
| S4 | ETH-USDT 6H | tp2 | +3.2% | 55.2% | 0.06 | vt25/60 ladder | +6.8% | 18.4% | 0.37 | vt25/60 crash10/90dh ladder |
| S1+S5 | ETH-USDT 6H | none | +11.0% | 60.8% | 0.18 | vt25/60 crash10/180dz | -1.6% | 31.8% | -0.05 | fixed100 crash15/180dz ladder |
| S2+S5 | ETH-USDT 6H | time30 | +27.5% | 36.5% | 0.75 | vt15/60 | +9.6% | 15.5% | 0.62 | fixed50 ladder |

Medians over 28 runs: all-in max DD 54.2% → 19.3%; CAGR +11.4% → +4.9%; Calmar 0.28 → 0.31. Both columns replay the most-selected rule with FIXED parameters over every test window (no re-selection), so they differ from the walk-forward numbers in the summary table, which re-select the rule and sizing every window. All-in = 100% of equity, no crash filter, no ladder (the Sprint 2 convention); chosen = the most-selected sizing of the walk-forward.

## Drawdown ladder — cost in return, gain in drawdown (chosen sizing with vs without the ladder, fixed replay)

| Candidate | Series | Return without → with | Max DD without → with | Calmar without → with |
|---|---|---:|---:|---:|
| baseline | BTC-USDT 4H | +59.1% → +34.3% | 29.3% → 20.2% | 0.38 → 0.35 |
| S1 | BTC-USDT 4H | +27.9% → +13.5% | 41.4% → 25.6% | 0.14 → 0.12 |
| S2 | BTC-USDT 4H | +13.1% → +12.3% | 10.2% → 10.2% | 0.28 → 0.27 |
| S3 | BTC-USDT 4H | -2.4% → -2.4% | 5.9% → 5.9% | -0.09 → -0.09 |
| S4 | BTC-USDT 4H | +36.5% → +17.7% | 24.2% → 22.7% | 0.31 → 0.17 |
| S1+S5 | BTC-USDT 4H | +59.1% → +48.7% | 29.9% → 22.9% | 0.38 → 0.42 |
| S2+S5 | BTC-USDT 4H | +13.3% → +12.5% | 10.2% → 10.2% | 0.29 → 0.27 |
| baseline | BTC-USDT 6H | +76.0% → +43.2% | 29.1% → 22.6% | 0.48 → 0.38 |
| S1 | BTC-USDT 6H | +101.2% → +78.8% | 27.3% → 20.1% | 0.65 → 0.72 |
| S2 | BTC-USDT 6H | +19.4% → +13.1% | 8.3% → 9.1% | 0.50 → 0.32 |
| S3 | BTC-USDT 6H | -3.6% → -4.5% | 9.3% → 10.2% | -0.09 → -0.11 |
| S4 | BTC-USDT 6H | +40.1% → +36.3% | 12.4% → 12.6% | 0.66 → 0.59 |
| S1+S5 | BTC-USDT 6H | +97.6% → +78.3% | 28.7% → 20.9% | 0.60 → 0.69 |
| S2+S5 | BTC-USDT 6H | +19.4% → +13.1% | 8.3% → 9.1% | 0.50 → 0.32 |
| baseline | ETH-USDT 4H | +19.9% → +7.1% | 21.6% → 16.6% | 0.20 → 0.10 |
| S1 | ETH-USDT 4H | +17.3% → +5.6% | 31.7% → 23.1% | 0.12 → 0.06 |
| S2 | ETH-USDT 4H | +29.7% → +27.7% | 20.4% → 16.6% | 0.30 → 0.35 |
| S3 | ETH-USDT 4H | +15.6% → +15.6% | 6.7% → 6.7% | 0.50 → 0.50 |
| S4 | ETH-USDT 4H | -16.2% → -16.2% | 16.4% → 16.4% | -0.24 → -0.24 |
| S1+S5 | ETH-USDT 4H | +77.7% → +27.3% | 25.0% → 15.6% | 0.57 → 0.36 |
| S2+S5 | ETH-USDT 4H | +32.5% → +18.1% | 15.9% → 14.0% | 0.42 → 0.28 |
| baseline | ETH-USDT 6H | +25.8% → +15.5% | 21.8% → 18.0% | 0.25 → 0.19 |
| S1 | ETH-USDT 6H | -3.8% → -6.1% | 28.2% → 18.9% | -0.03 → -0.08 |
| S2 | ETH-USDT 6H | +36.5% → +35.3% | 15.5% → 11.9% | 0.48 → 0.61 |
| S3 | ETH-USDT 6H | +12.8% → +12.8% | 11.3% → 11.3% | 0.25 → 0.25 |
| S4 | ETH-USDT 6H | +35.4% → +32.7% | 23.4% → 18.4% | 0.31 → 0.37 |
| S1+S5 | ETH-USDT 6H | -6.6% → -10.7% | 31.8% → 24.1% | -0.05 → -0.11 |
| S2+S5 | ETH-USDT 6H | +48.4% → +41.1% | 15.5% → 11.9% | 0.62 → 0.70 |

Median effect of the ladder over 28 runs: return -6.3%, max drawdown -3.7% (negative = smaller drawdown), Calmar -0.02.

## Exit brackets — give-back before/after (same rule and sizing, fixed replay)

Give-back = trades that reached +3 % unrealized gain yet closed at a loss (the fleets paper's finding); 'none' = the strategy's own exits only.

| Candidate | Series | Bracket compared | Return none → bracket | PF none → bracket | Max DD none → bracket | Give-back share none → bracket | Avg give-back none → bracket |
|---|---|---|---:|---:|---:|---:|---:|
| baseline | BTC-USDT 4H | none (selected); comparison shows trail1 | +34.3% → +16.2% | 1.45 → 1.12 | 20.2% → 22.5% | 58.2% (55) → 22.9% (131) | 8.8% → 4.7% |
| S1 | BTC-USDT 4H | none (selected); comparison shows trail1 | +27.9% → -25.3% | 1.22 → 0.92 | 41.4% → 45.5% | 40.4% (57) → 12.3% (163) | 7.6% → 3.8% |
| S2 | BTC-USDT 4H | none (selected); comparison shows trail1 | +12.3% → -0.2% | 1.35 → 1.01 | 10.2% → 12.9% | 55.3% (47) → 15.0% (113) | 8.7% → 4.0% |
| S3 | BTC-USDT 4H | none (selected); comparison shows trail1 | -2.4% → -4.3% | 0.90 → 0.81 | 5.9% → 7.8% | 0.0% (15) → 0.0% (15) | 1.0% → 1.1% |
| S4 | BTC-USDT 4H | none (selected); comparison shows trail1 | +17.7% → +14.2% | 1.28 → 1.21 | 22.7% → 22.3% | 36.0% (25) → 12.8% (39) | 6.7% → 4.9% |
| S1+S5 | BTC-USDT 4H | none (selected); comparison shows trail1 | +59.1% → -11.6% | 1.43 → 0.97 | 29.9% → 35.5% | 38.6% (57) → 12.3% (163) | 8.4% → 3.8% |
| S2+S5 | BTC-USDT 4H | none (selected); comparison shows trail1 | +12.5% → -0.0% | 1.35 → 1.01 | 10.2% → 12.9% | 54.3% (46) → 14.3% (112) | 8.7% → 4.0% |
| baseline | BTC-USDT 6H | none (selected); comparison shows trail1 | +43.2% → +4.9% | 1.58 → 1.05 | 22.6% → 25.9% | 59.0% (39) → 20.8% (125) | 10.8% → 4.8% |
| S1 | BTC-USDT 6H | tp2 | +89.3% → +78.8% | 2.15 → 1.53 | 15.7% → 20.1% | 41.9% (43) → 39.2% (79) | 8.9% → 4.0% |
| S2 | BTC-USDT 6H | none (selected); comparison shows trail1 | +13.1% → -2.0% | 1.42 → 0.97 | 9.1% → 13.3% | 48.1% (27) → 17.2% (58) | 8.5% → 4.4% |
| S3 | BTC-USDT 6H | none (selected); comparison shows trail1 | -3.6% → -4.3% | 0.89 → 0.86 | 9.3% → 10.0% | 5.9% (17) → 5.9% (17) | 1.4% → 1.5% |
| S4 | BTC-USDT 6H | none (selected); comparison shows trail1 | +40.1% → +13.3% | 1.86 → 1.21 | 12.4% → 9.3% | 29.3% (41) → 9.2% (65) | 5.7% → 4.1% |
| S1+S5 | BTC-USDT 6H | tp2 | +88.7% → +78.3% | 2.14 → 1.54 | 16.5% → 20.9% | 41.9% (43) → 38.5% (78) | 8.9% → 4.0% |
| S2+S5 | BTC-USDT 6H | none (selected); comparison shows trail1 | +13.1% → -2.0% | 1.42 → 0.97 | 9.1% → 13.3% | 48.1% (27) → 17.2% (58) | 8.5% → 4.4% |
| baseline | ETH-USDT 4H | none (selected); comparison shows trail1 | +19.9% → -11.6% | 1.21 → 0.95 | 21.6% → 27.3% | 45.3% (53) → 19.4% (191) | 12.2% → 4.7% |
| S1 | ETH-USDT 4H | none (selected); comparison shows trail1 | +5.6% → -11.2% | 1.13 → 0.93 | 23.1% → 29.0% | 52.6% (38) → 28.7% (87) | 13.3% → 7.2% |
| S2 | ETH-USDT 4H | none (selected); comparison shows trail1 | +29.7% → -2.2% | 1.48 → 1.01 | 20.4% → 24.1% | 54.1% (37) → 18.6% (145) | 14.6% → 5.1% |
| S3 | ETH-USDT 4H | trail2 | +16.0% → +15.6% | 1.48 → 1.47 | 6.8% → 6.7% | 4.5% (22) → 8.7% (23) | 2.0% → 2.0% |
| S4 | ETH-USDT 4H | none (selected); comparison shows trail1 | -16.2% → -16.2% | 0.38 → 0.36 | 16.4% → 16.4% | 55.6% (9) → 30.0% (10) | 5.5% → 4.8% |
| S1+S5 | ETH-USDT 4H | none (selected); comparison shows trail1 | +77.7% → +60.9% | 1.87 → 1.29 | 25.0% → 22.5% | 45.5% (33) → 27.1% (96) | 13.8% → 7.6% |
| S2+S5 | ETH-USDT 4H | none (selected); comparison shows trail1 | +32.5% → +5.9% | 1.63 → 1.05 | 15.9% → 16.4% | 56.8% (37) → 19.9% (146) | 14.3% → 5.1% |
| baseline | ETH-USDT 6H | time30 | +42.6% → +25.8% | 1.45 → 1.22 | 18.6% → 21.8% | 59.2% (49) → 63.3% (60) | 11.5% → 9.4% |
| S1 | ETH-USDT 6H | none (selected); comparison shows trail1 | -3.8% → -11.3% | 1.01 → 0.89 | 28.2% → 27.6% | 60.0% (20) → 51.7% (29) | 12.1% → 9.4% |
| S2 | ETH-USDT 6H | none (selected); comparison shows trail1 | +36.5% → +14.1% | 1.58 → 1.15 | 15.5% → 15.6% | 50.0% (42) → 20.8% (101) | 11.3% → 6.0% |
| S3 | ETH-USDT 6H | tp3 | +9.6% → +12.8% | 1.30 → 1.39 | 11.3% → 11.3% | 12.5% (32) → 12.5% (32) | 2.7% → 2.3% |
| S4 | ETH-USDT 6H | tp2 | +48.8% → +32.7% | 1.57 → 1.35 | 18.4% → 18.4% | 48.0% (50) → 41.5% (65) | 7.3% → 3.9% |
| S1+S5 | ETH-USDT 6H | none (selected); comparison shows trail1 | -6.6% → -20.5% | 0.95 → 0.82 | 31.8% → 29.4% | 63.6% (22) → 20.3% (59) | 11.7% → 5.5% |
| S2+S5 | ETH-USDT 6H | time30 | +46.3% → +48.4% | 1.82 → 1.80 | 15.5% → 15.5% | 43.2% (37) → 42.5% (40) | 11.2% → 10.4% |

The train stage kept the strategy's own exits (`none`) in 75.0% of the runs. Median effect of the compared bracket over 28 runs: profit factor -0.31, give-back share -24.7% (negative = fewer winners turned losers).

## 4H vs 6H (same candidate and instrument, walk-forward numbers)

| Candidate | Instrument | 4H Sharpe / Calmar / max DD / fees-yr / trades | 6H Sharpe / Calmar / max DD / fees-yr / trades | Higher Calmar |
|---|---|---|---|---|
| hold | BTC-USDT | 0.60 / 0.39 / 19.3% / 0.8% / 40 | 0.63 / 0.26 / 27.0% / 0.7% / 36 | 4H |
| baseline | BTC-USDT | 0.18 / 0.08 / 16.5% / 2.1% / 159 | 0.38 / 0.19 / 17.6% / 1.5% / 114 | 6H |
| S1 | BTC-USDT | 0.61 / 0.39 / 20.1% / 3.1% / 184 | 0.66 / 0.39 / 21.6% / 2.9% / 162 | 4H |
| S2 | BTC-USDT | 0.29 / 0.18 / 11.4% / 1.1% / 84 | -0.04 / -0.04 / 13.6% / 1.0% / 73 | 4H |
| S3 | BTC-USDT | -0.30 / -0.14 / 9.9% / 1.3% / 85 | -0.22 / -0.12 / 8.1% / 1.2% / 64 | 6H |
| S4 | BTC-USDT | 0.30 / 0.14 / 17.9% / 2.4% / 96 | 0.15 / 0.08 / 12.4% / 2.0% / 97 | 4H |
| S1+S5 | BTC-USDT | 0.41 / 0.25 / 20.5% / 3.3% / 193 | 0.66 / 0.38 / 22.0% / 2.7% / 153 | 6H |
| S2+S5 | BTC-USDT | 0.33 / 0.21 / 11.4% / 1.0% / 83 | -0.04 / -0.04 / 13.6% / 1.0% / 73 | 4H |
| hold | ETH-USDT | 0.18 / 0.06 / 20.2% / 0.8% / 79 | 0.08 / 0.01 / 19.1% / 0.6% / 55 | 4H |
| baseline | ETH-USDT | 0.31 / 0.12 / 22.9% / 2.0% / 194 | 0.21 / 0.07 / 24.2% / 1.8% / 215 | 4H |
| S1 | ETH-USDT | -0.05 / -0.05 / 22.1% / 2.8% / 221 | -0.01 / -0.04 / 19.1% / 2.2% / 168 | 6H |
| S2 | ETH-USDT | -0.00 / -0.02 / 28.8% / 1.3% / 103 | 0.03 / -0.01 / 20.0% / 1.3% / 96 | 6H |
| S3 | ETH-USDT | -0.58 / -0.19 / 43.5% / 1.5% / 64 | -0.04 / -0.03 / 15.1% / 1.1% / 48 | 6H |
| S4 | ETH-USDT | -0.64 / -0.15 / 28.1% / 1.1% / 66 | 0.83 / 0.58 / 13.2% / 1.1% / 66 | 6H |
| S1+S5 | ETH-USDT | -0.05 / -0.05 / 27.2% / 3.2% / 219 | 0.11 / 0.03 / 19.0% / 2.3% / 168 | 6H |
| S2+S5 | ETH-USDT | 0.19 / 0.06 / 26.9% / 1.2% / 85 | 0.14 / 0.05 / 19.8% / 1.3% / 87 | 4H |

6H had the higher Calmar in 8 of 16 pairs, 4H in 8.

## Positioning filter (S5) — base rule vs base + funding/open-interest filter

| Base | Series | Base Sharpe / Calmar / max DD / trades | +S5 Sharpe / Calmar / max DD / trades | Data coverage (funding / OI) |
|---|---|---|---|---|
| S1 | BTC-USDT 4H | 0.61 / 0.39 / 20.1% / 184 | 0.41 / 0.25 / 20.5% / 193 | 100.0% / 87.8% |
| S2 | BTC-USDT 4H | 0.29 / 0.18 / 11.4% / 84 | 0.33 / 0.21 / 11.4% / 83 | 100.0% / 87.8% |
| S1 | BTC-USDT 6H | 0.66 / 0.39 / 21.6% / 162 | 0.66 / 0.38 / 22.0% / 153 | 100.0% / 87.8% |
| S2 | BTC-USDT 6H | -0.04 / -0.04 / 13.6% / 73 | -0.04 / -0.04 / 13.6% / 73 | 100.0% / 87.8% |
| S1 | ETH-USDT 4H | -0.05 / -0.05 / 22.1% / 221 | -0.05 / -0.05 / 27.2% / 219 | 100.0% / 66.5% |
| S2 | ETH-USDT 4H | -0.00 / -0.02 / 28.8% / 103 | 0.19 / 0.06 / 26.9% / 85 | 100.0% / 66.5% |
| S1 | ETH-USDT 6H | -0.01 / -0.04 / 19.1% / 168 | 0.11 / 0.03 / 19.0% / 168 | 100.0% / 66.5% |
| S2 | ETH-USDT 6H | 0.03 / -0.01 / 20.0% / 96 | 0.14 / 0.05 / 19.8% / 87 | 100.0% / 66.5% |

## Portfolio combination (daily compounding of the sleeves' out-of-sample returns)

| Portfolio | Sleeves | Weights | Ladder | CAGR | Sharpe | Max DD | Calmar | Div. ratio | Pos. years |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| S2+S4 x BTC+ETH, equal capital | 4 | S2/BTC/4H=0.25, S2/ETH/6H=0.25, S4/BTC/4H=0.25, S4/ETH/6H=0.25 | no | +3.1% | 0.49 | 11.3% | 0.28 | 1.42 | 2/5 |
| S2+S4 x BTC+ETH, equal capital, ladder | 4 | S2/BTC/4H=0.25, S2/ETH/6H=0.25, S4/BTC/4H=0.25, S4/ETH/6H=0.25 | yes | +2.3% | 0.44 | 8.2% | 0.28 | 1.80 | 2/5 |
| S2+S4 x BTC+ETH, equal risk | 4 | S2/BTC/4H=0.28, S2/ETH/6H=0.25, S4/BTC/4H=0.23, S4/ETH/6H=0.24 | no | +3.1% | 0.48 | 11.2% | 0.27 | 1.42 | 2/5 |
| S2+S4 x BTC+ETH, equal risk, ladder | 4 | S2/BTC/4H=0.28, S2/ETH/6H=0.25, S4/BTC/4H=0.23, S4/ETH/6H=0.24 | yes | +2.2% | 0.43 | 8.1% | 0.27 | 1.80 | 2/5 |
| S1+S2+S4 x BTC+ETH, equal capital | 6 | S1/BTC/4H=0.17, S1/ETH/6H=0.17, S2/BTC/4H=0.17, S2/ETH/6H=0.17, S4/BTC/4H=0.17, S4/ETH/6H=0.17 | no | +3.4% | 0.46 | 12.8% | 0.26 | 1.38 | 3/5 |
| S1+S2+S4 x BTC+ETH, equal capital, ladder | 6 | S1/BTC/4H=0.17, S1/ETH/6H=0.17, S2/BTC/4H=0.17, S2/ETH/6H=0.17, S4/BTC/4H=0.17, S4/ETH/6H=0.17 | yes | +1.9% | 0.35 | 9.2% | 0.20 | 1.94 | 3/5 |
| S1+S2+S4 x BTC+ETH, equal risk | 6 | S1/BTC/4H=0.12, S1/ETH/6H=0.15, S2/BTC/4H=0.21, S2/ETH/6H=0.18, S4/BTC/4H=0.17, S4/ETH/6H=0.18 | no | +3.1% | 0.45 | 12.4% | 0.25 | 1.40 | 3/5 |
| S1+S2+S4 x BTC+ETH, equal risk, ladder | 6 | S1/BTC/4H=0.12, S1/ETH/6H=0.15, S2/BTC/4H=0.21, S2/ETH/6H=0.18, S4/BTC/4H=0.17, S4/ETH/6H=0.18 | yes | +1.8% | 0.36 | 8.8% | 0.21 | 1.94 | 3/5 |

Correlation of daily sleeve returns:

| | S1/BTC/4H | S1/ETH/6H | S2/BTC/4H | S2/ETH/6H | S4/BTC/4H | S4/ETH/6H |
|---|---:|---:|---:|---:|---:|---:|
| S1/BTC/4H | 1.00 | 0.56 | 0.69 | 0.43 | 0.42 | 0.29 |
| S1/ETH/6H | 0.56 | 1.00 | 0.47 | 0.58 | 0.20 | 0.37 |
| S2/BTC/4H | 0.69 | 0.47 | 1.00 | 0.44 | 0.34 | 0.35 |
| S2/ETH/6H | 0.43 | 0.58 | 0.44 | 1.00 | 0.22 | 0.36 |
| S4/BTC/4H | 0.42 | 0.20 | 0.34 | 0.22 | 1.00 | 0.21 |
| S4/ETH/6H | 0.29 | 0.37 | 0.35 | 0.36 | 0.21 | 1.00 |

Sleeves use, for every (strategy family, instrument), the timeframe with the higher out-of-sample Calmar — a mild selection on out-of-sample data, so treat portfolio numbers as slightly optimistic. Each sleeve compounds its own capital bucket.

## Positioning data (external, research features only)

| Instrument | Source | Funding span | Funding coverage (in-sample bars) | Open-interest span | OI coverage |
|---|---|---|---:|---|---:|
| BTC-USDT | binance | 2019-09-10->2026-10-20 (7792 rows) | 100.0% | 2020-09-01->2026-10-19 (53738 rows) | 87.8% |
| ETH-USDT | binance | 2019-11-27->2026-10-20 (7558 rows) | 100.0% | 2021-12-01->2026-10-19 (42806 rows) | 66.5% |

Binance public history is the long-history source (funding since 2019-09/2019-11, 5-minute open interest reduced to hourly since 2020-09 for BTC and 2021-12 for ETH); OKX's own series (months of history) keep being collected for the forward period. Features only — this project never trades on Binance.

## hold — Always-long reference (sizing overlays only, no stop) (BTC-USDT 4H)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bracket': 'none'}`. Most-selected sizing: `vt10/60 crash20/90dz ladder` (selected 1 of 9 windows; other choices: vt10).

| Year | OOS return |
|---|---:|
| 2021 | -3.3% |
| 2022 | -7.7% |
| 2023 | +31.1% |
| 2024 | +15.9% |
| 2025 | +0.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -8.2% | -1.66 |
| highvol_range | 3.7% | -2.8% | -0.70 |
| highvol_up | 13.3% | +33.3% | 2.82 |
| lowvol_down | 13.4% | -6.7% | -2.54 |
| lowvol_range | 13.2% | +1.7% | 0.33 |
| lowvol_up | 17.8% | +20.3% | 1.83 |
| midvol_down | 7.6% | -9.9% | -3.72 |
| midvol_range | 7.1% | -3.7% | -0.62 |
| midvol_up | 12.8% | +16.0% | 1.83 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +23.9%, neighbours median -, min -, share profitable - over 0 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +43.0% → +23.9%, max DD 13.3% → 12.7%, Calmar 0.64 → 0.40.

Entry-sized only (no mid-trade reductions) for comparison: return +36.4%, max DD 15.0%, Calmar 0.49.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 40 OOS trades): terminal growth p05 0.76× / p50 1.30× / p95 2.71×, P(loss) 23.6%, max DD p50 18.8%, p95 34.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +23.9%, x2: +22.7%, x3: +21.6%

Deflated Sharpe: 391 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.020 per bar vs observed OOS 0.013 → DSR 0.24.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +14.8%, CAGR +3.2%, Sharpe 0.59, PF 2.88, max DD 7.2%, Calmar 0.45, trades 9, robust - → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, enough_trades, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

- passive reference: always long, no stop, sizing overlays only; excluded from the shortlist

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (BTC-USDT 4H)

Rule grid: 126 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'short_window': 10, 'long_window': 100, 'stop_loss_pct': 0.04, 'bracket': 'none'}`. Most-selected sizing: `vt25/60 ladder` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -7.7% |
| 2022 | -6.8% |
| 2023 | +15.2% |
| 2024 | +15.7% |
| 2025 | -7.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -12.7% | -2.74 |
| highvol_range | 3.7% | +8.0% | 5.42 |
| highvol_up | 13.3% | +4.4% | 0.54 |
| lowvol_down | 13.4% | -0.8% | -0.24 |
| lowvol_range | 13.2% | -0.8% | -0.13 |
| lowvol_up | 17.8% | +3.0% | 0.41 |
| midvol_down | 7.6% | -4.2% | -1.91 |
| midvol_range | 7.1% | +6.7% | 2.23 |
| midvol_up | 12.8% | +3.9% | 0.58 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +34.3%, neighbours median +25.7%, min -5.6%, share profitable 87.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +59.1% → +34.3%, max DD 29.3% → 20.2%, Calmar 0.38 → 0.35.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +34.3% → +16.2%, PF 1.45 → 1.12, max DD 20.2% → 22.5%. Give-back (trades that reached +3% unrealized yet closed negative): 58.2% of 55 → 22.9% of 131; average give-back 8.8% → 4.7%.

Entry-sized only (no mid-trade reductions) for comparison: return +4.0%, max DD 17.9%, Calmar 0.05.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 159 OOS trades): terminal growth p05 0.73× / p50 1.06× / p95 1.56×, P(loss) 41.6%, max DD p50 19.0%, p95 33.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +34.3%, x2: +29.3%, x3: +25.0%

Deflated Sharpe: 516 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.004 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +7.9%, CAGR +1.8%, Sharpe 0.33, PF 1.19, max DD 8.5%, Calmar 0.21, trades 154, robust 87.5% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 4H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'lookbacks_days': (7, 30, 90), 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'bracket': 'none'}`. Most-selected sizing: `fixed50` (selected 2 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | +2.7% |
| 2022 | -9.8% |
| 2023 | +32.8% |
| 2024 | +7.1% |
| 2025 | +5.5% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -6.8% | -1.62 |
| highvol_range | 3.7% | +4.2% | 1.98 |
| highvol_up | 13.3% | +21.5% | 1.42 |
| lowvol_down | 13.4% | -4.6% | -1.91 |
| lowvol_range | 13.2% | +10.9% | 1.94 |
| lowvol_up | 17.8% | -4.3% | -0.40 |
| midvol_down | 7.6% | -3.3% | -1.64 |
| midvol_range | 7.1% | +4.1% | 1.10 |
| midvol_up | 12.8% | +15.4% | 1.60 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +27.9%, neighbours median +23.4%, min -32.1%, share profitable 62.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +27.9% → +13.5%, max DD 41.4% → 25.6%, Calmar 0.14 → 0.12.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +27.9% → -25.3%, PF 1.22 → 0.92, max DD 41.4% → 45.5%. Give-back (trades that reached +3% unrealized yet closed negative): 40.4% of 57 → 12.3% of 163; average give-back 7.6% → 3.8%.

Entry-sized only (no mid-trade reductions) for comparison: return +27.9%, max DD 41.4%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 184 OOS trades): terminal growth p05 0.78× / p50 1.38× / p95 2.56×, P(loss) 18.8%, max DD p50 20.2%, p95 36.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +27.9%, x2: +14.3%, x3: +2.1%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.013 → DSR 0.05.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=yes, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +9.8%, CAGR +2.2%, Sharpe 0.39, PF 1.24, max DD 8.3%, Calmar 0.26, trades 185, robust 75.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 4H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Most-selected sizing: `vt10/60 crash15/90dh ladder` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -1.8% |
| 2022 | -7.2% |
| 2023 | +15.8% |
| 2024 | +7.8% |
| 2025 | -3.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -8.0% | -3.03 |
| highvol_range | 3.7% | +5.9% | 4.56 |
| highvol_up | 13.3% | +1.8% | 0.30 |
| lowvol_down | 13.4% | -4.1% | -1.38 |
| lowvol_range | 13.2% | +3.7% | 1.08 |
| lowvol_up | 17.8% | -3.9% | -0.54 |
| midvol_down | 7.6% | +0.4% | 0.25 |
| midvol_range | 7.1% | +2.6% | 1.44 |
| midvol_up | 12.8% | +11.8% | 1.85 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +12.3%, neighbours median +13.7%, min +11.1%, share profitable 100.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +13.1% → +12.3%, max DD 10.2% → 10.2%, Calmar 0.28 → 0.27.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +12.3% → -0.2%, PF 1.35 → 1.01, max DD 10.2% → 12.9%. Give-back (trades that reached +3% unrealized yet closed negative): 55.3% of 47 → 15.0% of 113; average give-back 8.7% → 4.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +17.0%, max DD 10.5%, Calmar 0.35.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 84 OOS trades): terminal growth p05 0.82× / p50 1.08× / p95 1.47×, P(loss) 34.5%, max DD p50 13.0%, p95 23.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.3%, x2: +10.3%, x3: +8.4%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.006 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +15.4%, CAGR +3.4%, Sharpe 0.59, PF 1.48, max DD 8.6%, Calmar 0.39, trades 84, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (BTC-USDT 4H)

Rule grid: 378 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -2.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 2.5, 'time_stop_days': 2.0, 'bracket': 'none'}`. Most-selected sizing: `vt10/20 crash20/90dz` (selected 1 of 9 windows; other choices: vt10).

| Year | OOS return |
|---|---:|
| 2021 | -1.1% |
| 2022 | -2.4% |
| 2023 | -2.6% |
| 2024 | -1.7% |
| 2025 | +1.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | +2.1% | 1.15 |
| highvol_range | 3.7% | -5.1% | -4.06 |
| highvol_up | 13.3% | +2.4% | 2.38 |
| lowvol_down | 13.4% | -3.2% | -2.86 |
| lowvol_range | 13.2% | -1.8% | -0.67 |
| lowvol_up | 17.8% | -0.8% | -0.78 |
| midvol_down | 7.6% | -0.5% | -0.80 |
| midvol_range | 7.1% | +1.1% | 0.37 |
| midvol_up | 12.8% | +0.1% | 0.07 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set -2.4%, neighbours median -3.9%, min -9.7%, share profitable 20.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return -2.4% → -2.4%, max DD 5.9% → 5.9%, Calmar -0.09 → -0.09.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return -2.4% → -4.3%, PF 0.90 → 0.81, max DD 5.9% → 7.8%. Give-back (trades that reached +3% unrealized yet closed negative): 0.0% of 15 → 0.0% of 15; average give-back 1.0% → 1.1%.

Entry-sized only (no mid-trade reductions) for comparison: return -0.4%, max DD 5.3%, Calmar -0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.81× / p50 0.94× / p95 1.11×, P(loss) 75.3%, max DD p50 11.7%, p95 21.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -2.4%, x2: -4.5%, x3: -6.5%

Deflated Sharpe: 768 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.030 per bar vs observed OOS -0.006 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -4.5%, CAGR -1.0%, Sharpe -0.40, PF 0.81, max DD 8.6%, Calmar -0.12, trades 100, robust 30.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 4H)

Rule grid: 84 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Most-selected sizing: `fixed100 crash10/90dz ladder` (selected 2 of 9 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | -2.5% |
| 2022 | -3.9% |
| 2023 | +9.8% |
| 2024 | +22.6% |
| 2025 | -11.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | +0.8% | 0.52 |
| highvol_range | 3.7% | +6.6% | 2.53 |
| highvol_up | 13.3% | +13.1% | 1.44 |
| lowvol_down | 13.4% | -3.3% | -1.86 |
| lowvol_range | 13.2% | -5.7% | -1.56 |
| lowvol_up | 17.8% | -4.8% | -0.44 |
| midvol_down | 7.6% | -2.1% | -2.72 |
| midvol_range | 7.1% | +2.8% | 0.78 |
| midvol_up | 12.8% | +5.1% | 0.82 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +17.7%, neighbours median +21.8%, min -6.9%, share profitable 62.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +36.5% → +17.7%, max DD 24.2% → 22.7%, Calmar 0.31 → 0.17.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +17.7% → +14.2%, PF 1.28 → 1.21, max DD 22.7% → 22.3%. Give-back (trades that reached +3% unrealized yet closed negative): 36.0% of 25 → 12.8% of 39; average give-back 6.7% → 4.9%.

Entry-sized only (no mid-trade reductions) for comparison: return +8.2%, max DD 18.1%, Calmar 0.10.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 96 OOS trades): terminal growth p05 0.75× / p50 1.12× / p95 1.71×, P(loss) 33.9%, max DD p50 18.5%, p95 33.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +17.7%, x2: +18.2%, x3: +14.0%

Deflated Sharpe: 474 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.006 → DSR 0.11.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +7.4%, CAGR +1.6%, Sharpe 0.38, PF 1.21, max DD 9.9%, Calmar 0.17, trades 113, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 4H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': (7, 30, 90), 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `vt20/60` (selected 1 of 9 windows; other choices: vt15).

| Year | OOS return |
|---|---:|
| 2021 | +2.8% |
| 2022 | -10.0% |
| 2023 | +23.8% |
| 2024 | +9.1% |
| 2025 | -1.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -8.8% | -1.92 |
| highvol_range | 3.7% | +4.2% | 1.75 |
| highvol_up | 13.3% | +19.1% | 1.36 |
| lowvol_down | 13.4% | -5.2% | -2.15 |
| lowvol_range | 13.2% | +1.9% | 0.35 |
| lowvol_up | 17.8% | +0.9% | 0.15 |
| midvol_down | 7.6% | -4.4% | -2.12 |
| midvol_range | 7.1% | -0.9% | -0.16 |
| midvol_up | 12.8% | +18.3% | 1.65 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +59.1%, neighbours median +51.2%, min -5.6%, share profitable 70.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +59.1% → +48.7%, max DD 29.9% → 22.9%, Calmar 0.38 → 0.42.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +59.1% → -11.6%, PF 1.43 → 0.97, max DD 29.9% → 35.5%. Give-back (trades that reached +3% unrealized yet closed negative): 38.6% of 57 → 12.3% of 163; average give-back 8.4% → 3.8%.

Entry-sized only (no mid-trade reductions) for comparison: return +112.4%, max DD 30.3%, Calmar 0.63.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 193 OOS trades): terminal growth p05 0.72× / p50 1.22× / p95 2.26×, P(loss) 28.6%, max DD p50 22.4%, p95 38.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +59.1%, x2: +43.0%, x3: +28.6%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.035 per bar vs observed OOS 0.009 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +7.2%, CAGR +1.6%, Sharpe 0.29, PF 1.17, max DD 8.1%, Calmar 0.20, trades 193, robust 80.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 4H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `vt10/60 crash15/90dh ladder` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -1.7% |
| 2022 | -5.7% |
| 2023 | +15.7% |
| 2024 | +7.8% |
| 2025 | -3.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -7.3% | -2.69 |
| highvol_range | 3.7% | +5.9% | 4.56 |
| highvol_up | 13.3% | +1.3% | 0.24 |
| lowvol_down | 13.4% | -4.2% | -1.37 |
| lowvol_range | 13.2% | +4.0% | 1.12 |
| lowvol_up | 17.8% | -3.8% | -0.54 |
| midvol_down | 7.6% | +1.3% | 0.68 |
| midvol_range | 7.1% | +2.9% | 1.59 |
| midvol_up | 12.8% | +11.8% | 1.86 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +12.5%, neighbours median +12.6%, min +8.8%, share profitable 100.0% over 12 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +13.3% → +12.5%, max DD 10.2% → 10.2%, Calmar 0.29 → 0.27.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +12.5% → -0.0%, PF 1.35 → 1.01, max DD 10.2% → 12.9%. Give-back (trades that reached +3% unrealized yet closed negative): 54.3% of 46 → 14.3% of 112; average give-back 8.7% → 4.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +17.2%, max DD 10.5%, Calmar 0.36.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 83 OOS trades): terminal growth p05 0.83× / p50 1.10× / p95 1.52×, P(loss) 29.4%, max DD p50 12.4%, p95 22.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.5%, x2: +10.4%, x3: +8.6%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.034 per bar vs observed OOS 0.007 → DSR 0.00.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +16.1%, CAGR +3.5%, Sharpe 0.61, PF 1.51, max DD 8.6%, Calmar 0.41, trades 83, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (BTC-USDT 6H)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bracket': 'none'}`. Most-selected sizing: `vt20/20 crash10/180dz ladder` (selected 1 of 9 windows; other choices: vt10).

| Year | OOS return |
|---|---:|
| 2021 | -1.7% |
| 2022 | -5.9% |
| 2023 | +30.4% |
| 2024 | +9.1% |
| 2025 | +2.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -4.2% | -1.16 |
| highvol_range | 3.3% | -4.3% | -1.38 |
| highvol_up | 12.5% | +20.2% | 1.74 |
| lowvol_down | 12.8% | -3.6% | -1.30 |
| lowvol_range | 13.0% | -6.6% | -1.94 |
| lowvol_up | 17.5% | +26.2% | 2.94 |
| midvol_down | 9.2% | -4.6% | -1.91 |
| midvol_range | 7.9% | +0.7% | 0.22 |
| midvol_up | 14.1% | +12.0% | 1.34 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +11.0%, neighbours median -, min -, share profitable - over 0 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +27.2% → +11.0%, max DD 19.5% → 14.2%, Calmar 0.29 → 0.17.

Entry-sized only (no mid-trade reductions) for comparison: return +33.9%, max DD 15.8%, Calmar 0.44.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 36 OOS trades): terminal growth p05 0.79× / p50 1.30× / p95 2.61×, P(loss) 21.6%, max DD p50 15.2%, p95 29.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.0%, x2: +8.5%, x3: +6.4%

Deflated Sharpe: 391 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.016 → DSR 0.37.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +11.8%, CAGR +2.6%, Sharpe 0.49, PF 2.37, max DD 8.0%, Calmar 0.33, trades 9, robust - → fail (sharpe_gt_0_7, calmar_gt_0_5, enough_trades, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

- passive reference: always long, no stop, sizing overlays only; excluded from the shortlist

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (BTC-USDT 6H)

Rule grid: 126 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'short_window': 5, 'long_window': 100, 'stop_loss_pct': 0.04, 'bracket': 'none'}`. Most-selected sizing: `vt25/60 ladder` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | +11.2% |
| 2022 | -3.3% |
| 2023 | +5.6% |
| 2024 | +6.2% |
| 2025 | -4.5% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -3.9% | -0.98 |
| highvol_range | 3.3% | +8.1% | 3.59 |
| highvol_up | 12.5% | +5.9% | 0.69 |
| lowvol_down | 12.8% | -1.4% | -1.25 |
| lowvol_range | 13.0% | -3.9% | -1.57 |
| lowvol_up | 17.5% | +9.7% | 1.53 |
| midvol_down | 9.2% | -3.7% | -1.83 |
| midvol_range | 7.9% | +9.4% | 2.52 |
| midvol_up | 14.1% | -4.3% | -0.56 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +43.2%, neighbours median +51.6%, min +34.7%, share profitable 100.0% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +76.0% → +43.2%, max DD 29.1% → 22.6%, Calmar 0.48 → 0.38.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +43.2% → +4.9%, PF 1.58 → 1.05, max DD 22.6% → 25.9%. Give-back (trades that reached +3% unrealized yet closed negative): 59.0% of 39 → 20.8% of 125; average give-back 10.8% → 4.8%.

Entry-sized only (no mid-trade reductions) for comparison: return +37.1%, max DD 18.0%, Calmar 0.42.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 114 OOS trades): terminal growth p05 0.83× / p50 1.15× / p95 1.64×, P(loss) 24.7%, max DD p50 14.1%, p95 26.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +43.2%, x2: +39.4%, x3: +43.3%

Deflated Sharpe: 516 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.055 per bar vs observed OOS 0.010 → DSR 0.00.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +8.1%, CAGR +1.8%, Sharpe 0.33, PF 1.18, max DD 9.9%, Calmar 0.18, trades 144, robust 100.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 6H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': (14, 30, 60), 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'bracket': 'tp2'}`. Most-selected sizing: `vt25/60 ladder` (selected 1 of 9 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | +12.6% |
| 2022 | -15.8% |
| 2023 | +17.4% |
| 2024 | +21.1% |
| 2025 | +4.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -6.6% | -1.51 |
| highvol_range | 3.3% | +10.2% | 4.07 |
| highvol_up | 12.5% | +17.4% | 1.24 |
| lowvol_down | 12.8% | -7.8% | -3.14 |
| lowvol_range | 13.0% | +1.8% | 0.50 |
| lowvol_up | 17.5% | +12.8% | 1.60 |
| midvol_down | 9.2% | -4.4% | -1.18 |
| midvol_range | 7.9% | +6.9% | 1.94 |
| midvol_up | 14.1% | +8.2% | 0.91 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +78.8%, neighbours median +32.5%, min -5.8%, share profitable 87.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +101.2% → +78.8%, max DD 27.3% → 20.1%, Calmar 0.65 → 0.72.

Exit bracket `tp2` vs none (same rule, fixed replay): return +89.3% → +78.8%, PF 2.15 → 1.53, max DD 15.7% → 20.1%. Give-back (trades that reached +3% unrealized yet closed negative): 41.9% of 43 → 39.2% of 79; average give-back 8.9% → 4.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +38.9%, max DD 16.8%, Calmar 0.47.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 162 OOS trades): terminal growth p05 0.88× / p50 1.41× / p95 2.24×, P(loss) 10.9%, max DD p50 16.8%, p95 30.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +78.8%, x2: +71.8%, x3: +56.8%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.044 per bar vs observed OOS 0.017 → DSR 0.02.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=yes, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +14.5%, CAGR +3.2%, Sharpe 0.54, PF 1.32, max DD 10.4%, Calmar 0.31, trades 173, robust 87.5% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 6H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (7 traded, 2 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Most-selected sizing: `vt15/20 crash20/180dz ladder` (selected 1 of 7 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | -1.9% |
| 2024 | +4.7% |
| 2025 | -4.8% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -1.5% | -1.95 |
| highvol_range | 3.3% | -0.7% | -0.68 |
| highvol_up | 12.5% | -4.0% | -0.54 |
| lowvol_down | 12.8% | +0.1% | 0.10 |
| lowvol_range | 13.0% | -5.1% | -1.95 |
| lowvol_up | 17.5% | +7.8% | 1.38 |
| midvol_down | 9.2% | -2.6% | -2.54 |
| midvol_range | 7.9% | +2.3% | 0.96 |
| midvol_up | 14.1% | +2.1% | 0.41 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +13.1%, neighbours median +10.1%, min +2.7%, share profitable 100.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +19.4% → +13.1%, max DD 8.3% → 9.1%, Calmar 0.50 → 0.32.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +13.1% → -2.0%, PF 1.42 → 0.97, max DD 9.1% → 13.3%. Give-back (trades that reached +3% unrealized yet closed negative): 48.1% of 27 → 17.2% of 58; average give-back 8.5% → 4.4%.

Entry-sized only (no mid-trade reductions) for comparison: return +16.3%, max DD 12.0%, Calmar 0.30.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 73 OOS trades): terminal growth p05 0.78× / p50 0.99× / p95 1.25×, P(loss) 54.0%, max DD p50 13.7%, p95 26.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.1%, x2: +12.8%, x3: +11.5%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.033 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +1.5%, CAGR +0.3%, Sharpe 0.09, PF 1.05, max DD 10.0%, Calmar 0.03, trades 82, robust 100.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (BTC-USDT 6H)

Rule grid: 378 combinations (entries × exit brackets). Windows: 9 (8 traded, 3 positive). Most-selected rule: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -1.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 2.5, 'time_stop_days': 2.0, 'bracket': 'none'}`. Most-selected sizing: `vt10/60 crash20/90dz` (selected 2 of 8 windows; other choices: vt15).

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | -1.4% |
| 2024 | +0.3% |
| 2025 | -3.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | +0.8% | 1.65 |
| highvol_range | 3.3% | -3.0% | -1.62 |
| highvol_up | 12.5% | +3.8% | 2.56 |
| lowvol_down | 12.8% | -1.9% | -2.09 |
| lowvol_range | 13.0% | -7.5% | -2.37 |
| lowvol_up | 17.5% | -1.3% | -0.51 |
| midvol_down | 9.2% | +0.2% | 0.68 |
| midvol_range | 7.9% | -0.3% | -0.19 |
| midvol_up | 14.1% | +5.4% | 2.09 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set -3.6%, neighbours median -5.6%, min -10.1%, share profitable 10.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return -3.6% → -4.5%, max DD 9.3% → 10.2%, Calmar -0.09 → -0.11.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return -3.6% → -4.3%, PF 0.89 → 0.86, max DD 9.3% → 10.0%. Give-back (trades that reached +3% unrealized yet closed negative): 5.9% of 17 → 5.9% of 17; average give-back 1.4% → 1.5%.

Entry-sized only (no mid-trade reductions) for comparison: return -3.4%, max DD 10.1%, Calmar -0.08.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 64 OOS trades): terminal growth p05 0.80× / p50 0.95× / p95 1.13×, P(loss) 66.0%, max DD p50 11.7%, p95 23.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -4.1%, x2: -6.4%, x3: -8.6%

Deflated Sharpe: 768 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.041 per bar vs observed OOS -0.006 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -6.7%, CAGR -1.6%, Sharpe -0.62, PF 0.71, max DD 7.3%, Calmar -0.22, trades 78, robust 10.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 6H)

Rule grid: 84 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Most-selected sizing: `vt20/60 crash10/180dh` (selected 1 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -0.6% |
| 2022 | -9.2% |
| 2023 | +6.5% |
| 2024 | +8.8% |
| 2025 | -0.5% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -7.5% | -2.51 |
| highvol_range | 3.3% | +0.7% | 1.21 |
| highvol_up | 12.5% | +9.4% | 1.23 |
| lowvol_down | 12.8% | -3.6% | -1.83 |
| lowvol_range | 13.0% | -3.2% | -0.75 |
| lowvol_up | 17.5% | +8.0% | 0.95 |
| midvol_down | 9.2% | -4.3% | -2.28 |
| midvol_range | 7.9% | +1.1% | 0.46 |
| midvol_up | 14.1% | +4.7% | 0.75 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +40.1%, neighbours median +41.6%, min +30.2%, share profitable 100.0% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +40.1% → +36.3%, max DD 12.4% → 12.6%, Calmar 0.66 → 0.59.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +40.1% → +13.3%, PF 1.86 → 1.21, max DD 12.4% → 9.3%. Give-back (trades that reached +3% unrealized yet closed negative): 29.3% of 41 → 9.2% of 65; average give-back 5.7% → 4.1%.

Entry-sized only (no mid-trade reductions) for comparison: return +40.3%, max DD 12.4%, Calmar 0.66.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 97 OOS trades): terminal growth p05 0.78× / p50 1.04× / p95 1.45×, P(loss) 41.8%, max DD p50 16.3%, p95 29.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +40.1%, x2: +36.0%, x3: +31.9%

Deflated Sharpe: 474 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.028 per bar vs observed OOS 0.004 → DSR 0.03.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +7.8%, CAGR +1.8%, Sharpe 0.40, PF 1.25, max DD 5.8%, Calmar 0.30, trades 98, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 6H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': (14, 30, 60), 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'tp2'}`. Most-selected sizing: `vt25/60 ladder` (selected 1 of 9 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | +12.6% |
| 2022 | -16.2% |
| 2023 | +15.5% |
| 2024 | +23.2% |
| 2025 | +5.1% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -7.2% | -1.65 |
| highvol_range | 3.3% | +10.2% | 4.07 |
| highvol_up | 12.5% | +17.3% | 1.25 |
| lowvol_down | 12.8% | -7.3% | -2.96 |
| lowvol_range | 13.0% | +0.4% | 0.15 |
| lowvol_up | 17.5% | +14.1% | 1.77 |
| midvol_down | 9.2% | -4.7% | -1.28 |
| midvol_range | 7.9% | +6.4% | 1.85 |
| midvol_up | 14.1% | +9.1% | 1.03 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +78.3%, neighbours median +56.7%, min +0.8%, share profitable 100.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +97.6% → +78.3%, max DD 28.7% → 20.9%, Calmar 0.60 → 0.69.

Exit bracket `tp2` vs none (same rule, fixed replay): return +88.7% → +78.3%, PF 2.14 → 1.54, max DD 16.5% → 20.9%. Give-back (trades that reached +3% unrealized yet closed negative): 41.9% of 43 → 38.5% of 78; average give-back 8.9% → 4.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +38.6%, max DD 17.3%, Calmar 0.46.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 153 OOS trades): terminal growth p05 0.91× / p50 1.40× / p95 2.25×, P(loss) 11.7%, max DD p50 16.8%, p95 30.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +78.3%, x2: +70.6%, x3: +54.9%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.048 per bar vs observed OOS 0.017 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=yes, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +11.3%, CAGR +2.5%, Sharpe 0.43, PF 1.26, max DD 9.9%, Calmar 0.25, trades 164, robust 90.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 6H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (7 traded, 2 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `vt15/20 crash20/180dz ladder` (selected 1 of 7 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | -1.9% |
| 2024 | +4.7% |
| 2025 | -4.8% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.7% | -1.5% | -1.95 |
| highvol_range | 3.3% | -0.7% | -0.68 |
| highvol_up | 12.5% | -4.0% | -0.54 |
| lowvol_down | 12.8% | +0.1% | 0.10 |
| lowvol_range | 13.0% | -5.1% | -1.95 |
| lowvol_up | 17.5% | +7.8% | 1.38 |
| midvol_down | 9.2% | -2.6% | -2.54 |
| midvol_range | 7.9% | +2.3% | 0.96 |
| midvol_up | 14.1% | +2.1% | 0.41 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +13.1%, neighbours median +12.2%, min +2.8%, share profitable 100.0% over 12 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +19.4% → +13.1%, max DD 8.3% → 9.1%, Calmar 0.50 → 0.32.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +13.1% → -2.0%, PF 1.42 → 0.97, max DD 9.1% → 13.3%. Give-back (trades that reached +3% unrealized yet closed negative): 48.1% of 27 → 17.2% of 58; average give-back 8.5% → 4.4%.

Entry-sized only (no mid-trade reductions) for comparison: return +16.3%, max DD 12.0%, Calmar 0.30.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 73 OOS trades): terminal growth p05 0.78× / p50 0.99× / p95 1.25×, P(loss) 54.0%, max DD p50 13.7%, p95 26.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.1%, x2: +12.8%, x3: +11.5%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.036 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +1.5%, CAGR +0.3%, Sharpe 0.09, PF 1.05, max DD 10.0%, Calmar 0.03, trades 82, robust 100.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (ETH-USDT 4H)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bracket': 'none'}`. Most-selected sizing: `vt10/20 crash15/180dz` (selected 2 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -5.7% |
| 2022 | -0.6% |
| 2023 | +14.6% |
| 2024 | -3.5% |
| 2025 | +1.5% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +3.2% | 1.57 |
| highvol_range | 7.9% | -4.1% | -1.25 |
| highvol_up | 11.9% | -1.9% | -0.28 |
| lowvol_down | 11.2% | -3.6% | -2.24 |
| lowvol_range | 12.3% | -4.0% | -1.19 |
| lowvol_up | 14.1% | +3.5% | 0.66 |
| midvol_down | 8.8% | -3.4% | -2.21 |
| midvol_range | 10.1% | -1.7% | -0.35 |
| midvol_up | 13.8% | +19.2% | 2.32 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +7.0%, neighbours median -, min -, share profitable - over 0 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +7.0% → +9.2%, max DD 13.7% → 11.9%, Calmar 0.11 → 0.17.

Entry-sized only (no mid-trade reductions) for comparison: return +29.7%, max DD 15.2%, Calmar 0.41.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 79 OOS trades): terminal growth p05 0.74× / p50 1.05× / p95 1.51×, P(loss) 40.2%, max DD p50 16.0%, p95 32.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.0%, x2: +5.4%, x3: +3.9%

Deflated Sharpe: 391 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.029 per bar vs observed OOS 0.004 → DSR 0.01.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +7.8%, CAGR +1.8%, Sharpe 0.38, PF 1.83, max DD 8.6%, Calmar 0.20, trades 9, robust - → fail (sharpe_gt_0_7, calmar_gt_0_5, enough_trades, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

- passive reference: always long, no stop, sizing overlays only; excluded from the shortlist

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (ETH-USDT 4H)

Rule grid: 126 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'short_window': 20, 'long_window': 100, 'stop_loss_pct': 0.04, 'bracket': 'none'}`. Most-selected sizing: `vt15/60` (selected 3 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -0.1% |
| 2022 | -5.3% |
| 2023 | -0.4% |
| 2024 | +19.5% |
| 2025 | +0.3% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -7.3% | -2.17 |
| highvol_range | 7.9% | +3.6% | 0.92 |
| highvol_up | 11.9% | +2.2% | 0.35 |
| lowvol_down | 11.2% | -7.1% | -2.59 |
| lowvol_range | 12.3% | -7.7% | -1.98 |
| lowvol_up | 14.1% | +8.7% | 1.53 |
| midvol_down | 8.8% | +1.3% | 0.42 |
| midvol_range | 10.1% | +2.9% | 0.75 |
| midvol_up | 13.8% | +18.4% | 1.92 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +19.9%, neighbours median +17.4%, min +0.1%, share profitable 100.0% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +19.9% → +7.1%, max DD 21.6% → 16.6%, Calmar 0.20 → 0.10.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +19.9% → -11.6%, PF 1.21 → 0.95, max DD 21.6% → 27.3%. Give-back (trades that reached +3% unrealized yet closed negative): 45.3% of 53 → 19.4% of 191; average give-back 12.2% → 4.7%.

Entry-sized only (no mid-trade reductions) for comparison: return +39.0%, max DD 24.4%, Calmar 0.32.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 194 OOS trades): terminal growth p05 0.73× / p50 1.11× / p95 1.81×, P(loss) 35.8%, max DD p50 20.0%, p95 34.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +19.9%, x2: +15.3%, x3: +10.9%

Deflated Sharpe: 516 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.052 per bar vs observed OOS 0.007 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -6.2%, CAGR -1.5%, Sharpe -0.24, PF 0.88, max DD 14.0%, Calmar -0.10, trades 194, robust 50.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 4H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': (30, 60, 90), 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'bracket': 'none'}`. Most-selected sizing: `vt25/30 crash15/90dz ladder` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -6.9% |
| 2022 | -7.4% |
| 2023 | -1.3% |
| 2024 | +3.4% |
| 2025 | +8.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +1.4% | 0.60 |
| highvol_range | 7.9% | +0.7% | 0.28 |
| highvol_up | 11.9% | +10.6% | 1.48 |
| lowvol_down | 11.2% | -7.0% | -3.86 |
| lowvol_range | 12.3% | -4.8% | -0.89 |
| lowvol_up | 14.1% | +2.4% | 0.34 |
| midvol_down | 8.8% | -5.6% | -4.57 |
| midvol_range | 10.1% | +0.9% | 0.24 |
| midvol_up | 13.8% | -2.2% | -0.22 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +5.6%, neighbours median +0.3%, min -7.8%, share profitable 62.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +17.3% → +5.6%, max DD 31.7% → 23.1%, Calmar 0.12 → 0.06.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +5.6% → -11.2%, PF 1.13 → 0.93, max DD 23.1% → 29.0%. Give-back (trades that reached +3% unrealized yet closed negative): 52.6% of 38 → 28.7% of 87; average give-back 13.3% → 7.2%.

Entry-sized only (no mid-trade reductions) for comparison: return +13.1%, max DD 20.3%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 221 OOS trades): terminal growth p05 0.68× / p50 0.95× / p95 1.38×, P(loss) 60.1%, max DD p50 21.6%, p95 36.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.6%, x2: +0.1%, x3: -3.4%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.035 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +1.5%, CAGR +0.3%, Sharpe 0.09, PF 1.04, max DD 13.5%, Calmar 0.02, trades 220, robust 75.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 4H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Most-selected sizing: `vt20/60 crash20/90dh` (selected 1 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -6.3% |
| 2022 | -4.9% |
| 2023 | +1.9% |
| 2024 | +8.5% |
| 2025 | -1.1% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -0.6% | -0.37 |
| highvol_range | 7.9% | -3.6% | -0.97 |
| highvol_up | 11.9% | -2.8% | -0.38 |
| lowvol_down | 11.2% | -13.7% | -4.47 |
| lowvol_range | 12.3% | -7.1% | -1.48 |
| lowvol_up | 14.1% | -1.7% | -0.20 |
| midvol_down | 8.8% | -9.4% | -3.92 |
| midvol_range | 10.1% | +14.6% | 2.88 |
| midvol_up | 13.8% | +28.0% | 2.71 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +29.7%, neighbours median +28.1%, min +14.9%, share profitable 100.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +29.7% → +27.7%, max DD 20.4% → 16.6%, Calmar 0.30 → 0.35.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +29.7% → -2.2%, PF 1.48 → 1.01, max DD 20.4% → 24.1%. Give-back (trades that reached +3% unrealized yet closed negative): 54.1% of 37 → 18.6% of 145; average give-back 14.6% → 5.1%.

Entry-sized only (no mid-trade reductions) for comparison: return +38.6%, max DD 21.8%, Calmar 0.36.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 103 OOS trades): terminal growth p05 0.68× / p50 0.97× / p95 1.48×, P(loss) 55.7%, max DD p50 21.2%, p95 36.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +29.7%, x2: +26.4%, x3: +23.2%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.028 per bar vs observed OOS -0.000 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +16.7%, CAGR +3.6%, Sharpe 0.62, PF 1.63, max DD 8.8%, Calmar 0.41, trades 77, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (ETH-USDT 4H)

Rule grid: 378 combinations (entries × exit brackets). Windows: 9 (8 traded, 2 positive). Most-selected rule: `{'rsi_period': 14, 'rsi_entry': 30.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -2.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 1.5, 'time_stop_days': 2.0, 'bracket': 'trail2'}`. Most-selected sizing: `vt25/20` (selected 1 of 8 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -28.1% |
| 2023 | -1.4% |
| 2024 | -1.4% |
| 2025 | -0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -15.6% | -1.09 |
| highvol_range | 7.9% | -7.1% | -1.51 |
| highvol_up | 11.9% | +0.8% | 0.97 |
| lowvol_down | 11.2% | -5.4% | -2.08 |
| lowvol_range | 12.3% | -3.6% | -0.58 |
| lowvol_up | 14.1% | +1.2% | 1.02 |
| midvol_down | 8.8% | -4.6% | -0.92 |
| midvol_range | 10.1% | -1.6% | -0.13 |
| midvol_up | 13.8% | +0.9% | 1.02 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +15.6%, neighbours median +5.1%, min -26.6%, share profitable 60.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +15.6% → +15.6%, max DD 6.7% → 6.7%, Calmar 0.50 → 0.50.

Exit bracket `trail2` vs none (same rule, fixed replay): return +16.0% → +15.6%, PF 1.48 → 1.47, max DD 6.8% → 6.7%. Give-back (trades that reached +3% unrealized yet closed negative): 4.5% of 22 → 8.7% of 23; average give-back 2.0% → 2.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +16.2%, max DD 6.7%, Calmar 0.52.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 64 OOS trades): terminal growth p05 0.44× / p50 0.70× / p95 1.13×, P(loss) 89.4%, max DD p50 38.6%, p95 58.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.9%, x2: +11.1%, x3: +8.4%

Deflated Sharpe: 768 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.041 per bar vs observed OOS -0.012 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -3.5%, CAGR -0.8%, Sharpe -0.42, PF 0.82, max DD 6.9%, Calmar -0.12, trades 97, robust 60.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 4H)

Rule grid: 84 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Most-selected sizing: `vt25/20 crash10/180dz` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -7.5% |
| 2022 | -5.3% |
| 2023 | -2.5% |
| 2024 | -5.7% |
| 2025 | +3.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +0.0% | 0.00 |
| highvol_range | 7.9% | +11.4% | 2.40 |
| highvol_up | 11.9% | -2.6% | -1.18 |
| lowvol_down | 11.2% | -7.5% | -2.64 |
| lowvol_range | 12.3% | -1.1% | -0.58 |
| lowvol_up | 14.1% | -5.7% | -1.25 |
| midvol_down | 8.8% | -2.7% | -0.90 |
| midvol_range | 10.1% | -1.6% | -0.85 |
| midvol_up | 13.8% | -7.2% | -2.35 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set -16.2%, neighbours median -17.6%, min -28.9%, share profitable 0.0% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return -16.2% → -16.2%, max DD 16.4% → 16.4%, Calmar -0.24 → -0.24.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return -16.2% → -16.2%, PF 0.38 → 0.36, max DD 16.4% → 16.4%. Give-back (trades that reached +3% unrealized yet closed negative): 55.6% of 9 → 30.0% of 10; average give-back 5.5% → 4.8%.

Entry-sized only (no mid-trade reductions) for comparison: return -16.8%, max DD 17.7%, Calmar -0.23.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 66 OOS trades): terminal growth p05 0.63× / p50 0.81× / p95 1.15×, P(loss) 84.7%, max DD p50 26.0%, p95 38.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -16.2%, x2: -17.5%, x3: -18.7%

Deflated Sharpe: 474 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.046 per bar vs observed OOS -0.014 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -6.4%, CAGR -1.5%, Sharpe -0.47, PF 0.78, max DD 9.8%, Calmar -0.16, trades 96, robust 37.5% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 4H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'lookbacks_days': (30, 60, 90), 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `vt25/60` (selected 2 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -6.9% |
| 2022 | -7.5% |
| 2023 | +0.1% |
| 2024 | +2.9% |
| 2025 | +6.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +1.5% | 0.67 |
| highvol_range | 7.9% | +4.1% | 0.92 |
| highvol_up | 11.9% | +8.5% | 1.14 |
| lowvol_down | 11.2% | -8.3% | -4.20 |
| lowvol_range | 12.3% | -6.7% | -1.10 |
| lowvol_up | 14.1% | +3.1% | 0.41 |
| midvol_down | 8.8% | -9.4% | -5.17 |
| midvol_range | 10.1% | +6.8% | 1.06 |
| midvol_up | 13.8% | -3.3% | -0.37 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +77.7%, neighbours median +44.5%, min -8.3%, share profitable 90.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +77.7% → +27.3%, max DD 25.0% → 15.6%, Calmar 0.57 → 0.36.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +77.7% → +60.9%, PF 1.87 → 1.29, max DD 25.0% → 22.5%. Give-back (trades that reached +3% unrealized yet closed negative): 45.5% of 33 → 27.1% of 96; average give-back 13.8% → 7.6%.

Entry-sized only (no mid-trade reductions) for comparison: return +139.0%, max DD 27.3%, Calmar 0.81.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 219 OOS trades): terminal growth p05 0.64× / p50 0.94× / p95 1.43×, P(loss) 59.6%, max DD p50 24.6%, p95 41.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +77.7%, x2: +68.6%, x3: +59.9%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.034 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +0.7%, CAGR +0.2%, Sharpe 0.06, PF 1.03, max DD 13.6%, Calmar 0.01, trades 218, robust 80.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 4H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `fixed25` (selected 2 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -6.3% |
| 2022 | -0.0% |
| 2023 | +3.9% |
| 2024 | +13.8% |
| 2025 | -3.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +1.7% | 0.64 |
| highvol_range | 7.9% | -2.3% | -0.48 |
| highvol_up | 11.9% | +3.5% | 0.50 |
| lowvol_down | 11.2% | -16.2% | -4.63 |
| lowvol_range | 12.3% | -6.8% | -1.34 |
| lowvol_up | 14.1% | +3.1% | 0.51 |
| midvol_down | 8.8% | -9.4% | -3.15 |
| midvol_range | 10.1% | +14.8% | 2.68 |
| midvol_up | 13.8% | +24.1% | 2.34 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +32.5%, neighbours median +30.7%, min +9.5%, share profitable 100.0% over 12 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +32.5% → +18.1%, max DD 15.9% → 14.0%, Calmar 0.42 → 0.28.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +32.5% → +5.9%, PF 1.63 → 1.05, max DD 15.9% → 16.4%. Give-back (trades that reached +3% unrealized yet closed negative): 56.8% of 37 → 19.9% of 146; average give-back 14.3% → 5.1%.

Entry-sized only (no mid-trade reductions) for comparison: return +32.5%, max DD 15.9%, Calmar 0.42.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.71× / p50 1.05× / p95 1.64×, P(loss) 43.1%, max DD p50 19.7%, p95 35.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +32.5%, x2: +30.1%, x3: +27.9%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.033 per bar vs observed OOS 0.004 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +12.0%, CAGR +2.6%, Sharpe 0.49, PF 1.44, max DD 8.4%, Calmar 0.31, trades 78, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (ETH-USDT 6H)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bracket': 'none'}`. Most-selected sizing: `vt25/60 crash15/90dz` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | -6.6% |
| 2022 | -6.5% |
| 2023 | +14.8% |
| 2024 | -1.2% |
| 2025 | +2.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | +0.7% | 0.45 |
| highvol_range | 7.6% | -9.7% | -3.30 |
| highvol_up | 13.8% | -9.1% | -0.89 |
| lowvol_down | 12.1% | +0.3% | 0.23 |
| lowvol_range | 13.0% | -6.9% | -1.46 |
| lowvol_up | 15.1% | +5.1% | 0.70 |
| midvol_down | 8.7% | -1.6% | -1.76 |
| midvol_range | 9.1% | +1.8% | 0.55 |
| midvol_up | 11.2% | +24.4% | 3.01 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +26.3%, neighbours median -, min -, share profitable - over 0 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +26.3% → +9.8%, max DD 31.1% → 23.7%, Calmar 0.18 → 0.09.

Entry-sized only (no mid-trade reductions) for comparison: return +29.5%, max DD 40.0%, Calmar 0.15.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 55 OOS trades): terminal growth p05 0.75× / p50 1.00× / p95 1.39×, P(loss) 50.3%, max DD p50 16.4%, p95 29.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +26.3%, x2: +22.5%, x3: +18.8%

Deflated Sharpe: 391 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.035 per bar vs observed OOS 0.002 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +11.0%, CAGR +2.5%, Sharpe 0.50, PF 2.04, max DD 9.6%, Calmar 0.26, trades 9, robust - → fail (sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, enough_trades, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

- passive reference: always long, no stop, sizing overlays only; excluded from the shortlist

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (ETH-USDT 6H)

Rule grid: 126 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'short_window': 5, 'long_window': 100, 'stop_loss_pct': 0.02, 'bracket': 'time30'}`. Most-selected sizing: `vt25/30 crash10/90dh` (selected 1 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -0.8% |
| 2022 | -5.8% |
| 2023 | +15.7% |
| 2024 | -2.8% |
| 2025 | +1.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -6.8% | -3.17 |
| highvol_range | 7.6% | +2.1% | 0.68 |
| highvol_up | 13.8% | -0.3% | 0.01 |
| lowvol_down | 12.1% | -4.0% | -1.79 |
| lowvol_range | 13.0% | +0.9% | 0.22 |
| lowvol_up | 15.1% | -2.2% | -0.27 |
| midvol_down | 8.7% | -1.6% | -0.59 |
| midvol_range | 9.1% | +1.3% | 0.34 |
| midvol_up | 11.2% | +19.6% | 2.27 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +25.8%, neighbours median +26.7%, min +8.0%, share profitable 100.0% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +25.8% → +15.5%, max DD 21.8% → 18.0%, Calmar 0.25 → 0.19.

Exit bracket `time30` vs none (same rule, fixed replay): return +42.6% → +25.8%, PF 1.45 → 1.22, max DD 18.6% → 21.8%. Give-back (trades that reached +3% unrealized yet closed negative): 59.2% of 49 → 63.3% of 60; average give-back 11.5% → 9.4%.

Entry-sized only (no mid-trade reductions) for comparison: return +33.0%, max DD 21.5%, Calmar 0.32.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 215 OOS trades): terminal growth p05 0.69× / p50 1.04× / p95 1.77×, P(loss) 43.3%, max DD p50 22.7%, p95 38.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +25.8%, x2: +18.1%, x3: +10.8%

Deflated Sharpe: 516 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.064 per bar vs observed OOS 0.005 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=no, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +0.3%, CAGR +0.1%, Sharpe 0.04, PF 1.02, max DD 13.7%, Calmar 0.01, trades 215, robust 100.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 6H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': (14, 30, 60), 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'bracket': 'none'}`. Most-selected sizing: `vt25/60 crash10/180dz` (selected 1 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -10.3% |
| 2022 | -6.8% |
| 2023 | +9.8% |
| 2024 | -2.9% |
| 2025 | +8.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -0.1% | -0.01 |
| highvol_range | 7.6% | -5.3% | -1.68 |
| highvol_up | 13.8% | -7.8% | -0.69 |
| lowvol_down | 12.1% | -4.6% | -2.82 |
| lowvol_range | 13.0% | +1.2% | 0.29 |
| lowvol_up | 15.1% | -5.8% | -0.59 |
| midvol_down | 8.7% | -2.9% | -2.03 |
| midvol_range | 9.1% | +5.6% | 1.35 |
| midvol_up | 11.2% | +19.0% | 2.42 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set -3.8%, neighbours median -2.7%, min -8.8%, share profitable 0.0% over 7 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return -3.8% → -6.1%, max DD 28.2% → 18.9%, Calmar -0.03 → -0.08.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return -3.8% → -11.3%, PF 1.01 → 0.89, max DD 28.2% → 27.6%. Give-back (trades that reached +3% unrealized yet closed negative): 60.0% of 20 → 51.7% of 29; average give-back 12.1% → 9.4%.

Entry-sized only (no mid-trade reductions) for comparison: return +4.2%, max DD 25.2%, Calmar 0.04.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 168 OOS trades): terminal growth p05 0.64× / p50 0.95× / p95 1.47×, P(loss) 58.6%, max DD p50 23.7%, p95 40.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -3.8%, x2: -6.7%, x3: -9.5%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.039 per bar vs observed OOS -0.000 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +4.7%, CAGR +1.1%, Sharpe 0.20, PF 1.10, max DD 8.7%, Calmar 0.12, trades 170, robust 100.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 6H)

Rule grid: 252 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Most-selected sizing: `vt15/60` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | +6.8% |
| 2022 | -15.0% |
| 2023 | +5.9% |
| 2024 | +3.3% |
| 2025 | -0.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -4.5% | -1.99 |
| highvol_range | 7.6% | +0.5% | 0.26 |
| highvol_up | 13.8% | -8.7% | -1.13 |
| lowvol_down | 12.1% | -7.4% | -2.56 |
| lowvol_range | 13.0% | -5.4% | -1.17 |
| lowvol_up | 15.1% | +5.5% | 0.90 |
| midvol_down | 8.7% | -1.6% | -1.12 |
| midvol_range | 9.1% | +1.8% | 0.40 |
| midvol_up | 11.2% | +22.0% | 3.25 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +36.5%, neighbours median +42.4%, min +25.0%, share profitable 100.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +36.5% → +35.3%, max DD 15.5% → 11.9%, Calmar 0.48 → 0.61.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return +36.5% → +14.1%, PF 1.58 → 1.15, max DD 15.5% → 15.6%. Give-back (trades that reached +3% unrealized yet closed negative): 50.0% of 42 → 20.8% of 101; average give-back 11.3% → 6.0%.

Entry-sized only (no mid-trade reductions) for comparison: return +43.7%, max DD 16.4%, Calmar 0.53.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 96 OOS trades): terminal growth p05 0.70× / p50 0.99× / p95 1.43×, P(loss) 52.8%, max DD p50 19.6%, p95 35.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +36.5%, x2: +33.8%, x3: +31.2%

Deflated Sharpe: 642 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.034 per bar vs observed OOS 0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +8.4%, CAGR +1.9%, Sharpe 0.38, PF 1.21, max DD 9.0%, Calmar 0.21, trades 94, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5).

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (ETH-USDT 6H)

Rule grid: 378 combinations (entries × exit brackets). Windows: 9 (7 traded, 3 positive). Most-selected rule: `{'rsi_period': 14, 'rsi_entry': 30.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -1.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 1.5, 'time_stop_days': 2.0, 'bracket': 'tp3'}`. Most-selected sizing: `vt25/20 crash20/90dh` (selected 2 of 7 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.6% |
| 2023 | -0.2% |
| 2024 | -0.7% |
| 2025 | +0.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -0.9% | -0.47 |
| highvol_range | 7.6% | +1.9% | 0.61 |
| highvol_up | 13.8% | +2.8% | 0.64 |
| lowvol_down | 12.1% | -6.5% | -2.82 |
| lowvol_range | 13.0% | -2.2% | -1.00 |
| lowvol_up | 15.1% | -1.0% | -0.22 |
| midvol_down | 8.7% | +0.2% | 0.12 |
| midvol_range | 9.1% | -0.9% | -0.29 |
| midvol_up | 11.2% | +5.2% | 1.75 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +12.8%, neighbours median +4.9%, min -17.2%, share profitable 70.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +12.8% → +12.8%, max DD 11.3% → 11.3%, Calmar 0.25 → 0.25.

Exit bracket `tp3` vs none (same rule, fixed replay): return +9.6% → +12.8%, PF 1.30 → 1.39, max DD 11.3% → 11.3%. Give-back (trades that reached +3% unrealized yet closed negative): 12.5% of 32 → 12.5% of 32; average give-back 2.7% → 2.3%.

Entry-sized only (no mid-trade reductions) for comparison: return +14.9%, max DD 11.3%, Calmar 0.29.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 48 OOS trades): terminal growth p05 0.78× / p50 0.97× / p95 1.23×, P(loss) 56.8%, max DD p50 13.1%, p95 25.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.6%, x2: +4.9%, x3: +2.3%

Deflated Sharpe: 768 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.043 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return -0.6%, CAGR -0.1%, Sharpe -0.05, PF 0.96, max DD 6.0%, Calmar -0.02, trades 60, robust 50.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 6H)

Rule grid: 84 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Most-selected sizing: `vt25/60 ladder` (selected 3 of 9 windows; other choices: fixe).

| Year | OOS return |
|---|---:|
| 2021 | -11.1% |
| 2022 | +3.8% |
| 2023 | -1.2% |
| 2024 | +32.7% |
| 2025 | +13.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -0.5% | -1.18 |
| highvol_range | 7.6% | +0.2% | 0.12 |
| highvol_up | 13.8% | +20.3% | 2.33 |
| lowvol_down | 12.1% | +0.7% | 0.27 |
| lowvol_range | 13.0% | +1.9% | 0.50 |
| lowvol_up | 15.1% | +2.4% | 0.39 |
| midvol_down | 8.7% | -5.1% | -3.75 |
| midvol_range | 9.1% | +3.4% | 1.12 |
| midvol_up | 11.2% | +11.4% | 1.55 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +32.7%, neighbours median +33.6%, min -7.0%, share profitable 87.5% over 8 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +35.4% → +32.7%, max DD 23.4% → 18.4%, Calmar 0.31 → 0.37.

Exit bracket `tp2` vs none (same rule, fixed replay): return +48.8% → +32.7%, PF 1.57 → 1.35, max DD 18.4% → 18.4%. Give-back (trades that reached +3% unrealized yet closed negative): 48.0% of 50 → 41.5% of 65; average give-back 7.3% → 3.9%.

Entry-sized only (no mid-trade reductions) for comparison: return +34.1%, max DD 17.6%, Calmar 0.40.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 66 OOS trades): terminal growth p05 0.91× / p50 1.36× / p95 2.23×, P(loss) 12.1%, max DD p50 13.1%, p95 24.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +32.7%, x2: +30.3%, x3: +24.1%

Deflated Sharpe: 474 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.022 → DSR 0.13.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +16.3%, CAGR +3.6%, Sharpe 0.87, PF 1.66, max DD 8.7%, Calmar 0.41, trades 82, robust 87.5% → fail (calmar_gt_0_5, positive_in_4_of_5_years).

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 6H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': (30, 60, 90), 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'none'}`. Most-selected sizing: `vt25/60 crash10/180dz` (selected 1 of 9 windows; other choices: vt25).

| Year | OOS return |
|---|---:|
| 2021 | -10.3% |
| 2022 | -6.7% |
| 2023 | +7.8% |
| 2024 | +4.9% |
| 2025 | +8.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | +0.1% | 0.06 |
| highvol_range | 7.6% | -5.9% | -1.74 |
| highvol_up | 13.8% | -6.2% | -0.48 |
| lowvol_down | 12.1% | -4.4% | -2.59 |
| lowvol_range | 13.0% | -0.4% | -0.04 |
| lowvol_up | 15.1% | -4.6% | -0.44 |
| midvol_down | 8.7% | -3.7% | -2.29 |
| midvol_range | 9.1% | +7.2% | 1.61 |
| midvol_up | 11.2% | +24.2% | 2.89 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set -6.6%, neighbours median -4.4%, min -11.5%, share profitable 20.0% over 10 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return -6.6% → -10.7%, max DD 31.8% → 24.1%, Calmar -0.05 → -0.11.

Exit bracket `none (selected); comparison shows trail1` vs none (same rule, fixed replay): return -6.6% → -20.5%, PF 0.95 → 0.82, max DD 31.8% → 29.4%. Give-back (trades that reached +3% unrealized yet closed negative): 63.6% of 22 → 20.3% of 59; average give-back 11.7% → 5.5%.

Entry-sized only (no mid-trade reductions) for comparison: return +13.4%, max DD 21.2%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 168 OOS trades): terminal growth p05 0.67× / p50 1.02× / p95 1.60×, P(loss) 47.8%, max DD p50 22.1%, p95 39.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -6.6%, x2: -9.6%, x3: -12.5%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.003 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=no

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +6.7%, CAGR +1.5%, Sharpe 0.28, PF 1.15, max DD 8.7%, Calmar 0.17, trades 170, robust 40.0% → fail (pf_gt_1_2, sharpe_gt_0_7, calmar_gt_0_5, positive_in_4_of_5_years, robust_pm30pct).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 6H)

Rule grid: 756 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'bracket': 'time30'}`. Most-selected sizing: `vt15/60` (selected 1 of 9 windows; other choices: vt20).

| Year | OOS return |
|---|---:|
| 2021 | +6.8% |
| 2022 | -14.9% |
| 2023 | +11.2% |
| 2024 | +3.1% |
| 2025 | -0.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.4% | -4.6% | -2.03 |
| highvol_range | 7.6% | +2.2% | 1.01 |
| highvol_up | 13.8% | -7.2% | -0.91 |
| lowvol_down | 12.1% | -8.3% | -2.92 |
| lowvol_range | 13.0% | -3.4% | -0.63 |
| lowvol_up | 15.1% | +7.0% | 1.10 |
| midvol_down | 8.7% | -3.6% | -2.44 |
| midvol_range | 9.1% | +3.4% | 0.63 |
| midvol_up | 11.2% | +21.7% | 3.12 |

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters and the chosen sizing over every out-of-sample test window, no re-selection): selected set +48.4%, neighbours median +45.4%, min +30.1%, share profitable 100.0% over 12 neighbours.

Drawdown ladder (chosen sizing with vs without the ladder, fixed replay): return +48.4% → +41.1%, max DD 15.5% → 11.9%, Calmar 0.62 → 0.70.

Exit bracket `time30` vs none (same rule, fixed replay): return +46.3% → +48.4%, PF 1.82 → 1.80, max DD 15.5% → 15.5%. Give-back (trades that reached +3% unrealized yet closed negative): 43.2% of 37 → 42.5% of 40; average give-back 11.2% → 10.4%.

Entry-sized only (no mid-trade reductions) for comparison: return +60.3%, max DD 15.5%, Calmar 0.74.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 87 OOS trades): terminal growth p05 0.73× / p50 1.04× / p95 1.52×, P(loss) 42.8%, max DD p50 18.1%, p95 33.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +48.4%, x2: +45.6%, x3: +42.7%

Deflated Sharpe: 1146 trials (rules + sizing variants in the last train window), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.004 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, positive_in_4_of_5_years=no, enough_trades=yes, robust_pm30pct=yes

Fixed policy sizing `vt10/30 crash15/90dh ladder`: return +9.5%, CAGR +2.1%, Sharpe 0.44, PF 1.26, max DD 8.8%, Calmar 0.24, trades 86, robust 100.0% → fail (sharpe_gt_0_7, calmar_gt_0_5).

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## Owner decisions (nothing below is decided by this report)

- **Yearly-consistency gate.** The gate counts calendar years of the stitched out-of-sample curve; the first and last are partial and 2022 was a bear year, so 25 of 28 configurations miss it. Keep it as specified, or redefine it on rolling 12-month windows (e.g. positive in ≥ 75 % of rolling years)? The report keeps the specification.
- **Sizing proposal mechanism.** Two mechanisms are shown: train-selected sizing (Calmar under a 10 % train drawdown cap, noisy across windows) and one fixed policy (10 % vol target, 15 %/90-day crash filter, drawdown ladder). Which one is the 'proposed sizing' for the gates going forward? The report applies the gates to both and shortlists both.
- **Sequencing.** Nothing passed. Sprint 3 (exchange-side stops in demo) does not depend on this result and can proceed; Sprint 2c (research only, proposed in the executive summary) is the next research step. Approve Sprint 2c, reorder, or stop research here?
- **Binance public data.** Funding and open-interest history come from Binance's public endpoints and bulk files under its API terms, used for internal research only and never traded on. Acceptable as a standing research source (it needs a nightly top-up like the OKX series)?
- **Timeframes.** 1H and 1D were not re-run in Sprint 2b (fee drag / too few trades in Sprint 2). Confirm 4H/6H as the research timeframes, or ask for a 1H/1D re-run with sizing.
- **Paper fleet controls.** If a paper fleet starts, should it include the `hold` + sizing references as controls so the timing rules are judged against them?

## Method notes and caveats

- Engine: `research/engine.py` — next-bar-open execution, intrabar stop with conservative gap fills, fees and slippage per side, fixed ATR stop at entry, optional take-profit / trailing stop (effective from the bar after the high that armed it) / time stop; sizing by a per-bar fraction of equity decided one bar earlier; reduce-only mid-trade adjustments; drawdown ladder on the strategy's own equity. With every overlay off the engine is bit-for-bit the Sprint 2 engine, which is parity-tested against `app/backtest/simulator.py`.
- Vol targeting uses the trailing realized vol of closes (past bars only); the crash filter uses the trailing rolling peak of closes; both are tested for look-ahead. 6H bars are resampled from stored 1H bars on the UTC grid, complete bars only.
- Two-stage selection (rule, then sizing) uses the train slice only; the purge gap removes boundary leakage; test slices are stitched and each window restarts from the same capital and flat. Robustness, the sizing sweep, the ladder/bracket comparisons and the slippage stress are FIXED replays over the same test windows, so they describe sensitivity, not new selections.
- Yearly windows are calendar years of the stitched out-of-sample curve; the first and last years are partial, and 2022 (a bear year for long-only rules) sits inside the span, so the 4-of-5 yearly gate is strict by construction.
- 1H and 1D were not re-run: Sprint 2 showed 1H rules paying 5–24 %/yr in fees and 1D grids rarely producing enough trades; 4H and 6H (resampled from 1H) are the working timeframes.
- Deflated Sharpe follows Bailey & López de Prado (2014) over every rule and sizing variant tried in the last train window.
- The Monte Carlo bootstraps equity-level trade contributions (trade return × size fraction); fractional sizing makes paths less extreme than Sprint 2's all-in bootstrap.
- Positioning features (S5) come from Binance public history aligned as-of onto OKX candles (a candle sees only values stamped at or before its open); where a series is missing the filter passes. Coverage is reported above. OKX keeps collecting its own series for the forward period.
- The event-driven cross-check only runs when the selected rule has no bracket, because the reviewed strategy contract carries a fixed stop only (exchange-side brackets are Sprint 3 scope); it runs at full size, so it checks the trade sequence, not the sized equity.
- Portfolios compound each sleeve's out-of-sample daily returns in its own capital bucket (no cross-sleeve rebalancing); equal-risk weights use the sleeves' realized out-of-sample vol (mildly in-sample). The portfolio ladder scales the next day's return by the previous day's multiplier.
- Every number is a simulation on historical public data and proves nothing about the future.
