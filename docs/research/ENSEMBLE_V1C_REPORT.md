# Ensemble v1c — regime gates, portfolio sizing and turnover (walk-forward, SIMULATION ONLY)

Generated 2026-10-20 16:18 UTC by `scripts/run_research_v1c.py`. Data: PUBLIC OKX spot candles from the Parquet lake (BTC-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); BTC-USDT 6H: 2019-12-29->2026-10-20 (9949 bars); ETH-USDT 4H: 2019-12-16->2026-10-20 (14999 bars); ETH-USDT 6H: 2019-12-29->2026-10-20 (9949 bars)); 6H bars resampled from 1H (UTC-aligned). Positioning features: binance (public, research only). Costs: fee 0.10% per side + slippage 0.050% per side. Long-only spot, no leverage. Walk-forward: train 540d → purge 7d → test 180d, rolling; the trading rule (entries × exit bracket) is selected on the train slice by sharpe with ≥20 train trades at full size, exactly as in Sprint 2b; the regime model (`hmm3 bear>=0.5 gate`, 3 states on log return + log 7-day realized vol) is fitted on the train slice of every window and applied forward as an ENTRY gate only; sizing is the fixed a-priori policy `vt10/30 crash15/90dh ladder` for every candidate (planner decision 2; the train-selected sizing of Sprint 2b is shown only as a comparison). S0 no-trade filter: S0 vol×3 spread p98 gap3 FOMC±6/6h. Brackets tried: ['none', 'tp2', 'trail1', 'time30']. Holdout: last 12 months (2025-10-20->2026-10-20), evaluated once and only for candidates that passed walk-forward.

**Nothing here authorizes paper, demo or live trading.** A passing candidate is a hypothesis for the forward paper fleet (Sprint 5), not a strategy to deploy. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we did.** We kept every entry rule from Sprint 2 exactly as it was and changed only when it is allowed to trade and how much: a market-regime model (a 3-state hidden Markov model on returns and volatility, fitted only on past data inside every walk-forward window) either blocks new entries in the bear state or shrinks them to a quarter size; a scheduled-event filter (FOMC days) and the no-trade filter block entries around shocks; sizing is one fixed, pre-declared policy (`vt10/30 crash15/90dh ladder`); lower-turnover clocks (weekly, daily-entry, hysteresis) cut fees; the positioning filter was re-tested with a 7–14-day funding window; and the sleeves were also sized jointly as one portfolio against a 15 % drawdown budget. 108 configurations (gate, none, scale) over 2019-12-16->2026-10-20, after fees and slippage; the last 12 months stayed untouched except for configurations that passed.
- **Result.** 4 of 108 configurations passed every Sprint 2c gate on the walk-forward at the fixed policy sizing: S2 on BTC-USDT 4H (hmm3 bear>=0.5 gate), S2+S5 on BTC-USDT 4H (hmm3 bear>=0.5 gate), S2+S5s on BTC-USDT 4H (hmm3 bear>=0.5 gate), S1+S5 on BTC-USDT 6H (no regime gate). The untouched 12-month holdout then confirmed 1 of them (S1+S5 on BTC-USDT 6H (no regime gate): +2.3%, PF 1.48, 32 trades) and contradicted 3 (S2 on BTC-USDT 4H (hmm3 bear>=0.5 gate): -4.9%, PF 0.28, 21 trades; S2+S5 on BTC-USDT 4H (hmm3 bear>=0.5 gate): -3.0%, PF 0.51, 18 trades; S2+S5s on BTC-USDT 4H (hmm3 bear>=0.5 gate): -4.4%, PF 0.29, 19 trades). Only the confirmed configurations are candidates for the forward paper fleet; a walk-forward pass that the holdout rejects is treated as selection luck among 108 configurations, not as edge.
- **Best so far.** S1+S5 on BTC-USDT 6H with `no regime gate` and exit `none`: out-of-sample +5.3% per year with a worst drawdown of 8.8% (Sharpe 0.86, Calmar 0.60, 139 trades, 78.0% of rolling 12-month windows positive). On the untouched holdout it made +2.3% with a 3.9% drawdown (PF 1.48, 32 trades) — consistent with the walk-forward. Plain buy-and-hold over the same months made +30.5% per year with a 77.0% drawdown (Calmar 0.40). Simply staying long BTC with the same policy sizing and no timing rule made +2.6% per year with a 8.0% drawdown (Calmar 0.33); on the holdout -4.0% with a 5.5% drawdown.
- **What the regime gate bought us.** Across the 48 rules run with and without the gate, blocking entries in the bear state moved the median 2022 return from -2.4% to -1.9%, the median worst drawdown from 9.1% to 9.0%, the median yearly return from +2.6% to +1.9% and the median Calmar from 0.31 to 0.18; quarter-sizing in the bear state gave Calmar 0.27. In other words, the gate cost more return than it saved: the bear state also contains the recoveries these rules need.
- **Portfolio, turnover and next step.** The best portfolio (S1+S2+S4 x BTC+ETH — jointly sized, vol target 15%, ladder 7.5/15) made +10.9% per year with a 13.2% drawdown (Sharpe 0.82, Calmar 0.83). The lower-turnover clocks cut the median fee drag from 1.1% to 0.7% per year and moved the median Calmar from 0.29 to 0.22. 4 configuration(s) passed the walk-forward gates but only 1 survived the untouched 12-month holdout (S2 BTC-USDT 4H [gate] holdout -4.9% PF 0.28; S2+S5 BTC-USDT 4H [gate] holdout -3.0% PF 0.51; S2+S5s BTC-USDT 4H [gate] holdout -4.4% PF 0.29; S1+S5 BTC-USDT 6H [none] holdout +2.3% PF 1.48). A walk-forward pass that the holdout rejects is selection luck among 108 configurations, not edge. Binding walk-forward gates: calmar_gt_0_5 (94/108), sharpe_gt_0_7 (93/108), rolling_12m_75pct_positive (90/108). On 4 of 4 series the best long-only timing rule beat vol-targeted holding by more than 0.1 Calmar on the walk-forward, and the controls lost on the holdout (hold+policy BTC-USDT 4H holdout -4.3%; hold+policy BTC-USDT 6H holdout -4.0%; hold+policy ETH-USDT 4H holdout -2.6%; hold+policy ETH-USDT 6H holdout -2.9%), so the honest, numbers-backed statement is narrower than 'timing never beats holding': the edge of long-only timing on BTC/ETH spot is REAL BUT THIN AND FRAGILE — of 108 configurations exactly 1 survived both the walk-forward and the holdout (S1+S5 BTC-USDT 6H [none] OOS CAGR +5.3% / max DD 8.8% / Calmar 0.60, holdout +2.3%), and the risk-managed return is a few percent a year at under 10 % drawdown. One surviving sleeve is not an ensemble. Per the Sprint 2c acceptance clause the Phase 7/8 product therefore stays 'risk-managed exposure + news brake' (hold with the policy sizing and the no-trade gates, the news agent as a brake), the confirmed sleeve(s) and the jointly sized portfolio run forward in the paper fleet next to the controls as the honest tiebreaker, and the Phase 9 long/short design study becomes the research priority.

## Gates (Sprint 2b item 8 + planner decision 1, at the fixed policy sizing)

- Out-of-sample profit factor > 1.2 after costs
- Max drawdown < 20%
- Sharpe > 0.7; Calmar (CAGR / max drawdown) > 0.5
- Yearly consistency v2: ≥ 75% of rolling 12-month windows (sampled every 30 days) positive AND no calendar year (≥ 60 days of data) worse than -10%
- At least 30 out-of-sample trades
- ≥ 50% of ±30% parameter neighbours stay profitable (replayed with the same regime gate and sizing)
- Deflated Sharpe reported (no threshold)

## Summary (fixed policy sizing; one row per candidate × series × regime mode)

| Candidate | Series | Regime | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Alloc. | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Verdict | Holdout (12m) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| hold | BTC-USDT 4H | no regime gate | none | +14.8% | +3.2% | 0.59 | 2.88 | 7.2% | 0.45 | 9 | 9.6% | 0.1% | 70.7% | -4.7% | - | 0.89 | fail | -4.3% / PF 0.00 / 1 tr ✗ |
| S1 | BTC-USDT 4H | no regime gate | none | +9.4% | +2.1% | 0.37 | 1.23 | 8.3% | 0.25 | 184 | 8.5% | 1.4% | 61.0% | -4.4% | 75.0% | 0.04 | fail | untouched |
| S1 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +7.0% | +1.6% | 0.29 | 1.18 | 10.5% | 0.15 | 151 | 8.2% | 1.2% | 65.9% | -2.7% | 100.0% | 0.06 | fail | untouched |
| S1 | BTC-USDT 4H | hmm3 bear>=0.5 scale0.25 | none | +7.9% | +1.8% | 0.42 | 1.25 | 6.5% | 0.27 | 184 | 5.1% | 1.2% | 70.7% | -2.8% | 62.5% | 0.05 | fail | untouched |
| S2 | BTC-USDT 4H | no regime gate | none | +14.9% | +3.3% | 0.57 | 1.46 | 8.7% | 0.38 | 85 | 7.6% | 0.8% | 61.0% | -4.6% | 100.0% | 0.11 | fail | untouched |
| S2 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +24.7% | +5.2% | 0.86 | 1.94 | 6.5% | 0.80 | 69 | 7.8% | 0.7% | 80.5% | -3.2% | 100.0% | 0.19 | **PASS** | -4.9% / PF 0.28 / 21 tr ✗ |
| S2 | BTC-USDT 4H | hmm3 bear>=0.5 scale0.25 | none | +8.6% | +1.9% | 0.45 | 1.36 | 6.2% | 0.31 | 85 | 5.2% | 0.7% | 80.5% | -3.1% | 100.0% | 0.07 | fail | untouched |
| S4 | BTC-USDT 4H | no regime gate | none | +5.0% | +1.1% | 0.27 | 1.16 | 9.9% | 0.11 | 109 | 3.7% | 1.3% | 61.0% | -5.9% | 87.5% | 0.13 | fail | untouched |
| S4 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +5.1% | +1.2% | 0.30 | 1.19 | 9.0% | 0.13 | 84 | 3.0% | 1.0% | 65.9% | -3.8% | 87.5% | 0.23 | fail | untouched |
| S4 | BTC-USDT 4H | hmm3 bear>=0.5 scale0.25 | none | +4.3% | +1.0% | 0.26 | 1.16 | 10.2% | 0.10 | 109 | 3.0% | 1.1% | 73.2% | -4.0% | 87.5% | 0.12 | fail | untouched |
| S1w | BTC-USDT 4H | no regime gate | none | +4.8% | +1.1% | 0.20 | 1.14 | 9.6% | 0.11 | 95 | 9.0% | 1.0% | 63.4% | -4.1% | 62.5% | 0.03 | fail | untouched |
| S1w | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +21.5% | +4.6% | 0.74 | 1.70 | 10.2% | 0.45 | 84 | 9.0% | 0.7% | 78.0% | -4.0% | 62.5% | 0.28 | fail | untouched |
| S1d | BTC-USDT 4H | no regime gate | none | +7.4% | +1.7% | 0.30 | 1.17 | 10.0% | 0.17 | 132 | 7.4% | 1.2% | 61.0% | -6.7% | 100.0% | 0.03 | fail | untouched |
| S1d | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +2.0% | +0.5% | 0.11 | 1.06 | 10.4% | 0.04 | 124 | 6.5% | 1.2% | 46.3% | -5.8% | 100.0% | 0.01 | fail | untouched |
| S2d | BTC-USDT 4H | no regime gate | none | +6.8% | +1.5% | 0.30 | 1.24 | 9.2% | 0.16 | 86 | 7.4% | 0.7% | 61.0% | -6.1% | 100.0% | 0.02 | fail | untouched |
| S2d | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +8.9% | +2.0% | 0.37 | 1.33 | 8.3% | 0.24 | 82 | 7.2% | 0.7% | 61.0% | -5.3% | 100.0% | 0.03 | fail | untouched |
| S4d | BTC-USDT 4H | no regime gate | none | +11.6% | +2.6% | 0.60 | 1.32 | 7.0% | 0.37 | 102 | 3.3% | 1.2% | 75.6% | -3.6% | 100.0% | 0.28 | fail | untouched |
| S4d | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +9.5% | +2.1% | 0.52 | 1.26 | 5.3% | 0.40 | 108 | 3.2% | 1.4% | 61.0% | -2.4% | 100.0% | 0.48 | fail | untouched |
| S1h | BTC-USDT 4H | no regime gate | none | +16.9% | +3.7% | 0.64 | 1.53 | 7.8% | 0.47 | 104 | 7.4% | 1.1% | 85.4% | -1.0% | 100.0% | 0.08 | fail | untouched |
| S1h | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +7.4% | +1.7% | 0.31 | 1.20 | 11.2% | 0.15 | 131 | 6.5% | 1.5% | 75.6% | -1.5% | 90.0% | 0.04 | fail | untouched |
| S1+S5 | BTC-USDT 4H | no regime gate | none | +12.1% | +2.7% | 0.44 | 1.33 | 8.3% | 0.32 | 179 | 8.8% | 1.4% | 63.4% | -4.4% | 100.0% | 0.12 | fail | untouched |
| S1+S5 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +18.2% | +3.9% | 0.65 | 1.48 | 9.8% | 0.40 | 153 | 8.0% | 1.3% | 73.2% | -2.7% | 80.0% | 0.29 | fail | untouched |
| S1+S5s | BTC-USDT 4H | no regime gate | none | +11.0% | +2.4% | 0.42 | 1.29 | 9.2% | 0.26 | 174 | 8.3% | 1.4% | 53.7% | -5.3% | 100.0% | 0.05 | fail | untouched |
| S1+S5s | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +2.3% | +0.5% | 0.12 | 1.06 | 11.6% | 0.04 | 143 | 7.9% | 1.2% | 46.3% | -2.7% | 100.0% | 0.04 | fail | untouched |
| S2+S5 | BTC-USDT 4H | no regime gate | none | +16.2% | +3.5% | 0.61 | 1.52 | 8.7% | 0.40 | 83 | 7.6% | 0.8% | 61.0% | -4.6% | 100.0% | 0.42 | fail | untouched |
| S2+S5 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +24.8% | +5.2% | 0.87 | 1.94 | 6.5% | 0.80 | 69 | 7.8% | 0.7% | 80.5% | -3.2% | 100.0% | 0.49 | **PASS** | -3.0% / PF 0.51 / 18 tr ✗ |
| S2+S5s | BTC-USDT 4H | no regime gate | none | +12.6% | +2.8% | 0.49 | 1.41 | 8.5% | 0.33 | 84 | 7.6% | 0.8% | 61.0% | -6.1% | 100.0% | 0.21 | fail | untouched |
| S2+S5s | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +21.2% | +4.5% | 0.78 | 1.85 | 6.6% | 0.69 | 68 | 7.4% | 0.7% | 75.6% | -3.2% | 100.0% | 0.27 | **PASS** | -4.4% / PF 0.29 / 19 tr ✗ |
| hold | BTC-USDT 6H | no regime gate | none | +11.8% | +2.6% | 0.49 | 2.37 | 8.0% | 0.33 | 9 | 9.8% | 0.1% | 73.2% | -4.8% | - | 0.84 | fail | -4.0% / PF 0.00 / 1 tr ✗ |
| S1 | BTC-USDT 6H | no regime gate | none | +15.9% | +3.5% | 0.58 | 1.40 | 9.2% | 0.38 | 155 | 8.6% | 1.3% | 68.3% | -4.9% | 100.0% | 0.05 | fail | untouched |
| S1 | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +17.5% | +3.8% | 0.63 | 1.42 | 11.4% | 0.33 | 146 | 8.8% | 1.2% | 73.2% | -4.2% | 100.0% | 0.06 | fail | untouched |
| S1 | BTC-USDT 6H | hmm3 bear>=0.5 scale0.25 | none | +9.4% | +2.1% | 0.43 | 1.27 | 7.7% | 0.27 | 155 | 5.6% | 1.1% | 65.9% | -3.8% | 62.5% | 0.02 | fail | untouched |
| S2 | BTC-USDT 6H | no regime gate | none | +3.0% | +0.7% | 0.16 | 1.10 | 10.0% | 0.07 | 69 | 6.3% | 0.7% | 58.5% | -3.5% | 100.0% | 0.02 | fail | untouched |
| S2 | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +5.1% | +1.2% | 0.28 | 1.22 | 9.9% | 0.12 | 48 | 4.9% | 0.4% | 56.1% | -1.7% | 100.0% | 0.01 | fail | untouched |
| S2 | BTC-USDT 6H | hmm3 bear>=0.5 scale0.25 | none | +1.4% | +0.3% | 0.10 | 1.07 | 8.2% | 0.04 | 69 | 4.4% | 0.5% | 58.5% | -3.3% | 90.0% | 0.01 | fail | untouched |
| S4 | BTC-USDT 6H | no regime gate | trail1 | +10.6% | +2.4% | 0.52 | 1.36 | 5.8% | 0.41 | 92 | 4.1% | 1.0% | 82.9% | -3.4% | 62.5% | 0.09 | fail | untouched |
| S4 | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +11.1% | +2.5% | 0.58 | 1.41 | 7.3% | 0.34 | 75 | 3.3% | 0.8% | 70.7% | -3.5% | 87.5% | 0.24 | fail | untouched |
| S4 | BTC-USDT 6H | hmm3 bear>=0.5 scale0.25 | trail1 | +7.3% | +1.6% | 0.43 | 1.30 | 6.1% | 0.27 | 92 | 3.0% | 0.8% | 78.0% | -3.5% | 50.0% | 0.07 | fail | untouched |
| S1w | BTC-USDT 6H | no regime gate | none | +11.1% | +2.5% | 0.43 | 1.37 | 10.5% | 0.24 | 75 | 8.6% | 0.7% | 73.2% | -4.6% | 75.0% | 0.01 | fail | untouched |
| S1w | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | -2.0% | -0.5% | -0.05 | 0.98 | 13.3% | -0.04 | 107 | 7.8% | 0.8% | 65.9% | -8.0% | 14.3% | 0.00 | fail | untouched |
| S1d | BTC-USDT 6H | no regime gate | none | +13.7% | +3.0% | 0.53 | 1.37 | 10.3% | 0.30 | 137 | 7.4% | 1.1% | 75.6% | -4.3% | 100.0% | 0.03 | fail | untouched |
| S1d | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +8.8% | +2.0% | 0.36 | 1.21 | 11.0% | 0.18 | 134 | 7.4% | 1.1% | 78.0% | -3.9% | 100.0% | 0.01 | fail | untouched |
| S2d | BTC-USDT 6H | no regime gate | none | +5.0% | +1.1% | 0.24 | 1.16 | 11.0% | 0.10 | 66 | 6.8% | 0.6% | 63.4% | -3.6% | 100.0% | 0.03 | fail | untouched |
| S2d | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +6.3% | +1.4% | 0.33 | 1.27 | 9.0% | 0.16 | 50 | 5.4% | 0.5% | 56.1% | -2.1% | 100.0% | 0.01 | fail | untouched |
| S4d | BTC-USDT 6H | no regime gate | none | -0.1% | -0.0% | 0.01 | 1.01 | 10.3% | -0.00 | 88 | 3.7% | 1.0% | 53.7% | -3.8% | 100.0% | 0.03 | fail | untouched |
| S4d | BTC-USDT 6H | hmm3 bear>=0.5 gate | trail1 | +1.7% | +0.4% | 0.12 | 1.08 | 8.7% | 0.04 | 77 | 2.7% | 0.8% | 65.9% | -4.0% | 62.5% | 0.05 | fail | untouched |
| S1h | BTC-USDT 6H | no regime gate | none | +15.0% | +3.3% | 0.57 | 1.38 | 7.5% | 0.44 | 127 | 7.9% | 1.3% | 75.6% | -5.2% | 100.0% | 0.05 | fail | untouched |
| S1h | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +7.1% | +1.6% | 0.32 | 1.20 | 11.6% | 0.14 | 109 | 5.3% | 1.1% | 63.4% | -5.0% | 100.0% | 0.02 | fail | untouched |
| S1+S5 | BTC-USDT 6H | no regime gate | none | +24.7% | +5.3% | 0.86 | 1.68 | 8.8% | 0.60 | 139 | 8.4% | 1.2% | 78.0% | -5.7% | 100.0% | 0.23 | **PASS** | +2.3% / PF 1.48 / 32 tr ✓ |
| S1+S5 | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +14.7% | +3.2% | 0.54 | 1.41 | 7.6% | 0.42 | 139 | 8.1% | 1.3% | 70.7% | -5.0% | 100.0% | 0.09 | fail | untouched |
| S1+S5s | BTC-USDT 6H | no regime gate | none | +16.4% | +3.6% | 0.63 | 1.46 | 8.3% | 0.43 | 141 | 8.1% | 1.2% | 78.0% | -5.1% | 100.0% | 0.03 | fail | untouched |
| S1+S5s | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +9.0% | +2.0% | 0.36 | 1.26 | 9.1% | 0.22 | 135 | 7.8% | 1.2% | 68.3% | -5.2% | 100.0% | 0.02 | fail | untouched |
| S2+S5 | BTC-USDT 6H | no regime gate | none | +6.0% | +1.4% | 0.29 | 1.23 | 10.1% | 0.13 | 57 | 6.4% | 0.5% | 61.0% | -3.5% | 100.0% | 0.15 | fail | untouched |
| S2+S5 | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +8.0% | +1.8% | 0.42 | 1.46 | 10.0% | 0.18 | 35 | 4.8% | 0.3% | 63.4% | -1.7% | 100.0% | 0.07 | fail | untouched |
| S2+S5s | BTC-USDT 6H | no regime gate | none | +6.1% | +1.4% | 0.29 | 1.24 | 10.2% | 0.14 | 56 | 6.3% | 0.5% | 61.0% | -3.5% | 100.0% | 0.09 | fail | untouched |
| S2+S5s | BTC-USDT 6H | hmm3 bear>=0.5 gate | none | +8.2% | +1.8% | 0.43 | 1.47 | 9.8% | 0.19 | 35 | 4.8% | 0.3% | 63.4% | -1.7% | 100.0% | 0.03 | fail | untouched |
| hold | ETH-USDT 4H | no regime gate | none | +7.8% | +1.8% | 0.38 | 1.83 | 8.6% | 0.20 | 9 | 6.2% | 0.1% | 63.4% | -4.1% | - | 0.78 | fail | -2.6% / PF 0.00 / 1 tr ✗ |
| S1 | ETH-USDT 4H | no regime gate | tp2 | -0.1% | -0.0% | 0.03 | 1.01 | 13.4% | -0.00 | 225 | 5.8% | 1.4% | 31.7% | -4.5% | 25.0% | 0.02 | fail | untouched |
| S1 | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +5.6% | +1.3% | 0.25 | 1.18 | 11.5% | 0.11 | 150 | 4.9% | 1.1% | 39.0% | -3.0% | 87.5% | 0.10 | fail | untouched |
| S1 | ETH-USDT 4H | hmm3 bear>=0.5 scale0.25 | tp2 | +4.6% | +1.0% | 0.24 | 1.13 | 10.1% | 0.10 | 225 | 4.2% | 1.3% | 53.7% | -2.0% | 50.0% | 0.06 | fail | untouched |
| S2 | ETH-USDT 4H | no regime gate | none | +16.7% | +3.6% | 0.62 | 1.63 | 8.8% | 0.41 | 77 | 5.1% | 0.5% | 63.4% | -0.6% | 100.0% | 0.11 | fail | untouched |
| S2 | ETH-USDT 4H | hmm3 bear>=0.5 gate | time30 | +3.2% | +0.7% | 0.16 | 1.10 | 10.9% | 0.07 | 86 | 4.6% | 0.6% | 70.7% | -0.8% | 80.0% | 0.02 | fail | untouched |
| S2 | ETH-USDT 4H | hmm3 bear>=0.5 scale0.25 | none | +23.8% | +5.0% | 0.91 | 2.05 | 8.8% | 0.57 | 77 | 4.3% | 0.5% | 73.2% | -0.6% | 100.0% | 0.28 | fail | untouched |
| S4 | ETH-USDT 4H | no regime gate | none | -6.5% | -1.5% | -0.45 | 0.76 | 11.0% | -0.14 | 81 | 1.8% | 0.6% | 19.5% | -2.3% | 37.5% | 0.00 | fail | untouched |
| S4 | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +3.1% | +0.7% | 0.20 | 1.13 | 7.2% | 0.10 | 90 | 2.3% | 0.7% | 41.5% | -2.0% | 75.0% | 0.00 | fail | untouched |
| S4 | ETH-USDT 4H | hmm3 bear>=0.5 scale0.25 | none | -3.1% | -0.7% | -0.21 | 0.87 | 8.7% | -0.08 | 81 | 1.6% | 0.6% | 36.6% | -1.7% | 50.0% | 0.00 | fail | untouched |
| S1w | ETH-USDT 4H | no regime gate | none | +13.3% | +2.9% | 0.51 | 1.51 | 9.6% | 0.30 | 79 | 6.4% | 0.5% | 53.7% | -1.0% | 87.5% | 0.15 | fail | untouched |
| S1w | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | -3.0% | -0.7% | -0.10 | 0.93 | 14.9% | -0.05 | 92 | 5.3% | 0.6% | 36.6% | -5.0% | 87.5% | 0.01 | fail | untouched |
| S1d | ETH-USDT 4H | no regime gate | none | +10.1% | +2.2% | 0.44 | 1.25 | 9.6% | 0.23 | 154 | 5.2% | 1.0% | 46.3% | -2.3% | 87.5% | 0.11 | fail | untouched |
| S1d | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +10.9% | +2.4% | 0.46 | 1.34 | 7.9% | 0.30 | 113 | 5.7% | 0.8% | 46.3% | -2.3% | 87.5% | 0.19 | fail | untouched |
| S2d | ETH-USDT 4H | no regime gate | none | +18.0% | +3.9% | 0.66 | 1.64 | 8.3% | 0.47 | 76 | 5.2% | 0.5% | 61.0% | -1.4% | 100.0% | 0.15 | fail | untouched |
| S2d | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +9.3% | +2.1% | 0.40 | 1.22 | 8.3% | 0.25 | 108 | 5.0% | 0.8% | 58.5% | -1.4% | 100.0% | 0.07 | fail | untouched |
| S4d | ETH-USDT 4H | no regime gate | none | -5.8% | -1.4% | -0.48 | 0.76 | 8.2% | -0.16 | 76 | 1.5% | 0.6% | 24.4% | -3.1% | 50.0% | 0.00 | fail | untouched |
| S4d | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +0.2% | +0.1% | 0.03 | 1.02 | 7.5% | 0.01 | 90 | 2.1% | 0.7% | 46.3% | -2.3% | 87.5% | 0.00 | fail | untouched |
| S1h | ETH-USDT 4H | no regime gate | none | +17.6% | +3.8% | 0.65 | 1.43 | 7.8% | 0.49 | 114 | 5.0% | 1.0% | 65.9% | -0.9% | 90.0% | 0.30 | fail | untouched |
| S1h | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +17.7% | +3.8% | 0.67 | 1.75 | 6.1% | 0.63 | 79 | 4.7% | 0.7% | 65.9% | -1.6% | 90.0% | 0.35 | fail | untouched |
| S1+S5 | ETH-USDT 4H | no regime gate | none | +0.9% | +0.2% | 0.06 | 1.04 | 13.6% | 0.01 | 204 | 5.7% | 1.3% | 34.1% | -4.6% | 80.0% | 0.09 | fail | untouched |
| S1+S5 | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +2.3% | +0.5% | 0.12 | 1.07 | 11.1% | 0.05 | 168 | 4.8% | 1.3% | 39.0% | -3.0% | 90.0% | 0.15 | fail | untouched |
| S1+S5s | ETH-USDT 4H | no regime gate | none | -0.2% | -0.0% | 0.02 | 1.01 | 14.3% | -0.00 | 200 | 5.7% | 1.3% | 34.1% | -5.3% | 87.5% | 0.04 | fail | untouched |
| S1+S5s | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +1.1% | +0.3% | 0.07 | 1.04 | 11.6% | 0.02 | 169 | 4.8% | 1.3% | 39.0% | -3.0% | 87.5% | 0.08 | fail | untouched |
| S2+S5 | ETH-USDT 4H | no regime gate | none | +20.1% | +4.3% | 0.75 | 1.81 | 7.0% | 0.62 | 72 | 5.1% | 0.5% | 70.7% | -0.5% | 100.0% | 0.11 | fail | untouched |
| S2+S5 | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +5.5% | +1.2% | 0.27 | 1.17 | 10.6% | 0.12 | 80 | 4.4% | 0.6% | 70.7% | -0.6% | 91.7% | 0.01 | fail | untouched |
| S2+S5s | ETH-USDT 4H | no regime gate | none | +19.5% | +4.2% | 0.73 | 1.77 | 7.2% | 0.58 | 72 | 5.1% | 0.5% | 70.7% | -0.5% | 100.0% | 0.03 | fail | untouched |
| S2+S5s | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +4.8% | +1.1% | 0.24 | 1.15 | 10.0% | 0.11 | 80 | 4.3% | 0.5% | 65.9% | -0.8% | 94.4% | 0.00 | fail | untouched |
| hold | ETH-USDT 6H | no regime gate | none | +11.0% | +2.5% | 0.50 | 2.04 | 9.6% | 0.26 | 9 | 6.5% | 0.1% | 65.9% | -3.5% | - | 0.85 | fail | -2.9% / PF 0.00 / 1 tr ✗ |
| S1 | ETH-USDT 6H | no regime gate | none | +15.6% | +3.4% | 0.58 | 1.31 | 8.2% | 0.42 | 165 | 6.0% | 1.1% | 68.3% | -2.2% | 100.0% | 0.19 | fail | untouched |
| S1 | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +12.4% | +2.7% | 0.51 | 1.38 | 7.5% | 0.37 | 113 | 4.7% | 0.9% | 80.5% | -1.8% | 100.0% | 0.21 | fail | untouched |
| S1 | ETH-USDT 6H | hmm3 bear>=0.5 scale0.25 | none | +9.7% | +2.2% | 0.47 | 1.27 | 7.0% | 0.31 | 165 | 4.2% | 1.0% | 73.2% | -1.9% | 57.1% | 0.13 | fail | untouched |
| S2 | ETH-USDT 6H | no regime gate | none | +14.8% | +3.2% | 0.57 | 1.39 | 9.1% | 0.36 | 85 | 4.6% | 0.6% | 61.0% | -2.1% | 100.0% | 0.14 | fail | untouched |
| S2 | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +24.1% | +5.1% | 0.92 | 2.01 | 8.3% | 0.62 | 52 | 4.9% | 0.3% | 70.7% | +0.7% | 100.0% | 0.26 | fail | untouched |
| S2 | ETH-USDT 6H | hmm3 bear>=0.5 scale0.25 | none | +14.2% | +3.1% | 0.63 | 1.47 | 9.0% | 0.35 | 85 | 3.7% | 0.6% | 56.1% | -0.7% | 100.0% | 0.17 | fail | untouched |
| S4 | ETH-USDT 6H | no regime gate | tp2 | +14.6% | +3.2% | 0.78 | 1.54 | 9.5% | 0.34 | 88 | 2.8% | 0.6% | 53.7% | -3.9% | 87.5% | 0.33 | fail | untouched |
| S4 | ETH-USDT 6H | hmm3 bear>=0.5 gate | tp2 | +2.7% | +0.6% | 0.21 | 1.14 | 9.0% | 0.07 | 64 | 2.0% | 0.4% | 39.0% | -3.4% | 37.5% | 0.07 | fail | untouched |
| S4 | ETH-USDT 6H | hmm3 bear>=0.5 scale0.25 | tp2 | +4.9% | +1.1% | 0.34 | 1.20 | 9.5% | 0.12 | 88 | 2.2% | 0.6% | 48.8% | -4.0% | 37.5% | 0.09 | fail | untouched |
| S1w | ETH-USDT 6H | no regime gate | none | +9.5% | +2.1% | 0.41 | 1.34 | 10.1% | 0.21 | 69 | 5.3% | 0.5% | 61.0% | -1.8% | 100.0% | 0.15 | fail | untouched |
| S1w | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +17.0% | +3.7% | 0.67 | 1.55 | 9.8% | 0.38 | 66 | 5.1% | 0.5% | 70.7% | -2.0% | 75.0% | 0.26 | fail | untouched |
| S1d | ETH-USDT 6H | no regime gate | none | +8.6% | +1.9% | 0.37 | 1.25 | 9.1% | 0.21 | 117 | 5.2% | 0.7% | 58.5% | -1.2% | 100.0% | 0.15 | fail | untouched |
| S1d | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +1.3% | +0.3% | 0.08 | 1.05 | 10.4% | 0.03 | 101 | 4.3% | 0.6% | 41.5% | -3.7% | 100.0% | 0.06 | fail | untouched |
| S2d | ETH-USDT 6H | no regime gate | none | +20.6% | +4.4% | 0.77 | 1.70 | 8.0% | 0.55 | 57 | 5.0% | 0.4% | 73.2% | +0.2% | 90.0% | 0.20 | fail | untouched |
| S2d | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +20.6% | +4.4% | 0.84 | 1.89 | 7.1% | 0.62 | 43 | 4.0% | 0.3% | 65.9% | -1.1% | 100.0% | 0.26 | fail | untouched |
| S4d | ETH-USDT 6H | no regime gate | tp2 | +5.8% | +1.3% | 0.34 | 1.21 | 11.0% | 0.12 | 94 | 2.6% | 0.7% | 46.3% | -4.6% | 87.5% | 0.10 | fail | untouched |
| S4d | ETH-USDT 6H | hmm3 bear>=0.5 gate | tp2 | +3.2% | +0.7% | 0.27 | 1.20 | 7.4% | 0.10 | 54 | 1.5% | 0.3% | 39.0% | -4.1% | 37.5% | 0.11 | fail | untouched |
| S1h | ETH-USDT 6H | no regime gate | none | +19.9% | +4.3% | 0.72 | 1.57 | 6.7% | 0.64 | 99 | 4.8% | 0.8% | 73.2% | -1.2% | 100.0% | 0.31 | fail | untouched |
| S1h | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +12.2% | +2.7% | 0.51 | 1.39 | 5.9% | 0.46 | 90 | 4.2% | 0.8% | 58.5% | -2.0% | 100.0% | 0.22 | fail | untouched |
| S1+S5 | ETH-USDT 6H | no regime gate | none | +12.6% | +2.8% | 0.48 | 1.33 | 7.4% | 0.38 | 145 | 5.8% | 0.9% | 68.3% | -2.3% | 90.0% | 0.26 | fail | untouched |
| S1+S5 | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +13.0% | +2.9% | 0.53 | 1.43 | 7.2% | 0.40 | 101 | 5.0% | 0.8% | 80.5% | -2.0% | 100.0% | 0.39 | fail | untouched |
| S1+S5s | ETH-USDT 6H | no regime gate | none | +3.3% | +0.8% | 0.16 | 1.10 | 8.0% | 0.10 | 145 | 5.4% | 0.9% | 53.7% | -2.5% | 26.7% | 0.04 | fail | untouched |
| S1+S5s | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +10.3% | +2.3% | 0.43 | 1.32 | 7.5% | 0.31 | 112 | 4.6% | 0.9% | 78.0% | -1.7% | 100.0% | 0.21 | fail | untouched |
| S2+S5 | ETH-USDT 6H | no regime gate | none | +16.5% | +3.6% | 0.65 | 1.54 | 9.0% | 0.40 | 67 | 4.3% | 0.4% | 58.5% | -2.0% | 100.0% | 0.25 | fail | untouched |
| S2+S5 | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +23.7% | +5.1% | 0.90 | 2.04 | 8.5% | 0.59 | 51 | 4.9% | 0.3% | 70.7% | +0.7% | 100.0% | 0.29 | fail | untouched |
| S2+S5s | ETH-USDT 6H | no regime gate | none | +15.1% | +3.3% | 0.60 | 1.49 | 8.6% | 0.39 | 68 | 4.2% | 0.4% | 58.5% | -2.1% | 100.0% | 0.11 | fail | untouched |
| S2+S5s | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +24.4% | +5.2% | 0.92 | 2.10 | 8.3% | 0.62 | 50 | 4.9% | 0.3% | 70.7% | +0.7% | 100.0% | 0.15 | fail | untouched |

Configurations passing all walk-forward gates: **4** of 108; confirmed by the untouched holdout: **1**; contradicted by it: **3** (the `hold` rows are passive always-long controls with the same sizing machinery — planner decision 6 — not candidates; their holdout is shown for comparison only). Holdout ✓ = positive return, PF > 1 and ≥ 10 trades.

Buy-and-hold over the same out-of-sample span (after costs, all-in):

| Series | Total | CAGR | Sharpe | Max DD | Calmar |
|---|---:|---:|---:|---:|---:|
| BTC-USDT 4H | +176.1% | +26.2% | 0.70 | 77.0% | 0.34 |
| BTC-USDT 6H | +212.6% | +30.5% | 0.77 | 77.0% | 0.40 |
| ETH-USDT 4H | +56.0% | +11.1% | 0.50 | 81.1% | 0.14 |
| ETH-USDT 6H | +100.6% | +17.6% | 0.58 | 80.4% | 0.22 |

## Regime v2 as an entry gate — same rule without / with the gate / with quarter-size in the bear state

2022 is the bear year that broke the Sprint 2b yearly gate; it is shown explicitly (planner item 2). `blocked` = share of the selected rule's desired entry bars removed by the gate in the test windows.

| Candidate | Series | 2022 none → gate → scale | CAGR none → gate → scale | Max DD none → gate → scale | Calmar none → gate → scale | Trades none → gate | Blocked | Pass none / gate / scale |
|---|---|---|---|---|---|---|---:|---|
| S1 | BTC-USDT 4H | -4.4% → -2.7% → -2.8% | +2.1% → +1.6% → +1.8% | 8.3% → 10.5% → 6.5% | 0.25 → 0.15 → 0.27 | 184 → 151 | 12.7% | no / no / no |
| S2 | BTC-USDT 4H | -2.4% → -3.2% → -2.0% | +3.3% → +5.2% → +1.9% | 8.7% → 6.5% → 6.2% | 0.38 → 0.80 → 0.31 | 85 → 69 | 4.2% | no / yes / no |
| S4 | BTC-USDT 4H | -2.1% → -0.5% → -0.7% | +1.1% → +1.2% → +1.0% | 9.9% → 9.0% → 10.2% | 0.11 → 0.13 → 0.10 | 109 → 84 | 13.9% | no / no / no |
| S1w | BTC-USDT 4H | -3.4% → -4.0% → - | +1.1% → +4.6% → - | 9.6% → 10.2% → - | 0.11 → 0.45 → - | 95 → 84 | 2.9% | no / no / - |
| S1d | BTC-USDT 4H | -6.7% → -4.8% → - | +1.7% → +0.5% → - | 10.0% → 10.4% → - | 0.17 → 0.04 → - | 132 → 124 | 11.9% | no / no / - |
| S2d | BTC-USDT 4H | -4.7% → -3.5% → - | +1.5% → +2.0% → - | 9.2% → 8.3% → - | 0.16 → 0.24 → - | 86 → 82 | 7.8% | no / no / - |
| S4d | BTC-USDT 4H | -2.7% → -1.6% → - | +2.6% → +2.1% → - | 7.0% → 5.3% → - | 0.37 → 0.40 → - | 102 → 108 | 11.1% | no / no / - |
| S1h | BTC-USDT 4H | +0.1% → -1.5% → - | +3.7% → +1.7% → - | 7.8% → 11.2% → - | 0.47 → 0.15 → - | 104 → 131 | 6.5% | no / no / - |
| S1+S5 | BTC-USDT 4H | -4.4% → -2.7% → - | +2.7% → +3.9% → - | 8.3% → 9.8% → - | 0.32 → 0.40 → - | 179 → 153 | 12.1% | no / no / - |
| S1+S5s | BTC-USDT 4H | -5.3% → -2.7% → - | +2.4% → +0.5% → - | 9.2% → 11.6% → - | 0.26 → 0.04 → - | 174 → 143 | 12.4% | no / no / - |
| S2+S5 | BTC-USDT 4H | -2.4% → -3.2% → - | +3.5% → +5.2% → - | 8.7% → 6.5% → - | 0.40 → 0.80 → - | 83 → 69 | 4.2% | no / yes / - |
| S2+S5s | BTC-USDT 4H | -2.4% → -3.2% → - | +2.8% → +4.5% → - | 8.5% → 6.6% → - | 0.33 → 0.69 → - | 84 → 68 | 5.1% | no / yes / - |
| S1 | BTC-USDT 6H | -4.9% → -4.2% → -3.8% | +3.5% → +3.8% → +2.1% | 9.2% → 11.4% → 7.7% | 0.38 → 0.33 → 0.27 | 155 → 146 | 5.0% | no / no / no |
| S2 | BTC-USDT 6H | -2.8% → -1.4% → -2.3% | +0.7% → +1.2% → +0.3% | 10.0% → 9.9% → 8.2% | 0.07 → 0.12 → 0.04 | 69 → 48 | 19.9% | no / no / no |
| S4 | BTC-USDT 6H | -3.4% → -3.2% → -3.5% | +2.4% → +2.5% → +1.6% | 5.8% → 7.3% → 6.1% | 0.41 → 0.34 → 0.27 | 92 → 75 | 4.6% | no / no / no |
| S1w | BTC-USDT 6H | -4.6% → -8.0% → - | +2.5% → -0.5% → - | 10.5% → 13.3% → - | 0.24 → -0.04 → - | 75 → 107 | 12.1% | no / no / - |
| S1d | BTC-USDT 6H | -4.3% → -3.9% → - | +3.0% → +2.0% → - | 10.3% → 11.0% → - | 0.30 → 0.18 → - | 137 → 134 | 6.9% | no / no / - |
| S2d | BTC-USDT 6H | -1.4% → -1.7% → - | +1.1% → +1.4% → - | 11.0% → 9.0% → - | 0.10 → 0.16 → - | 66 → 50 | 19.2% | no / no / - |
| S4d | BTC-USDT 6H | -3.8% → -4.0% → - | -0.0% → +0.4% → - | 10.3% → 8.7% → - | -0.00 → 0.04 → - | 88 → 77 | 5.3% | no / no / - |
| S1h | BTC-USDT 6H | -5.2% → -5.0% → - | +3.3% → +1.6% → - | 7.5% → 11.6% → - | 0.44 → 0.14 → - | 127 → 109 | 19.6% | no / no / - |
| S1+S5 | BTC-USDT 6H | -5.7% → -5.0% → - | +5.3% → +3.2% → - | 8.8% → 7.6% → - | 0.60 → 0.42 → - | 139 → 139 | 6.3% | yes / no / - |
| S1+S5s | BTC-USDT 6H | -5.1% → -5.2% → - | +3.6% → +2.0% → - | 8.3% → 9.1% → - | 0.43 → 0.22 → - | 141 → 135 | 4.5% | no / no / - |
| S2+S5 | BTC-USDT 6H | -2.8% → -1.4% → - | +1.4% → +1.8% → - | 10.1% → 10.0% → - | 0.13 → 0.18 → - | 57 → 35 | 19.9% | no / no / - |
| S2+S5s | BTC-USDT 6H | -2.6% → -1.4% → - | +1.4% → +1.8% → - | 10.2% → 9.8% → - | 0.14 → 0.19 → - | 56 → 35 | 19.9% | no / no / - |
| S1 | ETH-USDT 4H | -4.5% → -3.0% → -0.1% | -0.0% → +1.3% → +1.0% | 13.4% → 11.5% → 10.1% | -0.00 → 0.11 → 0.10 | 225 → 150 | 3.1% | no / no / no |
| S2 | ETH-USDT 4H | -0.5% → +0.5% → +0.9% | +3.6% → +0.7% → +5.0% | 8.8% → 10.9% → 8.8% | 0.41 → 0.07 → 0.57 | 77 → 86 | 1.2% | no / no / no |
| S4 | ETH-USDT 4H | -2.3% → -1.3% → -1.3% | -1.5% → +0.7% → -0.7% | 11.0% → 7.2% → 8.7% | -0.14 → 0.10 → -0.08 | 81 → 90 | 10.6% | no / no / no |
| S1w | ETH-USDT 4H | -1.0% → -2.8% → - | +2.9% → -0.7% → - | 9.6% → 14.9% → - | 0.30 → -0.05 → - | 79 → 92 | 1.7% | no / no / - |
| S1d | ETH-USDT 4H | -2.3% → -2.3% → - | +2.2% → +2.4% → - | 9.6% → 7.9% → - | 0.23 → 0.30 → - | 154 → 113 | 2.7% | no / no / - |
| S2d | ETH-USDT 4H | -0.5% → -0.6% → - | +3.9% → +2.1% → - | 8.3% → 8.3% → - | 0.47 → 0.25 → - | 76 → 108 | 2.2% | no / no / - |
| S4d | ETH-USDT 4H | -0.6% → -0.4% → - | -1.4% → +0.1% → - | 8.2% → 7.5% → - | -0.16 → 0.01 → - | 76 → 90 | 9.6% | no / no / - |
| S1h | ETH-USDT 4H | -0.9% → -1.6% → - | +3.8% → +3.8% → - | 7.8% → 6.1% → - | 0.49 → 0.63 → - | 114 → 79 | 4.0% | no / no / - |
| S1+S5 | ETH-USDT 4H | -4.6% → -3.0% → - | +0.2% → +0.5% → - | 13.6% → 11.1% → - | 0.01 → 0.05 → - | 204 → 168 | 3.8% | no / no / - |
| S1+S5s | ETH-USDT 4H | -5.3% → -3.0% → - | -0.0% → +0.3% → - | 14.3% → 11.6% → - | -0.00 → 0.02 → - | 200 → 169 | 3.8% | no / no / - |
| S2+S5 | ETH-USDT 4H | +0.1% → +0.7% → - | +4.3% → +1.2% → - | 7.0% → 10.6% → - | 0.62 → 0.12 → - | 72 → 80 | 1.1% | no / no / - |
| S2+S5s | ETH-USDT 4H | -0.2% → +0.4% → - | +4.2% → +1.1% → - | 7.2% → 10.0% → - | 0.58 → 0.11 → - | 72 → 80 | 1.1% | no / no / - |
| S1 | ETH-USDT 6H | -2.2% → -1.8% → -1.9% | +3.4% → +2.7% → +2.2% | 8.2% → 7.5% → 7.0% | 0.42 → 0.37 → 0.31 | 165 → 113 | 11.2% | no / no / no |
| S2 | ETH-USDT 6H | -2.1% → +0.7% → -0.7% | +3.2% → +5.1% → +3.1% | 9.1% → 8.3% → 9.0% | 0.36 → 0.62 → 0.35 | 85 → 52 | 4.0% | no / no / no |
| S4 | ETH-USDT 6H | -0.2% → -1.1% → -0.3% | +3.2% → +0.6% → +1.1% | 9.5% → 9.0% → 9.5% | 0.34 → 0.07 → 0.12 | 88 → 64 | 9.6% | no / no / no |
| S1w | ETH-USDT 6H | -1.2% → -0.5% → - | +2.1% → +3.7% → - | 10.1% → 9.8% → - | 0.21 → 0.38 → - | 69 → 66 | 1.9% | no / no / - |
| S1d | ETH-USDT 6H | -1.2% → +0.8% → - | +1.9% → +0.3% → - | 9.1% → 10.4% → - | 0.21 → 0.03 → - | 117 → 101 | 10.7% | no / no / - |
| S2d | ETH-USDT 6H | +0.8% → +0.7% → - | +4.4% → +4.4% → - | 8.0% → 7.1% → - | 0.55 → 0.62 → - | 57 → 43 | 4.1% | no / no / - |
| S4d | ETH-USDT 6H | -0.8% → -0.6% → - | +1.3% → +0.7% → - | 11.0% → 7.4% → - | 0.12 → 0.10 → - | 94 → 54 | 9.7% | no / no / - |
| S1h | ETH-USDT 6H | -1.2% → -2.0% → - | +4.3% → +2.7% → - | 6.7% → 5.9% → - | 0.64 → 0.46 → - | 99 → 90 | 16.5% | no / no / - |
| S1+S5 | ETH-USDT 6H | -2.3% → -2.0% → - | +2.8% → +2.9% → - | 7.4% → 7.2% → - | 0.38 → 0.40 → - | 145 → 101 | 11.0% | no / no / - |
| S1+S5s | ETH-USDT 6H | -2.5% → -1.7% → - | +0.8% → +2.3% → - | 8.0% → 7.5% → - | 0.10 → 0.31 → - | 145 → 112 | 10.8% | no / no / - |
| S2+S5 | ETH-USDT 6H | -2.0% → +0.7% → - | +3.6% → +5.1% → - | 9.0% → 8.5% → - | 0.40 → 0.59 → - | 67 → 51 | 4.0% | no / no / - |
| S2+S5s | ETH-USDT 6H | -2.1% → +0.7% → - | +3.3% → +5.2% → - | 8.6% → 8.3% → - | 0.39 → 0.62 → - | 68 → 50 | 4.1% | no / no / - |

Medians over 48 rules: 2022 -2.4% → -1.9% (gate) / -1.6% (scale); max DD 9.1% → 9.0% / 8.5%; CAGR +2.6% → +1.9% / +1.7%; Calmar 0.31 → 0.18 / 0.27. The gate had the higher Calmar in 27 of 48 rules. In other words, the gate cost more return than it saved: the bear state also contains the recoveries these rules need.

Gate-threshold sensitivity (one rule, fixed replay of the most-selected parameters with the policy sizing):

| Rule | Series | bear_prob_max | CAGR | Max DD | Calmar | Trades | 2022 |
|---|---|---:|---:|---:|---:|---:|---:|
| S2 | BTC-USDT 4H | 0.35 | +4.5% | 8.3% | 0.54 | 78 | -2.8% |
| S2 | BTC-USDT 4H | 0.5 | +4.5% | 8.4% | 0.53 | 78 | -2.9% |
| S2 | BTC-USDT 4H | 0.65 | +4.5% | 8.4% | 0.53 | 78 | -2.9% |
| S4 | BTC-USDT 6H | 0.35 | +0.4% | 7.4% | 0.05 | 60 | -3.2% |
| S4 | BTC-USDT 6H | 0.5 | +0.4% | 7.4% | 0.05 | 61 | -3.2% |
| S4 | BTC-USDT 6H | 0.65 | +0.6% | 7.4% | 0.08 | 61 | -3.0% |
| S1 | ETH-USDT 4H | 0.35 | +1.8% | 7.0% | 0.26 | 103 | -4.4% |
| S1 | ETH-USDT 4H | 0.5 | +1.8% | 7.0% | 0.25 | 103 | -4.5% |
| S1 | ETH-USDT 4H | 0.65 | +1.8% | 7.0% | 0.25 | 103 | -4.5% |
| S2 | ETH-USDT 6H | 0.35 | +3.3% | 8.3% | 0.39 | 67 | -2.0% |
| S2 | ETH-USDT 6H | 0.5 | +3.1% | 8.6% | 0.36 | 68 | -2.0% |
| S2 | ETH-USDT 6H | 0.65 | +2.9% | 9.4% | 0.31 | 69 | -2.0% |

## Sizing: fixed policy (the proposal) vs train-selected sizing (comparison only)

| Candidate | Series | Regime | Policy CAGR / max DD / Calmar | Train-selected CAGR / max DD / Calmar | Most-selected comparison sizing |
|---|---|---|---|---|---|
| hold | BTC-USDT 4H | none | +3.2% / 7.2% / 0.45 | +2.5% / 13.3% / 0.19 | vt15/30 crash15/90dh ladder |
| S1 | BTC-USDT 4H | none | +2.1% / 8.3% / 0.25 | +3.7% / 17.3% / 0.21 | vt15/30 ladder |
| S1 | BTC-USDT 4H | gate | +1.6% / 10.5% / 0.15 | -0.5% / 14.9% / -0.03 | vt15/30 ladder |
| S1 | BTC-USDT 4H | scale | +1.8% / 6.5% / 0.27 | +2.6% / 13.3% / 0.19 | vt15/30 ladder |
| S2 | BTC-USDT 4H | none | +3.3% / 8.7% / 0.38 | +2.6% / 11.1% / 0.23 | vt15/30 crash15/90dh ladder |
| S2 | BTC-USDT 4H | gate | +5.2% / 6.5% / 0.80 | +4.0% / 10.2% / 0.39 | vt10/30 ladder |
| S2 | BTC-USDT 4H | scale | +1.9% / 6.2% / 0.31 | +3.0% / 9.6% / 0.32 | vt10/30 crash15/90dh ladder |
| S4 | BTC-USDT 4H | none | +1.1% / 9.9% / 0.11 | +3.7% / 13.5% / 0.28 | vt25/30 crash15/90dh ladder |
| S4 | BTC-USDT 4H | gate | +1.2% / 9.0% / 0.13 | +5.2% / 12.5% / 0.42 | vt25/30 crash15/90dh ladder |
| S4 | BTC-USDT 4H | scale | +1.0% / 10.2% / 0.10 | +4.4% / 14.9% / 0.30 | vt10/30 ladder |
| S1w | BTC-USDT 4H | none | +1.1% / 9.6% / 0.11 | +4.7% / 15.9% / 0.30 | vt15/30 crash15/90dh ladder |
| S1w | BTC-USDT 4H | gate | +4.6% / 10.2% / 0.45 | +5.8% / 14.0% / 0.42 | vt10/30 crash15/90dh ladder |
| S1d | BTC-USDT 4H | none | +1.7% / 10.0% / 0.17 | +2.2% / 16.0% / 0.14 | vt15/30 ladder |
| S1d | BTC-USDT 4H | gate | +0.5% / 10.4% / 0.04 | +2.0% / 13.4% / 0.15 | vt15/30 ladder |
| S2d | BTC-USDT 4H | none | +1.5% / 9.2% / 0.16 | -1.7% / 18.5% / -0.09 | vt10/30 crash15/90dh ladder |
| S2d | BTC-USDT 4H | gate | +2.0% / 8.3% / 0.24 | +3.8% / 13.5% / 0.29 | vt10/30 ladder |
| S4d | BTC-USDT 4H | none | +2.6% / 7.0% / 0.37 | +1.2% / 11.8% / 0.10 | vt25/30 ladder |
| S4d | BTC-USDT 4H | gate | +2.1% / 5.3% / 0.40 | +1.3% / 10.4% / 0.12 | vt15/30 crash15/90dh ladder |
| S1h | BTC-USDT 4H | none | +3.7% / 7.8% / 0.47 | +9.0% / 13.5% / 0.67 | vt15/30 ladder |
| S1h | BTC-USDT 4H | gate | +1.7% / 11.2% / 0.15 | +4.4% / 17.6% / 0.25 | vt15/30 ladder |
| S1+S5 | BTC-USDT 4H | none | +2.7% / 8.3% / 0.32 | +5.1% / 17.3% / 0.30 | vt10/30 ladder |
| S1+S5 | BTC-USDT 4H | gate | +3.9% / 9.8% / 0.40 | +2.7% / 15.3% / 0.18 | vt15/30 ladder |
| S1+S5s | BTC-USDT 4H | none | +2.4% / 9.2% / 0.26 | +5.4% / 19.3% / 0.28 | vt15/30 ladder |
| S1+S5s | BTC-USDT 4H | gate | +0.5% / 11.6% / 0.04 | -0.9% / 16.0% / -0.05 | vt15/30 ladder |
| S2+S5 | BTC-USDT 4H | none | +3.5% / 8.7% / 0.40 | +2.8% / 11.1% / 0.25 | vt15/30 crash15/90dh ladder |
| S2+S5 | BTC-USDT 4H | gate | +5.2% / 6.5% / 0.80 | +4.0% / 10.3% / 0.39 | vt10/30 ladder |
| S2+S5s | BTC-USDT 4H | none | +2.8% / 8.5% / 0.33 | +2.5% / 10.0% / 0.25 | vt10/30 ladder |
| S2+S5s | BTC-USDT 4H | gate | +4.5% / 6.6% / 0.69 | +4.6% / 10.2% / 0.45 | vt15/30 crash15/90dh ladder |
| hold | BTC-USDT 6H | none | +2.6% / 8.0% / 0.33 | +5.0% / 10.2% / 0.49 | vt15/30 crash15/90dh ladder |
| S1 | BTC-USDT 6H | none | +3.5% / 9.2% / 0.38 | +8.7% / 16.4% / 0.53 | vt25/30 crash15/90dh ladder |
| S1 | BTC-USDT 6H | gate | +3.8% / 11.4% / 0.33 | +6.3% / 15.4% / 0.41 | vt25/30 ladder |
| S1 | BTC-USDT 6H | scale | +2.1% / 7.7% / 0.27 | +4.5% / 10.8% / 0.42 | vt15/30 ladder |
| S2 | BTC-USDT 6H | none | +0.7% / 10.0% / 0.07 | +0.9% / 11.1% / 0.08 | vt10/30 crash15/90dh ladder |
| S2 | BTC-USDT 6H | gate | +1.2% / 9.9% / 0.12 | +2.0% / 10.9% / 0.18 | vt10/30 crash15/90dh ladder |
| S2 | BTC-USDT 6H | scale | +0.3% / 8.2% / 0.04 | +2.4% / 7.9% / 0.30 | vt10/30 ladder |
| S4 | BTC-USDT 6H | none | +2.4% / 5.8% / 0.41 | +3.9% / 11.6% / 0.33 | vt25/30 ladder |
| S4 | BTC-USDT 6H | gate | +2.5% / 7.3% / 0.34 | +2.5% / 13.3% / 0.19 | vt10/30 ladder |
| S4 | BTC-USDT 6H | scale | +1.6% / 6.1% / 0.27 | +2.5% / 15.4% / 0.16 | vt25/30 ladder |
| S1w | BTC-USDT 6H | none | +2.5% / 10.5% / 0.24 | +6.9% / 13.0% / 0.53 | vt10/30 crash15/90dh ladder |
| S1w | BTC-USDT 6H | gate | -0.5% / 13.3% / -0.04 | -0.8% / 18.0% / -0.05 | vt10/30 ladder |
| S1d | BTC-USDT 6H | none | +3.0% / 10.3% / 0.30 | +1.9% / 15.0% / 0.12 | vt15/30 ladder |
| S1d | BTC-USDT 6H | gate | +2.0% / 11.0% / 0.18 | +5.0% / 15.5% / 0.33 | vt25/30 ladder |
| S2d | BTC-USDT 6H | none | +1.1% / 11.0% / 0.10 | +1.2% / 12.6% / 0.09 | vt25/30 crash15/90dh ladder |
| S2d | BTC-USDT 6H | gate | +1.4% / 9.0% / 0.16 | +2.2% / 10.2% / 0.21 | vt10/30 crash15/90dh ladder |
| S4d | BTC-USDT 6H | none | -0.0% / 10.3% / -0.00 | +1.0% / 11.7% / 0.08 | vt15/30 ladder |
| S4d | BTC-USDT 6H | gate | +0.4% / 8.7% / 0.04 | +1.7% / 13.4% / 0.13 | vt15/30 ladder |
| S1h | BTC-USDT 6H | none | +3.3% / 7.5% / 0.44 | +3.4% / 15.1% / 0.22 | vt15/30 ladder |
| S1h | BTC-USDT 6H | gate | +1.6% / 11.6% / 0.14 | +2.5% / 12.0% / 0.21 | vt10/30 ladder |
| S1+S5 | BTC-USDT 6H | none | +5.3% / 8.8% / 0.60 | +8.3% / 14.7% / 0.57 | vt15/30 ladder |
| S1+S5 | BTC-USDT 6H | gate | +3.2% / 7.6% / 0.42 | +5.2% / 11.0% / 0.48 | vt15/30 ladder |
| S1+S5s | BTC-USDT 6H | none | +3.6% / 8.3% / 0.43 | +7.4% / 13.0% / 0.57 | vt10/30 crash15/90dh ladder |
| S1+S5s | BTC-USDT 6H | gate | +2.0% / 9.1% / 0.22 | +4.8% / 13.1% / 0.37 | vt15/30 ladder |
| S2+S5 | BTC-USDT 6H | none | +1.4% / 10.1% / 0.13 | +1.5% / 11.2% / 0.14 | vt10/30 crash15/90dh ladder |
| S2+S5 | BTC-USDT 6H | gate | +1.8% / 10.0% / 0.18 | +2.6% / 13.9% / 0.18 | vt10/30 crash15/90dh ladder |
| S2+S5s | BTC-USDT 6H | none | +1.4% / 10.2% / 0.14 | +3.1% / 12.3% / 0.25 | vt15/30 crash15/90dh ladder |
| S2+S5s | BTC-USDT 6H | gate | +1.8% / 9.8% / 0.19 | +3.8% / 11.9% / 0.32 | vt15/30 crash15/90dh ladder |
| hold | ETH-USDT 4H | none | +1.8% / 8.6% / 0.20 | +1.5% / 10.5% / 0.14 | vt10/30 crash15/90dh ladder |
| S1 | ETH-USDT 4H | none | -0.0% / 13.4% / -0.00 | -1.5% / 20.0% / -0.08 | vt15/30 ladder |
| S1 | ETH-USDT 4H | gate | +1.3% / 11.5% / 0.11 | +5.0% / 14.0% / 0.35 | vt10/30 ladder |
| S1 | ETH-USDT 4H | scale | +1.0% / 10.1% / 0.10 | +1.8% / 16.0% / 0.11 | vt15/30 crash15/90dh ladder |
| S2 | ETH-USDT 4H | none | +3.6% / 8.8% / 0.41 | +4.4% / 11.0% / 0.40 | vt15/30 ladder |
| S2 | ETH-USDT 4H | gate | +0.7% / 10.9% / 0.07 | +2.4% / 10.8% / 0.22 | vt10/30 ladder |
| S2 | ETH-USDT 4H | scale | +5.0% / 8.8% / 0.57 | +6.1% / 9.7% / 0.63 | vt10/30 ladder |
| S4 | ETH-USDT 4H | none | -1.5% / 11.0% / -0.14 | -2.3% / 16.7% / -0.14 | vt25/30 crash15/90dh ladder |
| S4 | ETH-USDT 4H | gate | +0.7% / 7.2% / 0.10 | +0.7% / 10.0% / 0.07 | vt15/30 crash15/90dh ladder |
| S4 | ETH-USDT 4H | scale | -0.7% / 8.7% / -0.08 | -2.3% / 16.1% / -0.14 | vt10/30 ladder |
| S1w | ETH-USDT 4H | none | +2.9% / 9.6% / 0.30 | +3.4% / 11.7% / 0.29 | vt10/30 crash15/90dh ladder |
| S1w | ETH-USDT 4H | gate | -0.7% / 14.9% / -0.05 | -1.1% / 17.6% / -0.06 | vt10/30 crash15/90dh ladder |
| S1d | ETH-USDT 4H | none | +2.2% / 9.6% / 0.23 | +5.4% / 12.8% / 0.42 | vt10/30 ladder |
| S1d | ETH-USDT 4H | gate | +2.4% / 7.9% / 0.30 | +2.8% / 17.1% / 0.16 | vt25/30 crash15/90dh ladder |
| S2d | ETH-USDT 4H | none | +3.9% / 8.3% / 0.47 | +3.2% / 10.7% / 0.30 | vt10/30 ladder |
| S2d | ETH-USDT 4H | gate | +2.1% / 8.3% / 0.25 | +2.9% / 10.0% / 0.29 | vt10/30 ladder |
| S4d | ETH-USDT 4H | none | -1.4% / 8.2% / -0.16 | -1.5% / 13.6% / -0.11 | vt10/30 ladder |
| S4d | ETH-USDT 4H | gate | +0.1% / 7.5% / 0.01 | +0.3% / 11.8% / 0.03 | vt15/30 ladder |
| S1h | ETH-USDT 4H | none | +3.8% / 7.8% / 0.49 | +6.1% / 12.0% / 0.51 | vt10/30 ladder |
| S1h | ETH-USDT 4H | gate | +3.8% / 6.1% / 0.63 | +3.2% / 8.7% / 0.37 | vt15/30 ladder |
| S1+S5 | ETH-USDT 4H | none | +0.2% / 13.6% / 0.01 | -1.5% / 19.8% / -0.07 | vt25/30 crash15/90dh ladder |
| S1+S5 | ETH-USDT 4H | gate | +0.5% / 11.1% / 0.05 | +4.3% / 13.7% / 0.31 | vt10/30 ladder |
| S1+S5s | ETH-USDT 4H | none | -0.0% / 14.3% / -0.00 | -1.3% / 19.4% / -0.07 | vt25/30 ladder |
| S1+S5s | ETH-USDT 4H | gate | +0.3% / 11.6% / 0.02 | +3.9% / 14.0% / 0.28 | vt10/30 ladder |
| S2+S5 | ETH-USDT 4H | none | +4.3% / 7.0% / 0.62 | +5.0% / 9.5% / 0.52 | vt15/30 crash15/90dh ladder |
| S2+S5 | ETH-USDT 4H | gate | +1.2% / 10.6% / 0.12 | +2.2% / 13.2% / 0.17 | vt10/30 ladder |
| S2+S5s | ETH-USDT 4H | none | +4.2% / 7.2% / 0.58 | +4.6% / 9.8% / 0.47 | vt15/30 ladder |
| S2+S5s | ETH-USDT 4H | gate | +1.1% / 10.0% / 0.11 | +1.9% / 14.2% / 0.13 | vt10/30 ladder |
| hold | ETH-USDT 6H | none | +2.5% / 9.6% / 0.26 | +3.9% / 12.8% / 0.30 | vt10/30 crash15/90dh ladder |
| S1 | ETH-USDT 6H | none | +3.4% / 8.2% / 0.42 | +2.9% / 10.7% / 0.27 | vt15/30 ladder |
| S1 | ETH-USDT 6H | gate | +2.7% / 7.5% / 0.37 | +3.0% / 13.0% / 0.23 | vt25/30 crash15/90dh ladder |
| S1 | ETH-USDT 6H | scale | +2.2% / 7.0% / 0.31 | +2.8% / 12.9% / 0.21 | vt25/30 ladder |
| S2 | ETH-USDT 6H | none | +3.2% / 9.1% / 0.36 | +5.4% / 13.1% / 0.41 | vt25/30 ladder |
| S2 | ETH-USDT 6H | gate | +5.1% / 8.3% / 0.62 | +10.1% / 11.5% / 0.87 | vt10/30 ladder |
| S2 | ETH-USDT 6H | scale | +3.1% / 9.0% / 0.35 | +5.8% / 14.2% / 0.41 | vt25/30 ladder |
| S4 | ETH-USDT 6H | none | +3.2% / 9.5% / 0.34 | +9.0% / 11.3% / 0.80 | vt15/30 ladder |
| S4 | ETH-USDT 6H | gate | +0.6% / 9.0% / 0.07 | +2.4% / 12.5% / 0.19 | vt10/30 ladder |
| S4 | ETH-USDT 6H | scale | +1.1% / 9.5% / 0.12 | +5.2% / 9.5% / 0.55 | vt10/30 ladder |
| S1w | ETH-USDT 6H | none | +2.1% / 10.1% / 0.21 | +4.1% / 10.5% / 0.39 | vt10/30 ladder |
| S1w | ETH-USDT 6H | gate | +3.7% / 9.8% / 0.38 | +5.5% / 13.4% / 0.41 | vt10/30 ladder |
| S1d | ETH-USDT 6H | none | +1.9% / 9.1% / 0.21 | +4.2% / 16.2% / 0.26 | vt25/30 crash15/90dh ladder |
| S1d | ETH-USDT 6H | gate | +0.3% / 10.4% / 0.03 | +4.3% / 17.7% / 0.24 | vt25/30 ladder |
| S2d | ETH-USDT 6H | none | +4.4% / 8.0% / 0.55 | +5.7% / 11.5% / 0.50 | vt10/30 ladder |
| S2d | ETH-USDT 6H | gate | +4.4% / 7.1% / 0.62 | +9.0% / 12.9% / 0.70 | vt10/30 ladder |
| S4d | ETH-USDT 6H | none | +1.3% / 11.0% / 0.12 | +5.9% / 12.7% / 0.46 | vt10/30 ladder |
| S4d | ETH-USDT 6H | gate | +0.7% / 7.4% / 0.10 | +3.5% / 11.9% / 0.29 | vt25/30 ladder |
| S1h | ETH-USDT 6H | none | +4.3% / 6.7% / 0.64 | +6.4% / 11.5% / 0.56 | vt10/30 ladder |
| S1h | ETH-USDT 6H | gate | +2.7% / 5.9% / 0.46 | +3.3% / 11.8% / 0.28 | vt25/30 ladder |
| S1+S5 | ETH-USDT 6H | none | +2.8% / 7.4% / 0.38 | +2.6% / 11.3% / 0.23 | vt10/30 ladder |
| S1+S5 | ETH-USDT 6H | gate | +2.9% / 7.2% / 0.40 | +3.8% / 12.7% / 0.30 | vt10/30 ladder |
| S1+S5s | ETH-USDT 6H | none | +0.8% / 8.0% / 0.10 | +0.8% / 13.1% / 0.06 | vt15/30 ladder |
| S1+S5s | ETH-USDT 6H | gate | +2.3% / 7.5% / 0.31 | +2.1% / 13.1% / 0.16 | vt15/30 ladder |
| S2+S5 | ETH-USDT 6H | none | +3.6% / 9.0% / 0.40 | +5.1% / 12.2% / 0.42 | vt15/30 ladder |
| S2+S5 | ETH-USDT 6H | gate | +5.1% / 8.5% / 0.59 | +10.0% / 11.7% / 0.85 | vt10/30 ladder |
| S2+S5s | ETH-USDT 6H | none | +3.3% / 8.6% / 0.39 | +4.0% / 12.0% / 0.33 | vt15/30 ladder |
| S2+S5s | ETH-USDT 6H | gate | +5.2% / 8.3% / 0.62 | +8.2% / 9.5% / 0.86 | vt10/30 ladder |

## Portfolio-level sizing (BTC+ETH × S1/S2/S4 sleeves, one drawdown budget)

Two constructions of the same sleeves (per family and instrument the timeframe with the higher OOS Calmar — a mild selection on OOS data): *sleeve-sized* = each sleeve already carries the policy sizing, equal-risk weights on full-sample vol, bucket compounding, portfolio ladder (Sprint 2b); *jointly sized* = sleeves at FULL size, trailing inverse-vol weights, one portfolio vol target and one 15 % drawdown ladder (Sprint 2c item 3). Gates on a portfolio use its daily curve and the pooled sleeve trades.

| Portfolio | Sleeves | Regime | CAGR | Sharpe | Max DD | Calmar | Rolling 12m + | Worst year | Avg scale | Trades (pooled) | PF (pooled) | Gates missed |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| S1+S2+S4 x BTC+ETH — sleeve-sized, equal risk, ladder 5/10 | 6 | none | +1.9% | 0.49 | 5.8% | 0.32 | 43.9% | -2.2% | - | 662 | 1.43 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive |
| S1+S2+S4 x BTC+ETH — jointly sized, vol target 10%, ladder 7.5/15 | 6 | none | +6.6% | 0.66 | 10.1% | 0.65 | 70.7% | +0.3% | 52.2% | 662 | 1.43 | Sharpe above 0.7, 75% of rolling 12-month windows positive |
| S1+S2+S4 x BTC+ETH — jointly sized, vol target 15%, ladder 7.5/15 | 6 | none | +10.9% | 0.82 | 13.2% | 0.83 | 82.9% | +0.1% | 69.4% | 662 | 1.43 | none — PASS |
| S1+S2+S4 x BTC+ETH — sleeve-sized, equal risk, ladder 5/10 | 6 | gate | +2.5% | 0.65 | 5.4% | 0.45 | 70.7% | -2.1% | - | 545 | 1.51 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive |
| S1+S2+S4 x BTC+ETH — jointly sized, vol target 10%, ladder 7.5/15 | 6 | gate | +2.6% | 0.33 | 12.7% | 0.20 | 56.1% | -1.9% | 53.6% | 545 | 1.51 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive |
| S1+S2+S4 x BTC+ETH — jointly sized, vol target 15%, ladder 7.5/15 | 6 | gate | +3.9% | 0.40 | 14.0% | 0.28 | 61.0% | -2.5% | 70.4% | 545 | 1.51 | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive |

Correlation of daily sleeve returns (full-size sleeves, no regime gate):

| | S1/BTC/6H | S1/ETH/6H | S2/BTC/4H | S2/ETH/4H | S4/BTC/6H | S4/ETH/6H |
|---|---:|---:|---:|---:|---:|---:|
| S1/BTC/6H | 1.00 | 0.62 | 0.71 | 0.57 | 0.53 | 0.35 |
| S1/ETH/6H | 0.62 | 1.00 | 0.46 | 0.75 | 0.33 | 0.48 |
| S2/BTC/4H | 0.71 | 0.46 | 1.00 | 0.49 | 0.65 | 0.34 |
| S2/ETH/4H | 0.57 | 0.75 | 0.49 | 1.00 | 0.38 | 0.51 |
| S4/BTC/6H | 0.53 | 0.33 | 0.65 | 0.38 | 1.00 | 0.34 |
| S4/ETH/6H | 0.35 | 0.48 | 0.34 | 0.51 | 0.34 | 1.00 |

## Lower-turnover variants — fee drag per variant (same regime mode and series as the base rule)

| Variant | Base | Series | Regime | Fees/yr base → variant | Trades/yr base → variant | CAGR base → variant | Max DD base → variant | Calmar base → variant | Variant passes |
|---|---|---|---|---|---|---|---|---|---|
| S1w | S1 | BTC-USDT 4H | none | 1.4% → 1.0% | 42 → 22 | +2.1% → +1.1% | 8.3% → 9.6% | 0.25 → 0.11 | no |
| S1w | S1 | BTC-USDT 4H | gate | 1.2% → 0.7% | 35 → 19 | +1.6% → +4.6% | 10.5% → 10.2% | 0.15 → 0.45 | no |
| S1w | S1 | BTC-USDT 6H | none | 1.3% → 0.7% | 36 → 17 | +3.5% → +2.5% | 9.2% → 10.5% | 0.38 → 0.24 | no |
| S1w | S1 | BTC-USDT 6H | gate | 1.2% → 0.8% | 34 → 25 | +3.8% → -0.5% | 11.4% → 13.3% | 0.33 → -0.04 | no |
| S1w | S1 | ETH-USDT 4H | none | 1.4% → 0.5% | 52 → 18 | -0.0% → +2.9% | 13.4% → 9.6% | -0.00 → 0.30 | no |
| S1w | S1 | ETH-USDT 4H | gate | 1.1% → 0.6% | 35 → 21 | +1.3% → -0.7% | 11.5% → 14.9% | 0.11 → -0.05 | no |
| S1w | S1 | ETH-USDT 6H | none | 1.1% → 0.5% | 38 → 16 | +3.4% → +2.1% | 8.2% → 10.1% | 0.42 → 0.21 | no |
| S1w | S1 | ETH-USDT 6H | gate | 0.9% → 0.5% | 26 → 15 | +2.7% → +3.7% | 7.5% → 9.8% | 0.37 → 0.38 | no |
| S1d | S1 | BTC-USDT 4H | none | 1.4% → 1.2% | 42 → 30 | +2.1% → +1.7% | 8.3% → 10.0% | 0.25 → 0.17 | no |
| S1d | S1 | BTC-USDT 4H | gate | 1.2% → 1.2% | 35 → 29 | +1.6% → +0.5% | 10.5% → 10.4% | 0.15 → 0.04 | no |
| S1d | S1 | BTC-USDT 6H | none | 1.3% → 1.1% | 36 → 32 | +3.5% → +3.0% | 9.2% → 10.3% | 0.38 → 0.30 | no |
| S1d | S1 | BTC-USDT 6H | gate | 1.2% → 1.1% | 34 → 31 | +3.8% → +2.0% | 11.4% → 11.0% | 0.33 → 0.18 | no |
| S1d | S1 | ETH-USDT 4H | none | 1.4% → 1.0% | 52 → 35 | -0.0% → +2.2% | 13.4% → 9.6% | -0.00 → 0.23 | no |
| S1d | S1 | ETH-USDT 4H | gate | 1.1% → 0.8% | 35 → 26 | +1.3% → +2.4% | 11.5% → 7.9% | 0.11 → 0.30 | no |
| S1d | S1 | ETH-USDT 6H | none | 1.1% → 0.7% | 38 → 27 | +3.4% → +1.9% | 8.2% → 9.1% | 0.42 → 0.21 | no |
| S1d | S1 | ETH-USDT 6H | gate | 0.9% → 0.6% | 26 → 23 | +2.7% → +0.3% | 7.5% → 10.4% | 0.37 → 0.03 | no |
| S2d | S2 | BTC-USDT 4H | none | 0.8% → 0.7% | 20 → 20 | +3.3% → +1.5% | 8.7% → 9.2% | 0.38 → 0.16 | no |
| S2d | S2 | BTC-USDT 4H | gate | 0.7% → 0.7% | 16 → 19 | +5.2% → +2.0% | 6.5% → 8.3% | 0.80 → 0.24 | no |
| S2d | S2 | BTC-USDT 6H | none | 0.7% → 0.6% | 16 → 15 | +0.7% → +1.1% | 10.0% → 11.0% | 0.07 → 0.10 | no |
| S2d | S2 | BTC-USDT 6H | gate | 0.4% → 0.5% | 11 → 12 | +1.2% → +1.4% | 9.9% → 9.0% | 0.12 → 0.16 | no |
| S2d | S2 | ETH-USDT 4H | none | 0.5% → 0.5% | 18 → 17 | +3.6% → +3.9% | 8.8% → 8.3% | 0.41 → 0.47 | no |
| S2d | S2 | ETH-USDT 4H | gate | 0.6% → 0.8% | 20 → 25 | +0.7% → +2.1% | 10.9% → 8.3% | 0.07 → 0.25 | no |
| S2d | S2 | ETH-USDT 6H | none | 0.6% → 0.4% | 20 → 13 | +3.2% → +4.4% | 9.1% → 8.0% | 0.36 → 0.55 | no |
| S2d | S2 | ETH-USDT 6H | gate | 0.3% → 0.3% | 12 → 10 | +5.1% → +4.4% | 8.3% → 7.1% | 0.62 → 0.62 | no |
| S4d | S4 | BTC-USDT 4H | none | 1.3% → 1.2% | 25 → 23 | +1.1% → +2.6% | 9.9% → 7.0% | 0.11 → 0.37 | no |
| S4d | S4 | BTC-USDT 4H | gate | 1.0% → 1.4% | 19 → 25 | +1.2% → +2.1% | 9.0% → 5.3% | 0.13 → 0.40 | no |
| S4d | S4 | BTC-USDT 6H | none | 1.0% → 1.0% | 21 → 20 | +2.4% → -0.0% | 5.8% → 10.3% | 0.41 → -0.00 | no |
| S4d | S4 | BTC-USDT 6H | gate | 0.8% → 0.8% | 17 → 18 | +2.5% → +0.4% | 7.3% → 8.7% | 0.34 → 0.04 | no |
| S4d | S4 | ETH-USDT 4H | none | 0.6% → 0.6% | 19 → 17 | -1.5% → -1.4% | 11.0% → 8.2% | -0.14 → -0.16 | no |
| S4d | S4 | ETH-USDT 4H | gate | 0.7% → 0.7% | 21 → 21 | +0.7% → +0.1% | 7.2% → 7.5% | 0.10 → 0.01 | no |
| S4d | S4 | ETH-USDT 6H | none | 0.6% → 0.7% | 20 → 22 | +3.2% → +1.3% | 9.5% → 11.0% | 0.34 → 0.12 | no |
| S4d | S4 | ETH-USDT 6H | gate | 0.4% → 0.3% | 15 → 13 | +0.6% → +0.7% | 9.0% → 7.4% | 0.07 → 0.10 | no |
| S1h | S1 | BTC-USDT 4H | none | 1.4% → 1.1% | 42 → 24 | +2.1% → +3.7% | 8.3% → 7.8% | 0.25 → 0.47 | no |
| S1h | S1 | BTC-USDT 4H | gate | 1.2% → 1.5% | 35 → 30 | +1.6% → +1.7% | 10.5% → 11.2% | 0.15 → 0.15 | no |
| S1h | S1 | BTC-USDT 6H | none | 1.3% → 1.3% | 36 → 29 | +3.5% → +3.3% | 9.2% → 7.5% | 0.38 → 0.44 | no |
| S1h | S1 | BTC-USDT 6H | gate | 1.2% → 1.1% | 34 → 25 | +3.8% → +1.6% | 11.4% → 11.6% | 0.33 → 0.14 | no |
| S1h | S1 | ETH-USDT 4H | none | 1.4% → 1.0% | 52 → 26 | -0.0% → +3.8% | 13.4% → 7.8% | -0.00 → 0.49 | no |
| S1h | S1 | ETH-USDT 4H | gate | 1.1% → 0.7% | 35 → 18 | +1.3% → +3.8% | 11.5% → 6.1% | 0.11 → 0.63 | no |
| S1h | S1 | ETH-USDT 6H | none | 1.1% → 0.8% | 38 → 23 | +3.4% → +4.3% | 8.2% → 6.7% | 0.42 → 0.64 | no |
| S1h | S1 | ETH-USDT 6H | gate | 0.9% → 0.8% | 26 → 21 | +2.7% → +2.7% | 7.5% → 5.9% | 0.37 → 0.46 | no |

Medians over 40 pairs: fees/yr 1.1% → 0.7%, Calmar 0.29 → 0.22; the variant had the higher Calmar in 20 of 40 pairs.

## Positioning filter re-test (S5) — base vs 30-day funding window vs 7–14-day window + OI change

| Variant | Series | Regime | Base Sharpe / Calmar / DD / trades | S5 (30d) Sharpe / Calmar / DD / trades | S5 short Sharpe / Calmar / DD / trades | Most-selected S5 params | Data coverage |
|---|---|---|---|---|---|---|---:|
| S1+S5s | BTC-USDT 4H | none | 0.37 / 0.25 / 8.3% / 184 | 0.44 / 0.32 / 8.3% / 179 | 0.42 / 0.26 / 9.2% / 174 | `{'funding_z_window': 42, 'funding_z_max': 2.0, 'oi_change_max': 0.25, 'oi_change_window_days': 1}` | 100.0% |
| S1+S5s | BTC-USDT 4H | gate | 0.29 / 0.15 / 10.5% / 151 | 0.65 / 0.40 / 9.8% / 153 | 0.12 / 0.04 / 11.6% / 143 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S1+S5s | BTC-USDT 6H | none | 0.58 / 0.38 / 9.2% / 155 | 0.86 / 0.60 / 8.8% / 139 | 0.63 / 0.43 / 8.3% / 141 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S1+S5s | BTC-USDT 6H | gate | 0.63 / 0.33 / 11.4% / 146 | 0.54 / 0.42 / 7.6% / 139 | 0.36 / 0.22 / 9.1% / 135 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S1+S5s | ETH-USDT 4H | none | 0.03 / -0.00 / 13.4% / 225 | 0.06 / 0.01 / 13.6% / 204 | 0.02 / -0.00 / 14.3% / 200 | `{'funding_z_window': 21, 'funding_z_max': 3.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S1+S5s | ETH-USDT 4H | gate | 0.25 / 0.11 / 11.5% / 150 | 0.12 / 0.05 / 11.1% / 168 | 0.07 / 0.02 / 11.6% / 169 | `{'funding_z_window': 21, 'funding_z_max': 3.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S1+S5s | ETH-USDT 6H | none | 0.58 / 0.42 / 8.2% / 165 | 0.48 / 0.38 / 7.4% / 145 | 0.16 / 0.10 / 8.0% / 145 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S1+S5s | ETH-USDT 6H | gate | 0.51 / 0.37 / 7.5% / 113 | 0.53 / 0.40 / 7.2% / 101 | 0.43 / 0.31 / 7.5% / 112 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S2+S5s | BTC-USDT 4H | none | 0.57 / 0.38 / 8.7% / 85 | 0.61 / 0.40 / 8.7% / 83 | 0.49 / 0.33 / 8.5% / 84 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S2+S5s | BTC-USDT 4H | gate | 0.86 / 0.80 / 6.5% / 69 | 0.87 / 0.80 / 6.5% / 69 | 0.78 / 0.69 / 6.6% / 68 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S2+S5s | BTC-USDT 6H | none | 0.16 / 0.07 / 10.0% / 69 | 0.29 / 0.13 / 10.1% / 57 | 0.29 / 0.14 / 10.2% / 56 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S2+S5s | BTC-USDT 6H | gate | 0.28 / 0.12 / 9.9% / 48 | 0.42 / 0.18 / 10.0% / 35 | 0.43 / 0.19 / 9.8% / 35 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.25, 'oi_change_window_days': 3}` | 100.0% |
| S2+S5s | ETH-USDT 4H | none | 0.62 / 0.41 / 8.8% / 77 | 0.75 / 0.62 / 7.0% / 72 | 0.73 / 0.58 / 7.2% / 72 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S2+S5s | ETH-USDT 4H | gate | 0.16 / 0.07 / 10.9% / 86 | 0.27 / 0.12 / 10.6% / 80 | 0.24 / 0.11 / 10.0% / 80 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 3}` | 100.0% |
| S2+S5s | ETH-USDT 6H | none | 0.57 / 0.36 / 9.1% / 85 | 0.65 / 0.40 / 9.0% / 67 | 0.60 / 0.39 / 8.6% / 68 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.1, 'oi_change_window_days': 1}` | 100.0% |
| S2+S5s | ETH-USDT 6H | gate | 0.92 / 0.62 / 8.3% / 52 | 0.90 / 0.59 / 8.5% / 51 | 0.92 / 0.62 / 8.3% / 50 | `{'funding_z_window': 21, 'funding_z_max': 2.0, 'oi_change_max': 0.25, 'oi_change_window_days': 1}` | 100.0% |

## Paper-fleet shortlist (ranked) — forward evidence only; nothing approved

Ranked by: passed all gates first, then Calmar, then Sharpe; only configurations with OOS profit factor > 1 and ≥ 30 trades. Machine-readable copy with the controls: `docs/research/paper_fleet_shortlist_v1c.json`.

| # | Candidate | Series | Regime | Bracket | CAGR | Sharpe | Calmar | Max DD | PF | Trades | Rolling 12m + | Worst year | DSR | Gates missed | Holdout |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | S1+S5 | BTC-USDT 6H | no regime gate | none | +5.3% | 0.86 | 0.60 | 8.8% | 1.68 | 139 | 78.0% | -5.7% | 0.23 | none — PASS | +2.3% / PF 1.48 / 32 tr ✓ |
| 2 | S2+S5 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +5.2% | 0.87 | 0.80 | 6.5% | 1.94 | 69 | 80.5% | -3.2% | 0.49 | none — PASS | -3.0% / PF 0.51 / 18 tr ✗ |
| 3 | S2 | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +5.2% | 0.86 | 0.80 | 6.5% | 1.94 | 69 | 80.5% | -3.2% | 0.19 | none — PASS | -4.9% / PF 0.28 / 21 tr ✗ |
| 4 | S2+S5s | BTC-USDT 4H | hmm3 bear>=0.5 gate | none | +4.5% | 0.78 | 0.69 | 6.6% | 1.85 | 68 | 75.6% | -3.2% | 0.27 | none — PASS | -4.4% / PF 0.29 / 19 tr ✗ |
| 5 | S1h | ETH-USDT 6H | no regime gate | none | +4.3% | 0.72 | 0.64 | 6.7% | 1.57 | 99 | 73.2% | -1.2% | 0.31 | 75% of rolling 12-month windows positive | untouched |
| 6 | S1h | ETH-USDT 4H | hmm3 bear>=0.5 gate | none | +3.8% | 0.67 | 0.63 | 6.1% | 1.75 | 79 | 65.9% | -1.6% | 0.35 | Sharpe above 0.7, 75% of rolling 12-month windows positive | untouched |
| 7 | S2d | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +4.4% | 0.84 | 0.62 | 7.1% | 1.89 | 43 | 65.9% | -1.1% | 0.26 | 75% of rolling 12-month windows positive | untouched |
| 8 | S2+S5s | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +5.2% | 0.92 | 0.62 | 8.3% | 2.10 | 50 | 70.7% | +0.7% | 0.15 | 75% of rolling 12-month windows positive | untouched |
| 9 | S2+S5 | ETH-USDT 4H | no regime gate | none | +4.3% | 0.75 | 0.62 | 7.0% | 1.81 | 72 | 70.7% | -0.5% | 0.11 | 75% of rolling 12-month windows positive | untouched |
| 10 | S2 | ETH-USDT 6H | hmm3 bear>=0.5 gate | none | +5.1% | 0.92 | 0.62 | 8.3% | 2.01 | 52 | 70.7% | +0.7% | 0.26 | 75% of rolling 12-month windows positive | untouched |

Controls the fleet must run next to the shortlist (planner decision 6):

| Role | Series | Regime | CAGR | Sharpe | Calmar | Max DD | Holdout |
|---|---|---|---:|---:|---:|---:|---|
| control: always-long with policy sizing | BTC-USDT 4H | no regime gate | +3.2% | 0.59 | 0.45 | 7.2% | -4.3% / PF 0.00 / 1 tr ✗ |
| control: always-long with policy sizing | BTC-USDT 6H | no regime gate | +2.6% | 0.49 | 0.33 | 8.0% | -4.0% / PF 0.00 / 1 tr ✗ |
| control: always-long with policy sizing | ETH-USDT 4H | no regime gate | +1.8% | 0.38 | 0.20 | 8.6% | -2.6% / PF 0.00 / 1 tr ✗ |
| control: always-long with policy sizing | ETH-USDT 6H | no regime gate | +2.5% | 0.50 | 0.26 | 9.6% | -2.9% / PF 0.00 / 1 tr ✗ |
| control: plain buy-and-hold (all-in, after costs) | BTC-USDT 4H | - | +26.2% | 0.70 | 0.34 | 77.0% | - |
| control: plain buy-and-hold (all-in, after costs) | BTC-USDT 6H | - | +30.5% | 0.77 | 0.40 | 77.0% | - |
| control: plain buy-and-hold (all-in, after costs) | ETH-USDT 4H | - | +11.1% | 0.50 | 0.14 | 81.1% | - |
| control: plain buy-and-hold (all-in, after costs) | ETH-USDT 6H | - | +17.6% | 0.58 | 0.22 | 80.4% | - |

## hold — Always-long reference (sizing overlays only, no stop) (BTC-USDT 4H, no regime gate)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.2% |
| 2022 | -4.7% |
| 2023 | +16.4% |
| 2024 | +3.4% |
| 2025 | -0.1% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -6.5%, median +4.7%; worst calendar year 2022 at -4.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.8%, neighbours median -, min -, share profitable - over 0 neighbours.

Same rule at full size (no sizing, same gate): return +173.4%, max DD 77.0%, Calmar 0.34.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 9 OOS trades): terminal growth p05 0.94× / p50 1.14× / p95 1.43×, P(loss) 14.2%, max DD p50 5.0%, p95 10.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.8%, x2: +14.7%, x3: +14.5%

Deflated Sharpe: 1 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.000 per bar vs observed OOS 0.013 → DSR 0.89.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=no, robust_pm30pct=no

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -4.3%, CAGR -4.3%, Sharpe -1.70, PF 0.00, max DD 5.2%, Calmar -0.82, trades 1.

- passive control: always long, no stop, policy sizing only; excluded from the shortlist (planner decision 6)

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.2% |
| 2022 | -4.4% |
| 2023 | +15.3% |
| 2024 | -3.2% |
| 2025 | +1.2% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -7.1%, median +1.0%; worst calendar year 2022 at -4.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.6%, neighbours median +9.1%, min -9.8%, share profitable 75.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +37.6%, max DD 65.0%, Calmar 0.12.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 184 OOS trades): terminal growth p05 0.88× / p50 1.09× / p95 1.41×, P(loss) 27.3%, max DD p50 9.6%, p95 18.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.6%, x2: +9.6%, x3: +6.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.008 → DSR 0.04.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 12.7%.

| Year | OOS return |
|---|---:|
| 2021 | +0.6% |
| 2022 | -2.7% |
| 2023 | +3.2% |
| 2024 | +1.4% |
| 2025 | +4.4% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -5.7%, median +2.0%; worst calendar year 2022 at -2.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +8.5%, neighbours median +8.7%, min +3.7%, share profitable 100.0% over 7 neighbours.

Same rule at full size (no sizing, same gate): return -1.5%, max DD 74.6%, Calmar -0.00.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 151 OOS trades): terminal growth p05 0.85× / p50 1.06× / p95 1.38×, P(loss) 35.9%, max DD p50 10.9%, p95 20.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +8.5%, x2: +5.9%, x3: +3.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.006 → DSR 0.06.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -2.8% |
| 2023 | +11.5% |
| 2024 | -1.4% |
| 2025 | +2.0% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -5.2%, median +2.2%; worst calendar year 2022 at -2.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +0.9%, neighbours median +1.1%, min -8.8%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +37.6%, max DD 65.0%, Calmar 0.12.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 184 OOS trades): terminal growth p05 0.90× / p50 1.07× / p95 1.31×, P(loss) 27.3%, max DD p50 7.6%, p95 14.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.9%, x2: -3.7%, x3: -5.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.009 → DSR 0.05.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.8% |
| 2022 | -2.4% |
| 2023 | +14.4% |
| 2024 | +8.9% |
| 2025 | -4.6% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -4.5%, median +3.4%; worst calendar year 2025 at -4.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.3%, neighbours median +12.7%, min +8.7%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +6.7%, max DD 64.3%, Calmar 0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.90× / p50 1.13× / p95 1.55×, P(loss) 20.3%, max DD p50 8.9%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.3%, x2: +10.0%, x3: +8.3%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.012 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (8 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 4.2%.

| Year | OOS return |
|---|---:|
| 2021 | -0.9% |
| 2022 | -3.2% |
| 2023 | +14.1% |
| 2024 | +14.7% |
| 2025 | -0.6% |

Rolling 12-month windows: 41 sampled, 80.5% positive, min -5.6%, median +5.7%; worst calendar year 2022 at -3.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +20.9%, neighbours median +18.9%, min +13.4%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +76.6%, max DD 54.4%, Calmar 0.26.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 69 OOS trades): terminal growth p05 0.98× / p50 1.24× / p95 1.63×, P(loss) 7.2%, max DD p50 6.7%, p95 12.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +20.9%, x2: +20.6%, x3: +19.0%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.027 per bar vs observed OOS 0.018 → DSR 0.19.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -4.9%, CAGR -4.9%, Sharpe -1.85, PF 0.28, max DD 6.3%, Calmar -0.78, trades 21.

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -3.1% |
| 2022 | -2.0% |
| 2023 | +10.7% |
| 2024 | +5.9% |
| 2025 | -2.4% |

Rolling 12-month windows: 41 sampled, 80.5% positive, min -4.8%, median +3.9%; worst calendar year 2021 at -3.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +4.4%, neighbours median +6.1%, min +2.0%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +6.7%, max DD 64.3%, Calmar 0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.93× / p50 1.08× / p95 1.30×, P(loss) 21.6%, max DD p50 6.5%, p95 12.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +4.4%, x2: +2.7%, x3: +0.8%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.010 → DSR 0.07.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 4H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.2% |
| 2022 | -2.1% |
| 2023 | +4.3% |
| 2024 | +10.7% |
| 2025 | -5.9% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -3.6%, median +1.9%; worst calendar year 2025 at -5.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.7%, neighbours median +3.5%, min -3.4%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +78.9%, max DD 19.6%, Calmar 0.73.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 109 OOS trades): terminal growth p05 0.87× / p50 1.04× / p95 1.26×, P(loss) 35.4%, max DD p50 9.1%, p95 17.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.7%, x2: +10.2%, x3: +5.4%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.017 per bar vs observed OOS 0.006 → DSR 0.13.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 13.9%.

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -0.5% |
| 2023 | +1.5% |
| 2024 | +9.3% |
| 2025 | -3.8% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -2.8%, median +0.7%; worst calendar year 2025 at -3.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.3%, neighbours median +6.1%, min -1.0%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +91.1%, max DD 19.6%, Calmar 0.82.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 84 OOS trades): terminal growth p05 0.89× / p50 1.05× / p95 1.27×, P(loss) 32.5%, max DD p50 8.4%, p95 15.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.3%, x2: +11.2%, x3: +9.1%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.014 per bar vs observed OOS 0.006 → DSR 0.23.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -0.7% |
| 2023 | +4.1% |
| 2024 | +6.2% |
| 2025 | -4.0% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -1.8%, median +1.8%; worst calendar year 2025 at -4.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.2%, neighbours median +3.8%, min -1.1%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +78.9%, max DD 19.6%, Calmar 0.73.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 109 OOS trades): terminal growth p05 0.89× / p50 1.04× / p95 1.22×, P(loss) 34.6%, max DD p50 7.6%, p95 14.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.2%, x2: +8.2%, x3: +6.2%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.017 per bar vs observed OOS 0.006 → DSR 0.12.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -2.6% |
| 2022 | -3.4% |
| 2023 | +8.2% |
| 2024 | +7.3% |
| 2025 | -4.1% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -6.5%, median +1.9%; worst calendar year 2025 at -4.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +15.0%, neighbours median +11.2%, min -9.5%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +166.2%, max DD 43.8%, Calmar 0.58.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 95 OOS trades): terminal growth p05 0.83× / p50 1.04× / p95 1.36×, P(loss) 39.7%, max DD p50 12.1%, p95 21.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +15.0%, x2: +13.2%, x3: +11.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.004 → DSR 0.03.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 2.9%.

| Year | OOS return |
|---|---:|
| 2021 | -2.6% |
| 2022 | -4.0% |
| 2023 | +16.4% |
| 2024 | +11.2% |
| 2025 | +0.5% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -6.3%, median +4.4%; worst calendar year 2022 at -4.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +18.1%, neighbours median +13.8%, min -11.8%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +188.5%, max DD 46.3%, Calmar 0.60.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 84 OOS trades): terminal growth p05 0.95× / p50 1.20× / p95 1.61×, P(loss) 11.0%, max DD p50 7.7%, p95 14.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +18.1%, x2: +16.5%, x3: +14.7%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.016 → DSR 0.28.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.8% |
| 2022 | -6.7% |
| 2023 | +17.8% |
| 2024 | -3.1% |
| 2025 | -0.9% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -8.2%, median +1.8%; worst calendar year 2022 at -6.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +31.2%, neighbours median +23.1%, min +4.3%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +228.2%, max DD 47.0%, Calmar 0.67.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 132 OOS trades): terminal growth p05 0.84× / p50 1.07× / p95 1.40×, P(loss) 32.5%, max DD p50 11.9%, p95 21.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +31.2%, x2: +28.5%, x3: +25.9%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.007 → DSR 0.03.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 11.9%.

| Year | OOS return |
|---|---:|
| 2021 | +1.8% |
| 2022 | -4.8% |
| 2023 | +11.1% |
| 2024 | -5.8% |
| 2025 | +0.6% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -6.6%, median -1.0%; worst calendar year 2024 at -5.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +33.9%, neighbours median +24.3%, min +11.6%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +256.4%, max DD 36.6%, Calmar 0.93.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 124 OOS trades): terminal growth p05 0.82× / p50 1.01× / p95 1.28×, P(loss) 46.4%, max DD p50 11.8%, p95 21.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +33.9%, x2: +31.5%, x3: +29.3%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.002 → DSR 0.01.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.3% |
| 2022 | -4.7% |
| 2023 | +9.9% |
| 2024 | +10.0% |
| 2025 | -6.1% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -5.5%, median +1.8%; worst calendar year 2025 at -6.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.9%, neighbours median +5.7%, min +0.6%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return -19.4%, max DD 64.7%, Calmar -0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 86 OOS trades): terminal growth p05 0.86× / p50 1.05× / p95 1.37×, P(loss) 35.8%, max DD p50 9.7%, p95 17.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.9%, x2: +3.7%, x3: +1.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.006 → DSR 0.02.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 7.8%.

| Year | OOS return |
|---|---:|
| 2021 | -1.1% |
| 2022 | -3.5% |
| 2023 | +9.6% |
| 2024 | +9.9% |
| 2025 | -5.3% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -4.7%, median +2.8%; worst calendar year 2025 at -5.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.5%, neighbours median +11.7%, min +9.9%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +1.3%, max DD 61.4%, Calmar 0.00.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 82 OOS trades): terminal growth p05 0.89× / p50 1.08× / p95 1.38×, P(loss) 27.2%, max DD p50 8.4%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.5%, x2: +9.4%, x3: +7.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.027 per bar vs observed OOS 0.008 → DSR 0.03.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (BTC-USDT 4H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -3.6% |
| 2022 | -2.7% |
| 2023 | +12.8% |
| 2024 | +7.4% |
| 2025 | -1.7% |

Rolling 12-month windows: 41 sampled, 75.6% positive, min -4.6%, median +3.5%; worst calendar year 2021 at -3.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.6%, neighbours median +5.1%, min +2.7%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +60.7%, max DD 19.2%, Calmar 0.60.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 102 OOS trades): terminal growth p05 0.90× / p50 1.11× / p95 1.42×, P(loss) 21.7%, max DD p50 8.4%, p95 16.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.6%, x2: +12.1%, x3: +9.7%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.013 → DSR 0.28.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 11.1%.

| Year | OOS return |
|---|---:|
| 2021 | -2.4% |
| 2022 | -1.6% |
| 2023 | +8.7% |
| 2024 | +5.4% |
| 2025 | -0.5% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -3.4%, median +3.4%; worst calendar year 2021 at -2.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.1%, neighbours median +9.2%, min +1.5%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +62.7%, max DD 20.1%, Calmar 0.59.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 108 OOS trades): terminal growth p05 0.91× / p50 1.09× / p95 1.33×, P(loss) 22.2%, max DD p50 8.0%, p95 15.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.1%, x2: +11.8%, x3: +9.5%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.012 per bar vs observed OOS 0.011 → DSR 0.48.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (BTC-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.4% |
| 2022 | +0.1% |
| 2023 | +15.1% |
| 2024 | -1.0% |
| 2025 | +2.8% |

Rolling 12-month windows: 41 sampled, 85.4% positive, min -1.2%, median +3.6%; worst calendar year 2024 at -1.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +26.2%, neighbours median +26.0%, min +3.2%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +236.7%, max DD 34.4%, Calmar 0.94.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 104 OOS trades): terminal growth p05 0.94× / p50 1.16× / p95 1.48×, P(loss) 13.6%, max DD p50 7.5%, p95 14.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +26.2%, x2: +24.7%, x3: +20.0%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.028 per bar vs observed OOS 0.014 → DSR 0.08.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 6.5%.

| Year | OOS return |
|---|---:|
| 2021 | +3.3% |
| 2022 | -1.5% |
| 2023 | +5.4% |
| 2024 | +0.3% |
| 2025 | -0.1% |

Rolling 12-month windows: 41 sampled, 75.6% positive, min -4.7%, median +1.3%; worst calendar year 2022 at -1.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +21.7%, neighbours median +20.3%, min -1.9%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +144.6%, max DD 40.4%, Calmar 0.57.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 131 OOS trades): terminal growth p05 0.87× / p50 1.07× / p95 1.39×, P(loss) 31.8%, max DD p50 10.4%, p95 19.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +21.7%, x2: +19.8%, x3: +19.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.007 → DSR 0.04.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 4H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 3, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.3% |
| 2022 | -4.4% |
| 2023 | +13.2% |
| 2024 | +1.9% |
| 2025 | +0.4% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -7.1%, median +1.2%; worst calendar year 2022 at -4.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +16.3%, neighbours median +16.6%, min +13.9%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +103.6%, max DD 31.5%, Calmar 0.56.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 179 OOS trades): terminal growth p05 0.89× / p50 1.11× / p95 1.42×, P(loss) 22.5%, max DD p50 9.5%, p95 17.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +16.3%, x2: +13.2%, x3: +10.9%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.009 → DSR 0.12.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 12.1%.

| Year | OOS return |
|---|---:|
| 2021 | +1.4% |
| 2022 | -2.7% |
| 2023 | +12.8% |
| 2024 | +1.5% |
| 2025 | +4.6% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -5.3%, median +3.1%; worst calendar year 2022 at -2.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.0%, neighbours median +12.2%, min -10.3%, share profitable 80.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +45.1%, max DD 59.6%, Calmar 0.15.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 153 OOS trades): terminal growth p05 0.92× / p50 1.17× / p95 1.50×, P(loss) 14.3%, max DD p50 8.6%, p95 16.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.0%, x2: +8.7%, x3: +6.0%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.020 per bar vs observed OOS 0.014 → DSR 0.29.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (BTC-USDT 4H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 3, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 42, 'oi_change_max': 0.25, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.2% |
| 2022 | -5.3% |
| 2023 | +15.3% |
| 2024 | +1.8% |
| 2025 | -1.3% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -8.0%, median +0.9%; worst calendar year 2022 at -5.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +9.2%, neighbours median +9.2%, min +3.5%, share profitable 100.0% over 15 neighbours.

Same rule at full size (no sizing, same gate): return +93.9%, max DD 36.9%, Calmar 0.45.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 174 OOS trades): terminal growth p05 0.87× / p50 1.09× / p95 1.44×, P(loss) 26.4%, max DD p50 9.9%, p95 18.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +9.2%, x2: +6.2%, x3: +3.8%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.009 → DSR 0.05.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 1, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 12.4%.

| Year | OOS return |
|---|---:|
| 2021 | +0.8% |
| 2022 | -2.7% |
| 2023 | +2.1% |
| 2024 | -2.3% |
| 2025 | +4.5% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -6.7%, median -1.1%; worst calendar year 2022 at -2.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +6.5%, neighbours median +6.5%, min +3.5%, share profitable 100.0% over 15 neighbours.

Same rule at full size (no sizing, same gate): return -26.5%, max DD 78.7%, Calmar -0.09.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 143 OOS trades): terminal growth p05 0.84× / p50 1.02× / p95 1.28×, P(loss) 44.5%, max DD p50 11.9%, p95 21.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +6.5%, x2: +3.3%, x3: +0.0%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.003 → DSR 0.04.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 4H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.7% |
| 2022 | -2.4% |
| 2023 | +15.4% |
| 2024 | +8.9% |
| 2025 | -4.6% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -4.5%, median +4.0%; worst calendar year 2025 at -4.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.4%, neighbours median +12.4%, min +8.8%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +7.8%, max DD 64.2%, Calmar 0.03.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 83 OOS trades): terminal growth p05 0.92× / p50 1.15× / p95 1.54×, P(loss) 16.5%, max DD p50 8.3%, p95 15.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.4%, x2: +10.1%, x3: +8.4%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.015 per bar vs observed OOS 0.013 → DSR 0.42.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (8 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 4.2%.

| Year | OOS return |
|---|---:|
| 2021 | -0.8% |
| 2022 | -3.2% |
| 2023 | +14.1% |
| 2024 | +14.7% |
| 2025 | -0.6% |

Rolling 12-month windows: 41 sampled, 80.5% positive, min -5.5%, median +5.7%; worst calendar year 2022 at -3.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +16.4%, neighbours median +16.6%, min +12.8%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +22.3%, max DD 63.6%, Calmar 0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 69 OOS trades): terminal growth p05 0.98× / p50 1.24× / p95 1.63×, P(loss) 7.1%, max DD p50 6.7%, p95 12.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +16.4%, x2: +14.1%, x3: +12.6%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.018 → DSR 0.49.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -3.0%, CAGR -3.0%, Sharpe -0.73, PF 0.51, max DD 4.4%, Calmar -0.68, trades 18.

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (BTC-USDT 4H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.8% |
| 2022 | -2.4% |
| 2023 | +12.4% |
| 2024 | +10.2% |
| 2025 | -6.1% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -3.7%, median +2.9%; worst calendar year 2025 at -6.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.2%, neighbours median +13.1%, min +6.3%, share profitable 100.0% over 17 neighbours.

Same rule at full size (no sizing, same gate): return +8.1%, max DD 64.3%, Calmar 0.03.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 84 OOS trades): terminal growth p05 0.89× / p50 1.12× / p95 1.49×, P(loss) 22.3%, max DD p50 9.2%, p95 17.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.2%, x2: +10.1%, x3: +8.3%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.011 → DSR 0.21.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (BTC-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (8 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.4%, test bear share median 19.4%, entries blocked by the gate 5.1%.

| Year | OOS return |
|---|---:|
| 2021 | -0.7% |
| 2022 | -3.2% |
| 2023 | +14.1% |
| 2024 | +11.2% |
| 2025 | -0.6% |

Rolling 12-month windows: 41 sampled, 75.6% positive, min -5.4%, median +4.6%; worst calendar year 2022 at -3.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +17.4%, neighbours median +17.4%, min +14.2%, share profitable 100.0% over 17 neighbours.

Same rule at full size (no sizing, same gate): return +24.7%, max DD 63.8%, Calmar 0.08.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 68 OOS trades): terminal growth p05 0.97× / p50 1.20× / p95 1.58×, P(loss) 8.0%, max DD p50 6.5%, p95 12.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +17.4%, x2: +15.1%, x3: +12.9%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.023 per bar vs observed OOS 0.017 → DSR 0.27.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -4.4%, CAGR -4.4%, Sharpe -1.58, PF 0.29, max DD 5.3%, Calmar -0.83, trades 19.

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (BTC-USDT 6H, no regime gate)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.1% |
| 2022 | -4.8% |
| 2023 | +12.0% |
| 2024 | +3.5% |
| 2025 | +0.2% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -6.5%, median +4.5%; worst calendar year 2022 at -4.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.8%, neighbours median -, min -, share profitable - over 0 neighbours.

Same rule at full size (no sizing, same gate): return +200.5%, max DD 77.6%, Calmar 0.37.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 9 OOS trades): terminal growth p05 0.93× / p50 1.11× / p95 1.35×, P(loss) 16.6%, max DD p50 5.4%, p95 12.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.8%, x2: +11.6%, x3: +11.4%

Deflated Sharpe: 1 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.000 per bar vs observed OOS 0.013 → DSR 0.84.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=no, robust_pm30pct=no

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -4.0%, CAGR -4.0%, Sharpe -1.42, PF 0.00, max DD 5.5%, Calmar -0.73, trades 1.

- passive control: always long, no stop, policy sizing only; excluded from the shortlist (planner decision 6)

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +3.2% |
| 2022 | -4.9% |
| 2023 | +18.4% |
| 2024 | -2.6% |
| 2025 | +2.5% |

Rolling 12-month windows: 41 sampled, 68.3% positive, min -8.9%, median +4.3%; worst calendar year 2022 at -4.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +25.0%, neighbours median +13.5%, min +4.4%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +238.3%, max DD 52.0%, Calmar 0.63.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 155 OOS trades): terminal growth p05 0.91× / p50 1.15× / p95 1.52×, P(loss) 15.8%, max DD p50 9.1%, p95 17.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +25.0%, x2: +22.2%, x3: +19.5%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.015 → DSR 0.05.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 5.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.3% |
| 2022 | -4.2% |
| 2023 | +15.2% |
| 2024 | +2.9% |
| 2025 | +2.1% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -11.1%, median +3.9%; worst calendar year 2022 at -4.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +23.1%, neighbours median +14.7%, min +3.2%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +203.9%, max DD 43.7%, Calmar 0.67.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 146 OOS trades): terminal growth p05 0.91× / p50 1.16× / p95 1.60×, P(loss) 17.1%, max DD p50 9.1%, p95 17.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +23.1%, x2: +20.9%, x3: +18.8%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.035 per bar vs observed OOS 0.016 → DSR 0.06.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.1% |
| 2022 | -3.8% |
| 2023 | +15.3% |
| 2024 | -1.4% |
| 2025 | +1.0% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -6.4%, median +3.7%; worst calendar year 2022 at -3.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +7.3%, neighbours median +5.5%, min -3.9%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +238.3%, max DD 52.0%, Calmar 0.63.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 155 OOS trades): terminal growth p05 0.88× / p50 1.09× / p95 1.40×, P(loss) 26.4%, max DD p50 9.5%, p95 17.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.3%, x2: +5.3%, x3: +3.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.011 → DSR 0.02.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (7 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -2.8% |
| 2023 | +4.6% |
| 2024 | +5.0% |
| 2025 | -3.5% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -9.7%, median +0.7%; worst calendar year 2025 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.2%, neighbours median +9.6%, min +1.3%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +17.7%, max DD 60.6%, Calmar 0.06.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 69 OOS trades): terminal growth p05 0.85× / p50 1.02× / p95 1.31×, P(loss) 44.1%, max DD p50 10.2%, p95 18.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.2%, x2: +8.7%, x3: +7.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.031 per bar vs observed OOS 0.004 → DSR 0.02.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (6 traded, 3 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 19.9%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.4% |
| 2023 | +3.7% |
| 2024 | +4.6% |
| 2025 | -1.7% |

Rolling 12-month windows: 41 sampled, 56.1% positive, min -9.6%, median +0.3%; worst calendar year 2025 at -1.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +18.6%, neighbours median +11.1%, min +2.3%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +43.3%, max DD 61.1%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 48 OOS trades): terminal growth p05 0.88× / p50 1.04× / p95 1.31×, P(loss) 37.5%, max DD p50 8.4%, p95 15.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +18.6%, x2: +12.0%, x3: +11.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.007 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (7 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -2.3% |
| 2023 | +5.3% |
| 2024 | +1.9% |
| 2025 | -3.3% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -8.1%, median +1.3%; worst calendar year 2025 at -3.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.3%, neighbours median +4.7%, min -2.0%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +17.7%, max DD 60.6%, Calmar 0.06.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 69 OOS trades): terminal growth p05 0.88× / p50 1.01× / p95 1.21×, P(loss) 45.1%, max DD p50 8.0%, p95 14.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.3%, x2: +4.2%, x3: +3.3%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.031 per bar vs observed OOS 0.003 → DSR 0.01.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 6H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'trail1'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.6% |
| 2022 | -3.4% |
| 2023 | +5.7% |
| 2024 | +8.8% |
| 2025 | +0.2% |

Rolling 12-month windows: 41 sampled, 82.9% positive, min -3.8%, median +3.3%; worst calendar year 2022 at -3.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +4.3%, neighbours median +3.2%, min -4.6%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +40.2%, max DD 28.5%, Calmar 0.29.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 92 OOS trades): terminal growth p05 0.93× / p50 1.10× / p95 1.33×, P(loss) 17.9%, max DD p50 6.9%, p95 13.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +4.3%, x2: +1.3%, x3: -1.3%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.014 → DSR 0.09.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (7 traded, 4 positive). Most-selected rule: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 4.6%.

| Year | OOS return |
|---|---:|
| 2021 | -3.5% |
| 2022 | -3.2% |
| 2023 | +10.2% |
| 2024 | +7.8% |
| 2025 | +0.0% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -3.9%, median +2.5%; worst calendar year 2021 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +1.6%, neighbours median +3.6%, min -0.5%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +24.1%, max DD 33.0%, Calmar 0.16.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 75 OOS trades): terminal growth p05 0.92× / p50 1.11× / p95 1.38×, P(loss) 19.4%, max DD p50 7.4%, p95 14.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +1.6%, x2: +0.3%, x3: -1.0%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.015 → DSR 0.24.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'trail1'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.9% |
| 2022 | -3.5% |
| 2023 | +6.4% |
| 2024 | +6.2% |
| 2025 | +0.3% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -3.9%, median +2.4%; worst calendar year 2022 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +3.5%, neighbours median -0.3%, min -4.1%, share profitable 50.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +40.2%, max DD 28.5%, Calmar 0.29.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 92 OOS trades): terminal growth p05 0.92× / p50 1.07× / p95 1.27×, P(loss) 24.1%, max DD p50 6.4%, p95 12.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +3.5%, x2: +1.2%, x3: -1.0%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.011 → DSR 0.07.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.6% |
| 2022 | -4.6% |
| 2023 | +8.9% |
| 2024 | +6.5% |
| 2025 | -0.1% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -9.7%, median +3.6%; worst calendar year 2022 at -4.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.6%, neighbours median +11.7%, min -10.7%, share profitable 75.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +99.7%, max DD 58.7%, Calmar 0.30.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 75 OOS trades): terminal growth p05 0.85× / p50 1.10× / p95 1.45×, P(loss) 28.8%, max DD p50 10.3%, p95 19.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.6%, x2: +11.2%, x3: +9.5%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.039 per bar vs observed OOS 0.011 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 2 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 1, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 12.1%.

| Year | OOS return |
|---|---:|
| 2021 | -2.3% |
| 2022 | -8.0% |
| 2023 | +7.1% |
| 2024 | +6.5% |
| 2025 | -4.4% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -9.2%, median +1.7%; worst calendar year 2022 at -8.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -2.5%, neighbours median -6.3%, min -10.7%, share profitable 14.3% over 7 neighbours.

Same rule at full size (no sizing, same gate): return -29.4%, max DD 79.3%, Calmar -0.10.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 107 OOS trades): terminal growth p05 0.77× / p50 0.97× / p95 1.28×, P(loss) 57.6%, max DD p50 14.9%, p95 25.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -2.5%, x2: -3.6%, x3: -5.3%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.045 per bar vs observed OOS -0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +2.3% |
| 2022 | -4.3% |
| 2023 | +19.6% |
| 2024 | -0.7% |
| 2025 | -2.3% |

Rolling 12-month windows: 41 sampled, 75.6% positive, min -5.8%, median +5.1%; worst calendar year 2022 at -4.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +33.1%, neighbours median +24.4%, min +6.7%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +290.7%, max DD 47.8%, Calmar 0.78.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 137 OOS trades): terminal growth p05 0.87× / p50 1.13× / p95 1.54×, P(loss) 21.9%, max DD p50 10.4%, p95 19.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +33.1%, x2: +30.8%, x3: +28.5%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.038 per bar vs observed OOS 0.014 → DSR 0.03.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 6.9%.

| Year | OOS return |
|---|---:|
| 2021 | +1.5% |
| 2022 | -3.9% |
| 2023 | +12.8% |
| 2024 | -0.7% |
| 2025 | -0.5% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -5.3%, median +2.2%; worst calendar year 2022 at -3.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +30.2%, neighbours median +15.7%, min +2.9%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +200.8%, max DD 42.7%, Calmar 0.68.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 134 OOS trades): terminal growth p05 0.84× / p50 1.07× / p95 1.43×, P(loss) 32.2%, max DD p50 11.7%, p95 21.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +30.2%, x2: +24.9%, x3: +22.7%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.041 per bar vs observed OOS 0.009 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (7 traded, 3 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.4% |
| 2023 | +4.3% |
| 2024 | +5.9% |
| 2025 | -3.6% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -9.9%, median +0.8%; worst calendar year 2025 at -3.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.0%, neighbours median +11.1%, min +5.3%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +45.5%, max DD 57.0%, Calmar 0.16.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 66 OOS trades): terminal growth p05 0.84× / p50 1.04× / p95 1.34×, P(loss) 39.5%, max DD p50 10.5%, p95 19.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.0%, x2: +13.0%, x3: +11.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.006 → DSR 0.03.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (6 traded, 3 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 19.2%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.7% |
| 2023 | +3.4% |
| 2024 | +6.8% |
| 2025 | -2.1% |

Rolling 12-month windows: 41 sampled, 56.1% positive, min -8.5%, median +0.4%; worst calendar year 2025 at -2.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.9%, neighbours median +9.6%, min +2.2%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +39.5%, max DD 60.8%, Calmar 0.13.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 50 OOS trades): terminal growth p05 0.87× / p50 1.05× / p95 1.36×, P(loss) 34.4%, max DD p50 8.6%, p95 16.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.9%, x2: +11.9%, x3: +10.9%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.009 → DSR 0.01.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (BTC-USDT 6H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.2% |
| 2022 | -3.8% |
| 2023 | +1.3% |
| 2024 | +5.8% |
| 2025 | -2.0% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -8.2%, median +0.5%; worst calendar year 2022 at -3.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +8.1%, neighbours median +5.6%, min +3.6%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +36.4%, max DD 38.5%, Calmar 0.19.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 88 OOS trades): terminal growth p05 0.84× / p50 0.99× / p95 1.20×, P(loss) 51.8%, max DD p50 9.6%, p95 18.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +8.1%, x2: +6.1%, x3: +1.1%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.000 → DSR 0.03.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (7 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'trail1'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 5.3%.

| Year | OOS return |
|---|---:|
| 2021 | -3.6% |
| 2022 | -4.0% |
| 2023 | +3.1% |
| 2024 | +6.5% |
| 2025 | +0.0% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -6.6%, median +1.4%; worst calendar year 2022 at -4.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -1.7%, neighbours median +0.7%, min -3.2%, share profitable 62.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -6.0%, max DD 36.8%, Calmar -0.04.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 77 OOS trades): terminal growth p05 0.88× / p50 1.02× / p95 1.19×, P(loss) 43.9%, max DD p50 8.2%, p95 15.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -1.7%, x2: -4.0%, x3: -6.0%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.023 per bar vs observed OOS 0.003 → DSR 0.05.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (BTC-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +4.2% |
| 2022 | -5.2% |
| 2023 | +8.1% |
| 2024 | +11.2% |
| 2025 | -3.2% |

Rolling 12-month windows: 41 sampled, 75.6% positive, min -5.2%, median +3.4%; worst calendar year 2022 at -5.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +32.2%, neighbours median +22.7%, min +3.1%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +213.4%, max DD 49.5%, Calmar 0.61.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 127 OOS trades): terminal growth p05 0.91× / p50 1.14× / p95 1.50×, P(loss) 18.4%, max DD p50 8.6%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +32.2%, x2: +30.0%, x3: +15.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.035 per bar vs observed OOS 0.015 → DSR 0.05.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 19.6%.

| Year | OOS return |
|---|---:|
| 2021 | +0.8% |
| 2022 | -5.0% |
| 2023 | +6.3% |
| 2024 | +8.2% |
| 2025 | -2.8% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -6.7%, median +3.8%; worst calendar year 2022 at -5.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.6%, neighbours median +17.5%, min +1.3%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +87.9%, max DD 52.5%, Calmar 0.30.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 109 OOS trades): terminal growth p05 0.84× / p50 1.06× / p95 1.39×, P(loss) 37.2%, max DD p50 11.0%, p95 21.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.6%, x2: +13.3%, x3: +11.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.034 per bar vs observed OOS 0.008 → DSR 0.02.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 6H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +5.4% |
| 2022 | -5.7% |
| 2023 | +16.2% |
| 2024 | +5.3% |
| 2025 | +2.6% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -6.6%, median +3.7%; worst calendar year 2022 at -5.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +23.9%, neighbours median +20.7%, min +6.4%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +225.0%, max DD 54.1%, Calmar 0.58.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 139 OOS trades): terminal growth p05 0.94× / p50 1.23× / p95 1.73×, P(loss) 11.3%, max DD p50 8.7%, p95 16.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +23.9%, x2: +21.1%, x3: +18.5%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.032 per bar vs observed OOS 0.022 → DSR 0.23.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return +2.3%, CAGR +2.3%, Sharpe 0.51, PF 1.48, max DD 3.9%, Calmar 0.58, trades 32.

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 6.3%.

| Year | OOS return |
|---|---:|
| 2021 | +3.2% |
| 2022 | -5.0% |
| 2023 | +10.2% |
| 2024 | +5.5% |
| 2025 | +0.6% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -5.0%, median +2.1%; worst calendar year 2022 at -5.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +21.8%, neighbours median +20.4%, min +4.0%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +189.1%, max DD 46.2%, Calmar 0.60.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 139 OOS trades): terminal growth p05 0.90× / p50 1.14× / p95 1.53×, P(loss) 20.8%, max DD p50 9.5%, p95 17.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +21.8%, x2: +19.6%, x3: +17.6%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.031 per bar vs observed OOS 0.014 → DSR 0.09.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (BTC-USDT 6H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +5.3% |
| 2022 | -5.1% |
| 2023 | +12.8% |
| 2024 | +0.7% |
| 2025 | +2.6% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -6.0%, median +1.9%; worst calendar year 2022 at -5.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +20.3%, neighbours median +19.0%, min +2.5%, share profitable 100.0% over 16 neighbours.

Same rule at full size (no sizing, same gate): return +202.3%, max DD 50.1%, Calmar 0.58.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 141 OOS trades): terminal growth p05 0.91× / p50 1.16× / p95 1.57×, P(loss) 16.9%, max DD p50 9.1%, p95 17.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +20.3%, x2: +17.5%, x3: +15.7%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.039 per bar vs observed OOS 0.016 → DSR 0.03.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 4.5%.

| Year | OOS return |
|---|---:|
| 2021 | +3.2% |
| 2022 | -5.2% |
| 2023 | +13.3% |
| 2024 | -2.2% |
| 2025 | +0.5% |

Rolling 12-month windows: 41 sampled, 68.3% positive, min -6.3%, median +2.1%; worst calendar year 2022 at -5.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +21.7%, neighbours median +21.5%, min +2.8%, share profitable 100.0% over 16 neighbours.

Same rule at full size (no sizing, same gate): return +181.1%, max DD 46.7%, Calmar 0.58.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 135 OOS trades): terminal growth p05 0.87× / p50 1.08× / p95 1.40×, P(loss) 29.6%, max DD p50 10.2%, p95 18.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +21.7%, x2: +19.5%, x3: +17.5%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.010 → DSR 0.02.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 6H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (7 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -2.8% |
| 2023 | +6.3% |
| 2024 | +6.3% |
| 2025 | -3.5% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -9.9%, median +1.1%; worst calendar year 2025 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.2%, neighbours median +10.1%, min +1.5%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +17.7%, max DD 60.6%, Calmar 0.06.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 57 OOS trades): terminal growth p05 0.85× / p50 1.04× / p95 1.38×, P(loss) 38.8%, max DD p50 10.2%, p95 18.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.2%, x2: +8.7%, x3: +7.4%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.007 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (6 traded, 3 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 19.9%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.4% |
| 2023 | +5.3% |
| 2024 | +5.9% |
| 2025 | -1.7% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -9.7%, median +0.6%; worst calendar year 2025 at -1.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.3%, neighbours median +14.1%, min +4.4%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +53.7%, max DD 55.3%, Calmar 0.19.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 35 OOS trades): terminal growth p05 0.88× / p50 1.07× / p95 1.37×, P(loss) 32.6%, max DD p50 8.0%, p95 15.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.3%, x2: +13.6%, x3: +12.5%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.029 per bar vs observed OOS 0.011 → DSR 0.07.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (BTC-USDT 6H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (7 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -2.6% |
| 2023 | +6.4% |
| 2024 | +6.2% |
| 2025 | -3.5% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -9.9%, median +1.3%; worst calendar year 2025 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.8%, neighbours median +10.6%, min +2.9%, share profitable 100.0% over 18 neighbours.

Same rule at full size (no sizing, same gate): return +26.1%, max DD 58.2%, Calmar 0.09.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 56 OOS trades): terminal growth p05 0.85× / p50 1.05× / p95 1.41×, P(loss) 36.8%, max DD p50 10.1%, p95 18.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.8%, x2: +9.5%, x3: +8.1%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.008 → DSR 0.09.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (BTC-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (6 traded, 3 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.25, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.2%, test bear share median 19.0%, entries blocked by the gate 19.9%.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | -1.4% |
| 2023 | +5.3% |
| 2024 | +6.1% |
| 2025 | -1.7% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -9.5%, median +0.6%; worst calendar year 2025 at -1.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +18.4%, neighbours median +17.4%, min +2.3%, share profitable 100.0% over 18 neighbours.

Same rule at full size (no sizing, same gate): return +40.7%, max DD 61.8%, Calmar 0.13.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 35 OOS trades): terminal growth p05 0.88× / p50 1.07× / p95 1.38×, P(loss) 32.0%, max DD p50 7.9%, p95 14.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +18.4%, x2: +11.8%, x3: +10.9%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.035 per bar vs observed OOS 0.011 → DSR 0.03.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (ETH-USDT 4H, no regime gate)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.1% |
| 2022 | -4.1% |
| 2023 | +7.5% |
| 2024 | +1.0% |
| 2025 | +2.5% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -6.0%, median +1.1%; worst calendar year 2022 at -4.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +7.8%, neighbours median -, min -, share profitable - over 0 neighbours.

Same rule at full size (no sizing, same gate): return +59.7%, max DD 80.7%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 9 OOS trades): terminal growth p05 0.91× / p50 1.08× / p95 1.30×, P(loss) 24.8%, max DD p50 5.9%, p95 13.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.8%, x2: +7.7%, x3: +7.5%

Deflated Sharpe: 1 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.000 per bar vs observed OOS 0.008 → DSR 0.78.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=no, robust_pm30pct=no

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -2.6%, CAGR -2.6%, Sharpe -1.27, PF 0.00, max DD 4.0%, Calmar -0.67, trades 1.

- passive control: always long, no stop, policy sizing only; excluded from the shortlist (planner decision 6)

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.1% |
| 2022 | -4.5% |
| 2023 | -2.2% |
| 2024 | +0.6% |
| 2025 | +5.2% |

Rolling 12-month windows: 41 sampled, 31.7% positive, min -8.1%, median -1.8%; worst calendar year 2022 at -4.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +8.9%, neighbours median -3.8%, min -10.0%, share profitable 25.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +130.8%, max DD 37.2%, Calmar 0.57.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 225 OOS trades): terminal growth p05 0.82× / p50 0.99× / p95 1.23×, P(loss) 52.2%, max DD p50 11.9%, p95 22.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +8.9%, x2: +5.7%, x3: +2.5%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.001 → DSR 0.02.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 3.1%.

| Year | OOS return |
|---|---:|
| 2021 | +0.2% |
| 2022 | -3.0% |
| 2023 | -0.6% |
| 2024 | +3.4% |
| 2025 | +5.7% |

Rolling 12-month windows: 41 sampled, 39.0% positive, min -6.6%, median -0.9%; worst calendar year 2022 at -3.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +8.0%, neighbours median +6.3%, min -5.1%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +188.7%, max DD 54.1%, Calmar 0.51.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 150 OOS trades): terminal growth p05 0.88× / p50 1.05× / p95 1.30×, P(loss) 32.8%, max DD p50 8.9%, p95 16.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +8.0%, x2: +6.2%, x3: +4.7%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.005 → DSR 0.10.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.1% |
| 2022 | -0.1% |
| 2023 | -2.0% |
| 2024 | +5.0% |
| 2025 | +1.6% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -4.6%, median +0.4%; worst calendar year 2023 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.7%, neighbours median +0.7%, min -3.2%, share profitable 50.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +130.8%, max DD 37.2%, Calmar 0.57.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 225 OOS trades): terminal growth p05 0.88× / p50 1.04× / p95 1.24×, P(loss) 36.2%, max DD p50 8.5%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.7%, x2: +7.7%, x3: +4.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.005 → DSR 0.06.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.6% |
| 2022 | -0.5% |
| 2023 | +2.5% |
| 2024 | +8.2% |
| 2025 | +6.4% |

Rolling 12-month windows: 41 sampled, 63.4% positive, min -3.7%, median +2.3%; worst calendar year 2021 at -0.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.9%, neighbours median +8.5%, min +0.8%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +102.2%, max DD 51.8%, Calmar 0.34.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 77 OOS trades): terminal growth p05 0.92× / p50 1.15× / p95 1.56×, P(loss) 16.4%, max DD p50 7.5%, p95 14.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.9%, x2: +10.7%, x3: +9.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.013 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'time30'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 1.2%.

| Year | OOS return |
|---|---:|
| 2021 | -0.3% |
| 2022 | +0.5% |
| 2023 | -0.7% |
| 2024 | +4.5% |
| 2025 | -0.8% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -6.1%, median +1.2%; worst calendar year 2025 at -0.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.4%, neighbours median +4.1%, min -3.4%, share profitable 80.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +73.0%, max DD 40.2%, Calmar 0.33.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 86 OOS trades): terminal growth p05 0.84× / p50 1.02× / p95 1.30×, P(loss) 45.1%, max DD p50 11.2%, p95 19.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.4%, x2: +3.1%, x3: +1.9%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.003 → DSR 0.02.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.6% |
| 2022 | +0.9% |
| 2023 | +2.3% |
| 2024 | +10.1% |
| 2025 | +9.5% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -2.2%, median +2.3%; worst calendar year 2021 at -0.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +15.1%, neighbours median +14.3%, min +4.5%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +102.2%, max DD 51.8%, Calmar 0.34.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 77 OOS trades): terminal growth p05 0.98× / p50 1.22× / p95 1.66×, P(loss) 7.8%, max DD p50 5.5%, p95 10.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +15.1%, x2: +13.9%, x3: +12.8%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.019 → DSR 0.28.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 4H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.4% |
| 2022 | -2.3% |
| 2023 | -1.7% |
| 2024 | -0.7% |
| 2025 | -0.5% |

Rolling 12-month windows: 41 sampled, 19.5% positive, min -7.3%, median -2.0%; worst calendar year 2022 at -2.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -2.2%, neighbours median -2.5%, min -16.6%, share profitable 37.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -8.6%, max DD 30.9%, Calmar -0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 81 OOS trades): terminal growth p05 0.83× / p50 0.93× / p95 1.06×, P(loss) 81.1%, max DD p50 11.3%, p95 19.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -2.2%, x2: -3.6%, x3: -4.9%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.048 per bar vs observed OOS -0.010 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 10.6%.

| Year | OOS return |
|---|---:|
| 2021 | -1.3% |
| 2022 | -1.3% |
| 2023 | -2.0% |
| 2024 | +9.9% |
| 2025 | -1.8% |

Rolling 12-month windows: 41 sampled, 41.5% positive, min -4.6%, median -0.7%; worst calendar year 2023 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +2.0%, neighbours median +2.2%, min -9.2%, share profitable 75.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +2.1%, max DD 52.4%, Calmar 0.01.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 90 OOS trades): terminal growth p05 0.88× / p50 1.02× / p95 1.23×, P(loss) 40.6%, max DD p50 8.2%, p95 15.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +2.0%, x2: -0.0%, x3: -1.6%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.042 per bar vs observed OOS 0.004 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 4H, hmm3 bear>=0.5 scale0.25)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.2% |
| 2022 | -1.3% |
| 2023 | -1.7% |
| 2024 | +1.7% |
| 2025 | -0.5% |

Rolling 12-month windows: 41 sampled, 36.6% positive, min -7.3%, median -1.3%; worst calendar year 2023 at -1.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -0.1%, neighbours median +0.1%, min -15.1%, share profitable 50.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -8.6%, max DD 30.9%, Calmar -0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 81 OOS trades): terminal growth p05 0.86× / p50 0.97× / p95 1.10×, P(loss) 67.0%, max DD p50 9.1%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -0.1%, x2: -1.4%, x3: -2.6%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.048 per bar vs observed OOS -0.005 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -1.0% |
| 2023 | +0.3% |
| 2024 | +10.2% |
| 2025 | +4.6% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -7.1%, median +0.4%; worst calendar year 2021 at -1.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +4.3%, neighbours median +5.7%, min -12.0%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +59.2%, max DD 53.4%, Calmar 0.21.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 79 OOS trades): terminal growth p05 0.92× / p50 1.12× / p95 1.47×, P(loss) 19.1%, max DD p50 7.5%, p95 14.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +4.3%, x2: +3.3%, x3: +2.0%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.011 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 1.7%.

| Year | OOS return |
|---|---:|
| 2021 | -0.9% |
| 2022 | -2.8% |
| 2023 | -5.0% |
| 2024 | +2.2% |
| 2025 | +3.7% |

Rolling 12-month windows: 41 sampled, 36.6% positive, min -10.8%, median -1.6%; worst calendar year 2023 at -5.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +4.3%, neighbours median +6.2%, min -1.1%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +82.5%, max DD 61.1%, Calmar 0.24.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 92 OOS trades): terminal growth p05 0.82× / p50 0.96× / p95 1.17×, P(loss) 63.5%, max DD p50 11.4%, p95 20.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +4.3%, x2: +3.3%, x3: +2.8%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS -0.002 → DSR 0.01.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.3% |
| 2022 | -2.3% |
| 2023 | +2.9% |
| 2024 | +3.2% |
| 2025 | +4.7% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -5.1%, median -0.6%; worst calendar year 2022 at -2.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +0.6%, neighbours median +3.4%, min -0.6%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +114.9%, max DD 56.2%, Calmar 0.34.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 154 OOS trades): terminal growth p05 0.90× / p50 1.09× / p95 1.33×, P(loss) 23.8%, max DD p50 8.6%, p95 16.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.6%, x2: -1.1%, x3: -3.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.009 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 2.7%.

| Year | OOS return |
|---|---:|
| 2021 | -1.0% |
| 2022 | -2.3% |
| 2023 | +3.2% |
| 2024 | +5.2% |
| 2025 | +5.6% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -4.3%, median -0.5%; worst calendar year 2022 at -2.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.2%, neighbours median +8.4%, min -1.8%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +224.9%, max DD 53.3%, Calmar 0.58.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 113 OOS trades): terminal growth p05 0.93× / p50 1.12× / p95 1.34×, P(loss) 16.9%, max DD p50 7.2%, p95 13.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.2%, x2: +8.6%, x3: +7.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.010 → DSR 0.19.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.4% |
| 2022 | -0.5% |
| 2023 | +4.8% |
| 2024 | +7.6% |
| 2025 | +6.6% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -4.1%, median +2.7%; worst calendar year 2021 at -1.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.8%, neighbours median +9.7%, min +1.1%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +90.2%, max DD 52.3%, Calmar 0.30.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 76 OOS trades): terminal growth p05 0.92× / p50 1.17× / p95 1.61×, P(loss) 15.2%, max DD p50 7.6%, p95 14.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.8%, x2: +10.0%, x3: +8.9%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.014 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 2.2%.

| Year | OOS return |
|---|---:|
| 2021 | -1.4% |
| 2022 | -0.6% |
| 2023 | +1.5% |
| 2024 | +5.5% |
| 2025 | +4.1% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -4.8%, median +3.0%; worst calendar year 2021 at -1.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.2%, neighbours median +9.7%, min +0.5%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +36.3%, max DD 52.8%, Calmar 0.14.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 108 OOS trades): terminal growth p05 0.89× / p50 1.09× / p95 1.39×, P(loss) 25.9%, max DD p50 9.2%, p95 17.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.2%, x2: +9.1%, x3: +8.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.009 → DSR 0.07.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (ETH-USDT 4H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 2 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -2.6% |
| 2022 | -0.6% |
| 2023 | +0.4% |
| 2024 | -3.1% |
| 2025 | -0.1% |

Rolling 12-month windows: 41 sampled, 24.4% positive, min -5.0%, median -2.1%; worst calendar year 2024 at -3.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -1.1%, neighbours median -1.1%, min -9.9%, share profitable 50.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -2.6%, max DD 27.1%, Calmar -0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 76 OOS trades): terminal growth p05 0.84× / p50 0.94× / p95 1.07×, P(loss) 80.7%, max DD p50 10.0%, p95 17.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -1.1%, x2: -2.3%, x3: -3.4%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.042 per bar vs observed OOS -0.010 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 2 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 9.6%.

| Year | OOS return |
|---|---:|
| 2021 | -2.3% |
| 2022 | -0.4% |
| 2023 | -1.8% |
| 2024 | +6.4% |
| 2025 | -1.3% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -4.6%, median -0.5%; worst calendar year 2021 at -2.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +1.0%, neighbours median +1.8%, min -6.1%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -10.2%, max DD 50.3%, Calmar -0.05.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 90 OOS trades): terminal growth p05 0.86× / p50 1.00× / p95 1.19×, P(loss) 51.7%, max DD p50 9.0%, p95 16.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +1.0%, x2: -0.8%, x3: -2.6%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.001 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (ETH-USDT 4H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +2.9% |
| 2022 | -0.9% |
| 2023 | +2.2% |
| 2024 | +4.5% |
| 2025 | +7.9% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -4.1%, median +2.5%; worst calendar year 2022 at -0.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +24.9%, neighbours median +18.4%, min -0.7%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +250.3%, max DD 45.4%, Calmar 0.74.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 114 OOS trades): terminal growth p05 0.92× / p50 1.16× / p95 1.56×, P(loss) 17.2%, max DD p50 8.7%, p95 15.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +24.9%, x2: +23.4%, x3: +21.9%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.019 per bar vs observed OOS 0.014 → DSR 0.30.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 4.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.8% |
| 2022 | -1.6% |
| 2023 | +4.8% |
| 2024 | +2.9% |
| 2025 | +10.0% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -2.4%, median +1.0%; worst calendar year 2022 at -1.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +23.3%, neighbours median +15.6%, min -11.6%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +193.9%, max DD 46.5%, Calmar 0.61.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 79 OOS trades): terminal growth p05 0.94× / p50 1.15× / p95 1.53×, P(loss) 13.2%, max DD p50 5.9%, p95 11.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +23.3%, x2: +21.7%, x3: +20.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.018 per bar vs observed OOS 0.014 → DSR 0.35.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 4H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.1% |
| 2022 | -4.6% |
| 2023 | -1.8% |
| 2024 | +2.1% |
| 2025 | +4.3% |

Rolling 12-month windows: 41 sampled, 34.1% positive, min -8.2%, median -1.4%; worst calendar year 2022 at -4.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +7.3%, neighbours median +7.4%, min -1.8%, share profitable 80.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +165.1%, max DD 55.1%, Calmar 0.46.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 204 OOS trades): terminal growth p05 0.84× / p50 1.00× / p95 1.25×, P(loss) 48.9%, max DD p50 10.9%, p95 20.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.3%, x2: +6.2%, x3: +4.7%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.015 per bar vs observed OOS 0.001 → DSR 0.09.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 3.8%.

| Year | OOS return |
|---|---:|
| 2021 | +0.2% |
| 2022 | -3.0% |
| 2023 | -0.6% |
| 2024 | +3.4% |
| 2025 | +2.4% |

Rolling 12-month windows: 41 sampled, 39.0% positive, min -6.5%, median -0.8%; worst calendar year 2022 at -3.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.5%, neighbours median +6.6%, min -4.6%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +152.8%, max DD 54.1%, Calmar 0.44.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 168 OOS trades): terminal growth p05 0.85× / p50 1.02× / p95 1.27×, P(loss) 45.2%, max DD p50 10.8%, p95 19.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.5%, x2: +3.9%, x3: +2.4%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.013 per bar vs observed OOS 0.003 → DSR 0.15.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (ETH-USDT 4H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 3.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.1% |
| 2022 | -5.3% |
| 2023 | -1.9% |
| 2024 | +2.3% |
| 2025 | +3.8% |

Rolling 12-month windows: 41 sampled, 34.1% positive, min -8.8%, median -2.1%; worst calendar year 2022 at -5.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +8.4%, neighbours median +8.2%, min -3.9%, share profitable 87.5% over 16 neighbours.

Same rule at full size (no sizing, same gate): return +177.5%, max DD 54.4%, Calmar 0.49.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 200 OOS trades): terminal growth p05 0.82× / p50 0.99× / p95 1.24×, P(loss) 52.5%, max DD p50 11.3%, p95 20.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +8.4%, x2: +7.2%, x3: +5.8%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.018 per bar vs observed OOS 0.000 → DSR 0.04.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 3 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 3.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 3.8%.

| Year | OOS return |
|---|---:|
| 2021 | +0.2% |
| 2022 | -3.0% |
| 2023 | -1.1% |
| 2024 | +3.6% |
| 2025 | +1.5% |

Rolling 12-month windows: 41 sampled, 39.0% positive, min -6.6%, median -1.2%; worst calendar year 2022 at -3.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.7%, neighbours median +10.5%, min -4.6%, share profitable 87.5% over 16 neighbours.

Same rule at full size (no sizing, same gate): return +226.6%, max DD 51.2%, Calmar 0.61.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 169 OOS trades): terminal growth p05 0.83× / p50 0.99× / p95 1.25×, P(loss) 51.6%, max DD p50 11.5%, p95 20.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.7%, x2: +9.3%, x3: +8.0%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.016 per bar vs observed OOS 0.002 → DSR 0.08.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 4H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.5% |
| 2022 | +0.1% |
| 2023 | +4.5% |
| 2024 | +8.2% |
| 2025 | +6.6% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -3.5%, median +3.5%; worst calendar year 2021 at -0.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.9%, neighbours median +11.1%, min +0.6%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +123.7%, max DD 49.9%, Calmar 0.41.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 72 OOS trades): terminal growth p05 0.95× / p50 1.18× / p95 1.61×, P(loss) 10.9%, max DD p50 6.5%, p95 12.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.9%, x2: +11.6%, x3: +10.6%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.029 per bar vs observed OOS 0.016 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 1.1%.

| Year | OOS return |
|---|---:|
| 2021 | +0.4% |
| 2022 | +0.7% |
| 2023 | +0.4% |
| 2024 | +4.5% |
| 2025 | -0.6% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -6.0%, median +1.6%; worst calendar year 2025 at -0.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.4%, neighbours median +5.3%, min -6.0%, share profitable 91.7% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +45.5%, max DD 52.0%, Calmar 0.17.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 80 OOS trades): terminal growth p05 0.85× / p50 1.05× / p95 1.34×, P(loss) 35.8%, max DD p50 10.0%, p95 19.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.4%, x2: +4.3%, x3: +2.3%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.006 → DSR 0.01.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (ETH-USDT 4H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.5% |
| 2022 | -0.2% |
| 2023 | +4.3% |
| 2024 | +8.2% |
| 2025 | +6.6% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -3.4%, median +3.0%; worst calendar year 2021 at -0.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.8%, neighbours median +12.4%, min +4.5%, share profitable 100.0% over 17 neighbours.

Same rule at full size (no sizing, same gate): return +121.9%, max DD 50.1%, Calmar 0.40.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 72 OOS trades): terminal growth p05 0.95× / p50 1.18× / p95 1.61×, P(loss) 12.4%, max DD p50 6.8%, p95 12.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.8%, x2: +11.6%, x3: +10.6%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.036 per bar vs observed OOS 0.016 → DSR 0.03.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (ETH-USDT 4H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 3, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 32.9%, test bear share median 13.1%, entries blocked by the gate 1.1%.

| Year | OOS return |
|---|---:|
| 2021 | +0.4% |
| 2022 | +0.4% |
| 2023 | -0.8% |
| 2024 | +5.3% |
| 2025 | -0.5% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -6.0%, median +1.6%; worst calendar year 2023 at -0.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.6%, neighbours median +9.6%, min -7.0%, share profitable 94.4% over 18 neighbours.

Same rule at full size (no sizing, same gate): return +76.8%, max DD 49.9%, Calmar 0.28.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 80 OOS trades): terminal growth p05 0.85× / p50 1.04× / p95 1.34×, P(loss) 39.1%, max DD p50 10.0%, p95 18.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.6%, x2: +9.4%, x3: +8.3%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.005 → DSR 0.00.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## hold — Always-long reference (sizing overlays only, no stop) (ETH-USDT 6H, no regime gate)

Rule grid: 1 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +2.8% |
| 2022 | -3.5% |
| 2023 | +7.7% |
| 2024 | -0.1% |
| 2025 | +4.0% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -8.8%, median +2.8%; worst calendar year 2022 at -3.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.0%, neighbours median -, min -, share profitable - over 0 neighbours.

Same rule at full size (no sizing, same gate): return +88.4%, max DD 80.5%, Calmar 0.20.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 9 OOS trades): terminal growth p05 0.93× / p50 1.11× / p95 1.33×, P(loss) 17.6%, max DD p50 6.0%, p95 13.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.0%, x2: +10.9%, x3: +10.7%

Deflated Sharpe: 1 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.000 per bar vs observed OOS 0.013 → DSR 0.85.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=no, robust_pm30pct=no

**Holdout (2025-10-20->2026-10-20), evaluated once with the most-selected rule, the policy sizing and a regime model fitted on the whole in-sample span:** return -2.9%, CAGR -2.9%, Sharpe -1.37, PF 0.00, max DD 4.0%, Calmar -0.72, trades 1.

- passive control: always long, no stop, policy sizing only; excluded from the shortlist (planner decision 6)

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.3% |
| 2022 | -2.2% |
| 2023 | +4.1% |
| 2024 | +11.4% |
| 2025 | +2.2% |

Rolling 12-month windows: 41 sampled, 68.3% positive, min -4.2%, median +3.4%; worst calendar year 2022 at -2.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.7%, neighbours median +7.4%, min +2.3%, share profitable 100.0% over 7 neighbours.

Same rule at full size (no sizing, same gate): return +204.5%, max DD 66.6%, Calmar 0.44.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 165 OOS trades): terminal growth p05 0.89× / p50 1.14× / p95 1.57×, P(loss) 20.8%, max DD p50 10.1%, p95 19.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.7%, x2: +9.0%, x3: +8.5%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.015 → DSR 0.19.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 11.2%.

| Year | OOS return |
|---|---:|
| 2021 | +1.5% |
| 2022 | -1.8% |
| 2023 | +5.7% |
| 2024 | +3.1% |
| 2025 | +3.5% |

Rolling 12-month windows: 41 sampled, 80.5% positive, min -4.1%, median +2.0%; worst calendar year 2022 at -1.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.1%, neighbours median +13.3%, min +1.8%, share profitable 100.0% over 7 neighbours.

Same rule at full size (no sizing, same gate): return +211.8%, max DD 59.2%, Calmar 0.51.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 113 OOS trades): terminal growth p05 0.90× / p50 1.10× / p95 1.43×, P(loss) 22.9%, max DD p50 8.7%, p95 16.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.1%, x2: +8.6%, x3: +8.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.013 → DSR 0.21.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -1.1% |
| 2022 | -1.9% |
| 2023 | +5.4% |
| 2024 | +7.0% |
| 2025 | +0.3% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -2.9%, median +3.0%; worst calendar year 2022 at -1.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +7.0%, neighbours median +9.8%, min -3.0%, share profitable 57.1% over 7 neighbours.

Same rule at full size (no sizing, same gate): return +204.5%, max DD 66.6%, Calmar 0.44.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 165 OOS trades): terminal growth p05 0.89× / p50 1.09× / p95 1.41×, P(loss) 28.1%, max DD p50 8.3%, p95 16.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +7.0%, x2: +4.3%, x3: +4.0%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.012 → DSR 0.13.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.4% |
| 2022 | -2.1% |
| 2023 | +0.5% |
| 2024 | +6.3% |
| 2025 | +8.3% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -7.4%, median +0.8%; worst calendar year 2022 at -2.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +12.0%, neighbours median +14.3%, min +1.6%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return -4.6%, max DD 64.9%, Calmar -0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.87× / p50 1.13× / p95 1.59×, P(loss) 25.1%, max DD p50 10.0%, p95 18.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +12.0%, x2: +11.1%, x3: +10.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.029 per bar vs observed OOS 0.015 → DSR 0.14.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (8 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 4.0%.

| Year | OOS return |
|---|---:|
| 2021 | +2.0% |
| 2022 | +0.7% |
| 2023 | +3.4% |
| 2024 | +7.4% |
| 2025 | +8.7% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -6.0%, median +2.8%; worst calendar year 2022 at +0.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.0%, neighbours median +15.6%, min +3.0%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +20.5%, max DD 63.3%, Calmar 0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 52 OOS trades): terminal growth p05 0.92× / p50 1.22× / p95 1.80×, P(loss) 13.8%, max DD p50 7.8%, p95 14.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.0%, x2: +13.1%, x3: +12.4%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.032 per bar vs observed OOS 0.024 → DSR 0.26.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.0% |
| 2022 | -0.7% |
| 2023 | +1.4% |
| 2024 | +2.1% |
| 2025 | +10.0% |

Rolling 12-month windows: 41 sampled, 56.1% positive, min -4.2%, median +0.9%; worst calendar year 2022 at -0.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.2%, neighbours median +12.1%, min +4.6%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return -4.6%, max DD 64.9%, Calmar -0.02.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 85 OOS trades): terminal growth p05 0.89× / p50 1.12× / p95 1.54×, P(loss) 23.2%, max DD p50 7.8%, p95 15.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.2%, x2: +10.3%, x3: +9.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.029 per bar vs observed OOS 0.016 → DSR 0.17.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 6H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -3.9% |
| 2022 | -0.2% |
| 2023 | -3.3% |
| 2024 | +13.9% |
| 2025 | +8.4% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -5.2%, median +0.9%; worst calendar year 2021 at -3.9%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +5.1%, neighbours median +4.0%, min -3.1%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +13.2%, max DD 55.7%, Calmar 0.05.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 88 OOS trades): terminal growth p05 0.94× / p50 1.13× / p95 1.43×, P(loss) 13.5%, max DD p50 6.9%, p95 12.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +5.1%, x2: +3.4%, x3: +1.7%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.020 → DSR 0.33.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (7 traded, 2 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 9.6%.

| Year | OOS return |
|---|---:|
| 2021 | -3.4% |
| 2022 | -1.1% |
| 2023 | -2.2% |
| 2024 | +1.1% |
| 2025 | +8.7% |

Rolling 12-month windows: 41 sampled, 39.0% positive, min -4.5%, median -0.7%; worst calendar year 2021 at -3.4%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -2.9%, neighbours median -1.5%, min -7.8%, share profitable 37.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -20.1%, max DD 56.3%, Calmar -0.09.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 64 OOS trades): terminal growth p05 0.87× / p50 1.01× / p95 1.26×, P(loss) 44.5%, max DD p50 8.3%, p95 15.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -2.9%, x2: -4.3%, x3: -5.7%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.005 → DSR 0.07.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 6H, hmm3 bear>=0.5 scale0.25)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 4 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -4.0% |
| 2022 | -0.3% |
| 2023 | -3.1% |
| 2024 | +3.9% |
| 2025 | +8.9% |

Rolling 12-month windows: 41 sampled, 48.8% positive, min -6.1%, median -0.3%; worst calendar year 2021 at -4.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -2.2%, neighbours median -2.1%, min -6.6%, share profitable 37.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +13.2%, max DD 55.7%, Calmar 0.05.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 88 OOS trades): terminal growth p05 0.90× / p50 1.04× / p95 1.25×, P(loss) 34.7%, max DD p50 7.4%, p95 14.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -2.2%, x2: -3.6%, x3: -5.1%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.009 → DSR 0.09.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.3% |
| 2022 | -1.2% |
| 2023 | -1.8% |
| 2024 | +9.5% |
| 2025 | +3.4% |

Rolling 12-month windows: 41 sampled, 61.0% positive, min -7.7%, median +0.7%; worst calendar year 2023 at -1.8%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +6.8%, neighbours median +10.8%, min +1.1%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +129.5%, max DD 50.4%, Calmar 0.42.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 69 OOS trades): terminal growth p05 0.88× / p50 1.10× / p95 1.46×, P(loss) 27.9%, max DD p50 9.3%, p95 17.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +6.8%, x2: +6.1%, x3: +5.2%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.024 per bar vs observed OOS 0.011 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1w — TSMOM multi-lookback (vol-scaled) — weekly clock (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 1.9%.

| Year | OOS return |
|---|---:|
| 2021 | +0.9% |
| 2022 | -0.5% |
| 2023 | -2.0% |
| 2024 | +7.5% |
| 2025 | +10.6% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -7.5%, median +1.8%; worst calendar year 2023 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.3%, neighbours median +14.1%, min -4.5%, share profitable 75.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +90.4%, max DD 46.0%, Calmar 0.35.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 66 OOS trades): terminal growth p05 0.88× / p50 1.15× / p95 1.66×, P(loss) 21.8%, max DD p50 9.6%, p95 18.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.3%, x2: +11.9%, x3: +10.6%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.017 → DSR 0.26.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 1, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +0.7% |
| 2022 | -1.2% |
| 2023 | +2.1% |
| 2024 | +1.8% |
| 2025 | +5.0% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -5.3%, median +0.8%; worst calendar year 2022 at -1.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +6.1%, neighbours median +10.0%, min +1.7%, share profitable 100.0% over 7 neighbours.

Same rule at full size (no sizing, same gate): return +203.0%, max DD 57.7%, Calmar 0.51.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 117 OOS trades): terminal growth p05 0.90× / p50 1.08× / p95 1.32×, P(loss) 25.9%, max DD p50 8.5%, p95 16.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +6.1%, x2: +3.6%, x3: +2.3%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.023 per bar vs observed OOS 0.010 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1d — TSMOM multi-lookback (vol-scaled) — 1D entry clock (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 3, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 10.7%.

| Year | OOS return |
|---|---:|
| 2021 | -0.0% |
| 2022 | +0.8% |
| 2023 | +1.0% |
| 2024 | -3.7% |
| 2025 | +3.4% |

Rolling 12-month windows: 41 sampled, 41.5% positive, min -6.0%, median -0.5%; worst calendar year 2024 at -3.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.0%, neighbours median +12.8%, min +10.6%, share profitable 100.0% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +132.7%, max DD 36.8%, Calmar 0.59.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 101 OOS trades): terminal growth p05 0.85× / p50 1.00× / p95 1.22×, P(loss) 49.1%, max DD p50 9.8%, p95 18.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.0%, x2: +11.3%, x3: +9.8%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.002 → DSR 0.06.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (8 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.4% |
| 2022 | +0.8% |
| 2023 | +0.2% |
| 2024 | +9.1% |
| 2025 | +8.0% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -5.1%, median +1.8%; worst calendar year 2023 at +0.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.5%, neighbours median +13.5%, min -0.7%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return -1.6%, max DD 62.2%, Calmar -0.01.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 57 OOS trades): terminal growth p05 0.90× / p50 1.18× / p95 1.67×, P(loss) 18.9%, max DD p50 9.2%, p95 17.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.5%, x2: +10.6%, x3: +9.7%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.020 → DSR 0.20.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2d — Donchian breakout + volume/ATR filters — 1D entry clock (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (7 traded, 5 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 4.1%.

| Year | OOS return |
|---|---:|
| 2021 | +2.3% |
| 2022 | +0.7% |
| 2023 | -1.1% |
| 2024 | +9.2% |
| 2025 | +8.4% |

Rolling 12-month windows: 41 sampled, 65.9% positive, min -3.9%, median +2.0%; worst calendar year 2023 at -1.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +13.4%, neighbours median +14.7%, min +1.2%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +25.6%, max DD 59.2%, Calmar 0.09.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 43 OOS trades): terminal growth p05 0.91× / p50 1.19× / p95 1.70×, P(loss) 17.2%, max DD p50 8.0%, p95 15.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +13.4%, x2: +12.5%, x3: +11.7%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.022 → DSR 0.26.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (ETH-USDT 6H, no regime gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (9 traded, 2 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -4.6% |
| 2022 | -0.8% |
| 2023 | -3.6% |
| 2024 | +9.1% |
| 2025 | +6.2% |

Rolling 12-month windows: 41 sampled, 46.3% positive, min -5.5%, median -1.0%; worst calendar year 2021 at -4.6%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.3%, neighbours median +4.5%, min -1.2%, share profitable 87.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return +34.7%, max DD 44.9%, Calmar 0.16.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 94 OOS trades): terminal growth p05 0.89× / p50 1.05× / p95 1.29×, P(loss) 31.6%, max DD p50 8.2%, p95 15.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.3%, x2: +8.7%, x3: +7.1%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.009 → DSR 0.10.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4d — Vol-compression (BB squeeze) breakout — 1D entry clock (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 48 combinations (entries × exit brackets). Windows: 9 (6 traded, 2 positive). Most-selected rule: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0, 'bracket': 'tp2'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 9.7%.

| Year | OOS return |
|---|---:|
| 2021 | -4.1% |
| 2022 | -0.6% |
| 2023 | +0.0% |
| 2024 | +0.2% |
| 2025 | +8.0% |

Rolling 12-month windows: 41 sampled, 39.0% positive, min -4.7%, median +0.0%; worst calendar year 2021 at -4.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -1.7%, neighbours median -1.7%, min -8.2%, share profitable 37.5% over 8 neighbours.

Same rule at full size (no sizing, same gate): return -24.4%, max DD 54.5%, Calmar -0.12.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 54 OOS trades): terminal growth p05 0.90× / p50 1.02× / p95 1.22×, P(loss) 40.8%, max DD p50 6.4%, p95 12.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -1.7%, x2: -3.0%, x3: -4.3%

Deflated Sharpe: 48 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.022 per bar vs observed OOS 0.007 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (ETH-USDT 6H, no regime gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.2% |
| 2022 | -1.2% |
| 2023 | +5.0% |
| 2024 | +5.0% |
| 2025 | +8.8% |

Rolling 12-month windows: 41 sampled, 73.2% positive, min -2.9%, median +1.9%; worst calendar year 2022 at -1.2%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +24.1%, neighbours median +19.3%, min +11.4%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +183.5%, max DD 42.2%, Calmar 0.65.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 99 OOS trades): terminal growth p05 0.95× / p50 1.18× / p95 1.56×, P(loss) 11.2%, max DD p50 7.7%, p95 14.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +24.1%, x2: +22.6%, x3: +21.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.025 per bar vs observed OOS 0.019 → DSR 0.31.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1h — TSMOM multi-lookback — hysteresis bands (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 144 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 3, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'entry_band': 0.1, 'exit_band': 0.25, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 16.5%.

| Year | OOS return |
|---|---:|
| 2021 | +0.2% |
| 2022 | -2.0% |
| 2023 | +5.9% |
| 2024 | -0.5% |
| 2025 | +8.5% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -2.7%, median +1.0%; worst calendar year 2022 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +10.2%, neighbours median +14.2%, min +5.5%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +83.5%, max DD 34.6%, Calmar 0.44.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 90 OOS trades): terminal growth p05 0.90× / p50 1.11× / p95 1.41×, P(loss) 21.2%, max DD p50 8.3%, p95 16.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +10.2%, x2: +8.1%, x3: +6.1%

Deflated Sharpe: 144 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.023 per bar vs observed OOS 0.013 → DSR 0.22.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 6H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 30, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.3% |
| 2022 | -2.3% |
| 2023 | +5.3% |
| 2024 | +7.3% |
| 2025 | +2.2% |

Rolling 12-month windows: 41 sampled, 68.3% positive, min -4.2%, median +3.4%; worst calendar year 2022 at -2.3%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.8%, neighbours median +9.4%, min -4.6%, share profitable 90.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +175.1%, max DD 48.6%, Calmar 0.54.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 145 OOS trades): terminal growth p05 0.89× / p50 1.11× / p95 1.46×, P(loss) 22.4%, max DD p50 9.3%, p95 17.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.8%, x2: +6.4%, x3: +4.7%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.012 → DSR 0.26.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [7, 14, 30], 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 11.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.5% |
| 2022 | -2.0% |
| 2023 | +8.1% |
| 2024 | +2.8% |
| 2025 | +2.2% |

Rolling 12-month windows: 41 sampled, 80.5% positive, min -4.3%, median +2.3%; worst calendar year 2022 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.1%, neighbours median +12.0%, min +3.7%, share profitable 100.0% over 10 neighbours.

Same rule at full size (no sizing, same gate): return +88.2%, max DD 39.0%, Calmar 0.40.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 101 OOS trades): terminal growth p05 0.88× / p50 1.12× / p95 1.51×, P(loss) 23.0%, max DD p50 9.0%, p95 17.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.1%, x2: +8.6%, x3: +6.4%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.017 per bar vs observed OOS 0.014 → DSR 0.39.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (ETH-USDT 6H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 5 positive). Most-selected rule: `{'lookbacks_days': [30, 60, 90], 'vote': 2, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | -0.3% |
| 2022 | -2.5% |
| 2023 | +4.8% |
| 2024 | +0.3% |
| 2025 | +1.3% |

Rolling 12-month windows: 41 sampled, 53.7% positive, min -6.0%, median +0.5%; worst calendar year 2022 at -2.5%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set -4.0%, neighbours median -4.0%, min -5.8%, share profitable 26.7% over 15 neighbours.

Same rule at full size (no sizing, same gate): return +48.0%, max DD 62.8%, Calmar 0.15.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 145 OOS trades): terminal growth p05 0.86× / p50 1.03× / p95 1.27×, P(loss) 41.4%, max DD p50 10.0%, p95 18.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -4.0%, x2: -5.6%, x3: -6.4%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.004 → DSR 0.04.

Checks: pf_gt_1_2=no, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=no

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S1+S5s — TSMOM multi-lookback (vol-scaled) + positioning filter (7–14d funding window, OI change) (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 6 positive). Most-selected rule: `{'lookbacks_days': [14, 30, 60], 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'entry_band': 0.0, 'exit_band': 0.0, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 10.8%.

| Year | OOS return |
|---|---:|
| 2021 | +1.5% |
| 2022 | -1.7% |
| 2023 | +5.5% |
| 2024 | +3.1% |
| 2025 | +1.7% |

Rolling 12-month windows: 41 sampled, 78.0% positive, min -4.0%, median +2.1%; worst calendar year 2022 at -1.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +11.0%, neighbours median +10.9%, min +1.8%, share profitable 100.0% over 14 neighbours.

Same rule at full size (no sizing, same gate): return +240.0%, max DD 55.5%, Calmar 0.59.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 112 OOS trades): terminal growth p05 0.88× / p50 1.09× / p95 1.39×, P(loss) 27.2%, max DD p50 9.2%, p95 17.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.0%, x2: +9.5%, x3: +9.0%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.021 per bar vs observed OOS 0.011 → DSR 0.21.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=yes, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 6H, no regime gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.0% |
| 2022 | -2.0% |
| 2023 | +2.0% |
| 2024 | +6.6% |
| 2025 | +8.3% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -7.3%, median +1.5%; worst calendar year 2022 at -2.0%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +15.1%, neighbours median +16.7%, min +7.6%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +63.6%, max DD 48.0%, Calmar 0.25.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 67 OOS trades): terminal growth p05 0.87× / p50 1.13× / p95 1.63×, P(loss) 23.2%, max DD p50 9.8%, p95 18.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +15.1%, x2: +13.9%, x3: +12.7%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.026 per bar vs observed OOS 0.017 → DSR 0.25.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 108 combinations (entries × exit brackets). Windows: 9 (8 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 4.0%.

| Year | OOS return |
|---|---:|
| 2021 | +2.0% |
| 2022 | +0.7% |
| 2023 | +3.4% |
| 2024 | +7.1% |
| 2025 | +8.7% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -6.3%, median +2.8%; worst calendar year 2022 at +0.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.1%, neighbours median +15.1%, min +3.0%, share profitable 100.0% over 12 neighbours.

Same rule at full size (no sizing, same gate): return +20.3%, max DD 63.4%, Calmar 0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 51 OOS trades): terminal growth p05 0.93× / p50 1.21× / p95 1.73×, P(loss) 14.1%, max DD p50 7.3%, p95 14.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.1%, x2: +13.1%, x3: +12.4%

Deflated Sharpe: 108 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.030 per bar vs observed OOS 0.023 → DSR 0.29.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (ETH-USDT 6H, no regime gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (9 traded, 7 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 3.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.1, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median -, test bear share median -, entries blocked by the gate 0.0%.

| Year | OOS return |
|---|---:|
| 2021 | +1.0% |
| 2022 | -2.1% |
| 2023 | +0.5% |
| 2024 | +6.9% |
| 2025 | +8.3% |

Rolling 12-month windows: 41 sampled, 58.5% positive, min -6.8%, median +1.2%; worst calendar year 2022 at -2.1%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +17.8%, neighbours median +17.8%, min +12.7%, share profitable 100.0% over 17 neighbours.

Same rule at full size (no sizing, same gate): return +93.6%, max DD 45.7%, Calmar 0.36.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 68 OOS trades): terminal growth p05 0.87× / p50 1.13× / p95 1.59×, P(loss) 24.6%, max DD p50 10.1%, p95 18.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +17.8%, x2: +16.8%, x3: +15.9%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.031 per bar vs observed OOS 0.016 → DSR 0.11.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=no, calmar_gt_0_5=no, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## S2+S5s — Donchian breakout + volume/ATR filters + positioning filter (7–14d funding window, OI change) (ETH-USDT 6H, hmm3 bear>=0.5 gate)

Rule grid: 576 combinations (entries × exit brackets). Windows: 9 (8 traded, 6 positive). Most-selected rule: `{'entry_days': 10, 'exit_days': 20, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 21, 'oi_change_max': 0.25, 'oi_change_window_days': 1, 'bracket': 'none'}`. Policy sizing: `vt10/30 crash15/90dh ladder`. Regime: train bear share median 35.2%, test bear share median 18.9%, entries blocked by the gate 4.1%.

| Year | OOS return |
|---|---:|
| 2021 | +2.0% |
| 2022 | +0.7% |
| 2023 | +3.4% |
| 2024 | +7.7% |
| 2025 | +8.7% |

Rolling 12-month windows: 41 sampled, 70.7% positive, min -5.8%, median +2.8%; worst calendar year 2022 at +0.7%.

Robustness (rule parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters, the same per-window regime gate and the policy sizing over every test window): selected set +14.0%, neighbours median +14.0%, min +3.0%, share profitable 100.0% over 17 neighbours.

Same rule at full size (no sizing, same gate): return +20.5%, max DD 63.3%, Calmar 0.07.

Monte Carlo (trade-order bootstrap of equity-level trade returns, 2000 paths over 50 OOS trades): terminal growth p05 0.94× / p50 1.23× / p95 1.72×, P(loss) 12.2%, max DD p50 7.3%, p95 13.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +14.0%, x2: +13.1%, x3: +12.4%

Deflated Sharpe: 576 rule trials in the last train window (× 3 regime modes tried a priori), expected max SR (zero skill) 0.037 per bar vs observed OOS 0.024 → DSR 0.15.

Checks: pf_gt_1_2=yes, max_dd_lt_20pct=yes, sharpe_gt_0_7=yes, calmar_gt_0_5=yes, rolling_12m_75pct_positive=no, no_calendar_year_below_minus_10pct=yes, enough_trades=yes, robust_pm30pct=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data (binance) cover 100.0% of in-sample bars (filter passes elsewhere)

## Owner decisions (nothing below is decided by this report)

- **Acceptance clause.** Fewer than two configurations passed. The report's next-step sentence states, with numbers, that long-only timing does not reliably beat vol-targeted holding. Confirm the pivot of the Phase 7/8 product to 'risk-managed exposure + news brake' and authorize the Phase 9 long/short DESIGN STUDY (research only, no derivatives access) as the next research priority — or ask for one more research sprint on a specific idea.
- **Paper fleet anyway?** Forward evidence on live public data is cheap. Recommended: start the fleet with the shortlist AND the controls (hold + policy sizing on BTC and ETH, plain buy-and-hold) even if nothing passed, so the next decision rests on forward numbers.
- **Regime gate.** In other words, the gate cost more return than it saved: the bear state also contains the recoveries these rules need. The gate threshold (0.5), the number of states and the modes were fixed before the run; changing them after seeing these results would be tuning on the test set — if you want a sweep, it is a new, pre-registered sprint, not an edit of this one.
- **FOMC calendar.** The S0 filter's scheduled-event windows use a calendar written from memory (`research/events.py`). Verify it against federalreserve.gov (or supply a JSON calendar) before any forward run relies on it; its effect on these numbers is small.
- **Positioning data.** Keep the nightly Binance public funding/open-interest top-up (research only) as decided? The 7–14-day funding window changed little; dropping S5 from the fleet would simplify it.

## Method notes and caveats

- Engine, sizing overlays, brackets, staged rule selection and the stitched out-of-sample construction are the Sprint 2b ones (`docs/RESEARCH_LAB.md`); the only new element inside a window is the regime gate, which is fitted on the train slice and applied forward (filtered probabilities, never smoothed), to entries only.
- The regime model is a diagonal-Gaussian HMM written for this repository (`research/hmm.py`), not `hmmlearn`: the lockfile stays audited and the filter exposes the forward-only posterior a trading decision needs. Tests check that the filtered probability of a bar does not change when later bars are appended.
- The yearly gate v2 samples trailing 12-month returns every 30 days along the stitched curve (overlapping windows, so the share is a smoothed statistic, not independent trials) and judges calendar years with at least 60 days of data.
- The fixed policy sizing was declared before the run (Sprint 2b's `vt10/30 crash15/90dh ladder`); the train-selected sizing is a comparison, not a proposal. The regime modes (none / gate / scale), the gate threshold and the turnover clocks were also fixed before the run; they still multiply the number of things tried, which is why the deflated Sharpe stays low.
- The FOMC calendar inside the S0 filter was written from memory of the published schedules; the owner should verify it before it matters (it blocks a few bars per meeting at 4H/6H, so its effect on these numbers is small).
- Portfolio-level sizing uses only past days for weights and the vol scale; the sleeve choice (timeframe per family and instrument) is a mild selection on OOS data, so portfolio numbers are slightly optimistic.
- Every number is a simulation on historical public data and proves nothing about the future.
