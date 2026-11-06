# Replication v1d — the Sprint 2c rule families on OKX spot markets they were never tuned on (walk-forward, SIMULATION ONLY)

Generated 2026-11-04 17:33 UTC by `scripts/run_replication_v1d.py` (plan row R12). Markets: XRP-USDT, DOGE-USDT, LINK-USDT, TRX-USDT, ADA-USDT, LTC-USDT, SOL-USDT — fixed before any result from one public ticker snapshot (2026-11-04T16:32:33+00:00). Rules: exactly Sprint 2c's, run by `scripts/run_research_v1c.py`'s own `run_series` (policy sizing `vt10/30 crash15/90dh ladder`, regime gate `hmm3 bear>=0.5 gate`, S0 filter S0 vol×3 spread p98 gap3 FOMC±6/6h, walk-forward train 540d → purge 7d → test 180d, fee 0.10% + slippage 0.050% per side, brackets ['none', 'tp2', 'trail1', 'time30']). Data: PUBLIC OKX spot candles (1H and 4H stored, 6H resampled from 1H) cut at Sprint 2c's data end (bar close ≤ 2026-10-20T10:00:00+00:00); Binance public funding of each market's USDT perpetual as the S5 feature. Holdout: the last 12 months (2025-10-20->2026-10-20), opened once and only for configurations that passed walk-forward on that market.

**Nothing here authorizes paper, demo or live trading.** A passing configuration is a hypothesis for the forward paper fleet, not a strategy to deploy. Every number is a simulation on historical public data.

## Executive summary (plain English)

- **What we did.** We took the Sprint 2c rules exactly as they were — the same entry rules, parameters, exit brackets, no-trade filter, regime gate, fixed sizing, walk-forward windows and gates — and ran them on 7 OKX spot markets they were never tuned on (XRP, DOGE, LINK, TRX, ADA, LTC, SOL), chosen by trading volume before any result existed. Before any new market was judged, the same code re-ran BTC and ETH and matched Sprint 2c's stored numbers in 36 of 36 configurations. Every market's candles stop where Sprint 2c's did, so the untouched last 12 months are the same calendar window (2025-10-20->2026-10-20).
- **Result: fragile.** 10 of 104 configurations passed every Sprint 2c gate on the new markets (S2 4H [gate] on DOGE; S2 6H [gate] on DOGE; S2 4H [none] on TRX; S2+S5 4H [none] on TRX; S2 6H [none] on ADA; S2 6H [gate] on ADA; S2+S5 6H [none] on ADA; S2+S5 6H [gate] on ADA; S1 6H [none] on SOL; S1+S5 6H [none] on SOL). Per family — S1: fragile (passes on 1 of 7 markets); S1+S5: fragile (passes on 1 of 6 markets); S2: fragile (passes on 3 of 7 markets); S2+S5: fragile (passes on 2 of 6 markets).
- **The three rules that passed on BTC in Sprint 2c, on the new markets.** S2 4H [gate] passed on 1 of 7 new markets (not replicated: needs 4); S2+S5 4H [gate] passed on 0 of 6 new markets (not replicated: needs 4); S1+S5 6H [none] passed on 1 of 6 new markets (not replicated: needs 4).
- **Holdout.** The untouched 12 months then confirmed 2 (S1 6H [none] on SOL, S1+S5 6H [none] on SOL) and contradicted 7 (S2 6H [gate] on DOGE, S2 4H [none] on TRX, S2+S5 4H [none] on TRX, S2 6H [none] on ADA, S2 6H [gate] on ADA, S2+S5 6H [none] on ADA, S2+S5 6H [gate] on ADA) and left 1 unconfirmed for lack of trades (fewer than 10: S2 4H [gate] on DOGE: +1.7% from 8 trades). A walk-forward pass that the holdout rejects is selection luck, not edge; only a confirmed configuration is a candidate for the paper fleet.
- **Beside BTC and ETH.** S1 median Calmar 0.15 on the new markets against 0.29 on BTC and 0.24 on ETH; S1+S5 median Calmar 0.19 on the new markets against 0.41 on BTC and 0.21 on ETH; S2 median Calmar 0.23 on the new markets against 0.25 on BTC and 0.38 on ETH; S2+S5 median Calmar 0.16 on the new markets against 0.29 on BTC and 0.50 on ETH. The gate asks for Calmar above 0.5.
- **Against simply holding with the same risk controls.** On 4 of 14 market-timeframe series the best timing rule beat hold + policy sizing by more than 0.1 Calmar; on the untouched 12 months the hold + policy control's return ranged from -3.7% to -0.1%.
- **Paper fleet.** 2 confirmed configuration(s) were appended to the fleet's shortlist with a source tag (S1+S5 SOL-USDT 6H, S1 SOL-USDT 6H); a running fleet takes them as new accounts at its next restart from an updated checkout. Existing accounts are untouched. Nothing is approved for demo or live trading.

## Fixed before the first run

Pre-registration hash (text, market snapshot and configuration): `baa51d87330156224444bde22e782f1a5c6e9b58253153fd1b0c3db53ee404a0`.

- **fixed_on**: 2026-11-04, before any candle of a new market was collected (plan row R12)
- **question**: Do the Sprint 2c rule families hold on large OKX spot USDT markets they were never tuned on, or are they BTC-specific?
- **markets**: the top 6 of the candidates with public 1H candles from before 2020-01-01 (XRP, LTC, ADA, LINK, BCH, DOGE, TRX, ETC, XLM, ATOM, ALGO), ranked by public 24-hour quote volume (OKX /api/v5/market/tickers, SPOT, volCcy24h) at one snapshot taken before any collection, plus SOL-USDT; the snapshot, the ranking and the chosen list are stored in docs/research/replication_v1d_preregistration.json
- **configurations**: exactly Sprint 2c's: S1, S1+S5, S2, S2+S5 x 4H/6H x regime none/gate = 16 judged configurations per market; hold + policy sizing and plain buy-and-hold as the controls (never judged, as in Sprint 2c); parameters, grids, brackets (none/tp2/trail1/time30; none for the S5 families), the S0 filter with the FOMC calendar, the fixed policy sizing vt10/30 crash15/90dh ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM on returns and 7-day vol, bear >= 0.5, fitted on every window's train slice), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then bracket) and the v1c gates — run by scripts/run_research_v1c.py's own run_series, not by a copy of it
- **data**: OKX public 1H and 4H spot candles through the GET-only lake client (4H stored, 6H resampled from 1H, as Sprint 2c's BTC/ETH data); every market's candles end where Sprint 2c's did (bar close <= 2026-10-20T10:00:00+00:00), so the untouched 12 months are the same calendar window, 2025-10-20 -> 2026-10-20; Binance public funding of the market's USDT perpetual as the S5 feature, through the research symbol table; the new markets have no open-interest history, so that leg of the S5 filter passes (as it does wherever data is missing); a market whose funding covers less than 90 % of its in-sample bars (Sprint 2b item 6) has its S5 configurations reported as 'run without S5' and never counted for the S1+S5 / S2+S5 families
- **reproduction**: before any new market is judged, the same code path re-runs BTC-USDT and ETH-USDT (the 16 configurations and the hold control) and must give Sprint 2c's stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts; otherwise the study stops
- **primary_test**: the configurations that passed every gate on BTC-USDT in Sprint 2c (taken from the stored results: S2 4H gate, S2+S5 4H gate, S1+S5 6H none) run unchanged on every new market; a configuration 'replicates' when it passes all v1c gates on at least half of the new markets
- **family_verdicts**: per family (S1, S1+S5, S2, S2+S5), a market counts when any of the family's four configurations passes all gates there: 'robust across markets' = at least half of the new markets; 'fragile' = at least one but fewer than half; 'BTC-specific' = none, for a family that passed on BTC in Sprint 2c; 'fails everywhere' = none, and it did not pass on BTC either
- **overall_verdict**: 'robust across markets' if any family is robust; 'fragile' if some configuration passes on a new market but no family is robust; 'BTC-specific' if no configuration passes on any new market
- **holdout**: each new market's last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward gate on that market, and only by the full pre-registered study (every chosen market, family, timeframe and mode, no --quick); the v1c verdict (positive return, PF > 1, >= 10 trades); the hold + policy control's 12 months are evaluated on every market as the comparison line, as Sprint 2c did (a reference, not a configuration under test); every opening goes into an append-only ledger the report shows; the new markets' price moves over those months were not looked at before the run
- **gates**: the v1c gates unchanged (research/report_v1c.py GATES)
- **fleet**: a configuration confirmed by its holdout on a new market is added to the paper fleet's shortlist as a new account with a source tag (existing entries and running accounts untouched); a walk-forward pass alone adds nothing
- **no_changes_after_results**: no gate, parameter, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so

The market snapshot (2026-11-04T16:32:33+00:00, `/api/v5/market/tickers?instType=SPOT`, volCcy24h (24-hour volume in the quote currency, USDT)); rule: the top 6 eligible candidates by 24-hour quote volume plus SOL-USDT; history condition: a public 1H candle before 2020-01-01 (probed with /api/v5/market/history-candles, one GET per candidate).

| Market | 24h quote volume | Newest 1H candle before the cutoff | Rank | Chosen | Why |
|---|---:|---|---:|---|---|
| XRP-USDT | 47.4 M USDT | 2019-12-31 23:00 | 1 | yes | rank 1 of 11 by 24-hour quote volume |
| DOGE-USDT | 40.8 M USDT | 2019-12-31 23:00 | 2 | yes | rank 2 of 11 by 24-hour quote volume |
| LINK-USDT | 8.6 M USDT | 2019-12-31 23:00 | 3 | yes | rank 3 of 11 by 24-hour quote volume |
| TRX-USDT | 7.9 M USDT | 2019-12-31 23:00 | 4 | yes | rank 4 of 11 by 24-hour quote volume |
| ADA-USDT | 7.7 M USDT | 2019-12-31 23:00 | 5 | yes | rank 5 of 11 by 24-hour quote volume |
| LTC-USDT | 6.2 M USDT | 2019-12-31 23:00 | 6 | yes | rank 6 of 11 by 24-hour quote volume |
| XLM-USDT | 5.9 M USDT | 2019-12-31 23:00 | 7 | no | rank 7 of 11 by 24-hour quote volume (not in the top 6) |
| BCH-USDT | 4.7 M USDT | 2019-12-31 23:00 | 8 | no | rank 8 of 11 by 24-hour quote volume (not in the top 6) |
| ETC-USDT | 1.5 M USDT | 2019-12-31 23:00 | 9 | no | rank 9 of 11 by 24-hour quote volume (not in the top 6) |
| ATOM-USDT | 1.0 M USDT | 2019-12-31 23:00 | 10 | no | rank 10 of 11 by 24-hour quote volume (not in the top 6) |
| ALGO-USDT | 0.8 M USDT | 2019-12-31 23:00 | 11 | no | rank 11 of 11 by 24-hour quote volume (not in the top 6) |
| SOL-USDT | 99.1 M USDT | - | - | yes | always included (history from 2020-09-29; the largest pair after BTC/ETH that is not a stablecoin) |

Protocol check against the stored Sprint 2c run: every parameter the same (checked: brackets, fee, holdout_months, ladder_recovery_days, min_trades, no_trade_label, policy_sizing, positioning_source, purge_days, quick, rebalance_threshold, regime, regime_modes, select_by, slippage, strategies, test_days, timeframes, train_days).

Gates (unchanged from Sprint 2c): profit_factor_min 1.2; max_drawdown_max 0.2; sharpe_min 0.7; calmar_min 0.5; rolling_12m_positive_min 0.75; worst_calendar_year_min -0.1; min_trades 30; robust_share_min 0.5; min_year_days 60.

## Reproduction of Sprint 2c

Before any new market ran, BTC-USDT and ETH-USDT went through the same loaded runner and had to give Sprint 2c's stored walk-forward numbers (stored with 6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts — otherwise the study stops.

| Candidate | Series | Regime | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |
|---|---|---|---|---|---|---:|---|---|---:|---|
| hold | BTC-USDT 4H | none | 0.147823 / 0.147823 | 0.594651 / 0.594651 | 0.072057 / 0.072057 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 4H | none | 0.093620 / 0.093620 | 0.374170 / 0.374170 | 0.083135 / 0.083135 | 184 / 184 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 4H | gate | 0.069956 / 0.069956 | 0.290839 / 0.290839 | 0.105133 / 0.105133 | 151 / 151 | yes | yes | 0.0e+00 | yes |
| S1+S5 | BTC-USDT 4H | none | 0.121162 / 0.121162 | 0.444672 / 0.444672 | 0.083272 / 0.083272 | 179 / 179 | yes | yes | 0.0e+00 | yes |
| S1+S5 | BTC-USDT 4H | gate | 0.181797 / 0.181797 | 0.654134 / 0.654134 | 0.097921 / 0.097921 | 153 / 153 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 4H | none | 0.149350 / 0.149350 | 0.570857 / 0.570857 | 0.086735 / 0.086735 | 85 / 85 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 4H | gate | 0.246926 / 0.246926 | 0.863110 / 0.863110 | 0.065190 / 0.065190 | 69 / 69 | yes | yes | 0.0e+00 | yes |
| S2+S5 | BTC-USDT 4H | none | 0.161672 / 0.161672 | 0.613595 / 0.613595 | 0.086735 / 0.086735 | 83 / 83 | yes | yes | 0.0e+00 | yes |
| S2+S5 | BTC-USDT 4H | gate | 0.247689 / 0.247689 | 0.865757 / 0.865757 | 0.065190 / 0.065190 | 69 / 69 | yes | yes | 0.0e+00 | yes |
| hold | BTC-USDT 6H | none | 0.118166 / 0.118166 | 0.486633 / 0.486633 | 0.079653 / 0.079653 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 6H | none | 0.159336 / 0.159336 | 0.584869 / 0.584869 | 0.091930 / 0.091930 | 155 / 155 | yes | yes | 0.0e+00 | yes |
| S1 | BTC-USDT 6H | gate | 0.175086 / 0.175086 | 0.625968 / 0.625968 | 0.114153 / 0.114153 | 146 / 146 | yes | yes | 0.0e+00 | yes |
| S1+S5 | BTC-USDT 6H | none | 0.247165 / 0.247165 | 0.856002 / 0.856002 | 0.087603 / 0.087603 | 139 / 139 | yes | yes | 0.0e+00 | yes |
| S1+S5 | BTC-USDT 6H | gate | 0.146569 / 0.146569 | 0.544042 / 0.544042 | 0.076251 / 0.076251 | 139 / 139 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 6H | none | 0.029879 / 0.029879 | 0.160691 / 0.160691 | 0.099668 / 0.099668 | 69 / 69 | yes | yes | 0.0e+00 | yes |
| S2 | BTC-USDT 6H | gate | 0.050630 / 0.050630 | 0.282661 / 0.282661 | 0.098563 / 0.098563 | 48 / 48 | yes | yes | 0.0e+00 | yes |
| S2+S5 | BTC-USDT 6H | none | 0.059688 / 0.059688 | 0.285487 / 0.285487 | 0.100927 / 0.100927 | 57 / 57 | yes | yes | 0.0e+00 | yes |
| S2+S5 | BTC-USDT 6H | gate | 0.079780 / 0.079780 | 0.420793 / 0.420793 | 0.099824 / 0.099824 | 35 / 35 | yes | yes | 0.0e+00 | yes |
| hold | ETH-USDT 4H | none | 0.078472 / 0.078472 | 0.377167 / 0.377167 | 0.086111 / 0.086111 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 4H | none | -0.000879 / -0.000879 | 0.025942 / 0.025942 | 0.134491 / 0.134491 | 225 / 225 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 4H | gate | 0.055714 / 0.055714 | 0.254772 / 0.254772 | 0.115195 / 0.115195 | 150 / 150 | yes | yes | 0.0e+00 | yes |
| S1+S5 | ETH-USDT 4H | none | 0.008910 / 0.008910 | 0.064212 / 0.064212 | 0.136380 / 0.136380 | 204 / 204 | yes | yes | 0.0e+00 | yes |
| S1+S5 | ETH-USDT 4H | gate | 0.023499 / 0.023499 | 0.124703 / 0.124703 | 0.111453 / 0.111453 | 168 / 168 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 4H | none | 0.167322 / 0.167322 | 0.616527 / 0.616527 | 0.088169 / 0.088169 | 77 / 77 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 4H | gate | 0.031911 / 0.031911 | 0.159041 / 0.159041 | 0.108802 / 0.108802 | 86 / 86 | yes | yes | 0.0e+00 | yes |
| S2+S5 | ETH-USDT 4H | none | 0.201207 / 0.201207 | 0.750096 / 0.750096 | 0.069942 / 0.069942 | 72 / 72 | yes | yes | 0.0e+00 | yes |
| S2+S5 | ETH-USDT 4H | gate | 0.054908 / 0.054908 | 0.265939 / 0.265939 | 0.106127 / 0.106127 | 80 / 80 | yes | yes | 0.0e+00 | yes |
| hold | ETH-USDT 6H | none | 0.110168 / 0.110168 | 0.496014 / 0.496014 | 0.095781 / 0.095781 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 6H | none | 0.155841 / 0.155841 | 0.578727 / 0.578727 | 0.082298 / 0.082298 | 165 / 165 | yes | yes | 0.0e+00 | yes |
| S1 | ETH-USDT 6H | gate | 0.123779 / 0.123779 | 0.509298 / 0.509298 | 0.075121 / 0.075121 | 113 / 113 | yes | yes | 0.0e+00 | yes |
| S1+S5 | ETH-USDT 6H | none | 0.125671 / 0.125671 | 0.477462 / 0.477462 | 0.073772 / 0.073772 | 145 / 145 | yes | yes | 0.0e+00 | yes |
| S1+S5 | ETH-USDT 6H | gate | 0.130131 / 0.130131 | 0.527524 / 0.527524 | 0.072093 / 0.072093 | 101 / 101 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 6H | none | 0.147567 / 0.147567 | 0.570377 / 0.570377 | 0.090869 / 0.090869 | 85 / 85 | yes | yes | 0.0e+00 | yes |
| S2 | ETH-USDT 6H | gate | 0.240615 / 0.240615 | 0.916072 / 0.916072 | 0.083290 / 0.083290 | 52 / 52 | yes | yes | 0.0e+00 | yes |
| S2+S5 | ETH-USDT 6H | none | 0.165432 / 0.165432 | 0.652554 / 0.652554 | 0.090444 / 0.090444 | 67 / 67 | yes | yes | 0.0e+00 | yes |
| S2+S5 | ETH-USDT 6H | gate | 0.237133 / 0.237133 | 0.897988 / 0.897988 | 0.085457 / 0.085457 | 51 / 51 | yes | yes | 0.0e+00 | yes |

36 of 36 reproduced.

## The primary test — the configurations that passed on BTC in Sprint 2c, run unchanged on the new markets

A configuration replicates when it passes every gate on at least half of the new markets.

### S2 4H [gate] — passes on 1 of 7 new markets (needs 4): **not replicated**

| Market | Verdict | Gates missed | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Holdout (12m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT (Sprint 2c) | **PASS** | - | +5.2% | 0.86 | 1.94 | 6.5% | 0.80 | 69 | 80.5% | -3.2% | -4.9% / PF 0.28 / 21 tr ✗ |
| XRP-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.4% | 0.28 | 1.20 | 12.3% | 0.11 | 110 | 45.2% | -5.1% | untouched |
| DOGE-USDT | **PASS** | - | +3.6% | 0.81 | 2.29 | 4.2% | 0.85 | 46 | 85.7% | -0.1% | +1.7% / PF 1.70 / 8 tr ✗ |
| LINK-USDT | fail | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | -1.2% | -0.23 | 0.84 | 11.1% | -0.10 | 97 | 35.7% | -4.3% | untouched |
| TRX-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +3.5% | 0.63 | 1.51 | 7.6% | 0.46 | 68 | 66.7% | -3.2% | untouched |
| ADA-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.0% | 0.27 | 1.23 | 7.1% | 0.14 | 58 | 45.2% | -3.6% | untouched |
| LTC-USDT | fail | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | -3.0% | -0.55 | 0.75 | 16.6% | -0.18 | 145 | 9.5% | -5.9% | untouched |
| SOL-USDT | fail | 75% of rolling 12-month windows positive | +4.9% | 0.91 | 1.86 | 7.8% | 0.62 | 70 | 70.0% | -4.4% | untouched |

### S2+S5 4H [gate] — passes on 0 of 6 new markets (needs 4): **not replicated**

| Market | Verdict | Gates missed | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Holdout (12m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT (Sprint 2c) | **PASS** | - | +5.2% | 0.87 | 1.94 | 6.5% | 0.80 | 69 | 80.5% | -3.2% | -3.0% / PF 0.51 / 18 tr ✗ |
| XRP-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.4% | 0.29 | 1.25 | 12.1% | 0.12 | 84 | 47.6% | -5.1% | untouched |
| DOGE-USDT | not judged (S5 inactive) | - | +3.3% | 0.75 | 2.43 | 4.1% | 0.81 | 40 | 85.7% | -0.1% | +1.7% / PF 1.70 / 8 tr ✗ |
| LINK-USDT | fail | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | -0.7% | -0.13 | 0.89 | 9.5% | -0.07 | 83 | 35.7% | -3.9% | untouched |
| TRX-USDT | fail | 75% of rolling 12-month windows positive | +4.2% | 0.74 | 1.66 | 7.2% | 0.57 | 63 | 73.8% | -1.8% | untouched |
| ADA-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.3% | 0.34 | 1.38 | 6.1% | 0.21 | 50 | 45.2% | -1.7% | untouched |
| LTC-USDT | fail | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | -2.7% | -0.48 | 0.63 | 15.2% | -0.18 | 85 | 9.5% | -5.9% | untouched |
| SOL-USDT | fail | 75% of rolling 12-month windows positive | +4.8% | 0.84 | 1.96 | 7.8% | 0.62 | 64 | 70.0% | -4.4% | untouched |

### S1+S5 6H [none] — passes on 1 of 6 new markets (needs 4): **not replicated**

| Market | Verdict | Gates missed | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Holdout (12m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT (Sprint 2c) | **PASS** | - | +5.3% | 0.86 | 1.68 | 8.8% | 0.60 | 139 | 78.0% | -5.7% | +2.3% / PF 1.48 / 32 tr ✓ |
| XRP-USDT | fail | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.2% | 0.22 | 1.19 | 17.2% | 0.07 | 179 | 28.6% | -7.3% | untouched |
| DOGE-USDT | not judged (S5 inactive) | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | -0.3% | -0.03 | 0.97 | 11.8% | -0.03 | 167 | 54.8% | -5.5% | untouched |
| LINK-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +2.5% | 0.45 | 1.42 | 9.3% | 0.27 | 163 | 54.8% | -3.5% | untouched |
| TRX-USDT | fail | Calmar above 0.5, 75% of rolling 12-month windows positive | +5.8% | 0.78 | 1.70 | 13.0% | 0.45 | 174 | 64.3% | -5.5% | untouched |
| ADA-USDT | fail | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | +1.5% | 0.32 | 1.27 | 9.2% | 0.17 | 143 | 57.1% | -2.2% | untouched |
| LTC-USDT | fail | profit factor above 1.2, max drawdown under 20%, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to ±30% parameter changes | -3.3% | -0.53 | 0.69 | 20.3% | -0.16 | 214 | 14.3% | -7.2% | untouched |
| SOL-USDT | **PASS** | - | +7.5% | 1.32 | 2.68 | 5.4% | 1.40 | 101 | 90.0% | -1.7% | +9.5% / PF 5.49 / 12 tr ✓ |


## Family verdicts (pre-registered rule)

A market counts for a family when any of its configurations (4H/6H × none/gate) passes every gate there. Medians are over the family's judged configurations on the new markets, and over the same configurations on BTC and on ETH in Sprint 2c.

| Family | New markets passing | Verdict | Passed on BTC / ETH in 2c | Median Calmar new / BTC / ETH | Median CAGR new / BTC / ETH | Median max DD new / BTC / ETH | PF > 1 (share of new) | Holdout confirmed / contradicted |
|---|---|---|---|---|---|---|---:|---|
| S1 | 1 of 7 (SOL) | **fragile** | no / no | 0.15 / 0.29 / 0.24 | +1.6% / +2.8% / +2.0% | 11.1% / 9.9% / 9.9% | 78.6% | SOL / none |
| S1+S5 | 1 of 6 (SOL) — S5 inactive on DOGE | **fragile** | yes / no | 0.19 / 0.41 / 0.21 | +1.8% / +3.6% / +1.7% | 12.0% / 8.5% / 9.3% | 79.2% | SOL / none |
| S2 | 3 of 7 (ADA, DOGE, TRX) | **fragile** | yes / no | 0.23 / 0.25 / 0.38 | +1.6% / +2.2% / +3.4% | 8.9% / 9.3% / 9.0% | 75.0% | none / ADA, DOGE, TRX |
| S2+S5 | 2 of 6 (ADA, TRX) — S5 inactive on DOGE | **fragile** | yes / no | 0.16 / 0.29 / 0.50 | +1.5% / +2.7% / +4.0% | 9.1% / 9.3% / 8.8% | 75.0% | none / ADA, TRX |

Overall: **fragile** — 10 of 104 judged configurations pass on the new markets; holdout confirmed 2, not confirmed 8 (of which 1 only for lack of trades), not opened 0. Binding gates on the new markets: 75% of rolling 12-month windows positive (92/104), Calmar above 0.5 (81/104), Sharpe above 0.7 (75/104), profit factor above 1.2 (42/104).

## Summary (fixed policy sizing; one row per configuration, grouped by market)

| Market | Candidate | TF | Regime | Bracket | OOS return | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Fees/yr | Rolling 12m + | Worst year | Robust ±30% | DSR | Verdict | Holdout (12m) |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| XRP-USDT | hold | 4H | none | none | +12.3% | +2.7% | 0.55 | 2.97 | 5.8% | 0.46 | 9 | 0.0% | 52.4% | -3.0% | - | 0.88 | control | -2.2% / PF 0.00 / 1 tr ✗ |
| XRP-USDT | S1 | 4H | none | none | -9.4% | -2.2% | -0.36 | 0.80 | 22.3% | -0.10 | 209 | 1.1% | 26.2% | -8.4% | 28.6% | 0.00 | fail | untouched |
| XRP-USDT | S1 | 4H | gate | none | +1.2% | +0.3% | 0.08 | 1.06 | 16.7% | 0.02 | 184 | 1.0% | 33.3% | -5.7% | 42.9% | 0.00 | fail | untouched |
| XRP-USDT | S1+S5 | 4H | none | none | -4.9% | -1.1% | -0.17 | 0.90 | 21.0% | -0.05 | 203 | 1.1% | 33.3% | -7.9% | 60.0% | 0.00 | fail | untouched |
| XRP-USDT | S1+S5 | 4H | gate | none | +2.7% | +0.6% | 0.14 | 1.11 | 15.8% | 0.04 | 175 | 1.0% | 33.3% | -5.7% | 55.6% | 0.01 | fail | untouched |
| XRP-USDT | S2 | 4H | none | none | -0.3% | -0.1% | 0.01 | 1.02 | 16.8% | -0.00 | 92 | 0.4% | 26.2% | -6.3% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2 | 4H | gate | none | +6.1% | +1.4% | 0.28 | 1.20 | 12.3% | 0.11 | 110 | 0.5% | 45.2% | -5.1% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2+S5 | 4H | none | none | +0.6% | +0.1% | 0.05 | 1.06 | 16.7% | 0.01 | 83 | 0.4% | 26.2% | -6.1% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2+S5 | 4H | gate | none | +6.5% | +1.4% | 0.29 | 1.25 | 12.1% | 0.12 | 84 | 0.4% | 47.6% | -5.1% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | hold | 6H | none | none | +21.1% | +4.4% | 0.79 | 4.72 | 5.8% | 0.77 | 9 | 0.0% | 61.9% | -2.8% | - | 0.96 | control | -2.7% / PF 0.00 / 1 tr ✗ |
| XRP-USDT | S1 | 6H | none | none | +7.3% | +1.6% | 0.29 | 1.23 | 16.7% | 0.10 | 192 | 1.0% | 35.7% | -8.8% | 85.7% | 0.04 | fail | untouched |
| XRP-USDT | S1 | 6H | gate | trail1 | +18.3% | +3.9% | 0.67 | 1.55 | 10.9% | 0.36 | 137 | 0.7% | 33.3% | -3.3% | 87.5% | 0.06 | fail | untouched |
| XRP-USDT | S1+S5 | 6H | none | none | +5.3% | +1.2% | 0.22 | 1.19 | 17.2% | 0.07 | 179 | 0.9% | 28.6% | -7.3% | 80.0% | 0.05 | fail | untouched |
| XRP-USDT | S1+S5 | 6H | gate | none | +17.2% | +3.7% | 0.62 | 1.70 | 11.6% | 0.32 | 118 | 0.6% | 33.3% | -3.4% | 100.0% | 0.08 | fail | untouched |
| XRP-USDT | S2 | 6H | none | time30 | +4.1% | +0.9% | 0.18 | 1.15 | 14.1% | 0.07 | 100 | 0.5% | 33.3% | -3.5% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2 | 6H | gate | none | -2.0% | -0.5% | -0.11 | 0.91 | 7.5% | -0.06 | 47 | 0.2% | 28.6% | -1.7% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2+S5 | 6H | none | none | +7.5% | +1.7% | 0.30 | 1.28 | 12.4% | 0.13 | 75 | 0.4% | 52.4% | -3.5% | 100.0% | 0.00 | fail | untouched |
| XRP-USDT | S2+S5 | 6H | gate | none | -0.1% | -0.0% | 0.01 | 1.01 | 6.7% | -0.00 | 39 | 0.2% | 40.5% | -1.4% | 100.0% | 0.00 | fail | untouched |
| DOGE-USDT | hold | 4H | none | none | +3.0% | +0.7% | 0.19 | 1.58 | 6.9% | 0.10 | 9 | 0.0% | 47.6% | -2.5% | - | 0.65 | control | -2.7% / PF 0.00 / 1 tr ✗ |
| DOGE-USDT | S1 | 4H | none | none | +16.2% | +3.5% | 0.67 | 1.42 | 6.3% | 0.55 | 252 | 1.0% | 85.7% | -2.9% | 100.0% | 0.38 | fail | untouched |
| DOGE-USDT | S1 | 4H | gate | trail1 | +3.4% | +0.8% | 0.20 | 1.14 | 5.8% | 0.13 | 132 | 0.5% | 57.1% | -2.7% | 100.0% | 0.02 | fail | untouched |
| DOGE-USDT | S1 (run without S5: funding covers 90% of the in-sample bars) | 4H | none | none | +5.8% | +1.3% | 0.28 | 1.18 | 7.8% | 0.16 | 206 | 0.8% | 59.5% | -3.1% | 100.0% | 0.23 | not judged | untouched |
| DOGE-USDT | S1 (run without S5: funding covers 90% of the in-sample bars) | 4H | gate | none | +4.2% | +1.0% | 0.23 | 1.18 | 6.0% | 0.16 | 114 | 0.5% | 57.1% | -2.7% | 100.0% | 0.08 | not judged | untouched |
| DOGE-USDT | S2 | 4H | none | none | +8.3% | +1.8% | 0.44 | 1.50 | 6.3% | 0.29 | 59 | 0.2% | 66.7% | -2.3% | 100.0% | 0.01 | fail | untouched |
| DOGE-USDT | S2 | 4H | gate | none | +16.7% | +3.6% | 0.81 | 2.29 | 4.2% | 0.85 | 46 | 0.2% | 85.7% | -0.1% | 100.0% | 0.14 | **PASS** | +1.7% / PF 1.70 / 8 tr ✗ |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) | 4H | none | none | +8.6% | +1.9% | 0.46 | 1.53 | 5.7% | 0.33 | 58 | 0.2% | 66.7% | -2.5% | 100.0% | 0.01 | not judged | untouched |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) | 4H | gate | none | +15.3% | +3.3% | 0.75 | 2.43 | 4.1% | 0.81 | 40 | 0.2% | 85.7% | -0.1% | 100.0% | 0.16 | not judged | +1.7% / PF 1.70 / 8 tr ✗ |
| DOGE-USDT | hold | 6H | none | none | +5.2% | +1.2% | 0.28 | 1.94 | 7.2% | 0.16 | 9 | 0.0% | 52.4% | -2.6% | - | 0.72 | control | -3.1% / PF 0.00 / 1 tr ✗ |
| DOGE-USDT | S1 | 6H | none | trail1 | +3.4% | +0.8% | 0.17 | 1.09 | 9.1% | 0.08 | 181 | 0.7% | 54.8% | -5.0% | 87.5% | 0.07 | fail | untouched |
| DOGE-USDT | S1 | 6H | gate | trail1 | +14.2% | +3.1% | 0.61 | 1.53 | 5.9% | 0.52 | 109 | 0.5% | 78.6% | -0.4% | 100.0% | 0.33 | fail | untouched |
| DOGE-USDT | S1 (run without S5: funding covers 90% of the in-sample bars) | 6H | none | none | -1.3% | -0.3% | -0.03 | 0.97 | 11.8% | -0.03 | 167 | 0.7% | 54.8% | -5.5% | 100.0% | 0.07 | not judged | untouched |
| DOGE-USDT | S1 (run without S5: funding covers 90% of the in-sample bars) | 6H | gate | none | +8.7% | +1.9% | 0.40 | 1.36 | 6.0% | 0.32 | 101 | 0.4% | 66.7% | -0.4% | 100.0% | 0.33 | not judged | untouched |
| DOGE-USDT | S2 | 6H | none | none | +10.5% | +2.3% | 0.52 | 1.76 | 6.8% | 0.34 | 45 | 0.2% | 66.7% | -0.1% | 100.0% | 0.00 | fail | untouched |
| DOGE-USDT | S2 | 6H | gate | none | +20.3% | +4.3% | 0.90 | 2.50 | 5.6% | 0.77 | 46 | 0.2% | 85.7% | +0.0% | 100.0% | 0.13 | **PASS** | -0.6% / PF 0.87 / 10 tr ✗ |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) | 6H | none | none | +9.7% | +2.1% | 0.49 | 1.68 | 7.5% | 0.29 | 46 | 0.2% | 66.7% | -0.1% | 100.0% | 0.01 | not judged | untouched |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) | 6H | gate | none | +20.4% | +4.3% | 0.90 | 3.07 | 5.6% | 0.77 | 36 | 0.2% | 85.7% | +0.0% | 100.0% | 0.14 | not judged | -0.6% / PF 0.88 / 10 tr ✗ |
| LINK-USDT | hold | 4H | none | none | +7.1% | +1.6% | 0.37 | 2.90 | 5.6% | 0.28 | 9 | 0.0% | 54.8% | -2.2% | - | 0.78 | control | -1.7% / PF 0.00 / 1 tr ✗ |
| LINK-USDT | S1 | 4H | none | time30 | -0.6% | -0.1% | 0.00 | 1.00 | 12.8% | -0.01 | 219 | 0.9% | 54.8% | -5.3% | 100.0% | 0.04 | fail | untouched |
| LINK-USDT | S1 | 4H | gate | time30 | +7.3% | +1.6% | 0.33 | 1.23 | 8.7% | 0.19 | 186 | 0.8% | 61.9% | -4.1% | 100.0% | 0.10 | fail | untouched |
| LINK-USDT | S1+S5 | 4H | none | none | +5.7% | +1.3% | 0.26 | 1.20 | 10.1% | 0.13 | 184 | 0.8% | 54.8% | -3.9% | 100.0% | 0.18 | fail | untouched |
| LINK-USDT | S1+S5 | 4H | gate | none | +9.2% | +2.0% | 0.40 | 1.35 | 9.2% | 0.22 | 165 | 0.8% | 61.9% | -4.1% | 100.0% | 0.22 | fail | untouched |
| LINK-USDT | S2 | 4H | none | none | -4.0% | -0.9% | -0.17 | 0.87 | 11.6% | -0.08 | 96 | 0.4% | 40.5% | -5.0% | 100.0% | 0.01 | fail | untouched |
| LINK-USDT | S2 | 4H | gate | none | -5.0% | -1.2% | -0.23 | 0.84 | 11.1% | -0.10 | 97 | 0.4% | 35.7% | -4.3% | 0.0% | 0.00 | fail | untouched |
| LINK-USDT | S2+S5 | 4H | none | none | -2.5% | -0.6% | -0.10 | 0.91 | 10.9% | -0.05 | 84 | 0.3% | 40.5% | -5.7% | 100.0% | 0.01 | fail | untouched |
| LINK-USDT | S2+S5 | 4H | gate | none | -3.1% | -0.7% | -0.13 | 0.89 | 9.5% | -0.07 | 83 | 0.3% | 35.7% | -3.9% | 0.0% | 0.02 | fail | untouched |
| LINK-USDT | hold | 6H | none | none | +8.9% | +2.0% | 0.42 | 3.52 | 5.5% | 0.35 | 9 | 0.0% | 54.8% | -2.4% | - | 0.81 | control | -1.7% / PF 0.00 / 1 tr ✗ |
| LINK-USDT | S1 | 6H | none | none | +8.8% | +1.9% | 0.37 | 1.28 | 9.1% | 0.21 | 173 | 0.7% | 54.8% | -3.5% | 100.0% | 0.15 | fail | untouched |
| LINK-USDT | S1 | 6H | gate | none | +5.0% | +1.1% | 0.23 | 1.17 | 11.3% | 0.10 | 164 | 0.6% | 54.8% | -5.1% | 57.1% | 0.20 | fail | untouched |
| LINK-USDT | S1+S5 | 6H | none | none | +11.5% | +2.5% | 0.45 | 1.42 | 9.3% | 0.27 | 163 | 0.6% | 54.8% | -3.5% | 80.0% | 0.24 | fail | untouched |
| LINK-USDT | S1+S5 | 6H | gate | none | +5.5% | +1.2% | 0.24 | 1.22 | 11.4% | 0.11 | 154 | 0.6% | 54.8% | -5.1% | 70.0% | 0.25 | fail | untouched |
| LINK-USDT | S2 | 6H | none | none | +0.8% | +0.2% | 0.06 | 1.05 | 10.8% | 0.02 | 79 | 0.3% | 40.5% | -4.1% | 50.0% | 0.08 | fail | untouched |
| LINK-USDT | S2 | 6H | gate | none | -0.1% | -0.0% | 0.02 | 1.02 | 10.0% | -0.00 | 57 | 0.2% | 45.2% | -3.4% | 20.0% | 0.00 | fail | untouched |
| LINK-USDT | S2+S5 | 6H | none | none | +1.9% | +0.4% | 0.11 | 1.11 | 9.1% | 0.05 | 65 | 0.2% | 40.5% | -3.6% | 8.3% | 0.15 | fail | untouched |
| LINK-USDT | S2+S5 | 6H | gate | none | +0.9% | +0.2% | 0.07 | 1.09 | 8.6% | 0.02 | 51 | 0.2% | 47.6% | -3.4% | 16.7% | 0.00 | fail | untouched |
| TRX-USDT | hold | 4H | none | none | +36.4% | +7.3% | 1.30 | 11.67 | 5.6% | 1.31 | 9 | 0.1% | 78.6% | -1.5% | - | 1.00 | control | -0.8% / PF 0.00 / 1 tr ✗ |
| TRX-USDT | S1 | 4H | none | none | +22.6% | +4.7% | 0.68 | 1.36 | 15.3% | 0.31 | 282 | 2.3% | 54.8% | -5.1% | 100.0% | 0.27 | fail | untouched |
| TRX-USDT | S1 | 4H | gate | none | +18.9% | +4.0% | 0.59 | 1.33 | 12.7% | 0.32 | 177 | 2.0% | 57.1% | -4.6% | 100.0% | 0.31 | fail | untouched |
| TRX-USDT | S1+S5 | 4H | none | none | +24.3% | +5.1% | 0.75 | 1.56 | 13.6% | 0.37 | 223 | 1.8% | 57.1% | -4.5% | 100.0% | 0.70 | fail | untouched |
| TRX-USDT | S1+S5 | 4H | gate | none | +23.4% | +4.9% | 0.72 | 1.57 | 12.5% | 0.39 | 145 | 1.6% | 57.1% | -4.9% | 100.0% | 0.78 | fail | untouched |
| TRX-USDT | S2 | 4H | none | none | +24.1% | +5.0% | 0.82 | 1.63 | 8.7% | 0.58 | 95 | 1.2% | 76.2% | -4.8% | 100.0% | 0.22 | **PASS** | -5.6% / PF 0.47 / 26 tr ✗ |
| TRX-USDT | S2 | 4H | gate | none | +16.3% | +3.5% | 0.63 | 1.51 | 7.6% | 0.46 | 68 | 1.0% | 66.7% | -3.2% | 100.0% | 0.18 | fail | untouched |
| TRX-USDT | S2+S5 | 4H | none | none | +24.4% | +5.1% | 0.82 | 1.80 | 8.5% | 0.60 | 77 | 0.9% | 76.2% | -4.6% | 100.0% | 0.25 | **PASS** | -5.6% / PF 0.47 / 26 tr ✗ |
| TRX-USDT | S2+S5 | 4H | gate | none | +19.6% | +4.2% | 0.74 | 1.66 | 7.2% | 0.57 | 63 | 0.9% | 73.8% | -1.8% | 100.0% | 0.26 | fail | untouched |
| TRX-USDT | hold | 6H | none | none | +36.3% | +7.3% | 1.13 | 8.79 | 6.6% | 1.11 | 9 | 0.1% | 71.4% | -2.7% | - | 1.00 | control | -0.1% / PF 0.00 / 1 tr ✗ |
| TRX-USDT | S1 | 6H | none | none | +29.2% | +6.0% | 0.76 | 1.56 | 12.6% | 0.48 | 198 | 1.7% | 64.3% | -5.7% | 100.0% | 0.44 | fail | untouched |
| TRX-USDT | S1 | 6H | gate | none | +28.2% | +5.8% | 0.74 | 1.54 | 15.1% | 0.39 | 199 | 1.9% | 66.7% | -7.7% | 100.0% | 0.40 | fail | untouched |
| TRX-USDT | S1+S5 | 6H | none | none | +28.3% | +5.8% | 0.78 | 1.70 | 13.0% | 0.45 | 174 | 1.5% | 64.3% | -5.5% | 100.0% | 0.70 | fail | untouched |
| TRX-USDT | S1+S5 | 6H | gate | none | +30.0% | +6.1% | 0.78 | 1.65 | 14.3% | 0.43 | 190 | 1.9% | 66.7% | -6.2% | 100.0% | 0.71 | fail | untouched |
| TRX-USDT | S2 | 6H | none | none | +32.2% | +6.6% | 0.84 | 1.64 | 12.6% | 0.52 | 119 | 1.5% | 64.3% | -7.2% | 100.0% | 0.09 | fail | untouched |
| TRX-USDT | S2 | 6H | gate | none | +32.1% | +6.5% | 0.90 | 1.75 | 12.1% | 0.54 | 98 | 1.3% | 61.9% | -7.2% | 100.0% | 0.18 | fail | untouched |
| TRX-USDT | S2+S5 | 6H | none | none | +37.2% | +7.5% | 0.97 | 2.16 | 11.3% | 0.66 | 70 | 0.9% | 64.3% | -7.2% | 100.0% | 0.17 | fail | untouched |
| TRX-USDT | S2+S5 | 6H | gate | none | +38.0% | +7.6% | 1.08 | 2.65 | 10.8% | 0.70 | 48 | 0.6% | 61.9% | -7.2% | 100.0% | 0.37 | fail | untouched |
| ADA-USDT | hold | 4H | none | none | +5.5% | +1.2% | 0.29 | 1.86 | 7.7% | 0.16 | 9 | 0.0% | 54.8% | -4.0% | - | 0.73 | control | -3.0% / PF 0.00 / 1 tr ✗ |
| ADA-USDT | S1 | 4H | none | none | +5.5% | +1.2% | 0.26 | 1.13 | 9.6% | 0.13 | 237 | 1.0% | 64.3% | -3.9% | 100.0% | 0.01 | fail | untouched |
| ADA-USDT | S1 | 4H | gate | none | +8.1% | +1.8% | 0.41 | 1.30 | 11.2% | 0.16 | 161 | 0.7% | 64.3% | -4.0% | 100.0% | 0.01 | fail | untouched |
| ADA-USDT | S1+S5 | 4H | none | none | +10.0% | +2.2% | 0.44 | 1.33 | 8.9% | 0.25 | 185 | 0.8% | 66.7% | -2.8% | 100.0% | 0.08 | fail | untouched |
| ADA-USDT | S1+S5 | 4H | gate | none | +4.9% | +1.1% | 0.26 | 1.21 | 13.0% | 0.08 | 158 | 0.7% | 61.9% | -3.9% | 100.0% | 0.01 | fail | untouched |
| ADA-USDT | S2 | 4H | none | none | +6.2% | +1.4% | 0.32 | 1.26 | 8.1% | 0.17 | 80 | 0.3% | 57.1% | -3.3% | 90.0% | 0.00 | fail | untouched |
| ADA-USDT | S2 | 4H | gate | none | +4.5% | +1.0% | 0.27 | 1.23 | 7.1% | 0.14 | 58 | 0.3% | 45.2% | -3.6% | 90.0% | 0.00 | fail | untouched |
| ADA-USDT | S2+S5 | 4H | none | none | +6.7% | +1.5% | 0.35 | 1.29 | 8.2% | 0.18 | 78 | 0.3% | 52.4% | -2.7% | 100.0% | 0.00 | fail | untouched |
| ADA-USDT | S2+S5 | 4H | gate | none | +5.7% | +1.3% | 0.34 | 1.38 | 6.1% | 0.21 | 50 | 0.2% | 45.2% | -1.7% | 91.7% | 0.00 | fail | untouched |
| ADA-USDT | hold | 6H | none | none | +5.9% | +1.3% | 0.30 | 1.93 | 8.0% | 0.16 | 9 | 0.0% | 54.8% | -4.6% | - | 0.73 | control | -3.7% / PF 0.00 / 1 tr ✗ |
| ADA-USDT | S1 | 6H | none | none | +4.1% | +0.9% | 0.20 | 1.13 | 11.0% | 0.08 | 155 | 0.6% | 57.1% | -3.7% | 100.0% | 0.01 | fail | untouched |
| ADA-USDT | S1 | 6H | gate | none | +3.9% | +0.9% | 0.20 | 1.12 | 10.4% | 0.08 | 147 | 0.6% | 52.4% | -4.1% | 100.0% | 0.00 | fail | untouched |
| ADA-USDT | S1+S5 | 6H | none | none | +6.9% | +1.5% | 0.32 | 1.27 | 9.2% | 0.17 | 143 | 0.6% | 57.1% | -2.2% | 66.7% | 0.05 | fail | untouched |
| ADA-USDT | S1+S5 | 6H | gate | none | +4.5% | +1.0% | 0.23 | 1.18 | 10.7% | 0.10 | 133 | 0.6% | 52.4% | -4.1% | 100.0% | 0.01 | fail | untouched |
| ADA-USDT | S2 | 6H | none | none | +20.6% | +4.3% | 0.87 | 1.99 | 6.9% | 0.63 | 65 | 0.3% | 83.3% | -1.7% | 100.0% | 0.03 | **PASS** | -4.6% / PF 0.28 / 20 tr ✗ |
| ADA-USDT | S2 | 6H | gate | none | +21.2% | +4.5% | 0.94 | 2.37 | 4.7% | 0.95 | 44 | 0.2% | 88.1% | -2.3% | 100.0% | 0.08 | **PASS** | -6.0% / PF 0.07 / 20 tr ✗ |
| ADA-USDT | S2+S5 | 6H | none | none | +19.7% | +4.2% | 0.85 | 1.96 | 6.9% | 0.60 | 66 | 0.3% | 85.7% | -1.7% | 100.0% | 0.04 | **PASS** | -4.6% / PF 0.28 / 20 tr ✗ |
| ADA-USDT | S2+S5 | 6H | gate | none | +20.9% | +4.4% | 0.93 | 2.29 | 5.1% | 0.87 | 45 | 0.2% | 88.1% | -3.5% | 100.0% | 0.10 | **PASS** | -6.0% / PF 0.07 / 20 tr ✗ |
| LTC-USDT | hold | 4H | none | none | -1.8% | -0.4% | -0.08 | 0.79 | 7.6% | -0.05 | 9 | 0.0% | 38.1% | -2.1% | - | 0.44 | control | -1.4% / PF 0.00 / 1 tr ✗ |
| LTC-USDT | S1 | 4H | none | none | -14.9% | -3.6% | -0.61 | 0.74 | 21.9% | -0.16 | 288 | 1.2% | 14.3% | -7.9% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1 | 4H | gate | none | -14.3% | -3.5% | -0.58 | 0.65 | 21.9% | -0.16 | 203 | 0.9% | 14.3% | -6.8% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1+S5 | 4H | none | none | -15.8% | -3.8% | -0.65 | 0.64 | 21.0% | -0.18 | 255 | 1.1% | 14.3% | -7.1% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1+S5 | 4H | gate | none | -15.0% | -3.6% | -0.60 | 0.59 | 21.0% | -0.17 | 185 | 0.9% | 19.0% | -5.7% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2 | 4H | none | none | -2.2% | -0.5% | -0.06 | 0.96 | 12.0% | -0.04 | 118 | 0.6% | 31.0% | -5.9% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2 | 4H | gate | none | -12.5% | -3.0% | -0.55 | 0.75 | 16.6% | -0.18 | 145 | 0.9% | 9.5% | -5.9% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2+S5 | 4H | none | none | -3.7% | -0.9% | -0.12 | 0.87 | 12.4% | -0.07 | 78 | 0.4% | 28.6% | -5.9% | 8.3% | 0.00 | fail | untouched |
| LTC-USDT | S2+S5 | 4H | gate | none | -11.2% | -2.7% | -0.48 | 0.63 | 15.2% | -0.18 | 85 | 0.5% | 9.5% | -5.9% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | hold | 6H | none | none | -0.7% | -0.1% | -0.01 | 0.94 | 7.6% | -0.02 | 9 | 0.0% | 47.6% | -2.0% | - | 0.49 | control | -1.1% / PF 0.00 / 1 tr ✗ |
| LTC-USDT | S1 | 6H | none | none | -13.5% | -3.2% | -0.50 | 0.71 | 19.9% | -0.16 | 221 | 0.9% | 14.3% | -6.3% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1 | 6H | gate | none | -14.9% | -3.6% | -0.61 | 0.66 | 22.0% | -0.16 | 187 | 0.8% | 11.9% | -7.0% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1+S5 | 6H | none | none | -13.9% | -3.3% | -0.53 | 0.69 | 20.3% | -0.16 | 214 | 0.9% | 14.3% | -7.2% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S1+S5 | 6H | gate | none | -14.9% | -3.6% | -0.63 | 0.61 | 22.0% | -0.16 | 174 | 0.8% | 14.3% | -6.6% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2 | 6H | none | none | -11.8% | -2.8% | -0.52 | 0.67 | 15.6% | -0.18 | 87 | 0.4% | 23.8% | -6.8% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2 | 6H | gate | none | -10.3% | -2.4% | -0.46 | 0.69 | 15.2% | -0.16 | 78 | 0.4% | 26.2% | -6.3% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2+S5 | 6H | none | none | -11.4% | -2.7% | -0.48 | 0.60 | 15.7% | -0.17 | 73 | 0.4% | 21.4% | -6.2% | 0.0% | 0.00 | fail | untouched |
| LTC-USDT | S2+S5 | 6H | gate | none | -10.6% | -2.5% | -0.46 | 0.63 | 15.5% | -0.16 | 67 | 0.3% | 26.2% | -6.5% | 0.0% | 0.00 | fail | untouched |
| SOL-USDT | hold | 4H | none | none | +23.9% | +6.4% | 1.07 | 4.84 | 6.7% | 0.96 | 7 | 0.0% | 76.7% | -5.3% | - | 0.98 | control | -2.3% / PF 0.00 / 1 tr ✗ |
| SOL-USDT | S1 | 4H | none | none | +18.1% | +4.9% | 0.92 | 1.85 | 7.5% | 0.65 | 141 | 0.7% | 70.0% | -3.2% | 100.0% | 0.35 | fail | untouched |
| SOL-USDT | S1 | 4H | gate | none | +6.0% | +1.7% | 0.39 | 1.25 | 6.2% | 0.27 | 134 | 0.7% | 53.3% | -3.3% | 100.0% | 0.18 | fail | untouched |
| SOL-USDT | S1+S5 | 4H | none | none | +16.7% | +4.6% | 0.88 | 1.78 | 8.9% | 0.51 | 138 | 0.7% | 70.0% | -4.3% | 100.0% | 0.52 | fail | untouched |
| SOL-USDT | S1+S5 | 4H | gate | none | +8.2% | +2.3% | 0.52 | 1.41 | 6.8% | 0.34 | 119 | 0.6% | 50.0% | -3.4% | 100.0% | 0.42 | fail | untouched |
| SOL-USDT | S2 | 4H | none | none | +11.7% | +3.3% | 0.60 | 1.62 | 7.2% | 0.46 | 73 | 0.3% | 60.0% | -4.4% | 100.0% | 0.32 | fail | untouched |
| SOL-USDT | S2 | 4H | gate | none | +17.9% | +4.9% | 0.91 | 1.86 | 7.8% | 0.62 | 70 | 0.3% | 70.0% | -4.4% | 100.0% | 0.57 | fail | untouched |
| SOL-USDT | S2+S5 | 4H | none | none | +11.7% | +3.3% | 0.60 | 1.62 | 7.2% | 0.45 | 73 | 0.3% | 60.0% | -4.4% | 100.0% | 0.52 | fail | untouched |
| SOL-USDT | S2+S5 | 4H | gate | none | +17.7% | +4.8% | 0.84 | 1.96 | 7.8% | 0.62 | 64 | 0.3% | 70.0% | -4.4% | 100.0% | 0.68 | fail | untouched |
| SOL-USDT | hold | 6H | none | none | +28.5% | +7.5% | 1.13 | 5.40 | 7.0% | 1.08 | 7 | 0.0% | 76.7% | -5.0% | - | 0.98 | control | -2.5% / PF 0.00 / 1 tr ✗ |
| SOL-USDT | S1 | 6H | none | time30 | +22.3% | +6.0% | 1.08 | 2.08 | 5.6% | 1.06 | 107 | 0.6% | 90.0% | -1.7% | 100.0% | 0.52 | **PASS** | +9.5% / PF 5.49 / 12 tr ✓ |
| SOL-USDT | S1 | 6H | gate | none | +18.9% | +5.1% | 0.92 | 1.99 | 6.9% | 0.74 | 105 | 0.5% | 60.0% | -2.7% | 100.0% | 0.49 | fail | untouched |
| SOL-USDT | S1+S5 | 6H | none | none | +28.3% | +7.5% | 1.32 | 2.68 | 5.4% | 1.40 | 101 | 0.6% | 90.0% | -1.7% | 100.0% | 0.88 | **PASS** | +9.5% / PF 5.49 / 12 tr ✓ |
| SOL-USDT | S1+S5 | 6H | gate | none | +18.9% | +5.1% | 0.94 | 2.06 | 6.9% | 0.74 | 101 | 0.5% | 63.3% | -2.7% | 100.0% | 0.68 | fail | untouched |
| SOL-USDT | S2 | 6H | none | none | +9.1% | +2.6% | 0.51 | 1.46 | 7.3% | 0.35 | 67 | 0.3% | 73.3% | -5.9% | 100.0% | 0.23 | fail | untouched |
| SOL-USDT | S2 | 6H | gate | none | +16.0% | +4.4% | 0.83 | 2.33 | 9.1% | 0.48 | 37 | 0.2% | 50.0% | -4.7% | 100.0% | 0.48 | fail | untouched |
| SOL-USDT | S2+S5 | 6H | none | none | +9.7% | +2.7% | 0.54 | 1.52 | 7.3% | 0.37 | 64 | 0.3% | 73.3% | -5.9% | 100.0% | 0.45 | fail | untouched |
| SOL-USDT | S2+S5 | 6H | gate | none | +16.0% | +4.4% | 0.82 | 2.31 | 9.2% | 0.48 | 37 | 0.2% | 50.0% | -4.8% | 100.0% | 0.72 | fail | untouched |

Data spans: XRP-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); XRP-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); DOGE-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); DOGE-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); LINK-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); LINK-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); TRX-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); TRX-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); ADA-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); ADA-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); LTC-USDT 4H: 2019-11-28->2026-10-20 (15107 bars); LTC-USDT 6H: 2019-11-28->2026-10-20 (10071 bars); SOL-USDT 4H: 2020-09-30->2026-10-20 (13266 bars); SOL-USDT 6H: 2020-09-30->2026-10-20 (8843 bars).

## Sprint 2c's own numbers for the same configurations (BTC-USDT and ETH-USDT, from `ensemble_v1c_results.json`)

| Market | Candidate | TF | Regime | CAGR | Sharpe | PF | Max DD | Calmar | Trades | Rolling 12m + | Worst year | Verdict | Holdout (12m) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| BTC-USDT | S1 | 4H | gate | +1.6% | 0.29 | 1.18 | 10.5% | 0.15 | 151 | 65.9% | -2.7% | fail | untouched |
| BTC-USDT | S1 | 4H | none | +2.1% | 0.37 | 1.23 | 8.3% | 0.25 | 184 | 61.0% | -4.4% | fail | untouched |
| BTC-USDT | S1+S5 | 4H | gate | +3.9% | 0.65 | 1.48 | 9.8% | 0.40 | 153 | 73.2% | -2.7% | fail | untouched |
| BTC-USDT | S1+S5 | 4H | none | +2.7% | 0.44 | 1.33 | 8.3% | 0.32 | 179 | 63.4% | -4.4% | fail | untouched |
| BTC-USDT | S2 | 4H | gate | +5.2% | 0.86 | 1.94 | 6.5% | 0.80 | 69 | 80.5% | -3.2% | **PASS** | -4.9% / PF 0.28 / 21 tr ✗ |
| BTC-USDT | S2 | 4H | none | +3.3% | 0.57 | 1.46 | 8.7% | 0.38 | 85 | 61.0% | -4.6% | fail | untouched |
| BTC-USDT | S2+S5 | 4H | gate | +5.2% | 0.87 | 1.94 | 6.5% | 0.80 | 69 | 80.5% | -3.2% | **PASS** | -3.0% / PF 0.51 / 18 tr ✗ |
| BTC-USDT | S2+S5 | 4H | none | +3.5% | 0.61 | 1.52 | 8.7% | 0.40 | 83 | 61.0% | -4.6% | fail | untouched |
| BTC-USDT | hold | 4H | none | +3.2% | 0.59 | 2.88 | 7.2% | 0.45 | 9 | 70.7% | -4.7% | control | -4.3% / PF 0.00 / 1 tr ✗ |
| BTC-USDT | S1 | 6H | gate | +3.8% | 0.63 | 1.42 | 11.4% | 0.33 | 146 | 73.2% | -4.2% | fail | untouched |
| BTC-USDT | S1 | 6H | none | +3.5% | 0.58 | 1.40 | 9.2% | 0.38 | 155 | 68.3% | -4.9% | fail | untouched |
| BTC-USDT | S1+S5 | 6H | gate | +3.2% | 0.54 | 1.41 | 7.6% | 0.42 | 139 | 70.7% | -5.0% | fail | untouched |
| BTC-USDT | S1+S5 | 6H | none | +5.3% | 0.86 | 1.68 | 8.8% | 0.60 | 139 | 78.0% | -5.7% | **PASS** | +2.3% / PF 1.48 / 32 tr ✓ |
| BTC-USDT | S2 | 6H | gate | +1.2% | 0.28 | 1.22 | 9.9% | 0.12 | 48 | 56.1% | -1.7% | fail | untouched |
| BTC-USDT | S2 | 6H | none | +0.7% | 0.16 | 1.10 | 10.0% | 0.07 | 69 | 58.5% | -3.5% | fail | untouched |
| BTC-USDT | S2+S5 | 6H | gate | +1.8% | 0.42 | 1.46 | 10.0% | 0.18 | 35 | 63.4% | -1.7% | fail | untouched |
| BTC-USDT | S2+S5 | 6H | none | +1.4% | 0.29 | 1.23 | 10.1% | 0.13 | 57 | 61.0% | -3.5% | fail | untouched |
| BTC-USDT | hold | 6H | none | +2.6% | 0.49 | 2.37 | 8.0% | 0.33 | 9 | 73.2% | -4.8% | control | -4.0% / PF 0.00 / 1 tr ✗ |
| ETH-USDT | S1 | 4H | gate | +1.3% | 0.25 | 1.18 | 11.5% | 0.11 | 150 | 39.0% | -3.0% | fail | untouched |
| ETH-USDT | S1 | 4H | none | -0.0% | 0.03 | 1.01 | 13.4% | -0.00 | 225 | 31.7% | -4.5% | fail | untouched |
| ETH-USDT | S1+S5 | 4H | gate | +0.5% | 0.12 | 1.07 | 11.1% | 0.05 | 168 | 39.0% | -3.0% | fail | untouched |
| ETH-USDT | S1+S5 | 4H | none | +0.2% | 0.06 | 1.04 | 13.6% | 0.01 | 204 | 34.1% | -4.6% | fail | untouched |
| ETH-USDT | S2 | 4H | gate | +0.7% | 0.16 | 1.10 | 10.9% | 0.07 | 86 | 70.7% | -0.8% | fail | untouched |
| ETH-USDT | S2 | 4H | none | +3.6% | 0.62 | 1.63 | 8.8% | 0.41 | 77 | 63.4% | -0.6% | fail | untouched |
| ETH-USDT | S2+S5 | 4H | gate | +1.2% | 0.27 | 1.17 | 10.6% | 0.12 | 80 | 70.7% | -0.6% | fail | untouched |
| ETH-USDT | S2+S5 | 4H | none | +4.3% | 0.75 | 1.81 | 7.0% | 0.62 | 72 | 70.7% | -0.5% | fail | untouched |
| ETH-USDT | hold | 4H | none | +1.8% | 0.38 | 1.83 | 8.6% | 0.20 | 9 | 63.4% | -4.1% | control | -2.6% / PF 0.00 / 1 tr ✗ |
| ETH-USDT | S1 | 6H | gate | +2.7% | 0.51 | 1.38 | 7.5% | 0.37 | 113 | 80.5% | -1.8% | fail | untouched |
| ETH-USDT | S1 | 6H | none | +3.4% | 0.58 | 1.31 | 8.2% | 0.42 | 165 | 68.3% | -2.2% | fail | untouched |
| ETH-USDT | S1+S5 | 6H | gate | +2.9% | 0.53 | 1.43 | 7.2% | 0.40 | 101 | 80.5% | -2.0% | fail | untouched |
| ETH-USDT | S1+S5 | 6H | none | +2.8% | 0.48 | 1.33 | 7.4% | 0.38 | 145 | 68.3% | -2.3% | fail | untouched |
| ETH-USDT | S2 | 6H | gate | +5.1% | 0.92 | 2.01 | 8.3% | 0.62 | 52 | 70.7% | +0.7% | fail | untouched |
| ETH-USDT | S2 | 6H | none | +3.2% | 0.57 | 1.39 | 9.1% | 0.36 | 85 | 61.0% | -2.1% | fail | untouched |
| ETH-USDT | S2+S5 | 6H | gate | +5.1% | 0.90 | 2.04 | 8.5% | 0.59 | 51 | 70.7% | +0.7% | fail | untouched |
| ETH-USDT | S2+S5 | 6H | none | +3.6% | 0.65 | 1.54 | 9.0% | 0.40 | 67 | 58.5% | -2.0% | fail | untouched |
| ETH-USDT | hold | 6H | none | +2.5% | 0.50 | 2.04 | 9.6% | 0.26 | 9 | 65.9% | -3.5% | control | -2.9% / PF 0.00 / 1 tr ✗ |

## Against the controls — the best timing rule of each series vs hold + policy sizing and plain buy-and-hold

| Series | Best rule | Best CAGR / max DD / Calmar | Hold + policy CAGR / max DD / Calmar | Beats hold by > 0.1 Calmar | Buy-and-hold CAGR / max DD / Calmar | Hold + policy, untouched 12 months |
|---|---|---|---|---|---|---:|
| XRP-USDT 4H | S2+S5 4H [gate] | +1.4% / 12.1% / 0.12 | +2.7% / 5.8% / 0.46 | no | +25.0% / 78.7% / 0.32 | -2.2% |
| XRP-USDT 6H | S1 6H [gate] | +3.9% / 10.9% / 0.36 | +4.4% / 5.8% / 0.77 | no | +24.9% / 78.4% / 0.32 | -2.7% |
| DOGE-USDT 4H | S2 4H [gate] | +3.6% / 4.2% / 0.85 | +0.7% / 6.9% / 0.10 | yes | -10.2% / 88.3% / -0.12 | -2.7% |
| DOGE-USDT 6H | S2 6H [gate] | +4.3% / 5.6% / 0.77 | +1.2% / 7.2% / 0.16 | yes | -10.3% / 88.1% / -0.12 | -3.1% |
| LINK-USDT 4H | S1+S5 4H [gate] | +2.0% / 9.2% / 0.22 | +1.6% / 5.6% / 0.28 | no | -11.4% / 86.8% / -0.13 | -1.7% |
| LINK-USDT 6H | S1+S5 6H [none] | +2.5% / 9.3% / 0.27 | +2.0% / 5.5% / 0.35 | no | -11.3% / 86.6% / -0.13 | -1.7% |
| TRX-USDT 4H | S2+S5 4H [none] | +5.1% / 8.5% / 0.60 | +7.3% / 5.6% / 1.31 | no | +39.7% / 62.8% / 0.63 | -0.8% |
| TRX-USDT 6H | S2+S5 6H [gate] | +7.6% / 10.8% / 0.70 | +7.3% / 6.6% / 1.11 | no | +40.1% / 63.8% / 0.63 | -0.1% |
| ADA-USDT 4H | S1+S5 4H [none] | +2.2% / 8.9% / 0.25 | +1.2% / 7.7% / 0.16 | no | -17.5% / 92.2% / -0.19 | -3.0% |
| ADA-USDT 6H | S2 6H [gate] | +4.5% / 4.7% / 0.95 | +1.3% / 8.0% / 0.16 | yes | -17.7% / 92.2% / -0.19 | -3.7% |
| LTC-USDT 4H | S2 4H [none] | -0.5% / 12.0% / -0.04 | -0.4% / 7.6% / -0.05 | no | -13.6% / 85.4% / -0.16 | -1.4% |
| LTC-USDT 6H | S2 6H [gate] | -2.4% / 15.2% / -0.16 | -0.1% / 7.6% / -0.02 | no | -13.4% / 85.4% / -0.16 | -1.1% |
| SOL-USDT 4H | S1 4H [none] | +4.9% / 7.5% / 0.65 | +6.4% / 6.7% / 0.96 | no | +12.1% / 93.7% / 0.13 | -2.3% |
| SOL-USDT 6H | S1+S5 6H [none] | +7.5% / 5.4% / 1.40 | +7.5% / 7.0% / 1.08 | yes | +12.7% / 93.4% / 0.14 | -2.5% |

The best rule beat hold + policy sizing by more than 0.1 Calmar on 4 of 14 series (Sprint 2c: 4 of 4 on BTC/ETH).

## Positioning data for the S5 filter (Binance public funding of each market's USDT perpetual, research feature only)

| Market | Source | Funding span | Funding coverage (in-sample bars) | Open interest | S5 counted |
|---|---|---|---:|---|---|
| XRP-USDT | binance | 2020-01-06->2026-11-04 (7484 rows) | 98.2% | none (that leg of S5 passes) | yes |
| DOGE-USDT | binance | 2020-07-10->2026-11-04 (6926 rows) | 89.5% | none (that leg of S5 passes) | no (below 90%: reported as run without S5) |
| LINK-USDT | binance | 2020-01-17->2026-11-04 (7451 rows) | 97.7% | none (that leg of S5 passes) | yes |
| TRX-USDT | binance | 2020-01-15->2026-11-04 (7457 rows) | 97.8% | none (that leg of S5 passes) | yes |
| ADA-USDT | binance | 2020-01-19->2026-11-04 (7444 rows) | 97.6% | none (that leg of S5 passes) | yes |
| LTC-USDT | binance | 2020-01-09->2026-11-04 (7475 rows) | 98.1% | none (that leg of S5 passes) | yes |
| SOL-USDT | binance | 2020-09-13->2026-11-04 (6805 rows) | 100.0% | none (that leg of S5 passes) | yes |

## The untouched 12 months

Opened once, only for configurations that passed every walk-forward gate on their market (and the hold + policy control as the comparison line). Verdict ✓ = positive return, PF > 1 and ≥ 10 trades.

| Market | Configuration | Return | Max DD | PF | Trades | Verdict |
|---|---|---:|---:|---:|---:|---|
| XRP-USDT | hold 4H [none] | -2.2% | 3.1% | 0.00 | 1 | control (comparison line) |
| XRP-USDT | hold 6H [none] | -2.7% | 3.9% | 0.00 | 1 | control (comparison line) |
| DOGE-USDT | hold 4H [none] | -2.7% | 3.0% | 0.00 | 1 | control (comparison line) |
| DOGE-USDT | S2 4H [gate] | +1.7% | 2.1% | 1.70 | 8 | not confirmed: 8 trades (fewer than 10) |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) 4H [gate] | +1.7% | 2.1% | 1.70 | 8 | not judged (S5 inactive on this market); would be not confirmed: 8 trades (fewer than 10) |
| DOGE-USDT | hold 6H [none] | -3.1% | 3.6% | 0.00 | 1 | control (comparison line) |
| DOGE-USDT | S2 6H [gate] | -0.6% | 3.0% | 0.87 | 10 | contradicted |
| DOGE-USDT | S2 (run without S5: funding covers 90% of the in-sample bars) 6H [gate] | -0.6% | 3.0% | 0.88 | 10 | not judged (S5 inactive on this market); would be contradicted |
| LINK-USDT | hold 4H [none] | -1.7% | 3.0% | 0.00 | 1 | control (comparison line) |
| LINK-USDT | hold 6H [none] | -1.7% | 3.4% | 0.00 | 1 | control (comparison line) |
| TRX-USDT | hold 4H [none] | -0.8% | 3.3% | 0.00 | 1 | control (comparison line) |
| TRX-USDT | S2 4H [none] | -5.6% | 7.5% | 0.47 | 26 | contradicted |
| TRX-USDT | S2+S5 4H [none] | -5.6% | 7.5% | 0.47 | 26 | contradicted |
| TRX-USDT | hold 6H [none] | -0.1% | 3.4% | 0.00 | 1 | control (comparison line) |
| ADA-USDT | hold 4H [none] | -3.0% | 3.6% | 0.00 | 1 | control (comparison line) |
| ADA-USDT | hold 6H [none] | -3.7% | 4.4% | 0.00 | 1 | control (comparison line) |
| ADA-USDT | S2 6H [none] | -4.6% | 5.4% | 0.28 | 20 | contradicted |
| ADA-USDT | S2 6H [gate] | -6.0% | 6.4% | 0.07 | 20 | contradicted |
| ADA-USDT | S2+S5 6H [none] | -4.6% | 5.4% | 0.28 | 20 | contradicted |
| ADA-USDT | S2+S5 6H [gate] | -6.0% | 6.4% | 0.07 | 20 | contradicted |
| LTC-USDT | hold 4H [none] | -1.4% | 2.8% | 0.00 | 1 | control (comparison line) |
| LTC-USDT | hold 6H [none] | -1.1% | 2.6% | 0.00 | 1 | control (comparison line) |
| SOL-USDT | hold 4H [none] | -2.3% | 3.6% | 0.00 | 1 | control (comparison line) |
| SOL-USDT | hold 6H [none] | -2.5% | 3.8% | 0.00 | 1 | control (comparison line) |
| SOL-USDT | S1 6H [none] | +9.5% | 2.1% | 5.49 | 12 | confirmed |
| SOL-USDT | S1+S5 6H [none] | +9.5% | 2.1% | 5.49 | 12 | confirmed |

### Every opening of the holdout (ledger)

Each run that opened a holdout appends its openings to `docs/research/replication_v1d_holdout_ledger.json`; earlier looks stay visible here even when a later run replaces the numbers above.

| Run | Configuration | Role | Return | Max DD | PF | Trades | Verdict |
|---|---|---|---:|---:|---:|---:|---|
| 1 (2026-11-04 17:33 UTC) | hold XRP-USDT 4H [none] | control | -2.2% | 3.1% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold XRP-USDT 6H [none] | control | -2.7% | 3.9% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold DOGE-USDT 4H [none] | control | -2.7% | 3.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | S2 DOGE-USDT 4H [gate] | configuration | +1.7% | 2.1% | 1.70 | 8 | not confirmed (8 trades) |
| 1 (2026-11-04 17:33 UTC) | S2+S5 DOGE-USDT 4H [gate] | configuration | +1.7% | 2.1% | 1.70 | 8 | not confirmed (8 trades) |
| 1 (2026-11-04 17:33 UTC) | hold DOGE-USDT 6H [none] | control | -3.1% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | S2 DOGE-USDT 6H [gate] | configuration | -0.6% | 3.0% | 0.87 | 10 | contradicted |
| 1 (2026-11-04 17:33 UTC) | S2+S5 DOGE-USDT 6H [gate] | configuration | -0.6% | 3.0% | 0.88 | 10 | contradicted |
| 1 (2026-11-04 17:33 UTC) | hold LINK-USDT 4H [none] | control | -1.7% | 3.0% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold LINK-USDT 6H [none] | control | -1.7% | 3.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold TRX-USDT 4H [none] | control | -0.8% | 3.3% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | S2 TRX-USDT 4H [none] | configuration | -5.6% | 7.5% | 0.47 | 26 | contradicted |
| 1 (2026-11-04 17:33 UTC) | S2+S5 TRX-USDT 4H [none] | configuration | -5.6% | 7.5% | 0.47 | 26 | contradicted |
| 1 (2026-11-04 17:33 UTC) | hold TRX-USDT 6H [none] | control | -0.1% | 3.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold ADA-USDT 4H [none] | control | -3.0% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold ADA-USDT 6H [none] | control | -3.7% | 4.4% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | S2 ADA-USDT 6H [none] | configuration | -4.6% | 5.4% | 0.28 | 20 | contradicted |
| 1 (2026-11-04 17:33 UTC) | S2 ADA-USDT 6H [gate] | configuration | -6.0% | 6.4% | 0.07 | 20 | contradicted |
| 1 (2026-11-04 17:33 UTC) | S2+S5 ADA-USDT 6H [none] | configuration | -4.6% | 5.4% | 0.28 | 20 | contradicted |
| 1 (2026-11-04 17:33 UTC) | S2+S5 ADA-USDT 6H [gate] | configuration | -6.0% | 6.4% | 0.07 | 20 | contradicted |
| 1 (2026-11-04 17:33 UTC) | hold LTC-USDT 4H [none] | control | -1.4% | 2.8% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold LTC-USDT 6H [none] | control | -1.1% | 2.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold SOL-USDT 4H [none] | control | -2.3% | 3.6% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | hold SOL-USDT 6H [none] | control | -2.5% | 3.8% | 0.00 | 1 | comparison |
| 1 (2026-11-04 17:33 UTC) | S1 SOL-USDT 6H [none] | configuration | +9.5% | 2.1% | 5.49 | 12 | confirmed |
| 1 (2026-11-04 17:33 UTC) | S1+S5 SOL-USDT 6H [none] | configuration | +9.5% | 2.1% | 5.49 | 12 | confirmed |

## Paper-fleet shortlist

Confirmed passers appended to `docs/research/paper_fleet_shortlist_v1c.json` with a `source` tag (existing entries and running accounts untouched):

- S1+S5 SOL-USDT 6H (no regime gate): walk-forward Calmar 1.40, holdout +9.5%
- S1 SOL-USDT 6H (no regime gate): walk-forward Calmar 1.06, holdout +9.5%

Shortlist file: docs/research/paper_fleet_shortlist_v1c.json now lists 12 configurations (22 fleet accounts).

## Owner decisions (nothing below is decided by this report)

- **Fleet.** 2 new paper account(s) join at the fleet's next restart from an updated checkout (`docs/runbooks/PAPER_FLEET.md`). Recommended: let them run; judge them at G7 with the rest.
- **What the verdict means.** The pre-registered reading of 'fragile' is written above; no gate, parameter or market changed after the results. If a gate looks wrong, that is a note for the next pre-registered study, not an edit of this one.

## Method notes and caveats

- The rules were not re-implemented: Sprint 2c's runner module ran them; the BTC/ETH reproduction table shows the same code gives the stored numbers.
- Every market's candles were cut at Sprint 2c's data end so the walk-forward and the untouched 12 months cover the same calendar window; the windows themselves are anchored at each market's first candle (the pre-2020 markets start within days of BTC/ETH; SOL-USDT starts 2020-09-29 and has fewer windows).
- 4H bars are OKX's own, 6H bars are resampled from 1H on the UTC clock — Sprint 2c's construction for BTC/ETH.
- The S5 positioning filter uses the market's Binance perpetual funding (as-of aligned) and has no open-interest history for the new markets, so its open-interest leg passes there; on BTC/ETH that leg was active from 2020-09 / 2021-12. Funding coverage per market is shown above; a market below the Sprint 2b threshold has its S5 rows reported as 'run without S5' and never counted for the S5 families.
- The regime gate's HMM is fitted on every window's train slice (deterministic), the FOMC calendar is the one checked in plan row R7, and the fixed policy sizing is Sprint 2b's; none of them was adapted to the new markets.
- 104 configurations on the new markets are 104 more comparisons; a pass or two among them at the Sprint 2c pass rate (4 of 108) would be expected by chance, which is why the holdout and the family rule, not single passes, carry the verdict.
- Every number is a simulation on historical public data and proves nothing about the future.
