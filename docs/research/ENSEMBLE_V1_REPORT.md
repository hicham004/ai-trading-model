# Ensemble v1 — walk-forward research report (SIMULATION ONLY)

Generated 2026-10-20 10:42 UTC by `scripts/run_research.py`. Data: PUBLIC OKX spot candles from the Parquet lake (BTC-USDT 1H: 2019-12-28→2026-10-20 (59699 bars); BTC-USDT 4H: 2019-12-16→2026-10-20 (14999 bars); BTC-USDT 1D: 2019-12-16→2026-10-18 (2499 bars); ETH-USDT 1H: 2019-12-28→2026-10-20 (59699 bars); ETH-USDT 4H: 2019-12-16→2026-10-20 (14999 bars); ETH-USDT 1D: 2019-12-16→2026-10-18 (2499 bars)). Costs: fee 0.10% per side + slippage 0.050% per side. Sizing: 100% of equity per entry (gross edge; production sizing is smaller). Long-only spot. Walk-forward: train 540d → purge 7d → test 180d, rolling; selection by sharpe with ≥20 train trades. Holdout: last 12 months (2025-10-18→2026-10-18), evaluated once and only for candidates that passed walk-forward.

**Nothing here authorizes paper, demo or live trading.** A passing candidate is a hypothesis for the forward paper fleet (Sprint 5), not a strategy to deploy.

## Acceptance criteria (master plan, Sprint 2)

- Out-of-sample profit factor > 1.2 after costs
- Positive in ≥ 3 of 4 yearly out-of-sample windows
- Max drawdown < 20%
- Not dependent on one parameter: ≥ 50% of grid neighbours within ±30% stay profitable
- At least 30 out-of-sample trades

## Summary

| Candidate | Series | OOS return | CAGR | Sharpe | Sortino | PF | Max DD | Trades | Win | Exposure | Fees/yr | Pos. years | Robust ±30% | DSR | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| baseline | BTC-USDT 1H | -48.2% | -14.1% | -0.23 | -0.32 | 0.94 | 73.6% | 390 | 25.9% | 51.6% | 17.6% | 2/5 | 25.0% | 0.00 | fail |
| S1 | BTC-USDT 1H | +9.6% | +2.2% | 0.23 | 0.33 | 1.13 | 50.2% | 341 | 17.0% | 48.8% | 14.6% | 3/5 | 100.0% | 0.04 | fail |
| S2 | BTC-USDT 1H | +0.2% | +0.1% | 0.18 | 0.25 | 1.13 | 53.5% | 117 | 14.5% | 51.0% | 5.0% | 3/5 | 90.0% | 0.28 | fail |
| S3 | BTC-USDT 1H | -55.2% | -17.0% | -1.53 | -2.00 | 0.50 | 57.1% | 133 | 42.1% | 3.7% | 5.8% | 0/5 | 0.0% | 0.00 | fail |
| S4 | BTC-USDT 1H | -49.4% | -14.6% | -0.76 | -1.11 | 0.78 | 56.2% | 347 | 26.8% | 14.4% | 15.5% | 0/5 | 12.5% | 0.00 | fail |
| S1+S5 | BTC-USDT 1H | +9.6% | +2.2% | 0.23 | 0.33 | 1.13 | 50.2% | 341 | 17.0% | 48.8% | 14.6% | 3/5 | 100.0% | 0.02 | fail |
| S2+S5 | BTC-USDT 1H | +0.2% | +0.1% | 0.18 | 0.25 | 1.13 | 53.5% | 117 | 14.5% | 51.0% | 5.0% | 3/5 | 91.7% | 0.22 | fail |
| baseline | BTC-USDT 4H | +33.3% | +6.8% | 0.36 | 0.52 | 1.20 | 59.0% | 153 | 28.8% | 51.9% | 6.8% | 2/5 | 75.0% | 0.14 | fail |
| S1 | BTC-USDT 4H | +30.0% | +6.2% | 0.35 | 0.50 | 1.17 | 57.0% | 172 | 27.9% | 52.5% | 8.0% | 4/5 | 87.5% | 0.17 | fail |
| S2 | BTC-USDT 4H | +51.8% | +10.1% | 0.45 | 0.66 | 1.30 | 50.2% | 84 | 25.0% | 46.0% | 3.9% | 3/5 | 100.0% | 0.37 | fail |
| S3 | BTC-USDT 4H | -6.0% | -1.4% | -0.01 | -0.01 | 0.99 | 32.7% | 100 | 49.0% | 6.8% | 4.6% | 2/5 | 40.0% | 0.01 | fail |
| S4 | BTC-USDT 4H | +36.4% | +7.4% | 0.44 | 0.68 | 1.29 | 31.6% | 98 | 33.7% | 17.7% | 4.4% | 2/5 | 100.0% | 0.44 | fail |
| S1+S5 | BTC-USDT 4H | +30.0% | +6.2% | 0.35 | 0.50 | 1.17 | 57.0% | 172 | 27.9% | 52.5% | 8.0% | 4/5 | 90.0% | 0.11 | fail |
| S2+S5 | BTC-USDT 4H | +51.8% | +10.1% | 0.45 | 0.66 | 1.30 | 50.2% | 84 | 25.0% | 46.0% | 3.9% | 3/5 | 100.0% | 0.29 | fail |
| baseline | BTC-USDT 1D | +44.2% | +8.8% | 0.42 | 0.65 | 1.48 | 45.9% | 92 | 18.5% | 47.9% | 3.8% | 2/5 | 100.0% | 0.21 | fail |
| S1 | BTC-USDT 1D | +3.3% | +0.8% | 0.21 | 0.31 | 1.14 | 62.9% | 107 | 28.0% | 51.2% | 4.8% | 3/5 | 100.0% | 0.18 | fail |
| S2 | BTC-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 90.0% | 0.14 | fail |
| S3 | BTC-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 20.0% | 0.00 | fail |
| S4 | BTC-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 25.0% | 0.04 | fail |
| S1+S5 | BTC-USDT 1D | +3.3% | +0.8% | 0.21 | 0.31 | 1.14 | 62.9% | 107 | 28.0% | 51.2% | 4.8% | 3/5 | 100.0% | 0.12 | fail |
| S2+S5 | BTC-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 91.7% | 0.10 | fail |
| baseline | ETH-USDT 1H | -73.5% | -26.5% | -0.44 | -0.63 | 0.89 | 89.9% | 532 | 25.0% | 51.0% | 23.7% | 1/5 | 0.0% | 0.00 | fail |
| S1 | ETH-USDT 1H | -38.8% | -10.8% | 0.00 | 0.00 | 0.97 | 82.8% | 357 | 20.2% | 50.5% | 15.8% | 2/5 | 42.9% | 0.04 | fail |
| S2 | ETH-USDT 1H | -59.7% | -19.0% | -0.26 | -0.35 | 0.78 | 79.0% | 131 | 10.7% | 41.4% | 5.4% | 1/5 | 40.0% | 0.04 | fail |
| S3 | ETH-USDT 1H | -33.0% | -8.9% | -0.56 | -0.77 | 0.79 | 48.5% | 127 | 48.8% | 3.4% | 5.8% | 1/5 | 0.0% | 0.00 | fail |
| S4 | ETH-USDT 1H | -69.3% | -24.0% | -1.14 | -1.69 | 0.72 | 76.3% | 388 | 24.5% | 13.0% | 17.2% | 0/5 | 0.0% | 0.00 | fail |
| S1+S5 | ETH-USDT 1H | -38.8% | -10.8% | 0.00 | 0.00 | 0.97 | 82.8% | 357 | 20.2% | 50.5% | 15.8% | 2/5 | 55.6% | 0.02 | fail |
| S2+S5 | ETH-USDT 1H | -59.7% | -19.0% | -0.26 | -0.35 | 0.78 | 79.0% | 131 | 10.7% | 41.4% | 5.4% | 1/5 | 33.3% | 0.02 | fail |
| baseline | ETH-USDT 4H | +4.9% | +1.1% | 0.26 | 0.37 | 1.10 | 60.0% | 194 | 24.7% | 49.5% | 8.7% | 2/5 | 50.0% | 0.18 | fail |
| S1 | ETH-USDT 4H | +40.7% | +8.2% | 0.41 | 0.59 | 1.27 | 80.6% | 207 | 27.5% | 58.4% | 9.5% | 3/5 | 50.0% | 0.32 | fail |
| S2 | ETH-USDT 4H | +110.5% | +18.7% | 0.62 | 0.91 | 1.50 | 50.1% | 76 | 21.1% | 41.6% | 3.4% | 4/5 | 90.0% | 0.19 | fail |
| S3 | ETH-USDT 4H | -28.4% | -7.4% | -0.29 | -0.42 | 0.88 | 52.1% | 94 | 41.5% | 5.0% | 4.1% | 3/5 | 20.0% | 0.00 | fail |
| S4 | ETH-USDT 4H | -35.7% | -9.7% | -0.33 | -0.47 | 0.80 | 53.0% | 86 | 23.3% | 13.3% | 3.8% | 2/5 | 37.5% | 0.00 | fail |
| S1+S5 | ETH-USDT 4H | +40.7% | +8.2% | 0.41 | 0.59 | 1.27 | 80.6% | 207 | 27.5% | 58.4% | 9.5% | 3/5 | 60.0% | 0.24 | fail |
| S2+S5 | ETH-USDT 4H | +110.5% | +18.7% | 0.62 | 0.91 | 1.50 | 50.1% | 76 | 21.1% | 41.6% | 3.4% | 4/5 | 91.7% | 0.10 | fail |
| baseline | ETH-USDT 1D | -49.3% | -14.5% | -0.14 | -0.21 | 0.82 | 78.7% | 135 | 15.6% | 42.5% | 5.7% | 2/5 | 100.0% | 0.10 | fail |
| S1 | ETH-USDT 1D | -27.0% | -7.0% | 0.09 | 0.13 | 0.99 | 72.4% | 91 | 26.4% | 45.4% | 4.3% | 4/5 | 50.0% | 0.11 | fail |
| S2 | ETH-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 100.0% | 0.08 | fail |
| S3 | ETH-USDT 1D | +11.6% | +2.6% | 0.79 | 26.26 | 999.00 | 0.1% | 2 | 100.0% | 0.2% | 0.1% | 1/5 | 50.0% | 0.02 | fail |
| S4 | ETH-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 100.0% | 0.09 | fail |
| S1+S5 | ETH-USDT 1D | -27.0% | -7.0% | 0.09 | 0.13 | 0.99 | 72.4% | 91 | 26.4% | 45.4% | 4.3% | 4/5 | 60.0% | 0.07 | fail |
| S2+S5 | ETH-USDT 1D | +0.0% | +0.0% | 0.00 | 0.00 | 0.00 | -0.0% | 0 | 0.0% | 0.0% | 0.0% | 0/5 | 100.0% | 0.05 | fail |

Candidates passing all criteria: **0** of 42.

Buy-and-hold over the same out-of-sample span (after costs):

- BTC-USDT 1H: +237.8% total, max DD 77.2%
- BTC-USDT 4H: +176.1% total, max DD 77.0%
- BTC-USDT 1D: +166.5% total, max DD 76.4%
- ETH-USDT 1H: +106.6% total, max DD 81.3%
- ETH-USDT 4H: +56.0% total, max DD 81.1%
- ETH-USDT 1D: +51.7% total, max DD 79.6%

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (BTC-USDT 1H)

Grid: 18 combinations. Windows: 9 (9 traded, 3 positive). Most-selected parameters: `{'short_window': 20, 'long_window': 100, 'stop_loss_pct': 0.04}`.

| Year | OOS return |
|---|---:|
| 2021 | -8.1% |
| 2022 | -56.2% |
| 2023 | +17.4% |
| 2024 | +29.6% |
| 2025 | -15.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -38.0% | -1.98 |
| highvol_range | 3.1% | +10.0% | 2.01 |
| highvol_up | 11.8% | +4.3% | 0.41 |
| lowvol_down | 13.6% | -39.0% | -3.05 |
| lowvol_range | 13.7% | +5.2% | 0.46 |
| lowvol_up | 18.1% | -12.1% | -0.39 |
| midvol_down | 7.5% | -15.9% | -1.09 |
| midvol_range | 7.4% | +23.8% | 2.02 |
| midvol_up | 14.2% | +24.0% | 1.13 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -14.5%, neighbours median -16.9%, min -49.1%, share profitable 25.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 390 OOS trades): terminal growth p05 0.12× / p50 0.52× / p95 2.33×, P(loss) 77.2%, max DD p50 71.4%, p95 90.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -48.2%, x2: -64.9%, x3: -76.3%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.019 per bar vs observed OOS -0.002 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 1H)

Grid: 36 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'lookbacks_days': (30, 60, 90), 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | +35.3% |
| 2022 | -37.2% |
| 2023 | +47.0% |
| 2024 | +10.9% |
| 2025 | -20.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -32.3% | -4.33 |
| highvol_range | 3.1% | -0.8% | 0.02 |
| highvol_up | 11.8% | +62.9% | 2.02 |
| lowvol_down | 13.6% | -17.0% | -2.49 |
| lowvol_range | 13.7% | +14.2% | 0.92 |
| lowvol_up | 18.1% | +6.7% | 0.41 |
| midvol_down | 7.5% | -26.1% | -3.50 |
| midvol_range | 7.4% | +11.6% | 1.17 |
| midvol_up | 14.2% | +20.2% | 0.94 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +51.1%, neighbours median +54.7%, min +41.2%, share profitable 100.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 341 OOS trades): terminal growth p05 0.26× / p50 1.06× / p95 5.83×, P(loss) 47.9%, max DD p50 58.3%, p95 81.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +9.6%, x2: -22.1%, x3: -44.6%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.012 per bar vs observed OOS 0.002 → DSR 0.04 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 1H)

Grid: 36 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 3.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | +41.1% |
| 2022 | -34.7% |
| 2023 | +13.8% |
| 2024 | +33.6% |
| 2025 | -28.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -27.5% | -2.41 |
| highvol_range | 3.1% | -10.2% | -1.85 |
| highvol_up | 11.8% | +35.4% | 1.36 |
| lowvol_down | 13.6% | -19.0% | -1.74 |
| lowvol_range | 13.7% | +3.5% | 0.35 |
| lowvol_up | 18.1% | +16.7% | 0.75 |
| midvol_down | 7.5% | -26.2% | -2.39 |
| midvol_range | 7.4% | +48.6% | 3.56 |
| midvol_up | 14.2% | +6.0% | 0.44 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +41.6%, neighbours median +17.3%, min -26.4%, share profitable 90.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 117 OOS trades): terminal growth p05 0.29× / p50 0.94× / p95 3.75×, P(loss) 53.1%, max DD p50 54.7%, p95 76.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.2%, x2: -10.8%, x3: -20.7%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.005 per bar vs observed OOS 0.002 → DSR 0.28 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (BTC-USDT 1H)

Grid: 54 combinations. Windows: 9 (9 traded, 1 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 25.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -2.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 2.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | -11.8% |
| 2022 | -31.4% |
| 2023 | -10.5% |
| 2024 | -6.3% |
| 2025 | -11.7% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -14.1% | -4.22 |
| highvol_range | 3.1% | +1.9% | 0.82 |
| highvol_up | 11.8% | +14.3% | 3.35 |
| lowvol_down | 13.6% | -18.3% | -2.94 |
| lowvol_range | 13.7% | -29.1% | -4.35 |
| lowvol_up | 18.1% | +1.8% | 0.39 |
| midvol_down | 7.5% | -9.1% | -2.69 |
| midvol_range | 7.4% | -21.6% | -3.14 |
| midvol_up | 14.2% | +6.6% | 1.16 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -39.6%, neighbours median -40.2%, min -68.5%, share profitable 0.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 133 OOS trades): terminal growth p05 0.30× / p50 0.45× / p95 0.66×, P(loss) 100.0%, max DD p50 57.3%, p95 70.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -55.2%, x2: -60.8%, x3: -65.7%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.013 per bar vs observed OOS -0.016 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 1H)

Grid: 12 combinations. Windows: 9 (9 traded, 1 positive). Most-selected parameters: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0}`.

| Year | OOS return |
|---|---:|
| 2021 | -8.9% |
| 2022 | -25.1% |
| 2023 | -16.4% |
| 2024 | -0.5% |
| 2025 | -11.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -16.6% | -2.34 |
| highvol_range | 3.1% | -1.8% | -0.81 |
| highvol_up | 11.8% | +1.8% | 0.30 |
| lowvol_down | 13.6% | -16.5% | -1.79 |
| lowvol_range | 13.7% | -14.7% | -1.41 |
| lowvol_up | 18.1% | -3.9% | -0.18 |
| midvol_down | 7.5% | -2.6% | -0.13 |
| midvol_range | 7.4% | -8.7% | -1.36 |
| midvol_up | 14.2% | -0.4% | 0.05 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -15.4%, neighbours median -43.9%, min -52.1%, share profitable 12.5% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 347 OOS trades): terminal growth p05 0.26× / p50 0.50× / p95 0.98×, P(loss) 95.3%, max DD p50 58.9%, p95 76.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -49.4%, x2: -64.3%, x3: -74.7%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.011 per bar vs observed OOS -0.008 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 1H)

Grid: 108 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'lookbacks_days': (30, 60, 90), 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +35.3% |
| 2022 | -37.2% |
| 2023 | +47.0% |
| 2024 | +10.9% |
| 2025 | -20.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -32.3% | -4.33 |
| highvol_range | 3.1% | -0.8% | 0.02 |
| highvol_up | 11.8% | +62.9% | 2.02 |
| lowvol_down | 13.6% | -17.0% | -2.49 |
| lowvol_range | 13.7% | +14.2% | 0.92 |
| lowvol_up | 18.1% | +6.7% | 0.41 |
| midvol_down | 7.5% | -26.1% | -3.50 |
| midvol_range | 7.4% | +11.6% | 1.17 |
| midvol_up | 14.2% | +20.2% | 0.94 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +51.1%, neighbours median +52.3%, min +41.2%, share profitable 100.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 341 OOS trades): terminal growth p05 0.26× / p50 1.06× / p95 5.83×, P(loss) 47.9%, max DD p50 58.3%, p95 81.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +9.6%, x2: -22.1%, x3: -44.6%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.014 per bar vs observed OOS 0.002 → DSR 0.02 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 1H)

Grid: 108 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 3.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +41.1% |
| 2022 | -34.7% |
| 2023 | +13.8% |
| 2024 | +33.6% |
| 2025 | -28.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 10.5% | -27.5% | -2.41 |
| highvol_range | 3.1% | -10.2% | -1.85 |
| highvol_up | 11.8% | +35.4% | 1.36 |
| lowvol_down | 13.6% | -19.0% | -1.74 |
| lowvol_range | 13.7% | +3.5% | 0.35 |
| lowvol_up | 18.1% | +16.7% | 0.75 |
| midvol_down | 7.5% | -26.2% | -2.39 |
| midvol_range | 7.4% | +48.6% | 3.56 |
| midvol_up | 14.2% | +6.0% | 0.44 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +41.6%, neighbours median +29.1%, min -26.4%, share profitable 91.7% over 12 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 117 OOS trades): terminal growth p05 0.29× / p50 0.94× / p95 3.75×, P(loss) 53.1%, max DD p50 54.7%, p95 76.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.2%, x2: -10.8%, x3: -20.7%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.006 per bar vs observed OOS 0.002 → DSR 0.22 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (BTC-USDT 4H)

Grid: 18 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'short_window': 10, 'long_window': 100, 'stop_loss_pct': 0.04}`.

| Year | OOS return |
|---|---:|
| 2021 | -15.6% |
| 2022 | -37.9% |
| 2023 | +71.4% |
| 2024 | +76.4% |
| 2025 | -15.8% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -50.0% | -2.95 |
| highvol_range | 3.7% | +33.8% | 4.89 |
| highvol_up | 13.3% | +44.5% | 1.59 |
| lowvol_down | 13.4% | -8.0% | -0.46 |
| lowvol_range | 13.2% | +8.3% | 0.65 |
| lowvol_up | 17.8% | -0.5% | 0.13 |
| midvol_down | 7.6% | -21.5% | -2.04 |
| midvol_range | 7.1% | +50.1% | 3.64 |
| midvol_up | 12.8% | +18.2% | 0.97 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +95.5%, neighbours median +60.7%, min -31.9%, share profitable 75.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 153 OOS trades): terminal growth p05 0.33× / p50 1.24× / p95 6.57×, P(loss) 39.6%, max DD p50 53.5%, p95 76.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +33.3%, x2: +14.4%, x3: -1.8%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.019 per bar vs observed OOS 0.008 → DSR 0.14 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 4H)

Grid: 36 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'lookbacks_days': (14, 30, 60), 'vote': 3, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | +13.4% |
| 2022 | -40.3% |
| 2023 | +75.1% |
| 2024 | +7.3% |
| 2025 | +2.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -36.3% | -2.39 |
| highvol_range | 3.7% | +7.9% | 1.26 |
| highvol_up | 13.3% | +38.2% | 1.36 |
| lowvol_down | 13.4% | -20.8% | -2.32 |
| lowvol_range | 13.2% | +28.0% | 1.70 |
| lowvol_up | 17.8% | +17.1% | 0.77 |
| midvol_down | 7.6% | -19.1% | -2.48 |
| midvol_range | 7.1% | +8.1% | 0.84 |
| midvol_up | 12.8% | +31.9% | 1.39 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +94.0%, neighbours median +77.2%, min -40.7%, share profitable 87.5% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 172 OOS trades): terminal growth p05 0.35× / p50 1.21× / p95 6.15×, P(loss) 40.2%, max DD p50 50.6%, p95 75.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +30.0%, x2: +9.5%, x3: -7.8%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.017 per bar vs observed OOS 0.007 → DSR 0.17 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 4H)

Grid: 36 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | +5.1% |
| 2022 | -33.7% |
| 2023 | +63.5% |
| 2024 | +47.2% |
| 2025 | -9.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -40.0% | -2.75 |
| highvol_range | 3.7% | +33.2% | 5.01 |
| highvol_up | 13.3% | +24.2% | 1.05 |
| lowvol_down | 13.4% | -18.7% | -1.41 |
| lowvol_range | 13.2% | +10.7% | 0.85 |
| lowvol_up | 17.8% | -4.8% | -0.07 |
| midvol_down | 7.6% | +3.4% | 0.49 |
| midvol_range | 7.1% | +24.3% | 2.25 |
| midvol_up | 12.8% | +39.0% | 1.73 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +12.4%, neighbours median +14.6%, min +5.2%, share profitable 100.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 84 OOS trades): terminal growth p05 0.47× / p50 1.44× / p95 5.55×, P(loss) 32.2%, max DD p50 44.4%, p95 68.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +51.8%, x2: +39.6%, x3: +28.3%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.013 per bar vs observed OOS 0.010 → DSR 0.37 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (BTC-USDT 4H)

Grid: 54 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -2.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 2.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | +6.7% |
| 2022 | -10.4% |
| 2023 | -4.2% |
| 2024 | -5.0% |
| 2025 | +8.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | +1.6% | 0.25 |
| highvol_range | 3.7% | -13.7% | -2.02 |
| highvol_up | 13.3% | +13.4% | 2.50 |
| lowvol_down | 13.4% | -15.1% | -2.78 |
| lowvol_range | 13.2% | -0.8% | -0.01 |
| lowvol_up | 17.8% | -1.7% | -0.32 |
| midvol_down | 7.6% | +0.6% | 0.22 |
| midvol_range | 7.1% | -8.5% | -1.17 |
| midvol_up | 12.8% | +24.2% | 2.95 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +1.2%, neighbours median -11.8%, min -32.4%, share profitable 40.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 100 OOS trades): terminal growth p05 0.55× / p50 0.94× / p95 1.59×, P(loss) 57.8%, max DD p50 30.9%, p95 53.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -6.0%, x2: -14.9%, x3: -23.0%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.024 per bar vs observed OOS -0.000 → DSR 0.01 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 4H)

Grid: 12 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'bb_window': 30, 'bb_k': 2.0, 'squeeze_pct': 0.3, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0}`.

| Year | OOS return |
|---|---:|
| 2021 | -5.3% |
| 2022 | -15.9% |
| 2023 | +28.0% |
| 2024 | +50.4% |
| 2025 | -11.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -7.8% | -0.99 |
| highvol_range | 3.7% | +11.6% | 2.91 |
| highvol_up | 13.3% | +21.3% | 1.41 |
| lowvol_down | 13.4% | -10.9% | -0.97 |
| lowvol_range | 13.2% | +16.7% | 1.42 |
| lowvol_up | 17.8% | -3.4% | -0.11 |
| midvol_down | 7.6% | -14.3% | -3.22 |
| midvol_range | 7.1% | +4.6% | 0.71 |
| midvol_up | 12.8% | +21.5% | 1.67 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +77.3%, neighbours median +77.0%, min +52.9%, share profitable 100.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 98 OOS trades): terminal growth p05 0.60× / p50 1.33× / p95 3.20×, P(loss) 29.1%, max DD p50 32.8%, p95 54.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +36.4%, x2: +23.6%, x3: +12.1%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.011 per bar vs observed OOS 0.009 → DSR 0.44 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 4H)

Grid: 108 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'lookbacks_days': (14, 30, 60), 'vote': 3, 'atr_window': 14, 'atr_mult': 2.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +13.4% |
| 2022 | -40.3% |
| 2023 | +75.1% |
| 2024 | +7.3% |
| 2025 | +2.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -36.3% | -2.39 |
| highvol_range | 3.7% | +7.9% | 1.26 |
| highvol_up | 13.3% | +38.2% | 1.36 |
| lowvol_down | 13.4% | -20.8% | -2.32 |
| lowvol_range | 13.2% | +28.0% | 1.70 |
| lowvol_up | 17.8% | +17.1% | 0.77 |
| midvol_down | 7.6% | -19.1% | -2.48 |
| midvol_range | 7.1% | +8.1% | 0.84 |
| midvol_up | 12.8% | +31.9% | 1.39 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +94.0%, neighbours median +93.4%, min -40.7%, share profitable 90.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 172 OOS trades): terminal growth p05 0.35× / p50 1.21× / p95 6.15×, P(loss) 40.2%, max DD p50 50.6%, p95 75.8%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +30.0%, x2: +9.5%, x3: -7.8%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.020 per bar vs observed OOS 0.007 → DSR 0.11 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 4H)

Grid: 108 combinations. Windows: 9 (9 traded, 6 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 5, 'vol_mult': 1.0, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +5.1% |
| 2022 | -33.7% |
| 2023 | +63.5% |
| 2024 | +47.2% |
| 2025 | -9.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.2% | -40.0% | -2.75 |
| highvol_range | 3.7% | +33.2% | 5.01 |
| highvol_up | 13.3% | +24.2% | 1.05 |
| lowvol_down | 13.4% | -18.7% | -1.41 |
| lowvol_range | 13.2% | +10.7% | 0.85 |
| lowvol_up | 17.8% | -4.8% | -0.07 |
| midvol_down | 7.6% | +3.4% | 0.49 |
| midvol_range | 7.1% | +24.3% | 2.25 |
| midvol_up | 12.8% | +39.0% | 1.73 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +12.4%, neighbours median +12.9%, min +5.2%, share profitable 100.0% over 12 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 84 OOS trades): terminal growth p05 0.47× / p50 1.44× / p95 5.55×, P(loss) 32.2%, max DD p50 44.4%, p95 68.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +51.8%, x2: +39.6%, x3: +28.3%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.015 per bar vs observed OOS 0.010 → DSR 0.29 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (BTC-USDT 1D)

Grid: 18 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'short_window': 5, 'long_window': 50, 'stop_loss_pct': 0.02}`.

| Year | OOS return |
|---|---:|
| 2021 | -10.1% |
| 2022 | -31.0% |
| 2023 | +119.3% |
| 2024 | +51.3% |
| 2025 | -29.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | -16.8% | -1.78 |
| highvol_range | 4.2% | +7.5% | 1.08 |
| highvol_up | 12.4% | +44.7% | 1.55 |
| lowvol_down | 13.3% | -3.5% | -0.38 |
| lowvol_range | 11.5% | +6.5% | 0.63 |
| lowvol_up | 16.2% | +2.3% | 0.26 |
| midvol_down | 11.1% | -37.3% | -4.41 |
| midvol_range | 8.0% | +48.6% | 3.44 |
| midvol_up | 15.1% | +13.6% | 0.67 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +109.1%, neighbours median +75.7%, min +14.7%, share profitable 100.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 92 OOS trades): terminal growth p05 0.43× / p50 1.42× / p95 5.24×, P(loss) 32.0%, max DD p50 43.0%, p95 66.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +44.2%, x2: +31.6%, x3: +20.0%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.042 per bar vs observed OOS 0.022 → DSR 0.21 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (BTC-USDT 1D)

Grid: 36 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 3, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | +16.2% |
| 2022 | -52.0% |
| 2023 | +66.7% |
| 2024 | +47.9% |
| 2025 | -24.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | -45.4% | -2.88 |
| highvol_range | 4.2% | +21.3% | 2.13 |
| highvol_up | 12.4% | +30.6% | 1.28 |
| lowvol_down | 13.3% | -28.3% | -2.27 |
| lowvol_range | 11.5% | +9.6% | 0.79 |
| lowvol_up | 16.2% | +29.8% | 1.66 |
| midvol_down | 11.1% | -35.4% | -1.93 |
| midvol_range | 8.0% | +43.5% | 3.21 |
| midvol_up | 15.1% | +26.1% | 1.08 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +70.3%, neighbours median +41.3%, min +8.6%, share profitable 100.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 107 OOS trades): terminal growth p05 0.27× / p50 0.99× / p95 4.37×, P(loss) 50.2%, max DD p50 56.6%, p95 80.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +3.3%, x2: -7.2%, x3: -16.6%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.034 per bar vs observed OOS 0.011 → DSR 0.18 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (BTC-USDT 1D)

Grid: 36 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'entry_days': 20, 'exit_days': 10, 'vol_mult': 1.2, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.5, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | +0.0% | 0.00 |
| highvol_range | 4.2% | +0.0% | 0.00 |
| highvol_up | 12.4% | +0.0% | 0.00 |
| lowvol_down | 13.3% | +0.0% | 0.00 |
| lowvol_range | 11.5% | +0.0% | 0.00 |
| lowvol_up | 16.2% | +0.0% | 0.00 |
| midvol_down | 11.1% | +0.0% | 0.00 |
| midvol_range | 8.0% | +0.0% | 0.00 |
| midvol_up | 15.1% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +42.0%, neighbours median +45.4%, min -7.5%, share profitable 90.0% over 10 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.028 per bar vs observed OOS 0.000 → DSR 0.14 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window

## S3 — Range mean-reversion (RSI/z-score, range regime only) (BTC-USDT 1D)

Grid: 54 combinations. Windows: 9 (1 traded, 0 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 55.0, 'z_window': 20, 'z_entry': -1.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 1.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | +0.0% | 0.00 |
| highvol_range | 4.2% | +0.0% | 0.00 |
| highvol_up | 12.4% | +0.0% | 0.00 |
| lowvol_down | 13.3% | +0.0% | 0.00 |
| lowvol_range | 11.5% | +0.0% | 0.00 |
| lowvol_up | 16.2% | +0.0% | 0.00 |
| midvol_down | 11.1% | +0.0% | 0.00 |
| midvol_range | 8.0% | +0.0% | 0.00 |
| midvol_up | 15.1% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -4.1%, neighbours median -4.0%, min -32.9%, share profitable 20.0% over 10 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.072 per bar vs observed OOS 0.000 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=no, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (BTC-USDT 1D)

Grid: 12 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.5}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | +0.0% | 0.00 |
| highvol_range | 4.2% | +0.0% | 0.00 |
| highvol_up | 12.4% | +0.0% | 0.00 |
| lowvol_down | 13.3% | +0.0% | 0.00 |
| lowvol_range | 11.5% | +0.0% | 0.00 |
| lowvol_up | 16.2% | +0.0% | 0.00 |
| midvol_down | 11.1% | +0.0% | 0.00 |
| midvol_range | 8.0% | +0.0% | 0.00 |
| midvol_up | 15.1% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -24.6%, neighbours median -19.5%, min -55.0%, share profitable 25.0% over 8 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.044 per bar vs observed OOS 0.000 → DSR 0.04 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=no, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (BTC-USDT 1D)

Grid: 108 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 3, 'atr_window': 14, 'atr_mult': 3.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +16.2% |
| 2022 | -52.0% |
| 2023 | +66.7% |
| 2024 | +47.9% |
| 2025 | -24.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | -45.4% | -2.88 |
| highvol_range | 4.2% | +21.3% | 2.13 |
| highvol_up | 12.4% | +30.6% | 1.28 |
| lowvol_down | 13.3% | -28.3% | -2.27 |
| lowvol_range | 11.5% | +9.6% | 0.79 |
| lowvol_up | 16.2% | +29.8% | 1.66 |
| midvol_down | 11.1% | -35.4% | -1.93 |
| midvol_range | 8.0% | +43.5% | 3.21 |
| midvol_up | 15.1% | +26.1% | 1.08 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +70.3%, neighbours median +57.3%, min +8.6%, share profitable 100.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 107 OOS trades): terminal growth p05 0.27× / p50 0.99× / p95 4.37×, P(loss) 50.2%, max DD p50 56.6%, p95 80.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +3.3%, x2: -7.2%, x3: -16.6%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.040 per bar vs observed OOS 0.011 → DSR 0.12 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (BTC-USDT 1D)

Grid: 108 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'entry_days': 20, 'exit_days': 10, 'vol_mult': 1.2, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.5, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 8.3% | +0.0% | 0.00 |
| highvol_range | 4.2% | +0.0% | 0.00 |
| highvol_up | 12.4% | +0.0% | 0.00 |
| lowvol_down | 13.3% | +0.0% | 0.00 |
| lowvol_range | 11.5% | +0.0% | 0.00 |
| lowvol_up | 16.2% | +0.0% | 0.00 |
| midvol_down | 11.1% | +0.0% | 0.00 |
| midvol_range | 8.0% | +0.0% | 0.00 |
| midvol_up | 15.1% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +42.0%, neighbours median +42.0%, min -7.5%, share profitable 91.7% over 12 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.033 per bar vs observed OOS 0.000 → DSR 0.10 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window
- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (ETH-USDT 1H)

Grid: 18 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'short_window': 5, 'long_window': 100, 'stop_loss_pct': 0.04}`.

| Year | OOS return |
|---|---:|
| 2021 | -13.6% |
| 2022 | -62.1% |
| 2023 | -16.3% |
| 2024 | +30.8% |
| 2025 | -26.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -51.9% | -2.47 |
| highvol_range | 6.9% | -19.0% | -1.09 |
| highvol_up | 12.3% | +13.9% | 0.73 |
| lowvol_down | 10.4% | -24.0% | -1.88 |
| lowvol_range | 12.8% | -36.4% | -2.36 |
| lowvol_up | 14.7% | -14.5% | -0.40 |
| midvol_down | 8.7% | -5.6% | -0.06 |
| midvol_range | 10.1% | -15.4% | -0.56 |
| midvol_up | 13.1% | +80.4% | 2.32 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -36.5%, neighbours median -37.9%, min -65.5%, share profitable 0.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 532 OOS trades): terminal growth p05 0.05× / p50 0.26× / p95 1.39×, P(loss) 90.5%, max DD p50 85.6%, p95 96.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -73.5%, x2: -84.4%, x3: -90.9%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.016 per bar vs observed OOS -0.005 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 1H)

Grid: 36 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (14, 30, 60), 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | -2.5% |
| 2022 | -52.4% |
| 2023 | -19.6% |
| 2024 | +6.1% |
| 2025 | +54.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -3.0% | -0.15 |
| highvol_range | 6.9% | -13.6% | -0.47 |
| highvol_up | 12.3% | +60.8% | 1.63 |
| lowvol_down | 10.4% | -19.9% | -2.33 |
| lowvol_range | 12.8% | -40.0% | -2.40 |
| lowvol_up | 14.7% | +7.1% | 0.46 |
| midvol_down | 8.7% | -29.9% | -2.18 |
| midvol_range | 10.1% | -31.6% | -1.63 |
| midvol_up | 13.1% | +83.9% | 2.13 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +200.3%, neighbours median -2.6%, min -50.3%, share profitable 42.9% over 7 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 357 OOS trades): terminal growth p05 0.11× / p50 0.55× / p95 4.33×, P(loss) 67.6%, max DD p50 76.1%, p95 92.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -38.8%, x2: -57.2%, x3: -70.1%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.009 per bar vs observed OOS 0.000 → DSR 0.04 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 1H)

Grid: 36 combinations. Windows: 9 (9 traded, 3 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 3.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | -12.1% |
| 2022 | -36.4% |
| 2023 | -3.2% |
| 2024 | +3.0% |
| 2025 | -27.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -25.0% | -1.44 |
| highvol_range | 6.9% | -7.6% | -0.27 |
| highvol_up | 12.3% | -18.8% | -0.46 |
| lowvol_down | 10.4% | -29.6% | -2.70 |
| lowvol_range | 12.8% | +6.2% | 0.50 |
| lowvol_up | 14.7% | -4.4% | 0.05 |
| midvol_down | 8.7% | -27.1% | -1.67 |
| midvol_range | 10.1% | -17.4% | -0.58 |
| midvol_up | 13.1% | +66.7% | 2.06 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -19.6%, neighbours median -11.7%, min -37.4%, share profitable 40.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 131 OOS trades): terminal growth p05 0.10× / p50 0.39× / p95 1.97×, P(loss) 84.5%, max DD p50 76.7%, p95 92.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -59.7%, x2: -64.6%, x3: -69.0%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.006 per bar vs observed OOS -0.003 → DSR 0.04 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (ETH-USDT 1H)

Grid: 54 combinations. Windows: 9 (9 traded, 2 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 30.0, 'rsi_exit': 55.0, 'z_window': 20, 'z_entry': -2.0, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 2.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | +17.3% |
| 2022 | -8.0% |
| 2023 | -9.9% |
| 2024 | -11.9% |
| 2025 | -21.7% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -6.8% | -1.02 |
| highvol_range | 6.9% | -6.4% | -1.03 |
| highvol_up | 12.3% | +21.9% | 2.73 |
| lowvol_down | 10.4% | -9.9% | -2.55 |
| lowvol_range | 12.8% | -16.3% | -1.96 |
| lowvol_up | 14.7% | -2.7% | -0.56 |
| midvol_down | 8.7% | -13.1% | -3.04 |
| midvol_range | 10.1% | -9.7% | -0.77 |
| midvol_up | 13.1% | +9.5% | 1.54 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -36.7%, neighbours median -40.7%, min -74.7%, share profitable 0.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 127 OOS trades): terminal growth p05 0.42× / p50 0.68× / p95 1.08×, P(loss) 91.5%, max DD p50 41.0%, p95 60.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -33.0%, x2: -41.0%, x3: -48.0%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.011 per bar vs observed OOS -0.006 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 1H)

Grid: 12 combinations. Windows: 9 (9 traded, 2 positive). Most-selected parameters: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | -6.2% |
| 2022 | -41.3% |
| 2023 | -14.8% |
| 2024 | -24.8% |
| 2025 | -13.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -6.9% | -1.03 |
| highvol_range | 6.9% | +4.1% | 0.96 |
| highvol_up | 12.3% | +6.6% | 0.63 |
| lowvol_down | 10.4% | -30.1% | -5.12 |
| lowvol_range | 12.8% | -32.8% | -3.21 |
| lowvol_up | 14.7% | -24.5% | -1.75 |
| midvol_down | 8.7% | -17.2% | -1.84 |
| midvol_range | 10.1% | -23.4% | -2.14 |
| midvol_up | 13.1% | +32.1% | 2.09 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -67.2%, neighbours median -67.7%, min -83.9%, share profitable 0.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 388 OOS trades): terminal growth p05 0.15× / p50 0.30× / p95 0.66×, P(loss) 99.4%, max DD p50 73.9%, p95 86.5%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -69.3%, x2: -79.2%, x3: -85.9%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.005 per bar vs observed OOS -0.012 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 1H)

Grid: 108 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (14, 30, 60), 'vote': 1, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | -2.5% |
| 2022 | -52.4% |
| 2023 | -19.6% |
| 2024 | +6.1% |
| 2025 | +54.4% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -3.0% | -0.15 |
| highvol_range | 6.9% | -13.6% | -0.47 |
| highvol_up | 12.3% | +60.8% | 1.63 |
| lowvol_down | 10.4% | -19.9% | -2.33 |
| lowvol_range | 12.8% | -40.0% | -2.40 |
| lowvol_up | 14.7% | +7.1% | 0.46 |
| midvol_down | 8.7% | -29.9% | -2.18 |
| midvol_range | 10.1% | -31.6% | -1.63 |
| midvol_up | 13.1% | +83.9% | 2.13 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +200.3%, neighbours median +111.6%, min -50.3%, share profitable 55.6% over 9 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 357 OOS trades): terminal growth p05 0.11× / p50 0.55× / p95 4.33×, P(loss) 67.6%, max DD p50 76.1%, p95 92.3%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -38.8%, x2: -57.2%, x3: -70.1%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.011 per bar vs observed OOS 0.000 → DSR 0.02 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 1H)

Grid: 108 combinations. Windows: 9 (9 traded, 3 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 3.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | -12.1% |
| 2022 | -36.4% |
| 2023 | -3.2% |
| 2024 | +3.0% |
| 2025 | -27.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 11.0% | -25.0% | -1.44 |
| highvol_range | 6.9% | -7.6% | -0.27 |
| highvol_up | 12.3% | -18.8% | -0.46 |
| lowvol_down | 10.4% | -29.6% | -2.70 |
| lowvol_range | 12.8% | +6.2% | 0.50 |
| lowvol_up | 14.7% | -4.4% | 0.05 |
| midvol_down | 8.7% | -27.1% | -1.67 |
| midvol_range | 10.1% | -17.4% | -0.58 |
| midvol_up | 13.1% | +66.7% | 2.06 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -19.6%, neighbours median -17.8%, min -37.4%, share profitable 33.3% over 12 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 131 OOS trades): terminal growth p05 0.10× / p50 0.39× / p95 1.97×, P(loss) 84.5%, max DD p50 76.7%, p95 92.1%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -59.7%, x2: -64.6%, x3: -69.0%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.007 per bar vs observed OOS -0.003 → DSR 0.02 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (ETH-USDT 4H)

Grid: 18 combinations. Windows: 9 (9 traded, 2 positive). Most-selected parameters: `{'short_window': 20, 'long_window': 100, 'stop_loss_pct': 0.04}`.

| Year | OOS return |
|---|---:|
| 2021 | +31.0% |
| 2022 | -23.0% |
| 2023 | -4.2% |
| 2024 | +52.8% |
| 2025 | -28.9% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -33.6% | -1.64 |
| highvol_range | 7.9% | +1.3% | 0.33 |
| highvol_up | 11.9% | +4.4% | 0.42 |
| lowvol_down | 11.2% | -28.4% | -2.06 |
| lowvol_range | 12.3% | -23.4% | -1.31 |
| lowvol_up | 14.1% | +31.1% | 1.24 |
| midvol_down | 8.8% | +3.2% | 0.40 |
| midvol_range | 10.1% | +12.7% | 0.82 |
| midvol_up | 13.8% | +78.6% | 2.02 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +8.2%, neighbours median +1.1%, min -37.1%, share profitable 50.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 194 OOS trades): terminal growth p05 0.18× / p50 1.00× / p95 5.81×, P(loss) 50.2%, max DD p50 65.4%, p95 87.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +4.9%, x2: -13.6%, x3: -28.8%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.015 per bar vs observed OOS 0.005 → DSR 0.18 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 4H)

Grid: 36 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | +44.0% |
| 2022 | -60.7% |
| 2023 | -2.4% |
| 2024 | +50.4% |
| 2025 | +69.3% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -0.3% | 0.28 |
| highvol_range | 7.9% | -14.1% | -0.32 |
| highvol_up | 11.9% | +100.0% | 2.26 |
| lowvol_down | 11.2% | -25.0% | -2.05 |
| lowvol_range | 12.3% | -38.1% | -2.12 |
| lowvol_up | 14.1% | +30.6% | 1.18 |
| midvol_down | 8.8% | -29.6% | -1.90 |
| midvol_range | 10.1% | -9.9% | -0.21 |
| midvol_up | 13.8% | +113.3% | 2.39 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +95.6%, neighbours median +27.9%, min -31.3%, share profitable 50.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 207 OOS trades): terminal growth p05 0.25× / p50 1.34× / p95 9.86×, P(loss) 39.5%, max DD p50 61.4%, p95 84.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +40.7%, x2: +14.4%, x3: -7.0%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.014 per bar vs observed OOS 0.009 → DSR 0.32 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 4H)

Grid: 36 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | +17.3% |
| 2022 | -17.8% |
| 2023 | +17.7% |
| 2024 | +40.2% |
| 2025 | +32.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -9.0% | -0.31 |
| highvol_range | 7.9% | +12.8% | 0.98 |
| highvol_up | 11.9% | +31.3% | 1.27 |
| lowvol_down | 11.2% | -36.0% | -2.89 |
| lowvol_range | 12.3% | -14.3% | -0.71 |
| lowvol_up | 14.1% | +15.7% | 0.81 |
| midvol_down | 8.8% | -20.3% | -1.54 |
| midvol_range | 10.1% | +30.0% | 1.66 |
| midvol_up | 13.8% | +137.5% | 3.18 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +102.2%, neighbours median +73.4%, min -7.6%, share profitable 90.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 76 OOS trades): terminal growth p05 0.41× / p50 2.09× / p95 14.02×, P(loss) 24.2%, max DD p50 49.7%, p95 74.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +110.5%, x2: +95.1%, x3: +80.8%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.022 per bar vs observed OOS 0.013 → DSR 0.19 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S3 — Range mean-reversion (RSI/z-score, range regime only) (ETH-USDT 4H)

Grid: 54 combinations. Windows: 9 (8 traded, 3 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -2.0, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 1.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | +1.3% |
| 2022 | -18.8% |
| 2023 | +2.5% |
| 2024 | -23.6% |
| 2025 | +11.1% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -7.5% | -0.32 |
| highvol_range | 7.9% | -8.8% | -0.63 |
| highvol_up | 11.9% | +23.0% | 2.88 |
| lowvol_down | 11.2% | -15.3% | -2.91 |
| lowvol_range | 12.3% | +7.9% | 0.87 |
| lowvol_up | 14.1% | +1.9% | 0.46 |
| midvol_down | 8.8% | -14.5% | -2.53 |
| midvol_range | 10.1% | -16.2% | -1.64 |
| midvol_up | 13.8% | +3.4% | 0.86 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -14.7%, neighbours median -23.5%, min -36.8%, share profitable 20.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 94 OOS trades): terminal growth p05 0.36× / p50 0.72× / p95 1.42×, P(loss) 79.0%, max DD p50 45.0%, p95 68.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -28.4%, x2: -34.9%, x3: -40.7%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.033 per bar vs observed OOS -0.006 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 4H)

Grid: 12 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.1, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 3.0}`.

| Year | OOS return |
|---|---:|
| 2021 | -13.4% |
| 2022 | -24.4% |
| 2023 | +3.8% |
| 2024 | -7.4% |
| 2025 | +2.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | +3.5% | 0.76 |
| highvol_range | 7.9% | +8.6% | 1.01 |
| highvol_up | 11.9% | -5.8% | -0.52 |
| lowvol_down | 11.2% | -23.3% | -2.93 |
| lowvol_range | 12.3% | +8.6% | 0.77 |
| lowvol_up | 14.1% | +17.1% | 1.27 |
| midvol_down | 8.8% | -17.9% | -1.85 |
| midvol_range | 10.1% | -10.9% | -0.72 |
| midvol_up | 13.8% | -14.9% | -0.90 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set -9.2%, neighbours median -10.1%, min -62.9%, share profitable 37.5% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 86 OOS trades): terminal growth p05 0.29× / p50 0.64× / p95 1.66×, P(loss) 79.1%, max DD p50 54.5%, p95 74.9%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -35.7%, x2: -41.0%, x3: -45.9%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.036 per bar vs observed OOS -0.007 → DSR 0.00 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=no, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 4H)

Grid: 108 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 3, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +44.0% |
| 2022 | -60.7% |
| 2023 | -2.4% |
| 2024 | +50.4% |
| 2025 | +69.3% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -0.3% | 0.28 |
| highvol_range | 7.9% | -14.1% | -0.32 |
| highvol_up | 11.9% | +100.0% | 2.26 |
| lowvol_down | 11.2% | -25.0% | -2.05 |
| lowvol_range | 12.3% | -38.1% | -2.12 |
| lowvol_up | 14.1% | +30.6% | 1.18 |
| midvol_down | 8.8% | -29.6% | -1.90 |
| midvol_range | 10.1% | -9.9% | -0.21 |
| midvol_up | 13.8% | +113.3% | 2.39 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +95.6%, neighbours median +89.0%, min -31.3%, share profitable 60.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 207 OOS trades): terminal growth p05 0.25× / p50 1.34× / p95 9.86×, P(loss) 39.5%, max DD p50 61.4%, p95 84.6%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +40.7%, x2: +14.4%, x3: -7.0%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.016 per bar vs observed OOS 0.009 → DSR 0.24 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 4H)

Grid: 108 combinations. Windows: 9 (9 traded, 5 positive). Most-selected parameters: `{'entry_days': 10, 'exit_days': 10, 'vol_mult': 1.5, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.0, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +17.3% |
| 2022 | -17.8% |
| 2023 | +17.7% |
| 2024 | +40.2% |
| 2025 | +32.2% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.8% | -9.0% | -0.31 |
| highvol_range | 7.9% | +12.8% | 0.98 |
| highvol_up | 11.9% | +31.3% | 1.27 |
| lowvol_down | 11.2% | -36.0% | -2.89 |
| lowvol_range | 12.3% | -14.3% | -0.71 |
| lowvol_up | 14.1% | +15.7% | 0.81 |
| midvol_down | 8.8% | -20.3% | -1.54 |
| midvol_range | 10.1% | +30.0% | 1.66 |
| midvol_up | 13.8% | +137.5% | 3.18 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +102.2%, neighbours median +96.0%, min -7.6%, share profitable 91.7% over 12 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 76 OOS trades): terminal growth p05 0.41× / p50 2.09× / p95 14.02×, P(loss) 24.2%, max DD p50 49.7%, p95 74.7%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +110.5%, x2: +95.1%, x3: +80.8%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.026 per bar vs observed OOS 0.013 → DSR 0.10 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## baseline — SMA crossover reference (10/30 bars, 2 % stop) (ETH-USDT 1D)

Grid: 18 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'short_window': 5, 'long_window': 30, 'stop_loss_pct': 0.04}`.

| Year | OOS return |
|---|---:|
| 2021 | +12.8% |
| 2022 | -16.7% |
| 2023 | +9.0% |
| 2024 | -27.4% |
| 2025 | -31.8% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +23.2% | 1.25 |
| highvol_range | 8.0% | -34.3% | -2.68 |
| highvol_up | 12.1% | -30.0% | -0.79 |
| lowvol_down | 11.2% | -29.5% | -4.02 |
| lowvol_range | 13.1% | -10.2% | -0.57 |
| lowvol_up | 14.1% | +55.1% | 2.09 |
| midvol_down | 9.3% | -32.8% | -3.52 |
| midvol_range | 9.0% | -27.1% | -1.61 |
| midvol_up | 13.9% | +86.1% | 2.04 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +55.0%, neighbours median +67.6%, min +17.2%, share profitable 100.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 135 OOS trades): terminal growth p05 0.14× / p50 0.48× / p95 1.97×, P(loss) 80.5%, max DD p50 71.6%, p95 88.4%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -49.3%, x2: -55.7%, x3: -61.3%

Deflated Sharpe: 18 trials in the last train window, expected max SR (zero skill) 0.026 per bar vs observed OOS -0.007 → DSR 0.10 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S1 — TSMOM multi-lookback (vol-scaled) (ETH-USDT 1D)

Grid: 36 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30}`.

| Year | OOS return |
|---|---:|
| 2021 | +9.8% |
| 2022 | -47.2% |
| 2023 | +9.3% |
| 2024 | +8.5% |
| 2025 | +6.1% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +15.7% | 0.91 |
| highvol_range | 8.0% | -35.6% | -2.55 |
| highvol_up | 12.1% | -37.9% | -0.89 |
| lowvol_down | 11.2% | -16.2% | -1.36 |
| lowvol_range | 13.1% | -7.6% | -0.36 |
| lowvol_up | 14.1% | +79.0% | 2.81 |
| midvol_down | 9.3% | -23.2% | -1.23 |
| midvol_range | 9.0% | -17.4% | -0.82 |
| midvol_up | 13.9% | +79.6% | 2.04 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +38.9%, neighbours median +0.6%, min -46.2%, share profitable 50.0% over 8 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 91 OOS trades): terminal growth p05 0.14× / p50 0.71× / p95 4.04×, P(loss) 63.6%, max DD p50 69.1%, p95 89.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -27.0%, x2: -33.3%, x3: -39.1%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.035 per bar vs observed OOS 0.005 → DSR 0.11 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

## S2 — Donchian breakout + volume/ATR filters (ETH-USDT 1D)

Grid: 36 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'entry_days': 20, 'exit_days': 10, 'vol_mult': 1.2, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.5, 'atr_pct_max': 0.9, 'atr_pct_days': 90}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +0.0% | 0.00 |
| highvol_range | 8.0% | +0.0% | 0.00 |
| highvol_up | 12.1% | +0.0% | 0.00 |
| lowvol_down | 11.2% | +0.0% | 0.00 |
| lowvol_range | 13.1% | +0.0% | 0.00 |
| lowvol_up | 14.1% | +0.0% | 0.00 |
| midvol_down | 9.3% | +0.0% | 0.00 |
| midvol_range | 9.0% | +0.0% | 0.00 |
| midvol_up | 13.9% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +46.1%, neighbours median +54.8%, min +9.1%, share profitable 100.0% over 10 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 36 trials in the last train window, expected max SR (zero skill) 0.035 per bar vs observed OOS 0.000 → DSR 0.08 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window

## S3 — Range mean-reversion (RSI/z-score, range regime only) (ETH-USDT 1D)

Grid: 54 combinations. Windows: 9 (1 traded, 1 positive). Most-selected parameters: `{'rsi_period': 14, 'rsi_entry': 35.0, 'rsi_exit': 50.0, 'z_window': 20, 'z_entry': -1.5, 'trend_days': 100, 'range_band': 0.08, 'atr_window': 14, 'atr_mult': 1.5, 'time_stop_days': 2.0}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +11.6% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +0.0% | 0.00 |
| highvol_range | 8.0% | +4.6% | 1.65 |
| highvol_up | 12.1% | +6.7% | 1.85 |
| lowvol_down | 11.2% | +0.0% | 0.00 |
| lowvol_range | 13.1% | +0.0% | 0.00 |
| lowvol_up | 14.1% | +0.0% | 0.00 |
| midvol_down | 9.3% | +0.0% | 0.00 |
| midvol_range | 9.0% | +0.0% | 0.00 |
| midvol_up | 13.9% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +27.0%, neighbours median +13.5%, min -43.9%, share profitable 50.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 2 OOS trades): terminal growth p05 1.05× / p50 1.12× / p95 1.19×, P(loss) 0.0%, max DD p50 -0.0%, p95 0.0%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +11.6%, x2: +11.4%, x3: +11.2%

Deflated Sharpe: 54 trials in the last train window, expected max SR (zero skill) 0.067 per bar vs observed OOS 0.041 → DSR 0.02 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=yes, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

## S4 — Vol-compression (BB squeeze) breakout (ETH-USDT 1D)

Grid: 12 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'bb_window': 20, 'bb_k': 2.0, 'squeeze_pct': 0.2, 'pct_days': 100, 'squeeze_lookback': 10, 'atr_window': 14, 'atr_mult': 2.5}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +0.0% | 0.00 |
| highvol_range | 8.0% | +0.0% | 0.00 |
| highvol_up | 12.1% | +0.0% | 0.00 |
| lowvol_down | 11.2% | +0.0% | 0.00 |
| lowvol_range | 13.1% | +0.0% | 0.00 |
| lowvol_up | 14.1% | +0.0% | 0.00 |
| midvol_down | 9.3% | +0.0% | 0.00 |
| midvol_range | 9.0% | +0.0% | 0.00 |
| midvol_up | 13.9% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +34.8%, neighbours median +49.0%, min +9.9%, share profitable 100.0% over 8 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 12 trials in the last train window, expected max SR (zero skill) 0.034 per bar vs observed OOS 0.000 → DSR 0.09 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window

## S1+S5 — TSMOM multi-lookback (vol-scaled) + positioning filter (ETH-USDT 1D)

Grid: 108 combinations. Windows: 9 (9 traded, 4 positive). Most-selected parameters: `{'lookbacks_days': (7, 14, 30), 'vote': 2, 'atr_window': 14, 'atr_mult': 4.0, 'vol_window_days': 30, 'funding_z_max': 1.5, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +9.8% |
| 2022 | -47.2% |
| 2023 | +9.3% |
| 2024 | +8.5% |
| 2025 | +6.1% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +15.7% | 0.91 |
| highvol_range | 8.0% | -35.6% | -2.55 |
| highvol_up | 12.1% | -37.9% | -0.89 |
| lowvol_down | 11.2% | -16.2% | -1.36 |
| lowvol_range | 13.1% | -7.6% | -0.36 |
| lowvol_up | 14.1% | +79.0% | 2.81 |
| midvol_down | 9.3% | -23.2% | -1.23 |
| midvol_range | 9.0% | -17.4% | -0.82 |
| midvol_up | 13.9% | +79.6% | 2.04 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +38.9%, neighbours median +16.1%, min -46.2%, share profitable 60.0% over 10 neighbours.

Monte Carlo (trade-order bootstrap, 2000 paths over 91 OOS trades): terminal growth p05 0.14× / p50 0.71× / p95 4.04×, P(loss) 63.6%, max DD p50 69.1%, p95 89.2%.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: -27.0%, x2: -33.3%, x3: -39.1%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.042 per bar vs observed OOS 0.005 → DSR 0.07 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=yes, max_dd_lt_20pct=no, robust_pm30pct=yes, enough_trades=yes

Holdout: untouched (candidate did not pass walk-forward).

- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## S2+S5 — Donchian breakout + volume/ATR filters + positioning filter (ETH-USDT 1D)

Grid: 108 combinations. Windows: 9 (0 traded, 0 positive). Most-selected parameters: `{'entry_days': 20, 'exit_days': 10, 'vol_mult': 1.2, 'volume_window': 20, 'atr_window': 14, 'atr_mult': 2.5, 'atr_pct_max': 0.9, 'atr_pct_days': 90, 'funding_z_max': 2.0, 'funding_z_window': 90, 'oi_change_max': 0.15}`.

| Year | OOS return |
|---|---:|
| 2021 | +0.0% |
| 2022 | +0.0% |
| 2023 | +0.0% |
| 2024 | +0.0% |
| 2025 | +0.0% |

| Regime | Share of time | OOS return | Sharpe |
|---|---:|---:|---:|
| highvol_down | 9.3% | +0.0% | 0.00 |
| highvol_range | 8.0% | +0.0% | 0.00 |
| highvol_up | 12.1% | +0.0% | 0.00 |
| lowvol_down | 11.2% | +0.0% | 0.00 |
| lowvol_range | 13.1% | +0.0% | 0.00 |
| lowvol_up | 14.1% | +0.0% | 0.00 |
| midvol_down | 9.3% | +0.0% | 0.00 |
| midvol_range | 9.0% | +0.0% | 0.00 |
| midvol_up | 13.9% | +0.0% | 0.00 |

Robustness (most-selected parameters perturbed ±30% one-at-a-time and jointly, each set replayed with FIXED parameters over every out-of-sample test window, no re-selection): selected set +46.1%, neighbours median +49.9%, min +9.1%, share profitable 100.0% over 12 neighbours.

Slippage stress (OOS total return with slippage ×1/×2/×3): x1: +0.0%, x2: +0.0%, x3: +0.0%

Deflated Sharpe: 108 trials in the last train window, expected max SR (zero skill) 0.041 per bar vs observed OOS 0.000 → DSR 0.05 (probability the OOS Sharpe beats the best-of-N noise level).

Checks: pf_gt_1_2=no, positive_in_3_of_4_years=no, max_dd_lt_20pct=yes, robust_pm30pct=yes, enough_trades=no

Holdout: untouched (candidate did not pass walk-forward).

- no parameter set qualified (min trades) in any training window
- positioning data cover 0.0% of in-sample bars (filter passes elsewhere)

## Method notes and caveats

- Engine: `research/engine.py`, next-bar-open execution, intrabar stop with conservative gap fills, fees and slippage per side, fixed ATR stop at entry, optional time stop; identical conventions to `app/backtest/simulator.py`.
- S0 (no-trade filter: vol spike, extreme bar range, data gaps) gates every candidate's entries.
- Walk-forward selection uses only the train slice; the purge gap removes boundary leakage; test slices are stitched. Each test window restarts from the same capital, so the stitched curve compounds window returns.
- Robustness replays ±30% parameter perturbations with fixed parameters over the same test windows (no re-selection), so it measures how sensitive the out-of-sample result is to the chosen parameters.
- Yearly windows are calendar years of the stitched out-of-sample curve; early years can be partial.
- Deflated Sharpe follows Bailey & López de Prado (2014) using the per-bar Sharpe of every grid point tried in the last train window.
- OKX 1D candles are UTC+8 aligned; 1H/4H are UTC aligned. Holdout = last 12 months of the stored data, evaluated once.
- Derivatives features (S5) exist only for the months OKX serves on its public rubik endpoints; the filter passes where data are missing.
- Every number is a simulation on historical public data and proves nothing about the future.
