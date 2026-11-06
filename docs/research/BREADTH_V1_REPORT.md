# Breadth v1 - the S1 family on nine OKX markets as ONE Trader-tier book, and one rotation test (walk-forward, SIMULATION ONLY)

Plan row R20 (`docs/TRADER_PLAN_2026-11-05.md`, section 6.1). Generated 2026-11-05 07:23 UTC by `scripts/run_breadth_v1.py` in 4.0 minutes on 12 worker(s). Data: PUBLIC OKX spot candles frozen at Sprint 2c's data end (bar close <= 2026-10-20T10:00:00+00:00); the untouched 12 months are 2025-10-20->2026-10-20. Research evidence for the paper fleet; nothing approved.

## Executive summary (plain English)

- **Reproduction.** 51 of 51 stored results (Sprint 2c, the replication study, rounds 1 and 2 at the Reference cell; the Trader Policy study and round 3 at the Trader cell) were reproduced to 6 decimals before anything was judged.
- **The breadth book** - the S1 family (26 sleeves on 9 markets, 6H bars) as one account at the Trader tier with the book-level brakes and the correlation cap, 2021-05-28 to 2025-10-19 - made -6.7% a year with a 30.1% worst fall (Sharpe -0.73, Calmar -0.22, profit factor 0.68, 460 trades, 9.0% realized volatility, on average 4.1% of the money at work). It **fails** the section 4.6 gates: profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, average win at least 2 x average loss.
- **Beside its parts.** 6 of 26 sleeves pass on their own at the Trader cell; their median Calmar is 0.34 and the best sleeve's 1.55 (S1+VC SOL-USDT 6H [none]); holding BTC with the Trader policy sizing made +6.0% a year at a 15.3% fall (Calmar 0.39). The diversification gain in Calmar is -0.56 against the median sleeve, -1.77 against the best sleeve and -0.61 against holding BTC; -1.36 against the equal-weight hold of the nine at the same volatility target.
- **The hard stop ended the book.** The book's equity fell 30 % below its peak on 2022-04-26; as pre-registered for a simulated account, no new entry was funded from then on, so the book sat flat for 79.3% of its days and the numbers above are those of an account that stopped trading there. Post hoc (NOT pre-registered, added after the first run, never a candidate): the same book with the hard stop off made -8.3% a year with a 43.3% worst fall (Sharpe -0.29, Calmar -0.19, profit factor 0.91, 2417 trades); it would still fail the section 4.6 gates (profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss).
- **Candidate?** **No** - fails the section 4.6 gates at the Trader tier: pf_gt_1_2, max_dd_within_tier, sharpe_gt_0_7, calmar_gt_0_5, rolling_12m_75pct_positive, payoff_ge_2. Nothing joins the fleet from the book.
- **The brakes at book level.** Of 65262 entry opportunities the book funded 460: the one-entry-per-market-per-day cap blocked 578, the three-per-day cap 355, the bar-after-an-exit rule 172, the rolling 24-hour loss limit 26 (tripped 8 times), the weekly limit 10 (tripped once), the monthly limit 114 (tripped once), the hard stop 63799 (tripped once); the Turtle ladder cut 314 entries; the heat cap scaled 293 entries and reduced open positions 2158 times (the highest heat wanted at an entry: 10.6% of equity); the correlation cap acted on 2 days; the cash ran short on 0 entries and blocked 0. The same signals with one layer switched off: every brake off: Calmar -0.22 (+0.00); the correlation cap off: Calmar -0.22 (-0.00); the 8 % heat cap: Calmar -0.20 (+0.02); no altcoin surcharge: Calmar -0.24 (-0.02). No layer costs more than 0.1 Calmar.
- **The rotation test** (top 3 of the nine by 3-week return, weekly, BTC 200-day filter, 20 % volatility target; 2020-07-20 to 2025-10-19) made +20.6% a year with a 20.3% worst fall (Calmar 1.02, Sharpe 1.13, 10.0 x equity a year of turnover, 4.3% a year in costs); holding BTC with the same sizing made +28.1% at a 40.5% fall (Calmar 0.69). It **does not beat BTC** by the pre-registered rule (Calmar ahead by more than 0.1: yes; CAGR ahead: no; drawdown within 25 %: yes), as expected before the run. The question is closed with our own numbers.
- **The sleeves on their own.** The 6 that pass at the Trader cell are S1 BTC-USDT 6H [none], S1+S5 BTC-USDT 6H [none], S1+VC ETH-USDT 6H [none], S1 SOL-USDT 6H [none], S1+VC SOL-USDT 6H [none], S1+S5 SOL-USDT 6H [none]; their untouched 12 months (a near-second look for most of them, see the ledger) confirmed 5 (S1 BTC-USDT, S1+S5 BTC-USDT, S1 SOL-USDT, S1+VC SOL-USDT, S1+S5 SOL-USDT) and contradicted 1 (S1+VC ETH-USDT). 3 of the 6 already run in the paper fleet at the Trader tier (S1+S5 BTC-USDT, S1 SOL-USDT, S1+S5 SOL-USDT); S1 BTC-USDT, S1+VC SOL-USDT pass and are confirmed but are NOT in the fleet, and this study's pre-registration lists no fleet ticket for a single sleeve (an owner decision, below).
- **Fleet.** 0 row(s) recorded for the paper fleet (none); none applied, because the fleet has no account type for a multi-market book or a weekly rotation. Nothing here is approved for demo or live.

## Fixed before the first run (the pre-registration)

Written 2026-11-05T06:55:50+00:00 to `docs/research/breadth_v1_preregistration.json` (sha256 of the study's fixed text, file and configuration: `22d968e90547ce7a...`). The study refuses to run if the text in `research/breadth_study.py` differs from the file.

- **question**: (1) Does the S1 family (S1; S1+VC; S1+S5 where the market has funding data) on the nine liquid OKX USDT markets, run as ONE account at the Trader tier under the section 4.3 brakes and allocator v2's correlation cap, pass the section 4.6 gates at the portfolio level, how much of a smoother curve do the imperfectly correlated markets buy (the diversification gain in Calmar beside the sleeves on their own, holding BTC with policy sizing and the equal-weight hold of the nine), how often does each book-level brake act and what does it cost, and does the book qualify as a candidate under the R5b rule? (2) Does one fixed rotation rule (the top 3 of the nine by trailing 3-week return, weekly, long only, under the BTC 200-day filter, 20 % volatility target) beat holding BTC with the same sizing after costs?
- **markets**: the nine liquid OKX USDT spot markets the lake holds: BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT, DOGE-USDT, LINK-USDT, TRX-USDT, ADA-USDT, LTC-USDT (BTC and ETH from Sprint 2c; the seven others exactly as the replication study fixed them, checked against docs/research/replication_v1d_preregistration.json), in this fixed order; 6H bars resampled from the stored 1H candles; no regime gate (mode 'none')
- **sleeves**: per market the S1 family: S1 (time-series momentum, multi-lookback vote, ATR stop), S1+VC (S1 with new entries only on a 30-day volume z-score above 1, round 1) and S1+S5 (S1 with the positioning filter) - S1+S5 only where the market's Binance funding covers at least 90 % of its in-sample bars (the replication study's rule; a market below it has its S1+S5 reported 'run without S5' and left out of the book, never counted twice); so up to 27 sleeves. Each sleeve's rule in each walk-forward window is the one Sprint 2c's own runner selects on that market (train Sharpe at full size, at least 20 train trades, entries among bracket-free rules then the exit bracket among siblings, the S0 no-trade filter with the FOMC calendar), with Sprint 2c's grids and brackets (none / tp2 / trail1 / time30; none for S1+S5): nothing is retuned, nothing is swept for the book
- **sleeve verdicts**: every sleeve is also judged on its own at the Trader cell (vt20/30 crash15/90dh cap2, the Turtle ladder, the section 4.3 brakes on one sleeve) by the section 4.6 gates, exactly as the Trader Policy study judged the five confirmed configurations; the Reference cell runs beside it for the reproduction of the stored numbers and for information
- **book**: ONE account: the sleeves share one equity from the first bar on which any sleeve's first walk-forward test window starts; a sleeve joins when its own first test window starts (SOL's history is shorter) and the book runs continuously to the in-sample end (the sleeves' own walk-forward verdicts restart flat every 180 days; the book does not, because the account's ladder, hard stop and loss limits are about a continuous equity). Each entry is sized by the Trader tier on the BOOK's equity marked at the previous close (20 % volatility target over 30 bars of that market, half size in that market's crash state, at most 2 % of equity at risk on the stop), takes at most the cash left (spot, no leverage: an open position is never sold to make room for a new one) and keeps the rule's own stop and exit, Sprint 2c's 0.25 reduce-only rebalance included. Several sleeves may hold the same market; they count as one bet
- **brakes**: the section 4.3 brakes at BOOK level, entries only, with their fixed numbers: the Turtle ladder (x0.8 at -10 % from the book's equity peak, x0.64 at -20 %, restored on a new high); the hard stop (-30 %: no new entry until the simulated account ends); the entry caps - at most 1 new entry per MARKET per UTC day across the market's sleeves, 3 per day across the book, none in a market on the bar after an exit there (when more entries want the same bar than the caps allow, the rules' own strength decides, ties by the fixed market order, then the sleeve order S1, S1+VC, S1+S5); the loss limits on the book's equity (3 % over the trailing 24 hours blocks entries for the next 24 hours; 6 % from Monday 00:00 UTC until the next Monday; 10 % from the month's start until the next month); the heat cap (the current risk, price to current stop on current equity, of the open positions plus the entries wanted, at most 6 % in total and 3 % per bet, a bet being the sleeves whose markets' trailing 60-day daily-return correlation is 0.70 or more, or the same market; when the wanted entries would exceed it, every open and new position of the bet with a positive risk is sized down equally - an open position whose stop has moved above the price carries no risk and is left alone). The brakes are read from the same EntryBrakes state machine the single-sleeve studies ran (one column, the book's equity), so their arithmetic is R18's
- **allocator v2**: reused for its daily record and its correlation cap only: at the first bar of every UTC day the sleeves of one bet may hold at most 50 % of equity at the previous close; above it the bet's positions are scaled down equally at the open and the bet's new entries that day are scaled by the same factor (groups by the 60-day correlation >= 0.70, at least 20 days, as in R5b); its portfolio volatility target and its weekly cash-out are OFF so the tier is not sized twice - the effective risk per position (the per-entry risk after the ladder, heat and correlation multipliers and the cash constraint) is reported
- **costs**: BTC-USDT and ETH-USDT at the engine's 0.10 % fee + 0.05 % slippage a side (0.30 % a round trip); the seven altcoins at 0.10 % + 0.15 % a side (0.50 % a round trip, plan section 4.2); the book is also replayed with every market at 0.30 % as an ablation
- **ablation rule**: ablations are diagnostics that explain the result; none is a candidate and none opens a holdout
- **gates**: the plan's section 4.6 gates at the Trader tier on the book's continuous equity: profit factor > 1.2 (pooled over the book's trades), Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, >= 30 trades, max drawdown <= 25 %, worst calendar year >= -15 %, average win / average loss >= 2; the +-30 % robustness gate is carried by the sleeves (the R5b construction) and counted as passed at the book level; expectancy in R is reported, not gated
- **candidate rule**: the R5b rule, pre-registered for portfolio studies: the book is a CANDIDATE only when it passes the gates AND (every sleeve in it passes the section 4.6 gates on its own at the Trader cell, OR the book's own holdout confirms it); a book that passes the gates but is not a candidate is 'passed, not a candidate' and nothing joins the fleet
- **comparison lines**: (a) holding BTC with policy sizing: the always-long control at the Trader cell on BTC-USDT 6H, run by the same runner (the stored R19/R18 numbers must reproduce), and the same hold run as one sleeve through the book simulator (continuous, no window restarts); (b) the equal-weight hold of the nine: 1/9 in every market with a close that day, re-sized weekly to the 20 % volatility target of the basket (the rotation's own machinery, the same costs), and plain equal-weight buy-and-hold; (c) each sleeve on its own at the Trader cell; (d) BTC buy-and-hold over the book's span
- **diversification reading**: the diversification gain in Calmar = the book's Calmar minus (i) the median Calmar of its sleeves at the Trader cell, (ii) the Calmar of the best sleeve, (iii) the Calmar of holding BTC with policy sizing (the Trader-cell control); the book's volatility beside the average sleeve volatility; the pairwise daily-return correlations of the nine markets over the in-sample years and since 2024-01-01 (in-sample part only; the plan's own figure for the four confirmed markets is 0.73-0.82 for 2024-26), and the correlations of the sleeves' daily P&L contributions inside the book
- **brake judgement**: every book-level brake is judged by its trigger counts and its cost: the book beside each ablation (the same signals, one layer off); a brake that costs more than 0.1 Calmar is flagged for the owner, never silently kept or dropped; the loss limits and the heat cap, which cannot act on one sleeve, are read here for the first time
- **holdout**: the last 12 months (2025-10-20 -> 2026-10-20), opened once, only by the full pre-registered study (every market, rule and cell, the book and the rotation, with the reproduction, never --quick): (a) by the runner for the sleeves that pass on their own at the Trader cell and for the hold controls (the comparison line, as in every study); (b) for the BOOK only when it passes the section 4.6 gates on the walk-forward years - the book runs over the untouched months with each sleeve's most-often-selected rule (the runner's own holdout construction), starting flat, the correlations warmed up on history; the v1c verdict (positive return, pooled profit factor > 1, >= 10 trades); (c) for the rotation only when it passes its in-sample rule. Every opening goes into an append-only ledger the report shows, beside the earlier looks at the same months (R12, R13, R16, R18, R19). CAVEAT, stated before the run: these months were opened before for every market (hold + policy lost on all nine) and for several of these very sleeves, so their falling direction is known; a confirmation is necessary, not sufficient, and the paper fleet's forward record is the judge
- **fleet**: a book that is a candidate is RECORDED for the paper fleet as one portfolio account (a source-tagged row naming the study, the tier, the brakes, the correlation cap, the sleeves and their rules); a rotation that passes and is confirmed is recorded likewise. The fleet has no account type that runs a multi-market Trader-tier book or a weekly rotation, so nothing is appended to the shortlist by this row: applying a recorded row is the next plan row's work (the R18a/R18b precedent), through the R18 loader extension, never omitting the protocol check; existing accounts are untouched; nothing joins demo or live
- **protocol**: Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series) with Sprint 2c's defaults for everything the cell does not define: the grids and brackets, the S0 filter with the FOMC calendar, the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then bracket) and the 0.25 reduce-only rebalance; the tier replaces only the policy sizing (and adds its brakes); every job's protocol check is recorded and the study stops on any mismatch the job does not explain (a tier is a recorded policy_sizing mismatch, never hidden); the book is a replay of the selected rules, not a selection
- **data**: OKX public 1H spot candles of the nine markets (6H resampled from 1H), frozen in a study lake at Sprint 2c's data end (bar close <= 2026-10-20T10:00:00+00:00) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window as in Sprint 2c, R12, R13, R16, R18 and R19; Binance public funding (and open interest for BTC/ETH) for the S5 filter as before; one close per UTC day from the 6H bars for the correlations and the rotation
- **reproduction**: before anything is judged, the same code path re-runs, at the Reference cell, hold / S1 / S1+S5 on every market (Sprint 2c's stored numbers for BTC/ETH, the replication study's for the seven others) and S1+VC on every market (round 1's for BTC/ETH, round 2's for the seven), and, at the Trader cell, hold on every market (round 3's) and S1+S5 BTC-USDT 6H, S1 and S1+S5 SOL-USDT 6H (the Trader Policy study's); each must give the stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts, otherwise the study stops
- **no changes after results**: no gate, tier, brake number, cap, rule, market, cost, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so
- **ablations**: `heat_8pct` = the heat-cap variant of section 4.3: 8 % instead of 6 %; `no_brakes` = every book brake off (the correlation cap and the cash constraint stay); `no_corr_cap` = the brakes on, allocator v2's correlation cap off; `uniform_cost` = every market at the engine's 0.30 % round trip (no altcoin surcharge); `raw` = no brake, no correlation cap: the sleeves share one equity and the cash constraint only

### The rotation test, as fixed

- **rule**: at every Sunday close (so the fill is Monday 00:00 UTC): rank the nine markets with at least 22 daily closes by their trailing 21-day close-to-close return, hold the top 3 at equal weight (ties by the fixed market order), long only; only while BTC's daily close is above its 200-day simple moving average - a BTC close below it at any day's close sends the basket to cash at the next open and keeps it there until a Sunday on which BTC is above it again; no per-coin stop: the weekly rebalance and the filter are its only exits; sized at each rebalance by a 20 % volatility target: the scale is min(1, 20 % / the annualized standard deviation of the equal-weight basket's last 30 daily returns); costs on the traded notional at every fill: 0.15 % a side on BTC/ETH (0.30 % a round trip), 0.25 % a side on the altcoins (+10 bps); one close per UTC day (the last 6H bar's close) and the next day's first open as the fill
- **comparison**: holding BTC with the same policy sizing and machinery: always long BTC, re-sized every Monday to the same 20 % volatility target of BTC's own trailing 30 daily returns, 0.15 % a side on the re-sizing; also the equal-weight hold of the nine with the same sizing, plain BTC buy-and-hold, and the stored always-long BTC-USDT 6H control at the Trader cell
- **span**: the in-sample period only: from the first Monday on which BTC's 200-day average, the 21-day lookback and the 30-day volatility are all available (2020-07 on this data) to the in-sample end (the last full UTC day before the holdout split); every comparison line is run over exactly the same days
- **pass rule**: the rotation 'beats BTC' when, over that span, its Calmar exceeds the BTC comparison's by more than 0.1, its CAGR exceeds the BTC comparison's, and its max drawdown is at most 25 %
- **expectation**: stated before the run: it does NOT beat BTC after costs (plan section 2.7: post-2020 long-only top-coin momentum has not reliably beaten holding Bitcoin after costs; the 1-4 week effect lives in the largest coins and decays within weeks); if it passes anyway its holdout is opened once and, if that confirms it (positive return and ahead of the BTC comparison over the same days), it is recorded for the fleet as one account; if it fails the question is closed with our own numbers

## Reproduction of the stored studies

51 of 51 stored results reproduced exactly (metrics to the stored 6 decimals, the same trade counts, the same most-selected rules, the same gate verdicts). The study stops if any differs.

| Configuration | Cell | Stored by | Max abs. difference | Trades (now / stored) | Rule matches | Verdict matches | OK |
|---|---|---|---:|---:|---|---|---|
| S1 ADA-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 155 / 155 | yes | yes | yes |
| S1 BTC-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 155 / 155 | yes | yes | yes |
| S1 DOGE-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 181 / 181 | yes | yes | yes |
| S1 ETH-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 165 / 165 | yes | yes | yes |
| S1 LINK-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 173 / 173 | yes | yes | yes |
| S1 LTC-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 221 / 221 | yes | yes | yes |
| S1 SOL-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 107 / 107 | yes | yes | yes |
| S1 TRX-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 198 / 198 | yes | yes | yes |
| S1 XRP-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 192 / 192 | yes | yes | yes |
| S1+S5 ADA-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 143 / 143 | yes | yes | yes |
| S1+S5 BTC-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 139 / 139 | yes | yes | yes |
| S1+S5 DOGE-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 167 / 167 | yes | yes | yes |
| S1+S5 ETH-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 145 / 145 | yes | yes | yes |
| S1+S5 LINK-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 163 / 163 | yes | yes | yes |
| S1+S5 LTC-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 214 / 214 | yes | yes | yes |
| S1+S5 SOL-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 101 / 101 | yes | yes | yes |
| S1+S5 TRX-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 174 / 174 | yes | yes | yes |
| S1+S5 XRP-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 179 / 179 | yes | yes | yes |
| S1+VC ADA-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 90 / 90 | yes | yes | yes |
| S1+VC BTC-USDT 6H [none] | reference\|nobrakes\|none | R13 research round 1 | 0.0e+00 | 93 / 93 | yes | yes | yes |
| S1+VC DOGE-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 93 / 93 | yes | yes | yes |
| S1+VC ETH-USDT 6H [none] | reference\|nobrakes\|none | R13 research round 1 | 0.0e+00 | 74 / 74 | yes | yes | yes |
| S1+VC LINK-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 91 / 91 | yes | yes | yes |
| S1+VC LTC-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 80 / 80 | yes | yes | yes |
| S1+VC SOL-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 41 / 41 | yes | yes | yes |
| S1+VC TRX-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 129 / 129 | yes | yes | yes |
| S1+VC XRP-USDT 6H [none] | reference\|nobrakes\|none | R16 research round 2 | 0.0e+00 | 82 / 82 | yes | yes | yes |
| hold ADA-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold BTC-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold DOGE-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold ETH-USDT 6H [none] | reference\|nobrakes\|none | Sprint 2c | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold LINK-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold LTC-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold SOL-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 7 / 7 | yes | yes | yes |
| hold TRX-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold XRP-USDT 6H [none] | reference\|nobrakes\|none | R12 replication | 0.0e+00 | 9 / 9 | yes | yes | yes |
| S1 BTC-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 140 / 140 | yes | yes | yes |
| S1 ETH-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 147 / 147 | yes | yes | yes |
| S1 SOL-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 98 / 98 | yes | yes | yes |
| S1+S5 BTC-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 130 / 130 | yes | yes | yes |
| S1+S5 ETH-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 134 / 134 | yes | yes | yes |
| S1+S5 SOL-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 95 / 95 | yes | yes | yes |
| hold ADA-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold BTC-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold DOGE-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold ETH-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold LINK-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold LTC-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold SOL-USDT 6H [none] | trader\|brakes\|none | R18 Trader Policy v1 | 0.0e+00 | 7 / 7 | yes | yes | yes |
| hold TRX-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |
| hold XRP-USDT 6H [none] | trader\|brakes\|none | R19 research round 3 | 0.0e+00 | 9 / 9 | yes | yes | yes |

## The sleeves on their own (both cells)

Each sleeve as Sprint 2c's runner judges it alone: the Reference cell (today's policy, for information) and the Trader cell (vt20/30 crash15/90dh cap2, the Turtle ladder, the brakes on one sleeve), the section 4.6 gates at the Trader tier, the holdout where the runner opened it. 'In book' marks the sleeves the book funds; an S1+S5 sleeve whose market's funding covers less than 90 % of the in-sample bars is run without S5 and left out.

| Market | Rule | In book | Reference: CAGR / max DD / Calmar | Trader: CAGR / max DD / Calmar / Sharpe / PF / trades / payoff / risk per trade | Trader gates missed | Holdout (Trader) |
|---|---|---|---|---|---|---|
| BTC-USDT | S1 | yes | +3.5% / 9.2% / 0.38 | +8.6% / 14.3% / 0.61 / 0.87 / 1.64 / 140 / 3.83 / 1.7% | **PASS** | +3.8% / PF 1.40 / 32 tr yes |
| BTC-USDT | S1+VC | yes | +3.2% / 8.4% / 0.38 | +4.2% / 15.6% / 0.27 / 0.45 / 1.31 / 90 / 3.60 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| BTC-USDT | S1+S5 | yes | +5.3% / 8.8% / 0.60 | +10.4% / 14.1% / 0.74 / 1.03 / 1.85 / 130 / 4.65 / 1.7% | **PASS** | +3.4% / PF 1.36 / 30 tr yes |
| ETH-USDT | S1 | yes | +3.4% / 8.2% / 0.42 | +4.3% / 11.0% / 0.40 / 0.50 / 1.28 / 147 / 2.48 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| ETH-USDT | S1+VC | yes | +2.0% / 8.8% / 0.23 | +9.0% / 12.7% / 0.71 / 0.86 / 1.92 / 72 / 4.09 / 1.3% | **PASS** | -5.8% / PF 0.42 / 20 tr no |
| ETH-USDT | S1+S5 | yes | +2.8% / 7.4% / 0.38 | +4.4% / 12.1% / 0.37 / 0.49 / 1.31 / 134 / 2.67 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| SOL-USDT | S1 | yes | +6.0% / 5.6% / 1.06 | +9.8% / 8.0% / 1.22 / 1.22 / 2.25 / 98 / 3.00 / 1.5% | **PASS** | +8.5% / PF 3.51 / 11 tr yes |
| SOL-USDT | S1+VC | yes | +9.1% / 5.9% / 1.54 | +17.5% / 11.3% / 1.55 / 1.32 / 4.29 / 39 / 12.45 / 1.1% | **PASS** | +5.0% / PF 1.50 / 23 tr yes |
| SOL-USDT | S1+S5 | yes | +7.5% / 5.4% / 1.40 | +13.6% / 9.8% / 1.39 / 1.39 / 2.78 / 95 / 4.18 / 1.6% | **PASS** | +8.5% / PF 3.51 / 11 tr yes |
| XRP-USDT | S1 | yes | +1.6% / 16.7% / 0.10 | -0.6% / 21.0% / -0.03 / -0.02 / 0.99 / 177 / 2.51 / 1.8% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| XRP-USDT | S1+VC | yes | +4.7% / 8.5% / 0.55 | +4.6% / 10.0% / 0.47 / 0.62 / 1.50 / 76 / 3.25 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| XRP-USDT | S1+S5 | yes | +1.2% / 17.2% / 0.07 | -0.8% / 22.1% / -0.04 / -0.05 / 0.97 / 166 / 2.68 / 1.7% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| DOGE-USDT | S1 | yes | +0.8% / 9.1% / 0.08 | +2.7% / 12.8% / 0.21 / 0.36 / 1.23 / 159 / 2.60 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| DOGE-USDT | S1+VC | yes | +3.4% / 6.6% / 0.52 | +5.5% / 8.9% / 0.62 / 0.64 / 1.62 / 84 / 2.63 / 1.3% | Sharpe above 0.7 | untouched |
| DOGE-USDT | S1+S5 (run without S5: funding covers 90% of the in-sample bars) | no | -0.3% / 11.8% / -0.03 | +1.1% / 16.9% / 0.07 / 0.17 / 1.11 / 149 / 2.55 / 1.5% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| LINK-USDT | S1 | yes | +1.9% / 9.1% / 0.21 | +2.5% / 11.9% / 0.21 / 0.31 / 1.24 / 154 / 1.89 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, average win at least 2 x average loss | untouched |
| LINK-USDT | S1+VC | yes | +1.2% / 9.6% / 0.12 | +1.2% / 16.0% / 0.07 / 0.17 / 1.15 / 86 / 2.03 / 1.4% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| LINK-USDT | S1+S5 | yes | +2.5% / 9.3% / 0.27 | +2.8% / 12.5% / 0.22 / 0.34 / 1.30 / 144 / 2.05 / 1.6% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| TRX-USDT | S1 | yes | +6.0% / 12.6% / 0.48 | +10.3% / 22.0% / 0.47 / 0.72 / 1.54 / 176 / 3.40 / 1.5% | Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| TRX-USDT | S1+VC | yes | +6.9% / 12.9% / 0.54 | +7.6% / 24.5% / 0.31 / 0.60 / 1.42 / 122 / 2.34 / 1.7% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| TRX-USDT | S1+S5 | yes | +5.8% / 13.0% / 0.45 | +11.8% / 24.4% / 0.48 / 0.85 / 1.76 / 157 / 4.38 / 1.3% | Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| ADA-USDT | S1 | yes | +0.9% / 11.0% / 0.08 | +1.9% / 17.0% / 0.11 / 0.26 / 1.18 / 144 / 2.51 / 1.5% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| ADA-USDT | S1+VC | yes | +3.0% / 8.6% / 0.35 | +4.8% / 13.0% / 0.37 / 0.66 / 1.55 / 86 / 3.21 / 1.3% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| ADA-USDT | S1+S5 | yes | +1.5% / 9.2% / 0.17 | +2.1% / 17.5% / 0.12 / 0.28 / 1.23 / 133 / 2.75 / 1.4% | Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive | untouched |
| LTC-USDT | S1 | yes | -3.2% / 19.9% / -0.16 | -3.7% / 25.9% / -0.14 / -0.30 / 0.81 / 205 / 1.77 / 1.3% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to +-30% parameter changes, average win at least 2 x average loss | untouched |
| LTC-USDT | S1+VC | yes | -2.2% / 14.9% / -0.15 | -2.1% / 18.7% / -0.11 / -0.17 / 0.82 / 78 / 2.23 / 1.6% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to +-30% parameter changes | untouched |
| LTC-USDT | S1+S5 | yes | -3.3% / 20.3% / -0.16 | -2.9% / 23.0% / -0.13 / -0.22 / 0.85 / 197 / 1.94 / 1.3% | profit factor above 1.2, Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, robust to +-30% parameter changes, average win at least 2 x average loss | untouched |

6 of the 26 sleeves in the book pass the section 4.6 gates on their own at the Trader cell: S1 BTC-USDT 6H [none], S1+S5 BTC-USDT 6H [none], S1+VC ETH-USDT 6H [none], S1 SOL-USDT 6H [none], S1+VC SOL-USDT 6H [none], S1+S5 SOL-USDT 6H [none].

## The breadth book

26 sleeves on 9 markets (BTC, ETH, SOL, XRP, DOGE, LINK, TRX, ADA, LTC), 6H bars, 2021-05-28 to 2025-10-19 (6422 bars, 1606 days). Configuration: turtle x0.8@-10%, x0.64@-20%; hard stop -30%; entry caps 1/market/day, 3/day, none on the bar after an exit; loss limits 3%/24h, 6%/week, 10%/month; heat cap 6% (group 50%, corr >= 0.7); correlation cap 50% per bet (corr >= 0.70 over 60d); no portfolio volatility target, no weekly cash-out (the tier sizes each entry). Costs per side: ADA 0.10% + 0.15%; BTC 0.10% + 0.05%; DOGE 0.10% + 0.15%; ETH 0.10% + 0.05%; LINK 0.10% + 0.15%; LTC 0.10% + 0.15%; SOL 0.10% + 0.15%; TRX 0.10% + 0.15%; XRP 0.10% + 0.15%.

| | CAGR | Vol | Sharpe | Max DD | Calmar | PF | Trades | Avg invested | Fees / yr | Section 4.6 gates (Trader tier) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **The book (pre-registered)** | -6.7% | 9.0% | -0.73 | 30.1% | -0.22 | 0.68 | 460 | 4.1% | 1.5% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, average win at least 2 x average loss |
| ablation `heat_8pct`: the heat-cap variant of section 4.3: 8 % instead of 6 % | -6.1% | 10.0% | -0.58 | 30.7% | -0.20 | 0.73 | 450 | 4.8% | 1.6% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss |
| ablation `no_brakes`: every book brake off (the correlation cap and the cash constraint stay) | -17.6% | 46.5% | -0.18 | 78.8% | -0.22 | 0.86 | 2745 | 67.2% | 9.1% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss |
| ablation `no_corr_cap`: the brakes on, allocator v2's correlation cap off | -6.7% | 9.0% | -0.73 | 30.1% | -0.22 | 0.68 | 459 | 4.1% | 1.5% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, average win at least 2 x average loss |
| ablation `uniform_cost`: every market at the engine's 0.30 % round trip (no altcoin surcharge) | -7.5% | 9.3% | -0.79 | 30.6% | -0.24 | 0.69 | 501 | 4.3% | 1.7% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss |
| ablation `raw`: no brake, no correlation cap: the sleeves share one equity and the cash constraint only | -26.6% | 56.6% | -0.26 | 87.0% | -0.31 | 0.74 | 1542 | 81.8% | 4.1% | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss |
| hold BTC + Trader policy sizing (the runner's control, windows restart flat) | +6.0% | 11.2% | 0.57 | 15.3% | 0.39 | 3.06 | 9 | 20.3% | 0.2% | - |
| hold BTC + Trader policy sizing through the book simulator (continuous) | +4.3% | 7.1% | 0.62 | 13.0% | 0.33 | - | 1 | 13.2% | 0.0% | - |
| BTC buy-and-hold over the book's span | +29.1% | 54.4% | 0.74 | 77.0% | 0.38 | - | - | 100% | - | - |
| equal-weight hold of the nine, 20 % volatility target (daily basket) | +35.4% | 23.2% | 1.42 | 31.3% | 1.13 | - | - | - | - | - |

| Calendar year | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| the book | -13.9% | -14.5% | +0.0% | +0.0% | +0.0% |
| `heat_8pct` | -10.8% | -15.2% | +0.0% | +0.0% | +0.0% |
| `no_brakes` | -11.2% | -49.9% | +13.6% | +15.6% | -26.9% |
| `no_corr_cap` | -13.9% | -14.6% | +0.0% | +0.0% | +0.0% |
| `uniform_cost` | -10.0% | -21.0% | +0.0% | +0.0% | +0.0% |
| `raw` | -22.3% | -70.3% | +85.5% | -19.6% | -25.3% |
| post hoc `no_hard_stop` (not pre-registered) | -13.9% | -27.9% | +29.4% | -5.7% | -9.9% |
| hold BTC + Trader policy sizing | +2.1% | -9.4% | +24.6% | +10.9% | +0.4% |

Gates at the Trader tier: profit factor above 1.2 no (0.68); max drawdown at most 25 % no (30.1%); Sharpe above 0.7 no (-0.73); Calmar above 0.5 no (-0.22); 75 % of rolling 12-month windows positive no (0.0% of 42); worst calendar year at least -15 % yes (-14.5%, 2022); at least 30 trades yes (460); average win at least 2 x average loss no (1.12); robustness carried by the sleeves. **Verdict: fail.**

**Candidate under the R5b rule: no** - fails the section 4.6 gates at the Trader tier: pf_gt_1_2, max_dd_within_tier, sharpe_gt_0_7, calmar_gt_0_5, rolling_12m_75pct_positive, payoff_ge_2.

### What the book-level rules did

| Rule | Acted | Note |
|---|---:|---|
| entry opportunities / funded entries | 65262 / 460 | bars on which at least one entry was blocked: 5397 |
| 1 new entry per market per day | 578 | across the market's sleeves |
| 3 new entries per day across the book | 355 | the rules' strength, then the market order, decide who enters |
| no entry in a market on the bar after an exit there | 172 | |
| rolling 24-hour loss limit (3 %) | 26 entries blocked | tripped 8 times |
| weekly loss limit (6 % from Monday 00:00 UTC) | 10 entries blocked | tripped once |
| monthly loss limit (10 %) | 114 entries blocked | tripped once |
| hard stop (-30 %) | 63799 entries blocked | tripped once; the book was halted from 2022-04-26 (79.3% of its days): as pre-registered, a simulated account never re-arms |
| Turtle ladder | 314 entries cut | bars at x0.8: 569, at x0.64: 5438 |
| heat cap (6 % total, 3 % per bet) | 293 entries scaled, 2158 open positions reduced | highest heat wanted at an entry 10.6%; mean 3.8% |
| correlation cap (50 % per bet, allocator v2) | 2 days | 33 positions reduced, 2 entries scaled; average cut 8.5% |
| cash (spot, no leverage) | 0 entries took less than the tier asked | 0 entries found no cash at all |

Effective risk per funded entry (the per-entry loss at the stop as a share of equity, after the ladder, heat and correlation multipliers and the cash constraint): mean 0.8%, median 0.8%, max 2.0%; expectancy -0.07 R a trade, 37.8% winners, average win 1.12 x the average loss; 92 stop-outs, 64 gaps past the stop, 36 re-entries within two bars of a stop-out. Positions: the book was flat on 78.5% of bars, held 2.00 positions on average and 24 at most, with 4.1% of equity invested on average and 55.0% at most.

| Ablation (the same signals, one layer changed) | Calmar | vs the book | CAGR | Max DD | Trades | Flag (> 0.1 Calmar) |
|---|---:|---:|---:|---:|---:|---|
| `heat_8pct`: the heat-cap variant of section 4.3: 8 % instead of 6 % | -0.20 | +0.02 | -6.1% | 30.7% | 450 | - |
| `no_brakes`: every book brake off (the correlation cap and the cash constraint stay) | -0.22 | +0.00 | -17.6% | 78.8% | 2745 | - |
| `no_corr_cap`: the brakes on, allocator v2's correlation cap off | -0.22 | -0.00 | -6.7% | 30.1% | 459 | - |
| `uniform_cost`: every market at the engine's 0.30 % round trip (no altcoin surcharge) | -0.24 | -0.02 | -7.5% | 30.6% | 501 | - |
| `raw`: no brake, no correlation cap: the sleeves share one equity and the cash constraint only | -0.31 | -0.08 | -26.6% | 87.0% | 1542 | - |

A positive 'vs the book' means the layer costs Calmar when it is on (the ablation without it does better); a layer that costs more than 0.1 Calmar is flagged for the owner, never silently kept or dropped. The ablations are diagnostics, not candidates.

| Post-hoc diagnostic (NOT pre-registered; added after the first run; never a candidate) | CAGR | Vol | Sharpe | Max DD | Calmar | PF | Trades | Gates (information) |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `no_hard_stop`: post hoc, not pre-registered: the hard stop off (the account re-arms at once instead of staying flat for good), everything else as registered | -8.3% | 21.9% | -0.29 | 43.3% | -0.19 | 0.91 | 2417 | profit factor above 1.2, max drawdown within the tier's limit (20 % Reference, 25 % higher tiers), Sharpe above 0.7, Calmar above 0.5, 75% of rolling 12-month windows positive, no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers), average win at least 2 x average loss |

The post-hoc line answers one question the first run raised - how much of the book's result is the hard stop's permanent halt - and nothing else: it was not pre-registered, it opens no holdout and it changes no verdict.

| Sleeve in the book | Funded trades | P&L (% of start) | Win rate | PF | Risk per entry | Funding multiplier (mean) | Cash-bound entries |
|---|---:|---:|---:|---:|---:|---:|---:|
| S1+VC/LTC | 11 | +2.8% | 54.5% | 2.91 | 0.8% | 0.68 | 0 |
| S1+VC/ETH | 10 | +1.5% | 60.0% | 3.22 | 0.9% | 0.56 | 0 |
| S1+S5/ADA | 12 | +1.3% | 66.7% | 2.44 | 0.4% | 0.54 | 0 |
| S1+S5/BTC | 11 | +0.7% | 36.4% | 1.40 | 0.8% | 0.55 | 0 |
| S1/BTC | 22 | +0.5% | 50.0% | 1.16 | 0.8% | 0.57 | 0 |
| S1+VC/ADA | 6 | +0.0% | 33.3% | 1.02 | 0.5% | 0.58 | 0 |
| S1+S5/SOL | 2 | -0.1% | 0.0% | 0.00 | 0.6% | 0.35 | 0 |
| S1/SOL | 3 | -0.1% | 0.0% | 0.00 | 1.0% | 0.55 | 0 |
| S1/LINK | 31 | -0.4% | 51.6% | 0.90 | 1.1% | 0.73 | 0 |
| S1+VC/SOL | 3 | -0.5% | 33.3% | 0.01 | 0.4% | 0.49 | 0 |
| S1+VC/LINK | 14 | -0.7% | 35.7% | 0.74 | 0.8% | 0.64 | 0 |
| S1/ETH | 20 | -0.8% | 40.0% | 0.70 | 0.7% | 0.60 | 0 |
| S1/XRP | 37 | -0.9% | 40.5% | 0.85 | 1.1% | 0.64 | 0 |
| S1+S5/TRX | 11 | -1.0% | 45.5% | 0.64 | 0.9% | 0.58 | 0 |
| S1+VC/DOGE | 15 | -1.7% | 26.7% | 0.58 | 0.6% | 0.68 | 0 |
| S1+VC/XRP | 11 | -1.7% | 27.3% | 0.63 | 0.8% | 0.64 | 0 |
| S1+S5/LTC | 20 | -1.8% | 35.0% | 0.46 | 0.5% | 0.54 | 0 |
| S1+S5/LINK | 16 | -1.9% | 25.0% | 0.24 | 0.9% | 0.52 | 0 |
| S1+VC/TRX | 18 | -2.1% | 38.9% | 0.47 | 1.0% | 0.56 | 0 |
| S1/ADA | 29 | -2.1% | 48.3% | 0.59 | 0.6% | 0.69 | 0 |
| S1/TRX | 28 | -2.1% | 25.0% | 0.56 | 1.2% | 0.78 | 0 |
| S1+VC/BTC | 16 | -2.4% | 31.2% | 0.50 | 0.8% | 0.63 | 0 |
| S1+S5/XRP | 23 | -2.7% | 26.1% | 0.53 | 1.0% | 0.54 | 0 |
| S1+S5/ETH | 15 | -3.0% | 13.3% | 0.26 | 0.8% | 0.61 | 0 |
| S1/LTC | 39 | -3.6% | 43.6% | 0.47 | 0.7% | 0.73 | 0 |
| S1/DOGE | 37 | -3.8% | 29.7% | 0.49 | 0.9% | 0.73 | 0 |

### Diversification and correlations

The book's Calmar is -0.22 against a median of 0.34 over its 26 sleeves on their own (mean 0.40; best 1.55, S1+VC SOL-USDT 6H [none]), 0.39 for holding BTC with the Trader policy sizing and 1.13 for the equal-weight hold of the nine at the same volatility target. Its realized volatility is 9.0% against a median sleeve volatility of 9.5%.

Daily-return correlations of the nine markets over the in-sample years (2019-11-28 to 2025-10-19, 2153 days): median pairwise 0.56 (range 0.23 to 0.81); among BTC, ETH, SOL and DOGE 0.25 to 0.81; BTC against each: ETH 0.81, SOL 0.57, XRP 0.56, DOGE 0.37, LINK 0.67, TRX 0.53, ADA 0.66, LTC 0.74.

Daily-return correlations of the nine markets over since 2024-01-01 (in-sample part) (2024-01-01 to 2025-10-19, 658 days): median pairwise 0.63 (range 0.18 to 0.78); among BTC, ETH, SOL and DOGE 0.70 to 0.78; BTC against each: ETH 0.78, SOL 0.76, XRP 0.57, DOGE 0.78, LINK 0.66, TRX 0.20, ADA 0.67, LTC 0.57.

Inside the book, the sleeves' daily P&L contributions correlate at a median of 0.00 pairwise (range -0.61 to 0.73; closed-trade P&L booked on the exit day as a share of the book's equity; days without an exit are zero).

### Why the book fails while most of its sleeves do not (computed from the numbers)

- **The hard stop ended it early.** The book funded 460 of 65262 entry opportunities; it lost 30 % of its equity by 2022-04-26 and, as pre-registered for a simulated account, took no new entry afterwards (63799 opportunities blocked, 79.3% of its days flat). Its calendar years read: 2021 -13.9%, 2022 -14.5%, 2023 +0.0%, 2024 +0.0%, 2025 +0.0%.
- **The heat cap trimmed the winners.** With nine markets that move together, the book's sleeves formed one bet most of the time, so every new signal in the bet scaled every open position down equally, as pre-registered: 2197 reductions on 460 trades (264 trades were trimmed at least once, 4.8 trims per trade on average; the heat cap alone reduced open positions 2158 times and scaled 293 entries). A trend rule earns its keep by letting winners run; here the average win was 1.12 x the average loss against a median of 2.68 x for the same sleeves on their own, and the expectancy was -0.07 R a trade against a median of +0.09 R on their own.
- **Every market lost in the book.** 9 of 9 markets ended with a loss; the worst: DOGE -5.5% over 52 trades, XRP -5.3% over 71 trades, TRX -5.1% over 57 trades, LINK -2.9% over 61 trades; BTC, the market whose sleeves are the strongest on their own, -1.2% over 49 trades, because its positions were trimmed whenever an altcoin signal fired.
- **The halt is not the cause.** Post hoc (not pre-registered), with the hard stop off the same book traded on: 2417 trades, 11365 heat-cap reductions, 9.4% of equity a year in costs against 1.5% for the registered book and a median of 1.1% for a sleeve on its own, and it ended at -8.3% a year with a 43.3% worst fall. The construction, not the hard stop, loses the money.
- **The brakes did what they are for.** Without them the same signals lost -26.6% a year with a 87.0% fall (no brake, no correlation cap) and -17.6% with 78.8% (the correlation cap alone): the brakes cut the fall to 30.1%. They cannot make a losing construction win.
- **What this says and does not say.** The S1 family's edge lives in a few markets (BTC, SOL and, at the Trader cell, S1+VC on ETH) and the fleet already runs those sleeves one by one. Pooling 26 sleeves of one highly correlated bet into one account under a cap that trims open positions is a different trading rule, and it fails; it does not retest the sleeves. A future portfolio study, if any, would pre-register a heat cap that acts on NEW entries only, one sleeve per market, and a re-arm rule for the hard stop - as a new row, never as an edit of this one.

### The book on the untouched 12 months

Not opened: the book did not pass the section 4.6 gates; the holdout stays untouched.

## The rotation test

One configuration, fixed before the run: the top 3 of the nine by trailing 3-week return, equal weight, decided at Sunday's close and filled Monday 00:00 UTC, long only, only while BTC's close is above its 200-day average (a close below it sends the basket to cash at the next open), sized by a 20 % volatility target, 0.15 % a side on BTC/ETH and 0.25 % on the altcoins. Span: 2020-07-20 to 2025-10-19 (1918 days), every line over the same days.

| Line | CAGR | Vol | Sharpe | Max DD | Calmar | Turnover / yr | Costs / yr | Invested (mean) | Days in cash by the filter | Rolling 12m + | Worst year |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **rotation (pre-registered)** | +20.6% | 18.0% | 1.13 | 20.3% | 1.02 | 10.0 x | 4.3% | 19.2% | 36.9% | 69.2% | +0.0% |
| rotation without the BTC filter (diagnostic) | +30.2% | 21.9% | 1.31 | 34.4% | 0.88 | 13.8 x | 6.9% | 30.6% | 0.0% | 71.2% | -23.9% |
| hold BTC, 20 % volatility target (the comparison) | +28.1% | 23.5% | 1.17 | 40.5% | 0.69 | 3.0 x | 1.0% | 42.2% | 0.0% | 75.0% | -32.2% |
| BTC buy-and-hold | +60.1% | 59.2% | 1.09 | 76.6% | 0.78 | 0.2 x | 0.0% | 99.9% | 0.0% | 67.3% | -64.2% |
| equal-weight hold of the nine, 20 % volatility target | +35.4% | 23.2% | 1.42 | 31.3% | 1.13 | 2.6 x | 1.5% | 32.5% | 0.0% | 78.8% | -21.7% |
| equal-weight hold of the nine, fully invested | +102.5% | 78.5% | 1.29 | 77.6% | 1.32 | 3.2 x | 11.9% | 99.9% | 0.0% | 71.2% | -65.4% |

| Calendar year | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|
| rotation (pre-registered) | +19.7% | +29.6% | +0.0% | +20.1% | +36.1% | +5.7% |
| rotation without the BTC filter (diagnostic) | +19.7% | +59.0% | -23.9% | +59.1% | +55.5% | +11.3% |
| hold BTC, 20 % volatility target (the comparison) | +73.4% | +16.8% | -32.2% | +61.0% | +52.8% | +8.8% |
| BTC buy-and-hold | +215.2% | +59.8% | -64.2% | +155.6% | +121.3% | +16.1% |
| equal-weight hold of the nine, 20 % volatility target | +25.4% | +87.5% | -21.7% | +48.1% | +63.5% | +10.3% |
| equal-weight hold of the nine, fully invested | +91.5% | +952.5% | -65.4% | +147.4% | +127.5% | +3.3% |

Pre-registered rule: Calmar ahead of the BTC comparison by more than 0.1 (1.02 vs 0.69): yes; CAGR ahead (+20.6% vs +28.1%): no; max drawdown at most 25 % (20.3%): yes. **Verdict: does not beat BTC** (the pre-registered expectation; the question is closed with our own numbers).

For information (no verdict rests on it): the rotation's worst fall was 20.3% against 40.5% for holding BTC at the same volatility target, which is the drawdown cut the plan's section 2.7 attributes to the BTC 200-day filter; its return stayed below BTC's, as the same section expected. The equal-weight hold of the nine at the same target made +35.4% a year at a 31.3% fall (Calmar 1.13) - a yardstick, not a candidate (it was pre-registered as a comparison line only).

How often each market was in the top 3 (share of the weekly selections): SOL 15%, BTC 14%, TRX 12%, ETH 12%, XRP 11%, ADA 10%, DOGE 10%, LINK 9%, LTC 8%.
The BTC filter sent the basket to cash 15 times, 10 of them followed by a re-entry within 30 days (the plan's whipsaw reading); the basket sat in cash by the filter on 36.9% of days.

Untouched 12 months: not opened - the rotation did not beat BTC in sample; the holdout stays untouched.

## The untouched 12 months

### Every opening of the holdout (ledger)

| Configuration | Cell | Role | Span | Return | Max DD | PF | Trades | Confirms |
|---|---|---|---|---:|---:|---:|---:|---|
| S1 BTC-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | +3.8% | 7.3% | 1.40 | 32 | yes |
| S1 SOL-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | +8.5% | 3.6% | 3.51 | 11 | yes |
| S1+S5 BTC-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | +3.4% | 7.7% | 1.36 | 30 | yes |
| S1+S5 SOL-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | +8.5% | 3.6% | 3.51 | 11 | yes |
| S1+VC ETH-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | -5.8% | 9.9% | 0.42 | 20 | no |
| S1+VC SOL-USDT 6H [none] | trader\|brakes\|none | sleeve | 2025-10-20->2026-10-20 | +5.0% | 8.7% | 1.50 | 23 | yes |
| hold ADA-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -7.3% | 8.8% | 0.00 | 1 | comparison line |
| hold BTC-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -7.7% | 11.5% | 0.00 | 1 | comparison line |
| hold DOGE-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -6.3% | 7.1% | 0.00 | 1 | comparison line |
| hold ETH-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -5.8% | 8.1% | 0.00 | 1 | comparison line |
| hold LINK-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -3.5% | 6.8% | 0.00 | 1 | comparison line |
| hold LTC-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -2.2% | 5.2% | 0.00 | 1 | comparison line |
| hold SOL-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -5.1% | 7.7% | 0.00 | 1 | comparison line |
| hold TRX-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -0.2% | 6.8% | 0.00 | 1 | comparison line |
| hold XRP-USDT 6H [none] | trader\|brakes\|none | control | 2025-10-20->2026-10-20 | -5.5% | 7.8% | 0.00 | 1 | comparison line |

Earlier looks at the same months by the stored studies (the holdout is a near-second look for these sleeves):

| Configuration | Earlier study | Cell | Earlier return | Earlier PF | Earlier trades | Earlier verdict |
|---|---|---|---:|---:|---:|---|
| S1 BTC-USDT 6H [none] | Sprint 2c (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1 BTC-USDT 6H [none] | R13 research round 1 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1 BTC-USDT 6H [none] | R16 research round 2 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1 BTC-USDT 6H [none] | R18 Trader Policy v1 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1 BTC-USDT 6H [none] | R18 Trader Policy v1 (hold BTC-USDT 6H [none]) | trader | -7.7% | 0.00 | 1 | comparison line |
| S1 BTC-USDT 6H [none] | R19 research round 3 (hold BTC-USDT 6H [none]) | trader | -7.7% | 0.00 | 1 | comparison line |
| S1 SOL-USDT 6H [none] | R12 replication (S1 SOL-USDT 6H [none]) | reference | +9.5% | 5.49 | 12 | confirmed |
| S1 SOL-USDT 6H [none] | R16 research round 2 (S1 SOL-USDT 6H [none]) | reference | +9.5% | 5.49 | 12 | confirmed |
| S1 SOL-USDT 6H [none] | R18 Trader Policy v1 (S1 SOL-USDT 6H [none]) | reference | +9.5% | 5.49 | 12 | confirmed |
| S1 SOL-USDT 6H [none] | R12 replication (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1 SOL-USDT 6H [none] | R16 research round 2 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1 SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1 SOL-USDT 6H [none] | R18 Trader Policy v1 (S1 SOL-USDT 6H [none]) | trader | +8.5% | 3.51 | 11 | confirmed |
| S1 SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |
| S1 SOL-USDT 6H [none] | R19 research round 3 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | Sprint 2c (S1+S5 BTC-USDT 6H [none]) | reference | +2.3% | 1.48 | 32 | confirmed |
| S1+S5 BTC-USDT 6H [none] | R18 Trader Policy v1 (S1+S5 BTC-USDT 6H [none]) | reference | +2.3% | 1.48 | 32 | confirmed |
| S1+S5 BTC-USDT 6H [none] | Sprint 2c (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | R13 research round 1 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | R16 research round 2 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | R18 Trader Policy v1 (hold BTC-USDT 6H [none]) | reference | -4.0% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | R18 Trader Policy v1 (S1+S5 BTC-USDT 6H [none]) | trader | +3.4% | 1.36 | 30 | confirmed |
| S1+S5 BTC-USDT 6H [none] | R18 Trader Policy v1 (hold BTC-USDT 6H [none]) | trader | -7.7% | 0.00 | 1 | comparison line |
| S1+S5 BTC-USDT 6H [none] | R19 research round 3 (hold BTC-USDT 6H [none]) | trader | -7.7% | 0.00 | 1 | comparison line |
| S1+S5 SOL-USDT 6H [none] | R12 replication (S1+S5 SOL-USDT 6H [none]) | reference | +9.5% | 5.49 | 12 | confirmed |
| S1+S5 SOL-USDT 6H [none] | R18 Trader Policy v1 (S1+S5 SOL-USDT 6H [none]) | reference | +9.5% | 5.49 | 12 | confirmed |
| S1+S5 SOL-USDT 6H [none] | R12 replication (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+S5 SOL-USDT 6H [none] | R16 research round 2 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+S5 SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+S5 SOL-USDT 6H [none] | R18 Trader Policy v1 (S1+S5 SOL-USDT 6H [none]) | trader | +8.5% | 3.51 | 11 | confirmed |
| S1+S5 SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |
| S1+S5 SOL-USDT 6H [none] | R19 research round 3 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | Sprint 2c (hold ETH-USDT 6H [none]) | reference | -2.9% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | R13 research round 1 (hold ETH-USDT 6H [none]) | reference | -2.9% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | R16 research round 2 (hold ETH-USDT 6H [none]) | reference | -2.9% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | R18 Trader Policy v1 (hold ETH-USDT 6H [none]) | reference | -2.9% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | R18 Trader Policy v1 (hold ETH-USDT 6H [none]) | trader | -5.8% | 0.00 | 1 | comparison line |
| S1+VC ETH-USDT 6H [none] | R19 research round 3 (hold ETH-USDT 6H [none]) | trader | -5.8% | 0.00 | 1 | comparison line |
| S1+VC SOL-USDT 6H [none] | R16 research round 2 (S1+VC SOL-USDT 6H [none]) | reference | -1.6% | 0.68 | 23 | contradicted |
| S1+VC SOL-USDT 6H [none] | R12 replication (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+VC SOL-USDT 6H [none] | R16 research round 2 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+VC SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | reference | -2.5% | 0.00 | 1 | comparison line |
| S1+VC SOL-USDT 6H [none] | R18 Trader Policy v1 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |
| S1+VC SOL-USDT 6H [none] | R19 research round 3 (hold SOL-USDT 6H [none]) | trader | -5.1% | 0.00 | 1 | comparison line |

Second looks (configurations whose holdout an earlier run of this study already opened; both looks stay in the ledger): S1 BTC-USDT 6H [none] @ trader|brakes|none, S1 SOL-USDT 6H [none] @ trader|brakes|none, S1+S5 BTC-USDT 6H [none] @ trader|brakes|none, S1+S5 SOL-USDT 6H [none] @ trader|brakes|none, S1+VC ETH-USDT 6H [none] @ trader|brakes|none, S1+VC SOL-USDT 6H [none] @ trader|brakes|none.

## Paper-fleet shortlist

Nothing recorded for the fleet: nothing recorded for the fleet. Existing accounts are untouched; nothing joins demo or live.

## Owner decisions (nothing below is decided by this report)

- The breadth book does not pass the section 4.6 gates. Recommendation: nothing to decide; the confirmed sleeves stay in the fleet as they are.
- The pre-registered book treats the -30 % hard stop as the end of the simulated account (it halted on 2022-04-26 and never re-armed), which is what the plan's rule says for a live account until the owner has reviewed; a real owner would review and decide. The post-hoc reading with the hard stop off (not pre-registered) gives -8.3% a year at a 43.3% fall (Calmar -0.19). Decision: whether a future portfolio study should pre-register a re-arm rule for the hard stop in simulation (for example re-arm after 30 flat days with the peak reset, as the Reference ladder does). Recommendation: yes, as a pre-registered rule of the next study, never as an edit of this one.
- Two findings this study was not pre-registered to act on: S1 BTC-USDT 6H [none] (walk-forward Calmar 0.61 at the Trader cell against 0.38 at the Reference cell, +8.6% a year at a 14.3% fall; holdout +3.8%, PF 1.40, 32 trades); S1+VC SOL-USDT 6H [none] (walk-forward Calmar 1.55 at the Trader cell against 1.54 at the Reference cell, +17.5% a year at a 11.3% fall; holdout +5.0%, PF 1.50, 23 trades) pass the section 4.6 gates at the Trader tier and their untouched 12 months confirm them, but neither runs in the paper fleet, and this study's pre-registration lists a fleet ticket only for the book and the rotation. Decision: whether to add them as Trader-tier accounts through the R18 loader path (a small new row). Recommendation: yes for S1 BTC-USDT 6H, as one small account read as a hypothesis (it never passed at the Reference tier, where its Calmar sat below the 0.5 gate; the larger size lifts the Calmar above it); no for now for S1+VC SOL-USDT 6H, whose holdout the round-2 study contradicted at the Reference tier (-1.6 %) and this study confirms at the Trader tier (+5.0 %) - the same rule, two tiers, two verdicts on one year of data is noise, and the fleet already runs the SOL S1 and S1+S5 sleeves at both tiers.
- The rotation did not beat holding BTC with the same sizing, as pre-registered. Recommendation: nothing to build; the question is closed with our own numbers.

## Method notes and caveats

- The sleeves' own verdicts come from Sprint 2c's runner (walk-forward windows that restart flat every 180 days); the book replays the per-window selected rules continuously from the first test window of any sleeve, so its drawdown can exceed any window's and its equity is one account, not a stitch.
- A sleeve joins the book when its own first test window starts (SOL's history is shorter); the hold comparison through the book simulator starts with BTC's first window.
- Each entry is sized by the Trader tier on the book's equity marked at the previous close, capped by the cash left; the engine sizes a single sleeve on its cash, which is the same thing when the sleeve is flat (the parity test), and the book never sells an open position to make room for a new one.
- The heat cap and the correlation cap scale open positions down at the next open (a reduce-only sale), as section 4.3 and allocator v2 prescribe; an open position whose stop has moved above the price carries no risk and is left alone by the heat cap.
- The brakes' equity arithmetic (ladder, hard stop, loss limits) is the R18 EntryBrakes state machine run on the book's equity as one column, so a count here means what it meant in the single-sleeve studies.
- Correlations use one close per UTC day from the 6H bars; the 'recent' window ends at the in-sample end, so the untouched months never enter a correlation shown here.
- The rotation's volatility window is 30 DAYS of daily returns (allocator v1's convention); the tier's is 30 bars of 6H candles. The last in-sample day may be a part day; every rotation line books the same days.
- Every number is a simulation on historical public data at the modelled costs and proves nothing about the future; nothing here authorizes paper, demo or live trading.
- The first full run (2026-11-05 07:00 UTC) started the book's clock at the data's first bar instead of the first walk-forward test window, so 1.5 flat years diluted every annualised figure of the book, and the daily baskets booked their costs against a negative cash balance (a hair of leverage); both were fixed and the whole study re-run with the pre-registration unchanged. The first run's holdout openings stay in the ledger as its first entry (second looks at the same months).
- The post-hoc diagnostic (the book with the hard stop off) was added after the first run showed the hard stop ending the book's entries for good; it is labelled as not pre-registered everywhere and the verdict does not use it.

