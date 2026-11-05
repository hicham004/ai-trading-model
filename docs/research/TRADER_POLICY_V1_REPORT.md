# Trader Policy v1 — the confirmed configurations at three fixed risk budgets, with brakes and variants (walk-forward, SIMULATION ONLY)

Generated 2026-11-05 03:34 UTC by `scripts/run_trader_policy_v1.py` (plan row R18; 9.6 min). Rules: Sprint 2c's, run by `scripts/run_research_v1c.py`'s own `run_series` with its plan-row-R18 arguments; everything the tier does not define is Sprint 2c's (regime gate `hmm3 bear>=0.5 gate` where the configuration has one, S0 filter S0 vol×3 spread p98 gap3 FOMC±6/6h, walk-forward train 540d → purge 7d → test 180d, fee 0.10% + slippage 0.050% per side, brackets ['none', 'tp2', 'trail1', 'time30']). Data: PUBLIC OKX spot candles of BTC-USDT, ETH-USDT, SOL-USDT and DOGE-USDT (1H and 4H stored, 6H resampled from 1H) frozen at Sprint 2c's data end (bar close ≤ 2026-10-20T10:00:00+00:00). Holdout: the last 12 months (2025-10-20->2026-10-20), opened only for the pre-registered cells.

**Nothing here authorizes paper, demo or live trading.** A tier that passes is a hypothesis for the forward paper fleet, not a budget to deploy. Every number is a simulation on historical public data. The demo shadow run, its caps and the 0.60 confidence floor are untouched.

## Executive summary (plain English)

- **What we did.** The five configurations the earlier studies confirmed were re-judged at three fixed risk budgets — Reference (today's 10 % volatility target), Trader (20 % target, at most 2 % of the account at risk on one stop, the Turtle ladder) and Aggressive (25 %, 2.5 %) — plus Kovner's 1.5 %-per-stop rule for information, with the section 4.3 brakes on and off and each section 4.2 position-management variant on alone, under the Sprint 2c walk-forward and the section 4.6 gates written down before the run. Before any tier was judged, the Reference cell of every configuration and hold control went through the same unchanged selection and matched the stored numbers (Sprint 2c's, the replication study's, round 1's, round 2's) in 11 of 11 cases. The rule each walk-forward window selects never sees the budget, so every configuration kept its ATR multiple and exit bracket; only the size of the same trades changes. 150 cells ran on 2019-12-16->2026-10-20 after fees and slippage.
- **S1+S5 BTC-USDT 6H [none].** Reference: +5.3% a year, worst drawdown 8.8%, Calmar 0.60, realized volatility 6.2%. Trader tier (brakes on): +10.4% a year, drawdown 14.1%, Calmar 0.74, volatility 10.1%, 1.66 x the Reference exposure, a stop costs 1.7% of the account on average (cap binding on 64% of entries), average win 4.7 x average loss, expectancy 0.27 R, passes the section 4.6 gates; holdout +3.4% / PF 1.36 / 30 tr ✓; chance of touching -30 % 0.6%. Aggressive: +12.4% a year, drawdown 17.2%, volatility 12.4%, passes, -30 % chance 2.9%.
- **S1 SOL-USDT 6H [none].** Reference: +6.0% a year, worst drawdown 5.6%, Calmar 1.06, realized volatility 5.5%. Trader tier (brakes on): +9.8% a year, drawdown 8.0%, Calmar 1.22, volatility 8.0%, 1.61 x the Reference exposure, a stop costs 1.5% of the account on average (cap binding on 35% of entries), average win 3.0 x average loss, expectancy 0.16 R, passes the section 4.6 gates; holdout +8.5% / PF 3.51 / 11 tr ✓; chance of touching -30 % 0.0%. Aggressive: +12.4% a year, drawdown 9.9%, volatility 9.9%, passes, -30 % chance 0.0%.
- **S1+S5 SOL-USDT 6H [none].** Reference: +7.5% a year, worst drawdown 5.4%, Calmar 1.40, realized volatility 5.6%. Trader tier (brakes on): +13.6% a year, drawdown 9.8%, Calmar 1.39, volatility 9.5%, 1.63 x the Reference exposure, a stop costs 1.6% of the account on average (cap binding on 34% of entries), average win 4.2 x average loss, expectancy 0.23 R, passes the section 4.6 gates; holdout +8.5% / PF 3.51 / 11 tr ✓; chance of touching -30 % 0.0%. Aggressive: +17.0% a year, drawdown 11.9%, volatility 11.8%, passes, -30 % chance 0.0%.
- **S1+VC BTC-USDT 4H [gate].** Reference: +4.3% a year, worst drawdown 7.8%, Calmar 0.55, realized volatility 6.3%. Trader tier (brakes on): +8.0% a year, drawdown 13.8%, Calmar 0.58, volatility 10.5%, 1.74 x the Reference exposure, a stop costs 1.4% of the account on average (cap binding on 32% of entries), average win 3.5 x average loss, expectancy 0.26 R, passes the section 4.6 gates; holdout +2.0% / PF 1.19 / 27 tr ✓; chance of touching -30 % 0.1%. Aggressive: +8.8% a year, drawdown 16.1%, volatility 12.7%, passes, -30 % chance 0.7%.
- **S1+VC DOGE-USDT 4H [gate].** Reference: +4.0% a year, worst drawdown 4.8%, Calmar 0.83, realized volatility 4.6%. Trader tier (brakes on): +6.3% a year, drawdown 9.4%, Calmar 0.67, volatility 7.9%, 1.82 x the Reference exposure, a stop costs 1.2% of the account on average (cap binding on 21% of entries), average win 2.7 x average loss, expectancy 0.23 R, passes the section 4.6 gates; holdout +1.3% / PF 1.23 / 16 tr ✓; chance of touching -30 % 0.0%. Aggressive: +7.9% a year, drawdown 11.6%, volatility 9.8%, passes, -30 % chance 0.0%.
- **Brakes.** At the Trader tier, over the five configurations' walk-forward years, the brakes acted as follows: bar-after-exit blocked 131 times, 1/market/day blocked 26 times, Turtle ladder cut an entry 7 times, 24 h loss limit blocked 1 times; never: weekly limit blocked, monthly limit blocked, heat cap cut. Their cost exceeded 0.1 Calmar (flagged for you) on: S1+VC DOGE-USDT 4H [gate] at reference, S1+VC DOGE-USDT 4H [gate] at aggressive. The Turtle ladder cost no sleeve more than 0.1 Calmar beside the same sleeve without a ladder.
- **Variants (size-neutral rule).** The ones that counted — Sharpe at least the base's and Calmar at least the base's after matching the base's volatility — per sleeve: add: S1+S5 BTC-USDT 6H [none]; scale_out: S1 SOL-USDT 6H [none], S1+S5 SOL-USDT 6H [none]; no_time_stop: S1 SOL-USDT 6H [none], S1+VC BTC-USDT 4H [gate], S1+VC DOGE-USDT 4H [gate]; wider_stop: S1+VC DOGE-USDT 4H [gate]. No variant joins the fleet in this row; a variant that counts is a candidate for a pre-registered forward test.
- **Conviction split.** Pooled over S1+S5 BTC-USDT 6H [none], S1 SOL-USDT 6H [none], S1+S5 SOL-USDT 6H [none]: the 1.25 x trades (46) earned 0.12 R each against 0.25 R for the 0.75 x trades (277): the split fails its pre-registered test.
- **A look the pre-registration did not list.** The runner opens the holdout for any cell that passes the gates, and the TF forward control passed at TF BTC-USDT 4H [none] @ aggressive|brakes|none, TF BTC-USDT 4H [none] @ trader|brakes|none, TF BTC-USDT 6H [none] @ aggressive|brakes|none, TF BTC-USDT 6H [none] @ trader|brakes|none, so its 12 months were opened there (the pre-registration listed only the configurations and the hold controls). Recorded in the ledger; TF is never judged and joins the fleet as a control regardless; the job planner now excludes the TF controls from the holdout.
- **Holdout and fleet.** 5 of 5 configurations pass every section 4.6 gate at the Trader tier with the brakes on and are confirmed by their untouched 12 months at that tier (S1+S5 BTC-USDT 6H [none], S1 SOL-USDT 6H [none], S1+S5 SOL-USDT 6H [none], S1+VC BTC-USDT 4H [gate], S1+VC DOGE-USDT 4H [gate]). A tier changes only the size of the same trades, so these holdout looks are near-second looks at months the Reference tier already opened (the ledger names each earlier look); they confirm the plumbing of the tier, not the edge. The rows for the paper fleet (the base rule at the Trader tier, all variants off, plus the 'always long above the 200-day average' forward control) are RECORDED in the results for plan row R18b, which extends the fleet's loader before applying them; the shortlist file and every running account are untouched. Nothing is approved for demo or live trading.

## Fixed before the first run (the pre-registration)

Pre-registration hash (text, file and configuration): `64d73064dfb183e98e3593213a1174b8418df13c5cbc32d591ab54dfbe2f3666`; file `docs/research/trader_policy_v1_preregistration.json` written 2026-11-05T03:10:26+00:00.

- **fixed_on**: 2026-11-05, before any run (plan row R18)
- **question**: At the three fixed risk budgets of Trader Policy v1 (Reference = today's 10 % volatility target with the Reference ladder; Trader = a 20 % target capped so that no stop costs more than 2 % of equity, with the Turtle ladder; Aggressive = 25 % and 2.5 %), with the section 4.3 brakes on and off and each section 4.2 position-management variant on alone, do the five confirmed configurations still pass the section 4.6 gates on the Sprint 2c walk-forward, what do the brakes and the variants cost or add, where does each tier's realized volatility, risk per trade and probability of a 30 % drawdown land, and which configurations therefore join the paper fleet at the Trader tier?
- **configurations**: S1+S5 BTC-USDT 6H [none] (stored by Sprint 2c); S1 SOL-USDT 6H [none] (stored by R12 replication); S1+S5 SOL-USDT 6H [none] (stored by R12 replication); S1+VC BTC-USDT 4H [gate] (stored by R13 research round 1); S1+VC DOGE-USDT 4H [gate] (stored by R16 research round 2)
- **controls**: hold BTC-USDT 4H [none]; hold BTC-USDT 6H [none]; hold ETH-USDT 4H [none]; hold ETH-USDT 6H [none]; hold SOL-USDT 6H [none]; hold DOGE-USDT 4H [none]; TF BTC-USDT 4H [none] (new forward control: long above the 200-day average, policy sizing; fixed rule, no exit bracket, no 20-train-trade qualification; never judged); TF BTC-USDT 6H [none] (new forward control: long above the 200-day average, policy sizing; fixed rule, no exit bracket, no 20-train-trade qualification; never judged); TF ETH-USDT 4H [none] (new forward control: long above the 200-day average, policy sizing; fixed rule, no exit bracket, no 20-train-trade qualification; never judged); TF ETH-USDT 6H [none] (new forward control: long above the 200-day average, policy sizing; fixed rule, no exit bracket, no 20-train-trade qualification; never judged)
- **tiers**:
  - reference: vt10/30 crash15/90dh ladder: today's policy: 10 % volatility target, half size in a crash state, the Reference ladder (half at -5 %, flat at -10 %)
  - trader: vt20/30 crash15/90dh cap2 turtle: 20 % volatility target, at most 2 % of equity at risk on one stop, the same crash de-risking, the Turtle ladder on entries
  - aggressive: vt25/30 crash15/90dh cap2.5 turtle: 25 % volatility target, at most 2.5 % of equity at risk on one stop, the same crash de-risking, the Turtle ladder on entries
  - risk1.5: risk1.5 crash15/90dh turtle: for information only: Kovner's rule, 1.5 % of equity at risk on every stop, the same crash de-risking, the Turtle ladder
  - trader-reference-ladder: vt20/30 crash15/90dh cap2 ladder: the Trader tier's size rule under the Reference ladder instead of the Turtle ladder (comparison only)
  - aggressive-reference-ladder: vt25/30 crash15/90dh cap2.5 ladder: the Aggressive tier's size rule under the Reference ladder (comparison only)
  - trader-no-ladder: vt20/30 crash15/90dh cap2: the Trader tier's size rule with no ladder at all (the ladder's cost)
  - aggressive-no-ladder: vt25/30 crash15/90dh cap2.5: the Aggressive tier's size rule with no ladder at all (the ladder's cost)
- **brakes**:
  - on: turtle x0.8@-10%, x0.64@-20%; hard stop -30%; entry caps 1/market/day, 3/day, none on the bar after an exit; loss limits 3%/24h, 6%/week, 10%/month; heat cap 6% (group 50%, corr >= 0.7)
  - off: the tier's own ladder only (Turtle for Trader/Aggressive/risk1.5, the Reference ladder for Reference, none for the no-ladder comparisons)
  - scope: entries only: no brake closes, reduces or otherwise touches an open position; the Reference ladder (which does reduce) is the Reference tier's own rule and the comparison for the higher tiers
  - windows: the walk-forward's test windows restart flat from the same capital every 180 days, so the ladder's equity peak, the hard stop and the loss windows restart with them, exactly as Sprint 2c's Reference ladder did; the stitched curve's drawdown can exceed any window's, and the brakes' counts are per-window counts summed
- **variants**:
  - add: one add of 0.5 x the initial quantity once the close is +1 R (first unit keeps its stop; the add gets the rule's own stop of the add bar; never after a loss)
  - scale_out: a 0.5 scale-out once the close is +2 R (the remainder keeps its stop; one trade, P&L pooled)
  - conviction: 1.25 x the tier's size when the 30-day volume z-score is above 1 at the entry bar, 0.75 x otherwise, never above the tier's per-trade cap (not on the S1+VC sleeves)
  - trail2: a trailing exit that activates at +1 R and follows the running high at 2 R
  - trail3: a trailing exit that activates at +1 R and follows the running high at 3 R
  - wider_stop: a wider initial stop: max(4, the selected multiple + 1) x ATR
  - no_time_stop: the selected exit bracket without its time stop (S1 SOL-USDT 6H's time30)
- **variant_rule**: each variant runs alone at the Trader tier with the brakes on and is compared with the same sleeve without it; it counts only with Sharpe >= the base's and Calmar >= the base's after scaling to the base's realized volatility (size-neutral); the conviction split additionally needs expectancy in R of its 1.25 x trades above its 0.75 x trades with >= 30 trades each, read per sleeve and pooled over the sleeves it applies to (S1+S5 BTC 6H, S1 and S1+S5 SOL 6H; not the S1+VC sleeves); no variant joins the fleet in this row (the fleet account is the base rule, all variants off)
- **protocol**: Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), with Sprint 2c's defaults for everything the tier does not define: the candidates' grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the regime-v2 entry gate where the configuration has one, the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then bracket) and the 0.25 reduce-only rebalance; the tier replaces only the policy sizing (and adds its brakes); the per-window selection of the rule variants is unchanged and never sees the tier, so every configuration keeps the ATR multiple and exit bracket its walk-forward selected (S1 SOL-USDT 6H's time30 included, also run once without it as a variant); the runner's defaults are checked against the stored Sprint 2c run before the study runs and the protocol check of every cell is recorded in the results (a tier is a recorded policy_sizing mismatch, never hidden); the TF control runs with --brackets none --min-trades 1, a recorded deviation, because R16 showed the 20-train-trade qualification leaves this slow rule flat
- **data**: OKX public 1H and 4H spot candles of BTC-USDT, ETH-USDT, SOL-USDT and DOGE-USDT (4H stored, 6H resampled from 1H), frozen in a study lake at Sprint 2c's data end (bar close <= 2026-10-20T10:00:00+00:00) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window as in Sprint 2c, R12, R13 and R16; Binance public funding and open interest for the S5 filter as before
- **costs**: the engine's 0.10 % fee + 0.05 % slippage a side (0.30 % a round trip) for the gates; the selected rule is also replayed, same windows and sizing, at 0.20 % a round trip (0.05 % + 0.05 % a side, the measured BTC/ETH cost) and at 0.50 % (0.10 % + 0.15 % a side, altcoins at +10 bps a side), reported, never gated
- **reproduction**: before any tier is judged, the Reference cell (brakes off) of every configuration and hold control must give the stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts — Sprint 2c's for BTC-USDT and ETH-USDT, the replication study's for SOL-USDT and DOGE-USDT, round 1's for S1+VC BTC-USDT 4H [gate], round 2's for S1+VC DOGE-USDT 4H [gate]; otherwise the study stops
- **gates**: section 4.6: the Sprint 2c gates (PF > 1.2, Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, >= 30 trades, >= 50 % of +-30 % neighbours profitable) with max drawdown <= 20 % and worst calendar year >= -10 % at the Reference tier, <= 25 % and >= -15 % at the higher tiers, plus average win / average loss >= 2 at every tier; expectancy in R (R = quantity x (entry fill - initial stop); under the add the first unit's R) is reported for every cell, not gated
- **brake_judgement**: the brakes are judged by their trigger counts and their cost: the same sleeve with and without them, and the tier with its ladder beside the same tier with no ladder and with the Reference ladder; a brake that costs more than 0.1 Calmar is flagged for the owner; the loss limits and the heat cap are expected to count zero on one sleeve (they act in the multi-market book, plan row R20); re-entries within two bars of a stop-out are the rule's own behaviour, counted, not changed
- **readings**: per configuration and tier: realized yearly volatility, average allocation and its ratio to the Reference tier, the effective risk per trade and how often the 2 % / 2.5 % cap binds, how often a tier put the whole account in one trade, trades whose loss exceeded the stop distance (gaps), re-entries within two bars of a stop-out, and the bootstrap probability of touching -30 % (the hard stop), beside section 4.1's expectations (Trader near 10-11 % realized volatility on the lead sleeve, about 1 in 30 for the hard stop; Aggressive near 13 % and about 1 in 10)
- **holdout**: the last 12 months (2025-10-20 -> 2026-10-20), opened only by the full pre-registered study (every configuration, control and cell, with the reproduction, never --quick), only for (a) the Reference reproduction, whose months the stored studies already opened and which must reproduce them, (b) the brakes-on cell of the Trader and Aggressive tiers when it passes every section 4.6 gate, and (c) the hold controls as the comparison line (as every study did); the v1c verdict (positive return, PF > 1, >= 10 trades); every opening goes into an append-only ledger the report shows. CAVEAT, stated before the run: a tier changes only the size of the same trades, so a holdout opened at a tier is a near-second look at months already opened at the Reference tier, and its falling direction was known for every market; a confirmation is necessary, not sufficient, and the paper fleet's forward record is the judge
- **fleet**: a configuration that passes every section 4.6 gate at the trader tier with the brakes on and whose holdout at that cell confirms joins the paper fleet's shortlist as a NEW account with a source tag naming this study, its tier, its brakes and 'no variant' — the base rule at the Trader tier (vt20, 2 % cap, Turtle ladder, hard stop and entry caps on, all variants off); the TF control on BTC-USDT and ETH-USDT (6H) joins as a forward control at the Reference sizing; the rows are recorded in the results (shortlist_additions) and applied by plan row R18b once the fleet's loader can validate a tier-tagged row; existing accounts are untouched; nothing joins demo or live
- **no_changes_after_results**: no gate, tier, brake number, variant, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so

Protocol check of the Reference cell against the stored Sprint 2c run: every parameter the same (checked: brackets, fee, holdout_months, ladder_recovery_days, min_trades, no_trade_label, policy_sizing, positioning_source, purge_days, quick, rebalance_threshold, regime, regime_modes, select_by, slippage, strategies, test_days, timeframes, train_days). Every other cell's check is stored with its result: a tier is a recorded `policy_sizing` mismatch (and the TF control's fixed-rule protocol a recorded `brackets` / `min_trades` mismatch); the study stops on any mismatch the cell does not explain.

Gates: Sprint 2c's (profit_factor_min 1.2; max_drawdown_max 0.2; sharpe_min 0.7; calmar_min 0.5; rolling_12m_positive_min 0.75; worst_calendar_year_min -0.1; min_trades 30; robust_share_min 0.5; min_year_days 60), with max drawdown ≤ 25 % and worst calendar year ≥ -15 % at the higher tiers (≤ 20 % and ≥ -10 % at the Reference tier), plus average win / average loss ≥ 2. Expectancy in R is reported, never gated.

**Warning — second look.** An earlier run of this study already opened the holdout of: S1 SOL-USDT 6H [none] @ aggressive|brakes|none, S1 SOL-USDT 6H [none] @ reference|nobrakes|none, S1 SOL-USDT 6H [none] @ trader|brakes|none, S1+S5 BTC-USDT 6H [none] @ aggressive|brakes|none, S1+S5 BTC-USDT 6H [none] @ reference|nobrakes|none, S1+S5 BTC-USDT 6H [none] @ trader|brakes|none, S1+S5 SOL-USDT 6H [none] @ aggressive|brakes|none, S1+S5 SOL-USDT 6H [none] @ reference|nobrakes|none, S1+S5 SOL-USDT 6H [none] @ trader|brakes|none, S1+VC BTC-USDT 4H [gate] @ reference|nobrakes|none, S1+VC DOGE-USDT 4H [gate] @ reference|nobrakes|none. Both looks are in the ledger below.

## Reproduction of the stored studies

The Reference cell (brakes off) of every configuration and hold control had to give the stored walk-forward numbers (6 decimals), the same trade counts, the same most-selected rules and the same gate verdicts, otherwise the study stops.

| Configuration | Stored by | Total return (reproduced / stored) | Sharpe (reproduced / stored) | Max DD (reproduced / stored) | Trades | Same rule | Same verdict | Largest difference | Agrees |
|---|---|---|---|---|---:|---|---|---:|---|
| S1+S5 BTC-USDT 6H [none] | Sprint 2c | 0.247165 / 0.247165 | 0.856002 / 0.856002 | 0.087603 / 0.087603 | 139 / 139 | yes | yes | 0.0e+00 | yes |
| S1 SOL-USDT 6H [none] | R12 replication | 0.222609 / 0.222609 | 1.079467 / 1.079467 | 0.056399 / 0.056399 | 107 / 107 | yes | yes | 0.0e+00 | yes |
| S1+S5 SOL-USDT 6H [none] | R12 replication | 0.282978 / 0.282978 | 1.319852 / 1.319852 | 0.053671 / 0.053671 | 101 / 101 | yes | yes | 0.0e+00 | yes |
| S1+VC BTC-USDT 4H [gate] | R13 research round 1 | 0.202091 / 0.202091 | 0.706484 / 0.706484 | 0.078371 / 0.078371 | 83 / 83 | yes | yes | 0.0e+00 | yes |
| S1+VC DOGE-USDT 4H [gate] | R16 research round 2 | 0.187211 / 0.187211 | 0.879949 / 0.879949 | 0.047791 / 0.047791 | 67 / 67 | yes | yes | 0.0e+00 | yes |
| hold BTC-USDT 4H [none] | Sprint 2c | 0.147823 / 0.147823 | 0.594651 / 0.594651 | 0.072057 / 0.072057 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| hold BTC-USDT 6H [none] | Sprint 2c | 0.118166 / 0.118166 | 0.486633 / 0.486633 | 0.079653 / 0.079653 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| hold ETH-USDT 4H [none] | Sprint 2c | 0.078472 / 0.078472 | 0.377167 / 0.377167 | 0.086111 / 0.086111 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| hold ETH-USDT 6H [none] | Sprint 2c | 0.110168 / 0.110168 | 0.496014 / 0.496014 | 0.095781 / 0.095781 | 9 / 9 | yes | yes | 0.0e+00 | yes |
| hold SOL-USDT 6H [none] | R12 replication | 0.285279 / 0.285279 | 1.134204 / 1.134204 | 0.069845 / 0.069845 | 7 / 7 | yes | yes | 0.0e+00 | yes |
| hold DOGE-USDT 4H [none] | R12 replication | 0.030347 / 0.030347 | 0.188892 / 0.188892 | 0.068967 / 0.068967 | 9 / 9 | yes | yes | 0.0e+00 | yes |

11 of 11 reproduced.

## S1+S5 BTC-USDT 6H [none] — **fleet candidate at the Trader tier**

Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; 'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.

| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| vt10/30 crash15/90dh ladder, brakes off | +5.3% | 0.86 | 8.8% | 0.60 | 1.68 | 139 | 29% | 4.2 | 0.22 | 6.2% | 8.4% | 1.00 | 1.1%, 2.9% | - | 0% | 0 | 5/15 | 0.0% | -5.7% | 78.0% | - | **PASS** | +2.3% / PF 1.48 / 32 tr ✓ |
| vt10/30 crash15/90dh ladder, brakes on | +5.0% | 0.82 | 9.3% | 0.54 | 1.65 | 130 | 28% | 4.1 | 0.23 | 6.1% | 8.2% | 0.98 | 1.1%, 2.9% | - | 0% | 0 | 4/14 | 0.0% | -5.5% | 78.0% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +10.8% | 1.05 | 14.5% | 0.75 | 1.87 | 139 | 29% | 4.6 | 0.26 | 10.3% | 14.4% | 1.71 | 1.7%, 2.0% | 63% | 0% | 0 | 5/15 | 1.2% | -10.9% | 85.4% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +10.4% | 1.03 | 14.1% | 0.74 | 1.85 | 130 | 28% | 4.7 | 0.27 | 10.1% | 14.0% | 1.66 | 1.7%, 2.0% | 64% | 0% | 0 | 4/14 | 0.6% | -10.4% | 85.4% | - | **PASS** | +3.4% / PF 1.36 / 30 tr ✓ |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +12.9% | 1.03 | 17.7% | 0.73 | 1.86 | 139 | 29% | 4.6 | 0.27 | 12.6% | 17.9% | 2.13 | 2.1%, 2.5% | 63% | 1% | 0 | 5/15 | 3.3% | -13.5% | 82.9% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +12.4% | 1.01 | 17.2% | 0.72 | 1.84 | 130 | 28% | 4.6 | 0.29 | 12.4% | 17.4% | 2.07 | 2.1%, 2.5% | 64% | 2% | 0 | 4/14 | 2.9% | -13.0% | 85.4% | - | **PASS** | +3.9% / PF 1.34 / 30 tr ✓ |
| risk1.5 crash15/90dh turtle, brakes off | +9.0% | 1.14 | 9.7% | 0.93 | 1.99 | 139 | 31% | 4.5 | 0.22 | 7.8% | 10.8% | 1.29 | 1.3%, 1.5% | - | 0% | 0 | 5/15 | 0.0% | -6.3% | 87.8% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +9.7% | 1.05 | 13.1% | 0.74 | 1.91 | 139 | 29% | 4.7 | 0.25 | 9.2% | 12.0% | 1.43 | 1.5%, 2.0% | 63% | 0% | 0 | 5/15 | 0.2% | -9.4% | 85.4% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +9.9% | 0.97 | 15.5% | 0.64 | 1.79 | 139 | 29% | 4.4 | 0.27 | 10.3% | 13.0% | 1.54 | 1.7%, 2.5% | 63% | 1% | 0 | 5/15 | 1.6% | -11.1% | 85.4% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2, brakes off | +11.1% | 1.07 | 14.5% | 0.77 | 1.89 | 139 | 29% | 4.7 | 0.25 | 10.4% | 14.6% | 1.73 | 1.7%, 2.0% | 63% | 0% | 0 | 5/15 | 1.2% | -10.9% | 85.4% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5, brakes off | +13.4% | 1.05 | 17.7% | 0.76 | 1.87 | 139 | 29% | 4.6 | 0.26 | 12.8% | 18.2% | 2.16 | 2.2%, 2.5% | 63% | 1% | 0 | 5/15 | 3.8% | -13.5% | 82.9% | - | **PASS** | untouched |

Calendar years (out of sample, stitched):

| Cell | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| vt10/30 crash15/90dh ladder, brakes off | +5.4% | -5.7% | +16.2% | +5.3% | +2.6% |
| vt10/30 crash15/90dh ladder, brakes on | +5.1% | -5.5% | +15.8% | +4.9% | +2.2% |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +11.2% | -10.9% | +32.0% | +11.5% | +6.8% |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +10.9% | -10.4% | +31.4% | +10.7% | +6.2% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +14.0% | -13.5% | +39.2% | +15.1% | +6.7% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +13.7% | -13.0% | +38.5% | +14.1% | +5.9% |
| risk1.5 crash15/90dh turtle, brakes off | +8.4% | -6.3% | +24.6% | +10.0% | +4.1% |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +11.2% | -9.4% | +32.5% | +6.8% | +4.5% |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +14.0% | -11.1% | +31.3% | +9.9% | +2.9% |
| vt20/30 crash15/90dh cap2, brakes off | +11.2% | -10.9% | +32.0% | +12.8% | +6.8% |
| vt25/30 crash15/90dh cap2.5, brakes off | +14.0% | -13.5% | +39.2% | +15.5% | +8.5% |

### Brakes (entries only) — trigger counts and cost

| Tier | Entry opportunities | Turtle ladder cut an entry | hard stop blocked | 1/market/day blocked | bar-after-exit blocked | 24 h loss limit blocked | weekly limit blocked | monthly limit blocked | heat cap cut | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| Reference | 165 | 0 | 0 | 9 | 32 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 130 / 139 | 0.60 → 0.54 | +0.06 | no |
| Trader | 165 | 1 | 0 | 9 | 32 | 0 | 0 | 0 | 0 | 0 | 2 / 0 / 0 | 130 / 139 | 0.75 → 0.74 | +0.00 | no |
| Aggressive | 165 | 16 | 0 | 9 | 32 | 0 | 0 | 0 | 0 | 0 | 6 / 0 / 0 | 130 / 139 | 0.73 → 0.72 | +0.01 | no |

The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:

| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |
|---|---|---|---:|---|---|---|
| Trader | +11.1% / 14.5% / 0.77 | +10.8% / 14.5% / 0.75 | +0.02 | no | 127 / 0 | +9.7% / 13.1% / 0.74 / yes |
| Aggressive | +13.4% / 17.7% / 0.76 | +12.9% / 17.7% / 0.73 | +0.03 | no | 423 / 0 | +9.9% / 15.5% / 0.64 / yes |

### Variants (each alone, Trader tier, brakes on) — the size-neutral rule

| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| add | yes | 1.03 → 1.24 | 0.74 → 0.95 (0.95) | +17.2% | 18.1% | 2.29 | 130 | 6.2 | 0.42 | 21 (1.52 / 1.73) | 0 | pass | **yes** |
| scale_out | yes | 1.03 → 0.85 | 0.74 → 0.51 (0.51) | +6.8% | 13.3% | 1.57 | 130 | 3.7 | 0.19 | - | 15 | pass | no |
| conviction | yes | 1.03 → 1.02 | 0.74 → 0.71 (0.71) | +9.2% | 12.9% | 1.83 | 130 | 4.6 | 0.29 | - | 0 | pass | no (too few trades for the pre-registered test (18 high, 112 low; 30 each needed)) |
| trail2 | yes | 1.03 → 0.69 | 0.74 → 0.52 (0.52) | +6.7% | 12.8% | 1.43 | 154 | 3.2 | 0.15 | - | 0 | Sharpe above 0.7 | no |
| trail3 | yes | 1.03 → 0.83 | 0.74 → 0.53 (0.53) | +8.2% | 15.5% | 1.65 | 140 | 3.5 | 0.20 | - | 0 | pass | no |
| wider_stop | yes | 1.03 → 1.00 | 0.74 → 0.63 (0.63) | +7.8% | 12.3% | 1.80 | 126 | 4.5 | 0.17 | - | 0 | pass | no |
| no_time_stop | no: no time stop among the rule's exit brackets | - | - | - | - | - | - | - | - | - | - | - | n/a |

### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)

| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |
|---|---|---|---|
| Reference | +23.4% / +5.0% / 0.54 / 9.3% | +26.8% / +5.7% / 0.56 / 10.1% | +18.7% / +4.1% / 0.37 / 11.0% |
| Trader | +53.4% / +10.4% / 0.74 / 14.1% | +64.3% / +12.2% / 0.90 / 13.6% | +45.9% / +9.2% / 0.59 / 15.4% |
| Aggressive | +65.5% / +12.4% / 0.72 / 17.2% | +80.6% / +14.7% / 0.88 / 16.7% | +56.1% / +10.9% / 0.58 / 18.8% |

## S1 SOL-USDT 6H [none] — **fleet candidate at the Trader tier**

Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; 'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.

| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| vt10/30 crash15/90dh ladder, brakes off | +6.0% | 1.08 | 5.6% | 1.06 | 2.08 | 107 | 40% | 3.1 | 0.12 | 5.5% | 2.6% | 1.00 | 0.9%, 2.4% | - | 0% | 0 | 12/14 | 0.0% | -1.7% | 90.0% | - | **PASS** | +9.5% / PF 5.49 / 12 tr ✓ |
| vt10/30 crash15/90dh ladder, brakes on | +6.3% | 1.15 | 5.5% | 1.15 | 2.25 | 98 | 43% | 3.0 | 0.13 | 5.5% | 2.6% | 0.98 | 1.0%, 2.6% | - | 0% | 0 | 10/13 | 0.0% | -1.6% | 90.0% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +8.8% | 1.09 | 8.4% | 1.04 | 1.99 | 107 | 40% | 3.0 | 0.13 | 8.0% | 4.4% | 1.65 | 1.5%, 2.0% | 31% | 0% | 0 | 12/14 | 0.0% | -3.5% | 96.7% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +9.8% | 1.22 | 8.0% | 1.22 | 2.25 | 98 | 43% | 3.0 | 0.16 | 8.0% | 4.2% | 1.61 | 1.5%, 2.0% | 35% | 0% | 0 | 10/13 | 0.0% | -3.1% | 96.7% | - | **PASS** | +8.5% / PF 3.51 / 11 tr ✓ |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +11.0% | 1.09 | 10.4% | 1.06 | 1.99 | 107 | 40% | 3.0 | 0.13 | 10.0% | 5.4% | 2.07 | 1.9%, 2.5% | 31% | 0% | 0 | 12/14 | 0.0% | -4.3% | 96.7% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +12.4% | 1.22 | 9.9% | 1.24 | 2.25 | 98 | 43% | 3.0 | 0.16 | 9.9% | 5.3% | 2.02 | 1.9%, 2.5% | 35% | 0% | 0 | 10/13 | 0.0% | -3.9% | 96.7% | - | **PASS** | +10.7% / PF 3.51 / 11 tr ✓ |
| risk1.5 crash15/90dh turtle, brakes off | +5.0% | 0.87 | 6.2% | 0.81 | 1.82 | 107 | 41% | 2.6 | 0.12 | 5.9% | 3.2% | 1.21 | 1.0%, 1.5% | - | 0% | 0 | 12/14 | 0.0% | -1.6% | 86.7% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +7.5% | 0.97 | 9.9% | 0.76 | 1.88 | 107 | 40% | 2.8 | 0.13 | 7.8% | 4.1% | 1.58 | 1.4%, 2.0% | 31% | 0% | 0 | 12/14 | 0.0% | -3.5% | 90.0% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +8.8% | 1.00 | 11.2% | 0.79 | 1.89 | 107 | 40% | 2.8 | 0.12 | 8.8% | 4.7% | 1.78 | 1.7%, 2.5% | 31% | 0% | 0 | 12/14 | 0.0% | -4.3% | 93.3% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2, brakes off | +8.8% | 1.09 | 8.4% | 1.04 | 1.99 | 107 | 40% | 3.0 | 0.13 | 8.0% | 4.4% | 1.65 | 1.5%, 2.0% | 31% | 0% | 0 | 12/14 | 0.0% | -3.5% | 96.7% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5, brakes off | +11.0% | 1.09 | 10.4% | 1.06 | 1.99 | 107 | 40% | 3.0 | 0.13 | 10.0% | 5.4% | 2.07 | 1.9%, 2.5% | 31% | 0% | 0 | 12/14 | 0.0% | -4.3% | 96.7% | - | **PASS** | untouched |

Calendar years (out of sample, stitched):

| Cell | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|
| vt10/30 crash15/90dh ladder, brakes off | -1.7% | +18.4% | +0.5% | +4.6% |
| vt10/30 crash15/90dh ladder, brakes on | -1.6% | +18.1% | +0.7% | +5.5% |
| vt20/30 crash15/90dh cap2 turtle, brakes off | -3.5% | +26.9% | -0.3% | +9.4% |
| vt20/30 crash15/90dh cap2 turtle, brakes on | -3.1% | +27.9% | +0.7% | +10.8% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | -4.3% | +34.4% | -0.4% | +11.8% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | -3.9% | +35.8% | +0.8% | +13.6% |
| risk1.5 crash15/90dh turtle, brakes off | -1.6% | +12.8% | -0.2% | +7.0% |
| vt20/30 crash15/90dh cap2 ladder, brakes off | -3.5% | +26.9% | -2.1% | +7.1% |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | -4.3% | +34.4% | -1.6% | +5.8% |
| vt20/30 crash15/90dh cap2, brakes off | -3.5% | +26.9% | -0.3% | +9.4% |
| vt25/30 crash15/90dh cap2.5, brakes off | -4.3% | +34.4% | -0.4% | +11.8% |

### Brakes (entries only) — trigger counts and cost

| Tier | Entry opportunities | Turtle ladder cut an entry | hard stop blocked | 1/market/day blocked | bar-after-exit blocked | 24 h loss limit blocked | weekly limit blocked | monthly limit blocked | heat cap cut | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| Reference | 131 | 0 | 0 | 6 | 31 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 98 / 107 | 1.06 → 1.15 | -0.09 | no |
| Trader | 131 | 0 | 0 | 6 | 31 | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 | 98 / 107 | 1.04 → 1.22 | -0.18 | no |
| Aggressive | 131 | 0 | 0 | 6 | 31 | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 | 98 / 107 | 1.06 → 1.24 | -0.19 | no |

The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:

| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |
|---|---|---|---:|---|---|---|
| Trader | +8.8% / 8.4% / 1.04 | +8.8% / 8.4% / 1.04 | +0.00 | no | 0 / 0 | +7.5% / 9.9% / 0.76 / yes |
| Aggressive | +11.0% / 10.4% / 1.06 | +11.0% / 10.4% / 1.06 | +0.00 | no | 0 / 0 | +8.8% / 11.2% / 0.79 / yes |

### Variants (each alone, Trader tier, brakes on) — the size-neutral rule

| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| add | yes | 1.22 → 1.12 | 1.22 → 1.05 (1.05) | +11.8% | 11.2% | 2.40 | 98 | 3.2 | 0.19 | 22 (1.16 / 1.82) | 0 | pass | no |
| scale_out | yes | 1.22 → 1.57 | 1.22 → 1.96 (1.96) | +11.8% | 6.0% | 2.51 | 98 | 3.1 | 0.21 | - | 16 | pass | **yes** |
| conviction | yes | 1.22 → 1.28 | 1.22 → 1.41 (1.41) | +9.2% | 6.5% | 2.40 | 98 | 3.2 | 0.16 | - | 0 | pass | no (too few trades for the pre-registered test (17 high, 81 low; 30 each needed)) |
| trail2 | yes | 1.22 → 1.05 | 1.22 → 0.83 (0.83) | +8.8% | 10.6% | 1.87 | 105 | 2.8 | 0.14 | - | 0 | pass | no |
| trail3 | yes | 1.22 → 1.15 | 1.22 → 1.09 (1.09) | +9.6% | 8.8% | 2.13 | 97 | 2.9 | 0.17 | - | 0 | pass | no |
| wider_stop | yes | 1.22 → 1.18 | 1.22 → 1.11 (1.11) | +7.5% | 6.8% | 2.32 | 96 | 3.2 | 0.13 | - | 0 | pass | no |
| no_time_stop | yes | 1.22 → 1.22 | 1.22 → 1.22 (1.22) | +9.8% | 8.0% | 2.25 | 98 | 3.0 | 0.16 | - | 0 | pass | **yes** |

### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)

| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |
|---|---|---|---|
| Reference | +23.5% / +6.3% / 1.15 / 5.5% | +19.8% / +5.4% / 0.98 / 5.5% | +17.0% / +4.6% / 0.78 / 6.0% |
| Trader | +38.3% / +9.8% / 1.22 / 8.0% | +31.4% / +8.2% / 1.23 / 6.7% | +26.8% / +7.1% / 0.94 / 7.6% |
| Aggressive | +49.5% / +12.4% / 1.24 / 9.9% | +40.0% / +10.2% / 1.24 / 8.3% | +33.9% / +8.8% / 0.94 / 9.4% |

## S1+S5 SOL-USDT 6H [none] — **fleet candidate at the Trader tier**

Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; 'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.

| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| vt10/30 crash15/90dh ladder, brakes off | +7.5% | 1.32 | 5.4% | 1.40 | 2.68 | 101 | 39% | 4.3 | 0.24 | 5.6% | 2.6% | 1.00 | 1.0%, 2.4% | - | 0% | 0 | 1/3 | 0.0% | -1.7% | 90.0% | - | **PASS** | +9.5% / PF 5.49 / 12 tr ✓ |
| vt10/30 crash15/90dh ladder, brakes on | +7.3% | 1.27 | 5.4% | 1.36 | 2.60 | 95 | 41% | 3.7 | 0.21 | 5.7% | 2.6% | 0.99 | 1.0%, 2.4% | - | 0% | 0 | 2/4 | 0.0% | -1.6% | 90.0% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +14.3% | 1.45 | 10.0% | 1.43 | 2.95 | 101 | 38% | 4.9 | 0.25 | 9.5% | 4.3% | 1.65 | 1.5%, 2.0% | 33% | 0% | 0 | 1/3 | 0.0% | -3.5% | 96.7% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +13.6% | 1.39 | 9.8% | 1.39 | 2.78 | 95 | 40% | 4.2 | 0.23 | 9.5% | 4.2% | 1.63 | 1.6%, 2.0% | 34% | 0% | 0 | 2/4 | 0.0% | -3.1% | 96.7% | - | **PASS** | +8.5% / PF 3.51 / 11 tr ✓ |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +17.9% | 1.46 | 12.2% | 1.46 | 2.95 | 101 | 38% | 4.9 | 0.25 | 11.8% | 5.4% | 2.07 | 1.9%, 2.5% | 33% | 0% | 0 | 1/3 | 0.0% | -4.3% | 96.7% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +17.0% | 1.39 | 11.9% | 1.43 | 2.77 | 95 | 40% | 4.2 | 0.23 | 11.8% | 5.3% | 2.03 | 1.9%, 2.5% | 34% | 0% | 0 | 1/4 | 0.0% | -3.9% | 96.7% | - | **PASS** | +10.7% / PF 3.51 / 11 tr ✓ |
| risk1.5 crash15/90dh turtle, brakes off | +10.1% | 1.34 | 7.1% | 1.43 | 2.92 | 101 | 39% | 4.6 | 0.25 | 7.4% | 3.1% | 1.21 | 1.1%, 1.5% | - | 0% | 0 | 1/3 | 0.0% | -1.6% | 86.7% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +13.6% | 1.45 | 8.4% | 1.61 | 2.96 | 101 | 38% | 4.9 | 0.25 | 9.1% | 4.1% | 1.58 | 1.5%, 2.0% | 33% | 0% | 0 | 1/3 | 0.0% | -3.5% | 96.7% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +15.6% | 1.42 | 9.5% | 1.65 | 2.87 | 101 | 38% | 4.8 | 0.25 | 10.6% | 4.7% | 1.81 | 1.7%, 2.5% | 33% | 0% | 0 | 1/3 | 0.0% | -4.3% | 96.7% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2, brakes off | +14.3% | 1.45 | 10.0% | 1.43 | 2.95 | 101 | 38% | 4.9 | 0.25 | 9.5% | 4.3% | 1.65 | 1.5%, 2.0% | 33% | 0% | 0 | 1/3 | 0.0% | -3.5% | 96.7% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5, brakes off | +17.9% | 1.46 | 12.2% | 1.46 | 2.95 | 101 | 38% | 4.9 | 0.25 | 11.8% | 5.4% | 2.07 | 1.9%, 2.5% | 33% | 0% | 0 | 1/3 | 0.0% | -4.3% | 96.7% | - | **PASS** | untouched |

Calendar years (out of sample, stitched):

| Cell | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|
| vt10/30 crash15/90dh ladder, brakes off | -1.7% | +21.6% | +2.5% | +4.8% |
| vt10/30 crash15/90dh ladder, brakes on | -1.6% | +20.1% | +2.2% | +5.5% |
| vt20/30 crash15/90dh cap2 turtle, brakes off | -3.5% | +48.7% | +2.6% | +7.6% |
| vt20/30 crash15/90dh cap2 turtle, brakes on | -3.1% | +47.1% | +1.7% | +7.2% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | -4.3% | +63.1% | +3.2% | +9.5% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | -3.9% | +61.0% | +1.8% | +9.1% |
| risk1.5 crash15/90dh turtle, brakes off | -1.6% | +34.7% | +1.5% | +3.7% |
| vt20/30 crash15/90dh cap2 ladder, brakes off | -3.5% | +48.7% | +0.4% | +7.6% |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | -4.3% | +58.6% | +1.5% | +7.0% |
| vt20/30 crash15/90dh cap2, brakes off | -3.5% | +48.7% | +2.6% | +7.6% |
| vt25/30 crash15/90dh cap2.5, brakes off | -4.3% | +63.1% | +3.2% | +9.5% |

### Brakes (entries only) — trigger counts and cost

| Tier | Entry opportunities | Turtle ladder cut an entry | hard stop blocked | 1/market/day blocked | bar-after-exit blocked | 24 h loss limit blocked | weekly limit blocked | monthly limit blocked | heat cap cut | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| Reference | 119 | 0 | 0 | 4 | 23 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 95 / 101 | 1.40 → 1.36 | +0.03 | no |
| Trader | 119 | 0 | 0 | 4 | 23 | 0 | 0 | 0 | 0 | 0 | 3 / 0 / 0 | 95 / 101 | 1.43 → 1.39 | +0.04 | no |
| Aggressive | 122 | 0 | 0 | 4 | 23 | 4 | 0 | 0 | 0 | 0 | 4 / 0 / 0 | 95 / 101 | 1.46 → 1.43 | +0.04 | no |

The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:

| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |
|---|---|---|---:|---|---|---|
| Trader | +14.3% / 10.0% / 1.43 | +14.3% / 10.0% / 1.43 | +0.00 | no | 0 / 0 | +13.6% / 8.4% / 1.61 / yes |
| Aggressive | +17.9% / 12.2% / 1.46 | +17.9% / 12.2% / 1.46 | +0.00 | no | 0 / 0 | +15.6% / 9.5% / 1.65 / yes |

### Variants (each alone, Trader tier, brakes on) — the size-neutral rule

| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| add | yes | 1.39 → 1.24 | 1.39 → 1.21 (1.21) | +15.5% | 12.8% | 2.97 | 95 | 4.5 | 0.26 | 21 (1.55 / 1.82) | 0 | pass | no |
| scale_out | yes | 1.39 → 1.58 | 1.39 → 2.22 (2.22) | +13.4% | 6.0% | 2.76 | 95 | 3.8 | 0.25 | - | 15 | pass | **yes** |
| conviction | yes | 1.39 → 1.36 | 1.39 → 1.41 (1.41) | +10.9% | 7.7% | 2.73 | 95 | 4.1 | 0.22 | - | 0 | pass | no (too few trades for the pre-registered test (11 high, 84 low; 30 each needed)) |
| trail2 | yes | 1.39 → 1.23 | 1.39 → 1.00 (1.00) | +11.5% | 11.6% | 2.17 | 111 | 3.6 | 0.18 | - | 0 | pass | no |
| trail3 | yes | 1.39 → 1.23 | 1.39 → 1.04 (1.04) | +11.9% | 11.5% | 2.33 | 103 | 3.5 | 0.20 | - | 0 | pass | no |
| wider_stop | yes | 1.39 → 1.35 | 1.39 → 1.24 (1.24) | +9.2% | 7.4% | 2.68 | 93 | 3.9 | 0.16 | - | 0 | pass | no |
| no_time_stop | no: no time stop among the rule's exit brackets | - | - | - | - | - | - | - | - | - | - | - | n/a |

### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)

| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |
|---|---|---|---|
| Reference | +27.5% / +7.3% / 1.36 / 5.4% | +22.8% / +6.1% / 1.08 / 5.7% | +20.0% / +5.4% / 0.90 / 6.0% |
| Trader | +55.4% / +13.6% / 1.39 / 9.8% | +34.5% / +9.0% / 1.42 / 6.3% | +29.9% / +7.9% / 1.16 / 6.8% |
| Aggressive | +71.7% / +17.0% / 1.43 / 11.9% | +44.1% / +11.2% / 1.43 / 7.8% | +38.0% / +9.8% / 1.16 / 8.4% |

## S1+VC BTC-USDT 4H [gate] — **fleet candidate at the Trader tier**

Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; 'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.

| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| vt10/30 crash15/90dh ladder, brakes off | +4.3% | 0.71 | 7.8% | 0.55 | 1.72 | 83 | 30% | 4.0 | 0.20 | 6.3% | 8.7% | 1.00 | 0.8%, 2.3% | - | 0% | 0 | 21/27 | 0.0% | -1.5% | 82.9% | - | **PASS** | +2.0% / PF 1.41 / 25 tr ✓ |
| vt10/30 crash15/90dh ladder, brakes on | +3.9% | 0.67 | 7.7% | 0.51 | 1.73 | 77 | 32% | 3.6 | 0.26 | 6.0% | 8.2% | 0.95 | 0.8%, 2.1% | - | 0% | 0 | 16/22 | 0.0% | -1.1% | 85.4% | Sharpe above 0.7 | fail | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +7.6% | 0.75 | 13.8% | 0.55 | 1.69 | 83 | 31% | 3.7 | 0.20 | 10.6% | 15.2% | 1.76 | 1.4%, 2.0% | 31% | 1% | 0 | 21/27 | 0.2% | -3.0% | 78.0% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +8.0% | 0.79 | 13.8% | 0.58 | 1.80 | 77 | 34% | 3.5 | 0.26 | 10.5% | 15.1% | 1.74 | 1.4%, 2.0% | 32% | 1% | 0 | 16/22 | 0.1% | -2.2% | 87.8% | - | **PASS** | +2.0% / PF 1.19 / 27 tr ✓ |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +7.9% | 0.66 | 16.6% | 0.48 | 1.59 | 83 | 30% | 3.7 | 0.21 | 12.8% | 18.5% | 2.14 | 1.7%, 2.5% | 31% | 2% | 0 | 21/27 | 2.0% | -3.7% | 78.0% | Sharpe above 0.7, Calmar above 0.5 | fail | untouched |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +8.8% | 0.73 | 16.1% | 0.55 | 1.71 | 77 | 32% | 3.6 | 0.25 | 12.7% | 18.5% | 2.13 | 1.7%, 2.5% | 32% | 3% | 0 | 14/22 | 0.7% | -2.7% | 87.8% | - | **PASS** | +0.1% / PF 1.01 / 27 tr ✓ |
| risk1.5 crash15/90dh turtle, brakes off | +6.2% | 0.66 | 11.5% | 0.54 | 1.63 | 83 | 31% | 3.6 | 0.22 | 9.9% | 13.3% | 1.54 | 1.3%, 1.5% | - | 0% | 0 | 21/27 | 0.1% | -4.2% | 87.8% | Sharpe above 0.7 | fail | untouched |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +6.2% | 0.69 | 10.1% | 0.61 | 1.69 | 83 | 31% | 3.7 | 0.21 | 9.2% | 13.0% | 1.50 | 1.2%, 2.0% | 31% | 1% | 0 | 21/27 | 0.0% | -3.0% | 78.0% | Sharpe above 0.7 | fail | untouched |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +5.4% | 0.56 | 10.1% | 0.53 | 1.53 | 83 | 31% | 3.3 | 0.20 | 10.4% | 14.5% | 1.67 | 1.4%, 2.5% | 31% | 0% | 0 | 21/27 | 0.4% | -3.6% | 73.2% | Sharpe above 0.7, 75% of rolling 12-month windows positive | fail | untouched |
| vt20/30 crash15/90dh cap2, brakes off | +7.6% | 0.75 | 13.8% | 0.55 | 1.69 | 83 | 31% | 3.7 | 0.20 | 10.6% | 15.2% | 1.76 | 1.4%, 2.0% | 31% | 1% | 0 | 21/27 | 0.2% | -3.0% | 78.0% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5, brakes off | +8.9% | 0.72 | 16.7% | 0.53 | 1.66 | 83 | 31% | 3.6 | 0.20 | 13.1% | 19.0% | 2.19 | 1.8%, 2.5% | 31% | 4% | 0 | 21/27 | 1.6% | -3.7% | 78.0% | - | **PASS** | untouched |

Calendar years (out of sample, stitched):

| Cell | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| vt10/30 crash15/90dh ladder, brakes off | +0.6% | -1.5% | +7.2% | +9.9% | +3.0% |
| vt10/30 crash15/90dh ladder, brakes on | +1.4% | -1.1% | +8.1% | +5.9% | +2.9% |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +1.0% | -3.0% | +14.3% | +17.0% | +5.1% |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +2.7% | -2.2% | +14.4% | +16.1% | +4.9% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +1.2% | -3.7% | +16.1% | +18.4% | +4.0% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +3.3% | -2.7% | +19.4% | +17.7% | +2.1% |
| risk1.5 crash15/90dh turtle, brakes off | +2.7% | -4.2% | +12.4% | +12.6% | +4.4% |
| vt20/30 crash15/90dh cap2 ladder, brakes off | -1.1% | -3.0% | +13.1% | +11.9% | +6.7% |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | -0.4% | -3.6% | +13.5% | +15.7% | -0.4% |
| vt20/30 crash15/90dh cap2, brakes off | +1.0% | -3.0% | +14.3% | +17.0% | +5.1% |
| vt25/30 crash15/90dh cap2.5, brakes off | +1.2% | -3.7% | +18.1% | +21.1% | +4.0% |

### Brakes (entries only) — trigger counts and cost

| Tier | Entry opportunities | Turtle ladder cut an entry | hard stop blocked | 1/market/day blocked | bar-after-exit blocked | 24 h loss limit blocked | weekly limit blocked | monthly limit blocked | heat cap cut | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| Reference | 100 | 0 | 0 | 3 | 21 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 77 / 83 | 0.55 → 0.51 | +0.04 | no |
| Trader | 100 | 6 | 0 | 3 | 21 | 1 | 0 | 0 | 0 | 0 | 2 / 0 / 0 | 77 / 83 | 0.55 → 0.58 | -0.03 | no |
| Aggressive | 112 | 22 | 0 | 3 | 21 | 13 | 0 | 0 | 0 | 0 | 8 / 1 / 0 | 77 / 83 | 0.48 → 0.55 | -0.07 | no |

The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:

| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |
|---|---|---|---:|---|---|---|
| Trader | +7.6% / 13.8% / 0.55 | +7.6% / 13.8% / 0.55 | +0.00 | no | 0 / 0 | +6.2% / 10.1% / 0.61 / no |
| Aggressive | +8.9% / 16.7% / 0.53 | +7.9% / 16.6% / 0.48 | +0.06 | no | 877 / 0 | +5.4% / 10.1% / 0.53 / no |

### Variants (each alone, Trader tier, brakes on) — the size-neutral rule

| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| add | yes | 0.79 → 0.76 | 0.58 → 0.68 (0.68) | +9.5% | 14.0% | 1.80 | 77 | 4.2 | 0.32 | 30 (1.54 / 1.91) | 0 | pass | no |
| scale_out | yes | 0.79 → 0.84 | 0.58 → 0.54 (0.54) | +7.2% | 13.4% | 1.76 | 77 | 2.9 | 0.25 | - | 22 | pass | no |
| conviction | no: the volume condition is this rule's entry condition; plain S1 is its comparison | - | - | - | - | - | - | - | - | - | - | - | n/a |
| trail2 | yes | 0.79 → 0.72 | 0.58 → 0.63 (0.63) | +7.5% | 11.9% | 1.46 | 117 | 2.8 | 0.15 | - | 0 | pass | no |
| trail3 | yes | 0.79 → 0.78 | 0.58 → 0.55 (0.55) | +8.2% | 14.8% | 1.65 | 94 | 3.0 | 0.22 | - | 0 | pass | no |
| wider_stop | yes | 0.79 → 0.70 | 0.58 → 0.42 (0.42) | +5.7% | 13.4% | 1.65 | 70 | 3.0 | 0.21 | - | 0 | Calmar above 0.5 | no |
| no_time_stop | yes | 0.79 → 0.88 | 0.58 → 0.78 (0.78) | +8.9% | 11.4% | 2.04 | 72 | 4.1 | 0.30 | - | 0 | pass | **yes** |

### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)

| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |
|---|---|---|---|
| Reference | +18.1% / +3.9% / 0.51 / 7.7% | +13.6% / +3.0% / 0.47 / 6.3% | +7.3% / +1.6% / 0.21 / 7.7% |
| Trader | +40.0% / +8.0% / 0.58 / 13.8% | +39.6% / +8.0% / 0.66 / 12.1% | +25.4% / +5.3% / 0.37 / 14.3% |
| Aggressive | +44.3% / +8.8% / 0.55 / 16.1% | +48.5% / +9.5% / 0.64 / 14.8% | +26.4% / +5.5% / 0.34 / 16.3% |

## S1+VC DOGE-USDT 4H [gate] — **fleet candidate at the Trader tier**

Every cell is the same rule and the same walk-forward selection; only the size of the trades changes. Risk/trade is the money at the initial stop over the equity at entry; 'cap binds' is the share of entries at which the per-trade cap, not the volatility target, set the size; 'all-in' the share of entries that put 100 % of the account in; gaps are stop-loss exits filled below the stop; re-entries are the rule's own re-entries within two bars of a stop-out (counted, not changed); P(DD ≥ 30 %) is the bootstrap share of trade-order paths that touch the hard stop.

| Cell | CAGR | Sharpe | Max DD | Calmar | PF | Trades | Win | Avg win/avg loss | Expectancy (R) | Realized vol | Avg allocation | x Reference | Risk/trade (mean, max) | Cap binds | All-in | Gaps | Re-entries <= 2 bars | P(DD >= 30 %) | Worst year | Rolling 12 m + | Gates missed | Verdict | Holdout (12 m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| vt10/30 crash15/90dh ladder, brakes off | +4.0% | 0.88 | 4.8% | 0.83 | 2.24 | 67 | 43% | 2.9 | 0.25 | 4.6% | 1.7% | 1.00 | 0.7%, 1.9% | - | 0% | 0 | 21/27 | 0.0% | -0.8% | 85.7% | - | **PASS** | +1.8% / PF 1.65 / 18 tr ✓ |
| vt10/30 crash15/90dh ladder, brakes on | +3.5% | 0.79 | 4.8% | 0.73 | 2.07 | 68 | 44% | 2.6 | 0.22 | 4.5% | 1.6% | 0.98 | 0.7%, 1.9% | - | 0% | 0 | 22/27 | 0.0% | -0.9% | 81.0% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes off | +7.2% | 0.91 | 9.3% | 0.77 | 2.25 | 67 | 43% | 3.0 | 0.27 | 8.0% | 3.1% | 1.86 | 1.2%, 2.0% | 22% | 0% | 0 | 21/27 | 0.0% | -1.6% | 83.3% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 turtle, brakes on | +6.3% | 0.81 | 9.4% | 0.67 | 2.04 | 68 | 43% | 2.7 | 0.23 | 7.9% | 3.0% | 1.82 | 1.2%, 2.0% | 21% | 0% | 0 | 22/27 | 0.0% | -1.8% | 81.0% | - | **PASS** | +1.3% / PF 1.23 / 16 tr ✓ |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | +9.0% | 0.92 | 11.5% | 0.78 | 2.25 | 67 | 43% | 3.0 | 0.27 | 9.9% | 3.9% | 2.33 | 1.6%, 2.5% | 22% | 0% | 0 | 21/27 | 0.0% | -1.9% | 83.3% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | +7.9% | 0.82 | 11.6% | 0.68 | 2.04 | 68 | 43% | 2.7 | 0.23 | 9.8% | 3.8% | 2.28 | 1.5%, 2.5% | 21% | 0% | 0 | 22/27 | 0.0% | -2.2% | 81.0% | - | **PASS** | +1.5% / PF 1.22 / 16 tr ✓ |
| risk1.5 crash15/90dh turtle, brakes off | +5.0% | 0.79 | 8.8% | 0.56 | 2.00 | 67 | 42% | 2.8 | 0.26 | 6.4% | 2.3% | 1.39 | 1.0%, 1.5% | - | 0% | 0 | 21/27 | 0.0% | -1.7% | 78.6% | - | **PASS** | untouched |
| vt20/30 crash15/90dh cap2 ladder, brakes off | +7.3% | 0.93 | 9.3% | 0.79 | 2.31 | 67 | 43% | 3.0 | 0.27 | 7.9% | 3.0% | 1.81 | 1.2%, 2.0% | 22% | 0% | 0 | 21/27 | 0.0% | -1.6% | 83.3% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | +5.9% | 0.70 | 11.5% | 0.52 | 1.87 | 67 | 43% | 2.4 | 0.19 | 8.8% | 3.4% | 2.05 | 1.5%, 2.5% | 22% | 0% | 0 | 21/27 | 0.0% | -5.7% | 59.5% | Sharpe above 0.7, 75% of rolling 12-month windows positive | fail | untouched |
| vt20/30 crash15/90dh cap2, brakes off | +7.2% | 0.91 | 9.3% | 0.77 | 2.25 | 67 | 43% | 3.0 | 0.27 | 8.0% | 3.1% | 1.86 | 1.2%, 2.0% | 22% | 0% | 0 | 21/27 | 0.0% | -1.6% | 83.3% | - | **PASS** | untouched |
| vt25/30 crash15/90dh cap2.5, brakes off | +9.0% | 0.92 | 11.5% | 0.78 | 2.25 | 67 | 43% | 3.0 | 0.27 | 9.9% | 3.9% | 2.33 | 1.6%, 2.5% | 22% | 0% | 0 | 21/27 | 0.0% | -1.9% | 83.3% | - | **PASS** | untouched |

Calendar years (out of sample, stitched):

| Cell | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| vt10/30 crash15/90dh ladder, brakes off | -0.8% | +0.4% | +1.9% | +13.7% | +2.8% |
| vt10/30 crash15/90dh ladder, brakes on | -0.9% | +0.5% | +1.1% | +12.3% | +2.8% |
| vt20/30 crash15/90dh cap2 turtle, brakes off | -1.6% | +0.7% | +2.8% | +24.6% | +6.9% |
| vt20/30 crash15/90dh cap2 turtle, brakes on | -1.8% | +0.9% | +1.3% | +21.8% | +6.9% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes off | -1.9% | +0.8% | +3.6% | +31.4% | +8.7% |
| vt25/30 crash15/90dh cap2.5 turtle, brakes on | -2.2% | +1.0% | +1.7% | +27.8% | +8.6% |
| risk1.5 crash15/90dh turtle, brakes off | -1.2% | -1.7% | +1.5% | +24.4% | +1.0% |
| vt20/30 crash15/90dh cap2 ladder, brakes off | -1.6% | +0.7% | +2.8% | +24.6% | +7.6% |
| vt25/30 crash15/90dh cap2.5 ladder, brakes off | -1.9% | -5.7% | +3.6% | +30.8% | +2.9% |
| vt20/30 crash15/90dh cap2, brakes off | -1.6% | +0.7% | +2.8% | +24.6% | +6.9% |
| vt25/30 crash15/90dh cap2.5, brakes off | -1.9% | +0.8% | +3.6% | +31.4% | +8.7% |

### Brakes (entries only) — trigger counts and cost

| Tier | Entry opportunities | Turtle ladder cut an entry | hard stop blocked | 1/market/day blocked | bar-after-exit blocked | 24 h loss limit blocked | weekly limit blocked | monthly limit blocked | heat cap cut | Hard-stop trips | 24 h / week / month trips | Trades on / off | Calmar off → on | Cost (Calmar) | Flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| Reference | 92 | 0 | 0 | 4 | 24 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 68 / 67 | 0.83 → 0.73 | +0.10 | yes |
| Trader | 92 | 0 | 0 | 4 | 24 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 68 / 67 | 0.77 → 0.67 | +0.10 | no |
| Aggressive | 92 | 0 | 0 | 4 | 24 | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 | 68 / 67 | 0.78 → 0.68 | +0.10 | yes |

The Turtle ladder's cost beside the same tier with no ladder, and the higher tier under the Reference ladder (which reduces open positions) instead:

| Tier | No ladder: CAGR / max DD / Calmar | Turtle ladder: CAGR / max DD / Calmar | Ladder cost (Calmar) | Flagged | Bars at x0.8 / x0.64 | Reference ladder instead: CAGR / max DD / Calmar / passes |
|---|---|---|---:|---|---|---|
| Trader | +7.2% / 9.3% / 0.77 | +7.2% / 9.3% / 0.77 | +0.00 | no | 0 / 0 | +7.3% / 9.3% / 0.79 / yes |
| Aggressive | +9.0% / 11.5% / 0.78 | +9.0% / 11.5% / 0.78 | +0.00 | no | 0 / 0 | +5.9% / 11.5% / 0.52 / no |

### Variants (each alone, Trader tier, brakes on) — the size-neutral rule

| Variant | Applies | Sharpe base → variant | Calmar base → variant (vol-matched) | CAGR | Max DD | PF | Trades | Avg win/avg loss | Expectancy (R) | Adds (worst case R mean / max) | Scale-outs | Gates | Counts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| add | yes | 0.81 → 0.75 | 0.67 → 0.71 (0.71) | +7.2% | 10.1% | 2.08 | 68 | 3.4 | 0.27 | 21 (1.11 / 1.83) | 0 | pass | no |
| scale_out | yes | 0.81 → 0.72 | 0.67 → 0.56 (0.56) | +4.8% | 8.5% | 1.80 | 68 | 2.3 | 0.16 | - | 12 | 75% of rolling 12-month windows positive | no |
| conviction | no: the volume condition is this rule's entry condition; plain S1 is its comparison | - | - | - | - | - | - | - | - | - | - | - | n/a |
| trail2 | yes | 0.81 → 0.60 | 0.67 → 0.47 (0.47) | +4.4% | 9.2% | 1.46 | 91 | 2.5 | 0.10 | - | 0 | Sharpe above 0.7, Calmar above 0.5 | no |
| trail3 | yes | 0.81 → 0.76 | 0.67 → 0.58 (0.58) | +5.6% | 9.8% | 1.68 | 78 | 3.2 | 0.17 | - | 0 | pass | no |
| wider_stop | yes | 0.81 → 0.85 | 0.67 → 0.72 (0.72) | +5.7% | 8.0% | 2.37 | 55 | 2.8 | 0.25 | - | 0 | pass | **yes** |
| no_time_stop | yes | 0.81 → 0.82 | 0.67 → 0.68 (0.68) | +6.3% | 9.4% | 2.05 | 66 | 3.0 | 0.29 | - | 0 | pass | **yes** |

### Costs — the selected rule replayed at other fee + slippage pairs (same windows, same sizing, brakes on)

| Tier | 0.30 % a round trip (gate cost): return / CAGR / Calmar / max DD | 0.20 % (measured BTC/ETH): return / CAGR / Calmar / max DD | 0.50 % (altcoins): return / CAGR / Calmar / max DD |
|---|---|---|---|
| Reference | +16.3% / +3.5% / 0.73 / 4.8% | +15.9% / +3.4% / 0.70 / 4.9% | +13.8% / +3.0% / 0.59 / 5.0% |
| Trader | +30.8% / +6.3% / 0.67 / 9.4% | +32.9% / +6.7% / 0.74 / 9.0% | +28.3% / +5.8% / 0.62 / 9.4% |
| Aggressive | +39.4% / +7.9% / 0.68 / 11.6% | +41.9% / +8.3% / 0.76 / 10.9% | +35.8% / +7.2% / 0.63 / 11.4% |

## Controls — hold + policy sizing at each tier, and the slow-trend forward control

The hold controls have no stop, so the per-trade cap cannot act on them: at the higher tiers they are the volatility target alone with the Turtle ladder on entries. TF (long above the 200-day average, policy sizing) ran as a fixed rule (no exit bracket, no 20-train-trade qualification; a recorded protocol deviation): it is the forward control of plan row R18b, never judged.

| Control | Cell | CAGR | Sharpe | Max DD | Calmar | Trades | Realized vol | Avg allocation | Worst year | Holdout (12 m) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| hold BTC-USDT 4H | vt10/30 crash15/90dh ladder, brakes off | +3.2% | 0.59 | 7.2% | 0.45 | 9 | 5.6% | 9.6% | -4.7% | -4.3% / PF 0.00 / 1 tr ✗ |
| hold BTC-USDT 4H | vt10/30 crash15/90dh ladder, brakes on | +3.2% | 0.59 | 7.2% | 0.45 | 9 | 5.6% | 9.6% | -4.7% | untouched |
| hold BTC-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes off | +6.9% | 0.66 | 14.0% | 0.49 | 9 | 10.9% | 19.6% | -9.2% | untouched |
| hold BTC-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes on | +6.9% | 0.66 | 14.0% | 0.49 | 9 | 10.9% | 19.6% | -9.2% | -7.5% / PF 0.00 / 1 tr ✗ |
| hold BTC-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +8.4% | 0.67 | 17.2% | 0.49 | 9 | 13.5% | 24.5% | -11.5% | untouched |
| hold BTC-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +8.4% | 0.67 | 17.2% | 0.49 | 9 | 13.5% | 24.5% | -11.5% | -9.4% / PF 0.00 / 1 tr ✗ |
| hold BTC-USDT 6H | vt10/30 crash15/90dh ladder, brakes off | +2.6% | 0.49 | 8.0% | 0.33 | 9 | 5.7% | 9.8% | -4.8% | -4.0% / PF 0.00 / 1 tr ✗ |
| hold BTC-USDT 6H | vt10/30 crash15/90dh ladder, brakes on | +2.6% | 0.49 | 8.0% | 0.33 | 9 | 5.7% | 9.8% | -4.8% | untouched |
| hold BTC-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes off | +6.0% | 0.57 | 15.3% | 0.39 | 9 | 11.2% | 20.3% | -9.4% | untouched |
| hold BTC-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes on | +6.0% | 0.57 | 15.3% | 0.39 | 9 | 11.2% | 20.3% | -9.4% | -7.7% / PF 0.00 / 1 tr ✗ |
| hold BTC-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +7.3% | 0.58 | 18.8% | 0.39 | 9 | 13.9% | 25.4% | -11.8% | untouched |
| hold BTC-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +7.3% | 0.58 | 18.8% | 0.39 | 9 | 13.9% | 25.4% | -11.8% | -9.6% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 4H | vt10/30 crash15/90dh ladder, brakes off | +1.8% | 0.38 | 8.6% | 0.20 | 9 | 4.9% | 6.2% | -4.1% | -2.6% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 4H | vt10/30 crash15/90dh ladder, brakes on | +1.8% | 0.38 | 8.6% | 0.20 | 9 | 4.9% | 6.2% | -4.1% | untouched |
| hold ETH-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes off | +3.7% | 0.42 | 14.8% | 0.25 | 9 | 9.7% | 12.9% | -8.1% | untouched |
| hold ETH-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes on | +3.7% | 0.42 | 14.8% | 0.25 | 9 | 9.7% | 12.9% | -8.1% | -5.3% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +4.5% | 0.43 | 18.1% | 0.25 | 9 | 12.0% | 16.1% | -10.0% | untouched |
| hold ETH-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +4.5% | 0.43 | 18.1% | 0.25 | 9 | 12.0% | 16.1% | -10.0% | -6.6% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 6H | vt10/30 crash15/90dh ladder, brakes off | +2.5% | 0.50 | 9.6% | 0.26 | 9 | 5.2% | 6.5% | -3.5% | -2.9% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 6H | vt10/30 crash15/90dh ladder, brakes on | +2.5% | 0.50 | 9.6% | 0.26 | 9 | 5.2% | 6.5% | -3.5% | untouched |
| hold ETH-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes off | +5.1% | 0.55 | 16.5% | 0.31 | 9 | 10.1% | 13.3% | -7.0% | untouched |
| hold ETH-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes on | +5.1% | 0.55 | 16.5% | 0.31 | 9 | 10.1% | 13.3% | -7.0% | -5.8% / PF 0.00 / 1 tr ✗ |
| hold ETH-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +6.3% | 0.55 | 20.1% | 0.31 | 9 | 12.5% | 16.6% | -8.8% | untouched |
| hold ETH-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +6.3% | 0.55 | 20.1% | 0.31 | 9 | 12.5% | 16.6% | -8.8% | -7.3% / PF 0.00 / 1 tr ✗ |
| hold SOL-USDT 6H | vt10/30 crash15/90dh ladder, brakes off | +7.5% | 1.13 | 7.0% | 1.08 | 7 | 6.6% | 3.9% | -5.0% | -2.5% / PF 0.00 / 1 tr ✗ |
| hold SOL-USDT 6H | vt10/30 crash15/90dh ladder, brakes on | +7.5% | 1.13 | 7.0% | 1.08 | 7 | 6.6% | 3.9% | -5.0% | untouched |
| hold SOL-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes off | +13.6% | 1.13 | 13.6% | 1.00 | 7 | 11.9% | 7.8% | -10.0% | untouched |
| hold SOL-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes on | +13.6% | 1.13 | 13.6% | 1.00 | 7 | 11.9% | 7.8% | -10.0% | -5.1% / PF 0.00 / 1 tr ✗ |
| hold SOL-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +16.2% | 1.12 | 16.8% | 0.96 | 7 | 14.3% | 9.7% | -12.4% | untouched |
| hold SOL-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +16.2% | 1.12 | 16.8% | 0.96 | 7 | 14.3% | 9.7% | -12.4% | -6.3% / PF 0.00 / 1 tr ✗ |
| hold DOGE-USDT 4H | vt10/30 crash15/90dh ladder, brakes off | +0.7% | 0.19 | 6.9% | 0.10 | 9 | 4.0% | 3.3% | -2.5% | -2.7% / PF 0.00 / 1 tr ✗ |
| hold DOGE-USDT 4H | vt10/30 crash15/90dh ladder, brakes on | +0.7% | 0.19 | 6.9% | 0.10 | 9 | 4.0% | 3.3% | -2.5% | untouched |
| hold DOGE-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes off | +1.3% | 0.20 | 13.4% | 0.10 | 9 | 7.9% | 6.7% | -4.9% | untouched |
| hold DOGE-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes on | +1.3% | 0.20 | 13.4% | 0.10 | 9 | 7.9% | 6.7% | -4.9% | -5.3% / PF 0.00 / 1 tr ✗ |
| hold DOGE-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +1.6% | 0.21 | 16.5% | 0.10 | 9 | 9.8% | 8.4% | -6.1% | untouched |
| hold DOGE-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +1.6% | 0.21 | 16.5% | 0.10 | 9 | 9.8% | 8.4% | -6.1% | -6.7% / PF 0.00 / 1 tr ✗ |
| TF BTC-USDT 4H | vt10/30 crash15/90dh ladder, brakes off | +3.7% | 0.65 | 6.5% | 0.58 | 43 | 5.9% | 8.7% | -2.7% | untouched |
| TF BTC-USDT 4H | vt10/30 crash15/90dh ladder, brakes on | +3.8% | 0.66 | 6.4% | 0.59 | 42 | 5.9% | 8.7% | -2.6% | untouched |
| TF BTC-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes off | +8.7% | 0.77 | 12.9% | 0.68 | 43 | 11.8% | 18.2% | -5.4% | untouched |
| TF BTC-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes on | +8.8% | 0.77 | 12.9% | 0.68 | 42 | 11.8% | 18.2% | -5.1% | +1.4% / PF 1.54 / 4 tr ✗ |
| TF BTC-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +11.0% | 0.79 | 15.3% | 0.72 | 43 | 14.5% | 22.6% | -6.7% | untouched |
| TF BTC-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +11.1% | 0.80 | 15.3% | 0.73 | 42 | 14.5% | 22.6% | -6.3% | +1.8% / PF 1.53 / 4 tr ✗ |
| TF BTC-USDT 6H | vt10/30 crash15/90dh ladder, brakes off | +3.7% | 0.62 | 7.6% | 0.48 | 40 | 6.1% | 9.3% | -1.9% | untouched |
| TF BTC-USDT 6H | vt10/30 crash15/90dh ladder, brakes on | +3.7% | 0.63 | 7.6% | 0.49 | 39 | 6.1% | 9.3% | -1.8% | untouched |
| TF BTC-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes off | +9.0% | 0.76 | 15.5% | 0.58 | 40 | 12.4% | 19.4% | -3.8% | untouched |
| TF BTC-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes on | +9.1% | 0.77 | 15.5% | 0.59 | 39 | 12.4% | 19.4% | -3.3% | -1.2% / PF 0.79 / 6 tr ✗ |
| TF BTC-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +10.8% | 0.76 | 18.4% | 0.59 | 40 | 15.1% | 24.0% | -4.6% | untouched |
| TF BTC-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +10.9% | 0.76 | 18.4% | 0.60 | 39 | 15.1% | 24.0% | -4.1% | -1.6% / PF 0.79 / 6 tr ✗ |
| TF ETH-USDT 4H | vt10/30 crash15/90dh ladder, brakes off | +3.8% | 0.68 | 7.4% | 0.51 | 36 | 5.7% | 5.4% | -1.5% | untouched |
| TF ETH-USDT 4H | vt10/30 crash15/90dh ladder, brakes on | +3.6% | 0.65 | 7.4% | 0.49 | 36 | 5.7% | 5.4% | -1.8% | untouched |
| TF ETH-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes off | +7.3% | 0.69 | 14.2% | 0.51 | 36 | 11.0% | 10.8% | -3.0% | untouched |
| TF ETH-USDT 4H | vt20/30 crash15/90dh cap2 turtle, brakes on | +6.9% | 0.66 | 14.1% | 0.49 | 36 | 11.0% | 10.8% | -3.5% | untouched |
| TF ETH-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +8.7% | 0.69 | 17.9% | 0.49 | 36 | 13.4% | 13.4% | -3.7% | untouched |
| TF ETH-USDT 4H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +8.3% | 0.66 | 17.8% | 0.46 | 36 | 13.4% | 13.3% | -4.4% | untouched |
| TF ETH-USDT 6H | vt10/30 crash15/90dh ladder, brakes off | +5.6% | 0.96 | 5.4% | 1.05 | 28 | 5.9% | 5.6% | -1.8% | untouched |
| TF ETH-USDT 6H | vt10/30 crash15/90dh ladder, brakes on | +5.7% | 0.97 | 5.4% | 1.07 | 28 | 5.9% | 5.6% | -1.8% | untouched |
| TF ETH-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes off | +10.9% | 0.97 | 10.2% | 1.07 | 28 | 11.3% | 11.2% | -3.6% | untouched |
| TF ETH-USDT 6H | vt20/30 crash15/90dh cap2 turtle, brakes on | +11.2% | 0.99 | 10.2% | 1.10 | 28 | 11.3% | 11.2% | -3.5% | untouched |
| TF ETH-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes off | +13.5% | 0.98 | 12.4% | 1.08 | 28 | 13.9% | 14.0% | -4.4% | untouched |
| TF ETH-USDT 6H | vt25/30 crash15/90dh cap2.5 turtle, brakes on | +13.3% | 0.97 | 12.4% | 1.07 | 28 | 13.8% | 13.8% | -4.4% | untouched |

## The untouched 12 months

Opened only for the pre-registered cells. A configuration's 12 months count as confirmed with a positive return, PF > 1 and at least 10 trades. A tier changes only the size of the same trades, so an opening at a tier is a near-second look at months the Reference tier already opened; the earlier look is named beside it.

| Configuration | Cell | Role | Return | Max DD | PF | Trades | Verdict | Earlier look (study: return / PF / trades, confirmed) |
|---|---|---|---:|---:|---:|---:|---|---|
| S1 SOL-USDT 6H [none] | aggressive|brakes|none | configuration | +10.7% | 4.4% | 3.51 | 11 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1 SOL-USDT 6H [none] | reference|nobrakes|none | configuration | +9.5% | 2.1% | 5.49 | 12 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1 SOL-USDT 6H [none] | trader|brakes|none | configuration | +8.5% | 3.6% | 3.51 | 11 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1+S5 BTC-USDT 6H [none] | aggressive|brakes|none | configuration | +3.9% | 9.3% | 1.34 | 30 | confirmed | Sprint 2c: +2.3% / 1.48 / 32, yes |
| S1+S5 BTC-USDT 6H [none] | reference|nobrakes|none | configuration | +2.3% | 3.9% | 1.48 | 32 | confirmed | Sprint 2c: +2.3% / 1.48 / 32, yes |
| S1+S5 BTC-USDT 6H [none] | trader|brakes|none | configuration | +3.4% | 7.7% | 1.36 | 30 | confirmed | Sprint 2c: +2.3% / 1.48 / 32, yes |
| S1+S5 SOL-USDT 6H [none] | aggressive|brakes|none | configuration | +10.7% | 4.4% | 3.51 | 11 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1+S5 SOL-USDT 6H [none] | reference|nobrakes|none | configuration | +9.5% | 2.1% | 5.49 | 12 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1+S5 SOL-USDT 6H [none] | trader|brakes|none | configuration | +8.5% | 3.6% | 3.51 | 11 | confirmed | R12 replication: +9.5% / 5.49 / 12, yes |
| S1+VC BTC-USDT 4H [gate] | aggressive|brakes|none | configuration | +0.1% | 11.1% | 1.01 | 27 | confirmed | R13 research round 1: +2.0% / 1.41 / 25, yes |
| S1+VC BTC-USDT 4H [gate] | reference|nobrakes|none | configuration | +2.0% | 4.4% | 1.41 | 25 | confirmed | R13 research round 1: +2.0% / 1.41 / 25, yes |
| S1+VC BTC-USDT 4H [gate] | trader|brakes|none | configuration | +2.0% | 9.3% | 1.19 | 27 | confirmed | R13 research round 1: +2.0% / 1.41 / 25, yes |
| S1+VC DOGE-USDT 4H [gate] | aggressive|brakes|none | configuration | +1.5% | 5.8% | 1.22 | 16 | confirmed | R16 research round 2: +1.8% / 1.65 / 18, yes |
| S1+VC DOGE-USDT 4H [gate] | reference|nobrakes|none | configuration | +1.8% | 2.3% | 1.65 | 18 | confirmed | R16 research round 2: +1.8% / 1.65 / 18, yes |
| S1+VC DOGE-USDT 4H [gate] | trader|brakes|none | configuration | +1.3% | 4.7% | 1.23 | 16 | confirmed | R16 research round 2: +1.8% / 1.65 / 18, yes |
| TF BTC-USDT 4H [none] | aggressive|brakes|none | tf_control | +1.8% | 4.3% | 1.53 | 4 | forward control: opened by the runner's passer rule, not pre-registered; no verdict | - |
| TF BTC-USDT 4H [none] | trader|brakes|none | tf_control | +1.4% | 3.5% | 1.54 | 4 | forward control: opened by the runner's passer rule, not pre-registered; no verdict | - |
| TF BTC-USDT 6H [none] | aggressive|brakes|none | tf_control | -1.6% | 7.4% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict | - |
| TF BTC-USDT 6H [none] | trader|brakes|none | tf_control | -1.2% | 5.9% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict | - |
| hold BTC-USDT 4H [none] | aggressive|brakes|none | control | -9.4% | 13.5% | 0.00 | 1 | comparison line | - |
| hold BTC-USDT 4H [none] | reference|nobrakes|none | control | -4.3% | 5.2% | 0.00 | 1 | comparison line | - |
| hold BTC-USDT 4H [none] | trader|brakes|none | control | -7.5% | 10.8% | 0.00 | 1 | comparison line | - |
| hold BTC-USDT 6H [none] | aggressive|brakes|none | control | -9.6% | 14.3% | 0.00 | 1 | comparison line | - |
| hold BTC-USDT 6H [none] | reference|nobrakes|none | control | -4.0% | 5.5% | 0.00 | 1 | comparison line | - |
| hold BTC-USDT 6H [none] | trader|brakes|none | control | -7.7% | 11.5% | 0.00 | 1 | comparison line | - |
| hold DOGE-USDT 4H [none] | aggressive|brakes|none | control | -6.7% | 7.6% | 0.00 | 1 | comparison line | - |
| hold DOGE-USDT 4H [none] | reference|nobrakes|none | control | -2.7% | 3.0% | 0.00 | 1 | comparison line | - |
| hold DOGE-USDT 4H [none] | trader|brakes|none | control | -5.3% | 6.1% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 4H [none] | aggressive|brakes|none | control | -6.6% | 9.8% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 4H [none] | reference|nobrakes|none | control | -2.6% | 4.0% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 4H [none] | trader|brakes|none | control | -5.3% | 7.9% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 6H [none] | aggressive|brakes|none | control | -7.3% | 10.1% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 6H [none] | reference|nobrakes|none | control | -2.9% | 4.0% | 0.00 | 1 | comparison line | - |
| hold ETH-USDT 6H [none] | trader|brakes|none | control | -5.8% | 8.1% | 0.00 | 1 | comparison line | - |
| hold SOL-USDT 6H [none] | aggressive|brakes|none | control | -6.3% | 9.6% | 0.00 | 1 | comparison line | - |
| hold SOL-USDT 6H [none] | reference|nobrakes|none | control | -2.5% | 3.8% | 0.00 | 1 | comparison line | - |
| hold SOL-USDT 6H [none] | trader|brakes|none | control | -5.1% | 7.7% | 0.00 | 1 | comparison line | - |

### Every opening of the holdout (ledger)

| Run (generated) | Configuration | Cell | Return | PF | Trades | Verdict |
|---|---|---|---:|---:|---:|---|
| 2026-11-05 03:22 UTC | S1 SOL-USDT 6H [none] | aggressive|brakes|none | +10.7% | 3.51 | 11 | confirmed |
| 2026-11-05 03:22 UTC | S1 SOL-USDT 6H [none] | reference|nobrakes|none | +9.5% | 5.49 | 12 | confirmed |
| 2026-11-05 03:22 UTC | S1 SOL-USDT 6H [none] | trader|brakes|none | +8.5% | 3.51 | 11 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 BTC-USDT 6H [none] | aggressive|brakes|none | +3.9% | 1.34 | 30 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 BTC-USDT 6H [none] | reference|nobrakes|none | +2.3% | 1.48 | 32 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 BTC-USDT 6H [none] | trader|brakes|none | +3.4% | 1.36 | 30 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 SOL-USDT 6H [none] | aggressive|brakes|none | +10.7% | 3.51 | 11 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 SOL-USDT 6H [none] | reference|nobrakes|none | +9.5% | 5.49 | 12 | confirmed |
| 2026-11-05 03:22 UTC | S1+S5 SOL-USDT 6H [none] | trader|brakes|none | +8.5% | 3.51 | 11 | confirmed |
| 2026-11-05 03:22 UTC | S1+VC BTC-USDT 4H [gate] | reference|nobrakes|none | +2.0% | 1.41 | 25 | confirmed |
| 2026-11-05 03:22 UTC | S1+VC DOGE-USDT 4H [gate] | reference|nobrakes|none | +1.8% | 1.65 | 18 | confirmed |
| 2026-11-05 03:22 UTC | TF BTC-USDT 6H [none] | aggressive|brakes|none | -1.6% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:22 UTC | TF BTC-USDT 6H [none] | trader|brakes|none | -1.2% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:22 UTC | hold BTC-USDT 4H [none] | aggressive|brakes|none | -9.4% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold BTC-USDT 4H [none] | reference|nobrakes|none | -4.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold BTC-USDT 4H [none] | trader|brakes|none | -7.5% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold BTC-USDT 6H [none] | aggressive|brakes|none | -9.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold BTC-USDT 6H [none] | reference|nobrakes|none | -4.0% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold BTC-USDT 6H [none] | trader|brakes|none | -7.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold DOGE-USDT 4H [none] | aggressive|brakes|none | -6.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold DOGE-USDT 4H [none] | reference|nobrakes|none | -2.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold DOGE-USDT 4H [none] | trader|brakes|none | -5.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 4H [none] | aggressive|brakes|none | -6.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 4H [none] | reference|nobrakes|none | -2.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 4H [none] | trader|brakes|none | -5.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 6H [none] | aggressive|brakes|none | -7.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 6H [none] | reference|nobrakes|none | -2.9% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold ETH-USDT 6H [none] | trader|brakes|none | -5.8% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold SOL-USDT 6H [none] | aggressive|brakes|none | -6.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold SOL-USDT 6H [none] | reference|nobrakes|none | -2.5% | 0.00 | 1 | comparison line |
| 2026-11-05 03:22 UTC | hold SOL-USDT 6H [none] | trader|brakes|none | -5.1% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | S1 SOL-USDT 6H [none] | aggressive|brakes|none | +10.7% | 3.51 | 11 | confirmed |
| 2026-11-05 03:34 UTC | S1 SOL-USDT 6H [none] | reference|nobrakes|none | +9.5% | 5.49 | 12 | confirmed |
| 2026-11-05 03:34 UTC | S1 SOL-USDT 6H [none] | trader|brakes|none | +8.5% | 3.51 | 11 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 BTC-USDT 6H [none] | aggressive|brakes|none | +3.9% | 1.34 | 30 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 BTC-USDT 6H [none] | reference|nobrakes|none | +2.3% | 1.48 | 32 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 BTC-USDT 6H [none] | trader|brakes|none | +3.4% | 1.36 | 30 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 SOL-USDT 6H [none] | aggressive|brakes|none | +10.7% | 3.51 | 11 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 SOL-USDT 6H [none] | reference|nobrakes|none | +9.5% | 5.49 | 12 | confirmed |
| 2026-11-05 03:34 UTC | S1+S5 SOL-USDT 6H [none] | trader|brakes|none | +8.5% | 3.51 | 11 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC BTC-USDT 4H [gate] | aggressive|brakes|none | +0.1% | 1.01 | 27 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC BTC-USDT 4H [gate] | reference|nobrakes|none | +2.0% | 1.41 | 25 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC BTC-USDT 4H [gate] | trader|brakes|none | +2.0% | 1.19 | 27 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC DOGE-USDT 4H [gate] | aggressive|brakes|none | +1.5% | 1.22 | 16 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC DOGE-USDT 4H [gate] | reference|nobrakes|none | +1.8% | 1.65 | 18 | confirmed |
| 2026-11-05 03:34 UTC | S1+VC DOGE-USDT 4H [gate] | trader|brakes|none | +1.3% | 1.23 | 16 | confirmed |
| 2026-11-05 03:34 UTC | TF BTC-USDT 4H [none] | aggressive|brakes|none | +1.8% | 1.53 | 4 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:34 UTC | TF BTC-USDT 4H [none] | trader|brakes|none | +1.4% | 1.54 | 4 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:34 UTC | TF BTC-USDT 6H [none] | aggressive|brakes|none | -1.6% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:34 UTC | TF BTC-USDT 6H [none] | trader|brakes|none | -1.2% | 0.79 | 6 | forward control: opened by the runner's passer rule, not pre-registered; no verdict |
| 2026-11-05 03:34 UTC | hold BTC-USDT 4H [none] | aggressive|brakes|none | -9.4% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold BTC-USDT 4H [none] | reference|nobrakes|none | -4.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold BTC-USDT 4H [none] | trader|brakes|none | -7.5% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold BTC-USDT 6H [none] | aggressive|brakes|none | -9.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold BTC-USDT 6H [none] | reference|nobrakes|none | -4.0% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold BTC-USDT 6H [none] | trader|brakes|none | -7.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold DOGE-USDT 4H [none] | aggressive|brakes|none | -6.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold DOGE-USDT 4H [none] | reference|nobrakes|none | -2.7% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold DOGE-USDT 4H [none] | trader|brakes|none | -5.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 4H [none] | aggressive|brakes|none | -6.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 4H [none] | reference|nobrakes|none | -2.6% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 4H [none] | trader|brakes|none | -5.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 6H [none] | aggressive|brakes|none | -7.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 6H [none] | reference|nobrakes|none | -2.9% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold ETH-USDT 6H [none] | trader|brakes|none | -5.8% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold SOL-USDT 6H [none] | aggressive|brakes|none | -6.3% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold SOL-USDT 6H [none] | reference|nobrakes|none | -2.5% | 0.00 | 1 | comparison line |
| 2026-11-05 03:34 UTC | hold SOL-USDT 6H [none] | trader|brakes|none | -5.1% | 0.00 | 1 | comparison line |

## Paper-fleet rows (recorded for plan row R18b)

| Candidate | Market, bars | Regime | Role | Tier | Walk-forward CAGR / max DD / Calmar | Holdout |
|---|---|---|---|---|---|---|
| S1+S5 | SOL-USDT 6H | no regime gate | candidate | trader | +13.6% / 9.8% / 1.39 | +8.5% / PF 3.51 / 11 tr |
| S1 | SOL-USDT 6H | no regime gate | candidate | trader | +9.8% / 8.0% / 1.22 | +8.5% / PF 3.51 / 11 tr |
| S1+S5 | BTC-USDT 6H | no regime gate | candidate | trader | +10.4% / 14.1% / 0.74 | +3.4% / PF 1.36 / 30 tr |
| S1+VC | DOGE-USDT 4H | hmm3 bear>=0.5 gate | candidate | trader | +6.3% / 9.4% / 0.67 | +1.3% / PF 1.23 / 16 tr |
| S1+VC | BTC-USDT 4H | hmm3 bear>=0.5 gate | candidate | trader | +8.0% / 13.8% / 0.58 | +2.0% / PF 1.19 / 27 tr |
| TF | ETH-USDT 6H | no regime gate | control | reference | +5.6% / 5.4% / 1.05 | untouched |
| TF | BTC-USDT 6H | no regime gate | control | reference | +3.7% / 7.6% / 0.48 | untouched |

recorded for plan row R18b: the fleet's loader must learn to validate a tier-tagged row before these are appended; the shortlist file is untouched by this run

## Owner decisions (nothing below is decided by this report)

- **The budget.** The Trader tier is the default the plan proposed for the paper fleet; 5 of 5 configurations qualify at it. Decide at G7, after 60+ fleet days, with these backtest numbers beside the forward ones.
- **Brakes flagged for cost.** S1+VC DOGE-USDT 4H [gate] at reference, S1+VC DOGE-USDT 4H [gate] at aggressive; ladder flagged: none. A flagged brake is a question, not a removal.
- **Variants that counted** are candidates for a pre-registered forward test, never a change to a running account.
- **Plan row R18b** adds the recorded rows to the paper fleet (loader extension first), the fleet engine's transcription of the tier and the brakes with its parity test, and the weekly report's tier-beside-tier view; nothing here changes demo or live.

## Method notes and caveats

- The walk-forward's test windows restart flat from the same capital every 180 days (Sprint 2c's protocol), so the ladder's equity peak, the hard stop and the loss windows restart with them; the stitched curve's worst drawdown can exceed any window's, and a −30 % drawdown inside one window is rare by construction. The brakes' counts are per-window counts summed.
- The per-trade cap reads the stop the trade actually carries (the selected ATR multiple; the wider stop under that variant); without a stop (hold, TF) it cannot act. It is set at the decision close: the next open's gap and the entry fee move the realized risk per trade a little above or below it (the table shows the realized mean and maximum).
- The add variant: one add of half the initial quantity at +1 R, with its own stop from the add bar; the first unit keeps its stop; if the whole position's stop is hit both units fill at that price (conservative); the reduce-only overlay treats a held add as a deliberate increase, not an over-allocation. Worst case at the stops is reported in first-unit R per add.
- The scale-out variant sells half at +2 R through the reduce-only path; the trade stays one trade with its P&L pooled (a partial exit otherwise counts as a win by construction).
- Costs: the gate cost is the engine's 0.30 % a round trip; the 0.20 % and 0.50 % lines are fixed replays of the selected rule (same windows, same sizing), not re-selections.
- A tier changes the size of the same trades, so every tier's holdout is a near-second look at months already opened at the Reference tier; the ledger names each earlier look. The holdout's falling direction was known for every market before this study.
- The Monte Carlo resamples the order of the realized (sized) trade returns with replacement, 2,000 paths; it ignores the brakes' path dependence and the window restarts.
- The study's first run (the ledger's first entry) had a unit bug in the brakes' bar calendar: stored 4H candles carry millisecond timestamps, which were read as nanoseconds, so every 4H bar fell on one calendar day and the one-entry-per-day cap blocked almost every entry on the 4H series (the 6H series, resampled from 1H with nanosecond timestamps, were right). Its own brake counts exposed it; the calendar was fixed and the whole study re-run with the pre-registration unchanged. Both runs' holdout openings stay in the append-only ledger; the second-look warning above names the configurations opened twice, and no gate, threshold or rule changed between the runs.
- Nothing here changes the demo shadow run, its caps, the 0.60 confidence floor or any file under app/ or config/.
