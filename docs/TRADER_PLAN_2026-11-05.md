# Trader Plan — profit when right, a small loss when wrong (2026-11-05)

Date: 2026-11-05. Author: Claude (Fable 5.1) for the owner, under the owner's blanket go of
2026-11-04 ("do the next appropriate steps without the need of my decisions") and the request
of 2026-11-05 quoted in section 1. Status: **PLAN OF RECORD for the research and paper-fleet
work in plan rows R17–R22** (`docs/PLAN_STATUS.md`). Nothing here changes the running demo
shadow, its risk caps, the 0.60 confidence floor, any file under `app/` or `config/`, or the
safety contract in `CLAUDE.md`. Moving any of this from the paper fleet to demo or live money
stays an explicit owner decision with an independent review.

Evidence base: an 8-question web research sweep run on 2026-11-05 (about 270 findings with
sources; the key ones are listed in section 11), the repository's own research records
(`docs/research/*.md` and the results files beside them), live reads of OKX's public API on
2026-11-04/05, and a four-lens independent review of this document on 2026-11-05 (80 findings,
all applied). Where a number rests on a weak or unverified source it says so.

---

## 0. Read this first (5 minutes)

**No real money is involved anywhere in this plan.** Everything below is research on past
prices and the paper fleet: 24 pretend accounts on your laptop that follow live OKX prices with
no keys and no way to trade. The demo account on the VPS is not changed by any of it.

**What you asked for.** Strategies that make money when they are right and lose only a little
when they are wrong. Real-trader risk, not a savings account and not a casino. A trader who
wants to excel at every trade. Later, more markets, including tokenized American stocks. Risk
handled the way a good human does it: some excitement and greed, and knowing when to stop.

**What the evidence says, in six points.**

1. "Profit when right, a small loss when wrong" is exactly the shape of trend/breakout trading.
   It wins 3 to 5 trades in 10, and the average winner is 2 to 6 times the average loser. The
   small loss comes from the stop and from the size of the bet, not from being right more often.
2. Our rules already have that shape. Our main rule (a trend rule on Bitcoin, 6-hour bars; a
   "sleeve" is one rule on one market) won 3 trades in 10 last year with winners 3.8 times the
   losers. What makes it feel like a savings account is the size: last year it had, on average,
   8 cents of every dollar at work (8.4 cents over the earlier test years). The risk
   budget, not the rules, is the lever you are asking for.
3. Professionals run about 12-15 % yearly volatility (how much the account swings in a year),
   risk 0.5-2 % of the account per trade with the stop deciding the size, stop for the day at
   3-5 %, and cut size mechanically in a drawdown (the fall from the account's high point to its
   low). Even the largest of them earn about 5-7 % a year with 16-23 % worst drawdowns, a 10 %
   drawdown about every two years and a 20 % drawdown once or twice in 25 years. That is what
   "real trader risk" looks like in numbers; the few who earn far more carry 45 %+ drawdowns.
4. The "greed" worth keeping is one thing: let winners run (wide stops, exit on the trend's own
   signal, size that grows with the account). Every other human impulse measured in the data
   costs money: holding losers, sizing up after losses, taking profits early, trading more when
   excited, trusting a streak. "Knowing when to stop" works as fixed circuit breakers (automatic
   stop-trading rules), never as a mood.
5. More markets is the real structural lever (the big trend funds trade 100+ markets; in crypto
   the useful set is the 10-15 most liquid coins). Rotating into "the hottest coins" does not
   survive costs. Tokenized US stocks exist on OKX today (about 164 pairs, 19 of them in the demo
   environment) but have under four months of history and thin weekends priced by estimate: a
   log-only data phase first, trading later and only with your separate approval.
6. Costs decide how often we may trade: at OKX's regular fee a 4H/6H system keeps half to most
   of a 10-15 % edge at 15-25 round trips (one buy and its sell) a year per market and loses all
   of it at 50-75.

**What we will do (the runner builds these in order; all research and paper-fleet work, free).**

| Row | What | Why |
|---|---|---|
| R17 | Paper-fleet hygiene: give the SOL and DOGE accounts their own public positioning data (today the fleet asks the app's BTC/ETH-only collector, so the SOL "S1+S5" account runs without its funding filter) | the fleet is the judge of everything below; its record must be honest |
| R18 | **Trader Policy v1** in the research engine: three fixed risk budgets, the brakes a professional uses, adding to winners and a conviction size as tested variants; the five confirmed rules re-judged at each budget; the confirmed sleeves that pass the section 4.6 gates at the Trader budget join the fleet as new accounts, next to the existing ones | this is your request: the same edge at a trader's size, with the brakes |
| R19 | Asymmetric setups, research round 3: trend-pullback continuation, the slow breakout with wide stops, 6H vs 4H vs daily after costs | the two setups the evidence supports and we do not have yet |
| R20 | Breadth: one rule across the 9 liquid OKX markets we already have data for, with a cap on the total you could lose if every open trade hit its stop ("heat"); plus one rotation test whose pass mark is written down before it runs ("pre-registered") to settle the "buy the strongest coins" question with our own data | more markets is the lever; rotation is expected to fail and we say so beforehand |
| R21 | Tokenized US stocks on OKX: feasibility study, a log-only data collector for the 15 liquid pairs, and the design note of everything that must change before one is ever traded | your later goal, started the safe way |
| R22 | What a 1k-20k USDT order really costs at our bar closes, replayed from OKX's free record of past trades and order books | the cost model decides how much we may trade; today it is a conservative guess |

**What only you can decide (defaults apply if you say nothing).**

- Which budgets run in the paper fleet: today's Reference accounts keep running and the
  **Trader** budget is added by default; say so in one line if you also want the Aggressive
  budget watched (free). Section 4.1 shows what each means in losses.
- Whether, after about 60 days of fleet evidence (plan row G7), the Trader policy goes to the
  demo account. That is a safety-core change and needs your explicit go and a review. If you say
  nothing, nothing moves to demo and the fleet keeps collecting evidence.
- Two minutes in the OKX app for tokenized stocks: does your account see them, and at what fee
  (`docs/OWNER_CHECKLIST.md`, step 9). If you say nothing, the data is collected anyway and no
  trading step is planned.
- A go for the small lot-precision fix of the demo run (`docs/PLAN_STATUS.md`, section 2, "From
  R14", part A; `docs/OWNER_CHECKLIST.md`, step 11). Until it is built, reviewed, merged and
  deployed, the demo run on the VPS most likely cannot open any trade, so no demo evidence is
  being collected. If you say nothing, it stays as it is.

**What does not change.** Demo only, spot only, long only, no leverage, no AI on the order
path, fail closed, no retuning of the running strategy, no martingale, exchange-side stops
before any live phase. Every rule in this plan is a research and paper-fleet rule until you
approve otherwise.

---

## 1. Your request, translated into requirements

Your words (2026-11-05): "research strategies that would make profit and slight loss if
failed ... I'm ok to lose money. not gamble style, but like take the risk like real traders do.
not just make money from my money as if I put them in a saving bank account ... not trade with
extreme risk management. i want you to be like a professional trader who wants to be best and
excelling at every trade he makes ... expand so we trade more things tokenized American stocks
... close to how a human would manage risk not ai (human have excitement and greed to make
money, not to that extreme, but that helps in some cases to make profit, and know when to stop)".

| # | Requirement | How this plan meets it |
|---|---|---|
| T1 | Asymmetric trades: a defined small loss when wrong, a larger gain when right | a stop on every trade, a cap on what one stop may cost (2 % of the account at the Trader budget, plus fees and slippage), exits that let winners run; judged by average win vs average loss, never by win rate (section 4) |
| T2 | Real-trader risk, not a savings account | a risk budget about 1.7-2 times today's exposure on the BTC and 4H sleeves (about 1.1 × on SOL 6H, whose 4 × ATR stop makes the 2 % cap bind hard; R18 reports each sleeve): a 20 % in-trade volatility target with a 2 % cap on one stop's loss, about 10-12 % realized because the sleeves are flat half the time, just below the professionals' realized 12-15 %, with the losses that come with it stated up front (section 4.1, section 7) |
| T3 | Not extreme risk management | the brakes are few, wide and mechanical: a drawdown ladder, one hard stop, entry caps, and for a multi-market book a heat cap and a daily, weekly and monthly loss limit on new entries. No streak rules, no tight trailing stops, no profit targets (section 4.3) |
| T4 | "Excelling at every trade" | fewer, better trades: 15-35 a year per market, wide stops, every signal taken, costs modelled, fills measured (sections 4.2, 6, R22) |
| T5 | Human-like risk: moderate greed, know when to stop | greed = ride winners, size grows with the account, a bounded add and a conviction size only after they prove out; stopping = circuit breakers coded as a state machine (sections 4.3-4.4) |
| T6 | Expand: more markets, tokenized US stocks later | breadth across the liquid OKX coins first (R20); tokenized stocks through a staged, separately approved path (section 6, R21) |
| T7 | Keep the safety contract | research → paper fleet → owner-approved demo → reviewed live gates; nothing in `app/` changes in these rows (section 8) |

---

## 2. What the evidence says

Each block: the finding, the numbers, what it means for us. Source quality is noted where it
matters; the full list is in section 11.

### 2.1 The payoff shape of trend and breakout trading

- Trend following loses most trades by construction. In an exactly solved model (Capital Fund
  Management, 2005) the win rate falls from 50 % toward 0 % as volatility rises; the typical case
  wins 36.5 % with winners held about twice as long as losers. The win rate measures style, not
  edge.
- Bitcoin, daily Donchian breakout (20-day entry, 10-day exit, 2 × ATR stop, long only, 0.1 %
  fee, vendor backtest Sep 2017 to Oct 2026): 46 trades, 46 % winners, average win +40.2 %
  against average loss −6.4 %, worst drawdown −48 % versus −83 % for holding. Without its five
  best trades the total return falls from +4,744 % to +56 %. From 2022 to 2026 it returned about
  the same as holding (+78 % vs +76 %).
- The Turtle rules on futures (1970-2009, Trading Blox): 72 % a year with a 66 % drawdown and
  flat since the early 1990s. Garner's revision (90/45-day channels, a 5-ATR stop instead of 2,
  scale-out at 10-ATR targets, a trend filter, more markets and heat caps, all together) gave
  35 % a year with a 15.6 % drawdown; the wider stop's own share of that is not isolated.
- Slow trend systems do not have positively skewed daily returns (NilssonHedge 2025; Carver 2019):
  the "small loss" property shows up per trade, not per day or per month.

**Meaning.** Expect 3-5 winners in 10, winners 2-6 times the losers, most of a year's profit
from two or three trades, and losing months. Every signal must be taken and winners must not be
cut early, or the few trades that pay are the ones we miss.

### 2.2 What professional trend traders actually earn

| Measure | Value | Period |
|---|---|---|
| SG Trend Index (ten largest trend funds), yearly return | 2022 +27.3 %, 2023 −4.2 %, 2024 +2.4 %, 2025 +2.4 %, 2026 about +12 % to early Nov | 2022-2026 |
| SG Trend Index since 2000 | about 5.7 % a year, 13-15 % volatility, worst drawdown 20.6-23 %, Sharpe 0.41 (Sharpe: return per unit of swing) | 2000-2026 |
| Drawdowns deeper than 10 % | 16 since 2000, about one every 18-24 months; 20 % or worse twice (23 % the largest; 20.4 % in May 2024-May 2025, then +31 % the following year) | 2000-2026 |
| BTOP50 (largest investable CTAs) since 2000 | 4.5 % a year, 15.9 % worst drawdown at 9.6 % volatility; roughly zero from 2009 to 2019 | 2000-2026 |
| 109 trend programs with 5+ years | median 5-year return 5.05 % a year; the benchmark's return-to-drawdown ratio 0.37; one program 53 % a year with 45 %+ drawdowns | to Feb 2026 |
| Volatility these managers run | 12-15 % a year (their stated target); AQR's century study 10 % | various |
| A Sharpe 0.5 strategy at 10 % volatility | nearly 4 in 5 odds of a 20 %-or-worse drawdown over 25 years (Man AHL simulation) | — |
| Crypto quant funds (Galaxy VisionTrack, voluntary reporting) | 2024 +61 %, 2025 −7.5 %, 2026 −0.4 % to Oct, against Bitcoin +121 %, −6.4 %, −4.5 %; about 35 % of crypto funds closed 2022-23 | 2024-2026 |

**Meaning.** "Real trader risk" is 12-15 % realized volatility, a 10 % drawdown every two
years, a 20 % drawdown once or twice in a career, flat decades possible, and 5-7 % a year as the
long-run result of the largest funds at that risk. A long-only two-coin system is lumpier than
these diversified indices, not smoother.

### 2.3 The risk rules professionals use (numbers)

| Rule | The professionals | Source quality |
|---|---|---|
| Risk per trade | Hite 1 %; Kovner 1-2 % ("cut your intended size in half"); Trout 1.5 %; Elder 2 %; Turtles 2 % per unit; O'Neil/Minervini a 7-8 % stop on the position against 20-25 % targets | Market Wizards quotes via secondary summaries; Turtle PDF primary |
| The stop decides the size | Kovner: "the position size is determined by the stop, and the stop is determined on a technical basis" | secondary |
| Total open risk ("heat") | Seykota 10 % of equity across all positions; Elder 6 % per month including open risk; Turtles 4 units per market, 6 in closely correlated markets, 12 per direction | primary / secondary |
| Daily loss | Trout: −4 % in a day, close everything, wait for tomorrow (secondary quote); FTMO 5 % (3 % on the 2026 one-step), The5ers 3 % pause, Topstep 2 % (primary pages, 2026); Apex 2 % (secondary guide) | mixed |
| Monthly loss | Elder 6 %; Trout 10 %: flat until next month | secondary |
| Drawdown → size cut | Turtles: −20 % of trading size for every −10 % of equity; Millennium (press-reported): risk halved at −5 %, wound down at −7.5 % | primary / press |
| Scale up only from banked profit | FTMO Futures raises contract limits as closed profit grows and lowers them when it falls (primary); Apex the same (secondary guide) | mixed |
| Consistency | prop firms cap the best day at 30-55 % of total profit: they pay for repeatable results, not hero days | primary pages |
| What kills accounts | 54 % of prop-firm failures are daily-limit breaches (PropSim, vendor); Topstep's risk team lists "letting losers grow larger than winners", "not using stops", revenge and FOMO trades | vendor / primary |
| Sizing theory | full Kelly halves the account half the time; half Kelly keeps 75 % of the growth; the edge is only estimated, so bet less than the optimum (Thorp; MacLean-Thorp-Ziemba; Baker-McHale) | peer-reviewed |
| Volatility targeting | raises the Sharpe of risk assets modestly (0.40 → 0.48-0.51 for US equities) and cuts the tails; not a dependable return booster in real time (Harvey et al. 2018; Cederburg et al. 2020) | peer-reviewed |

**Meaning.** The professional consensus is narrow: 0.5-2 % per trade sized from the stop,
6-10 % total heat, stop for the day at 3-5 %, stop for the month at 6-10 %, cut size as the
drawdown deepens and rebuild it only from profits. Prop-firm limits are a business model that
profits from failures, so they tell us what a firm tolerates, not what is optimal; the Market
Wizards' numbers and the Kelly literature point the same way anyway.

### 2.4 Trader-like position management: what helps, what is neutral, what hurts

| Overlay | Evidence | Verdict |
|---|---|---|
| Size each position by current volatility | Carver (40 futures): Sharpe 0.19 → 0.25; Harvey et al.: 0.40 → 0.48-0.51 | **helps** (risk control) |
| Wide initial stop, exit on the trend's own signal | Clare et al. 2013 (S&P 500, 23 years): no trailing stop from 3 % to 15 % beat the plain 200-day rule; "a change of trend is the best stop-loss"; the few studies that vary the width point to a wide plateau (roughly 3-8 ATR, or about half the annual volatility; one unverified preprint), with performance collapsing only at tight stops | **helps**; tight stops are a cost machine |
| Stops as crash insurance | Han-Zhou-Zhu: a 15 % stop on long-short stock momentum cut the worst month from −50 % to −17 % (gross); there the tighter 10 % stop did better still | helps where crash risk exists |
| Breakeven stops | Davey: +3-6 % profit in optimized tests, "not a game changer", invites curve-fitting | neutral |
| Pyramiding into winners (Turtle 0.5 N adds) | the only long test: higher return and higher drawdown together (72 %/66 %); a BTC vendor test: profit 145 → 212 %, drawdown 18 → 24 %, win rate 38 → 32 %; a full 4-unit pyramid risks 5 % of equity at a worse average price | **more of the same bet**, not a free upgrade: test it with its total risk written down |
| Tightening stops as profit grows | Carver: Sharpe 0.19 → 0.05 (buys skew at a steep cost) | **hurts** |
| Scaling out at targets | win rate 38 → 54 % but total return 22 → 18.5 % (vendor); a partial exit counts as a win by construction | **hurts** expectancy |
| Time stops | Davey (567,000 tests): "much worse" than letting the signal exit | **hurts** |
| Equity-curve / streak sizing | Carver: lowers returns for every positive-Sharpe system unless wins cluster (trend returns anti-cluster, about −0.3 autocorrelation); Davey: worse in 5 of 6 live systems | **hurts**; only slow, partial size reduction in a drawdown has support (Alvarez) |

### 2.5 The human in the data

- Holding losers and selling winners cost retail investors about 3.4 points a year on the
  affected positions (Odean 1998); pre-committed automatic exits significantly reduce it, reminders
  do not (Fischbacher et al. 2017). People gamble while a loss is still on paper and freeze once
  it is realized (Imas 2016): a stop that realizes the loss is a behavioural brake, not just a cap.
- Professional floor traders took more risk after a losing morning (31.2 % vs 27 % odds of
  above-average afternoon risk) and the market faded those trades (Coval & Shumway 2005); crypto
  traders on one exchange raised their next trade size after poor results (Marinoff 2024);
  emotionally reactive day traders earned less in both directions (Lo, Repin & Steenbarger 2005);
  97 % of persistent Brazilian day traders lost money and fewer than 1 % of Taiwanese day traders
  were predictably profitable.
- Sizing must be a formula: finance-trained people given a coin known to land heads 60 % of the
  time went bust 28 % of the time and 18 of 61 bet everything on one flip (Haghani & Dewey 2016).
  Conviction carries information only when committed in advance by a demonstrably skilled process
  (fund managers' "best ideas", Anton, Cohen & Polk); no study shows self-rated conviction helping
  retail or prop traders.
- Rule-based and discretionary funds earn about the same risk-adjusted return (Harvey et al.
  2017); mechanical prediction beats expert judgment by about 10 % across 136 studies (Grove et
  al. 2000). "Human-like" means human-designed rules, not human overrides at trade time.

### 2.6 Setups

- **Dip buying as a stand-alone rule has no edge** (AQR 2025: more than 60 % of 196 buy-the-dip
  variants on the S&P 500 had a lower Sharpe than holding, over 60 years; Estrada 2026: 155 years,
  a little more return for much more risk and a lower Sharpe). In BTC, continuation beats reversal
  at every horizon tested (intraday, daily, 1-4 weeks: Liu & Tsyvinski; Zaremba et al.; Shen et
  al.); for ETH the evidence is weaker (1-day continuation, a negative 5-day coefficient), so the
  trend filter matters more there. A pullback entry only makes sense as a trend-continuation
  entry: a dip inside an uptrend, entered when price turns back up, stop under the dip.
- **Donchian/Turtle breakouts** are the best-documented asymmetric design (section 2.1) and the
  one rule family a peer-reviewed Bitcoin study singled out as beating buy-and-hold (Gerritsen et
  al. 2020). Break-even cost per trade for Bitcoin technical rules: up to about 0.66 % (Hudson &
  Urquhart 2021).
- **Opening-range breakout** (Zarattini & Aziz): the headline numbers rest on stock selection, 4×
  leverage and zero slippage; two independent replications lose the edge once slippage is charged
  (two cents a share on QQQ; spread plus slippage on index CFDs); the same authors' other intraday
  strategy decayed as soon as it met unseen data. **Parked.**
- **VCP / Minervini**: no quantitative study exists; championship returns are top-of-distribution
  outcomes from hundreds of entrants; Bulkowski's closest pattern statistics show about one in
  three fails and a fat right tail. **Only as a mechanically defined rule measured in the fleet,
  later.**
- **Bar size**: one unreviewed 2026 preprint finds 6-hour bars the cost-adjusted sweet spot for
  crypto trend rules. Our own record is mixed: the S1 family and the R12 confirmations favoured
  6H, the S2 family and the two volume-confirmation sleeves (R13, R16) sit on 4H. Worth a
  pre-registered cost-adjusted comparison, not a conclusion.

### 2.7 Rotation ("buy the strongest coins")

- Crypto momentum is a 1-4 week effect that reverses after about a month (Liu-Tsyvinski-Wu
  2022; Dobrynskaya 2023; Borri et al. 2026); 3-6 month lookbacks are not significant even in the
  founding papers; it lives in the largest coins only; it needs weekly rebalancing and decays
  within 2-3 weeks.
- After realistic costs and the post-2020 data, a long-only top-coin momentum basket has not
  reliably beaten holding Bitcoin: the top-30 momentum portfolio lost money from Aug 2020 to Dec
  2023 while the basket gained (Grobys et al. 2025); the Bitwise 10 index returned +12 % against
  BTC +67 % since Sept 2021 and fell harder in 2022 (−68 % vs −64 %); altcoin baskets fell 15-25
  points more than BTC in 2018. The only cost-measured study (15 bps per trade, Han-Kang-Ryu)
  finds the profit in the long leg and in the largest coins (the short leg loses); its long-only
  version beat the market on Sharpe (1.42 vs 1.01) but with a 94 % drawdown, and the edge faded
  after 2021 (Sharpe 0.83, about the market's).
- Alt liquidity evaporates about 1.7-2 × faster than BTC's in stress (Kaiko 2025); last year's
  beta explains under 20 % of next year's; alt seasons are rare and short (416 alt-season days vs
  956 BTC-season days; mean length 17 days).
- The one thing that consistently helped was a **BTC regime filter**: long-only trend rules cut
  worst drawdowns from 83-89 % to 54-65 %, were near flat in 2022 and roughly halved the 2018 loss
  (−41 % against −82 % for the market), at the price of lagging recoveries and about 70 % of buy
  signals whipsawing within a month.

**Meaning.** Breadth should come from running the same validated rule on more liquid markets,
not from chasing the strongest. One small pre-registered rotation test (R20) settles the
question with our data; we expect it to fail and say so before running it.

### 2.8 Tokenized US stocks on OKX (as of 2026-11-05)

| Fact | Value | Source |
|---|---|---|
| Listed on OKX spot | since 16 Jul 2026; about 164-172 X-prefixed USDT pairs (194 instruments carry the "Stocks" category, counting USDC quotes and test names), issuer Backed (xStocks, the Kraken group's product) | OKX notices; public API |
| In OKX's demo environment | **19 pairs** with the "Stocks" category and an X-prefixed USDT id (XAMD, XASML, XAVGO, XCSCO, XDELL, XGME, XGOOGL, XHIMS, XINTC, XIWM, XLITE, XMRVL, XMSTR, XMU, XNVDA, XPLTR, XQQQ, XSPCX, XTSM), plus three older-style names (AAPLX, AMZNX, TSLAX) and USDC/USD-quoted variants; read 2026-11-05 through the public instruments endpoint with the demo header, no key | own check |
| Hours, quote | 24/7 against USDT; weekend prices are "last close plus a market estimate"; mint/redeem with the issuer is 24/5 | OKX product page; Backed |
| Liquidity | about $162 M a day across all pairs, 80 % of it in the top 10; 18 pairs above $1 M a day, about 55 below $10 K; XNVDA spread 1.5 bps with about $110 K/$51 K within 0.5 % of mid; a newly listed name (XMCD) 39 bps and $1.6 K a side; weekend volume about 9 % of weekday | OKX public API, 2026-11-04 |
| History | under 4 months for the oldest names, days for the newest | OKX candles API |
| Instrument rules | lot size 0.00001 share, minimum 0.01 share, price bands 2 % at open / 1 % floating (BTC's are 1 %/0.5 %), same fee group as BTC-USDT in the API (the actual rate for X pairs is not published; regular spot is 0.08 %/0.10 %), `lever` 10 on some pairs (margin is forbidden for us anyway) | OKX instruments API |
| What you would own | a Regulation S price-exposure certificate from a Jersey issuer: no voting rights; dividends arrive as a balance increase ("rebasing") net of 30 % US withholding; redemption only for qualified investors; mergers and delistings undocumented | OKX legal text; Backed; CF Benchmarks |
| Behaviour | IMF (Oct 2026): 1.5 × the volatility of the underlying stock, more than half of volume outside US hours, 87-99 % of overnight token moves pass through to the stock at the open; documented depegs: an Apple token +12 % intraday, an Amazon token at about 4 × off hours, SpaceX tokens $122-$176 around a $135 IPO | IMF GFSR ch. 3 (via press); CoinMarketCap Research |
| Who may trade | OKX names Southeast Asia, Northeast Asia, CIS, MENA and Türkiye; the US and all of Europe are excluded; Lebanon is in MENA and on no exclusion list we could read, but only the app confirms it; Singapore is doubtful (securities licence) | OKX pages; OKX compliance disclosure |
| Regulatory weather | the SEC's new exemption requires real shareholder rights (so this product class stays offshore); 49 of 62 companies objected to OKX-ICE's planned US venue; ESMA warns of investor misunderstanding; Gemini reportedly closed its UK/EEA/Australia accounts in April 2026 (secondary report, unverified) | SEC; CoinDesk; ESMA |

**Meaning.** The technical path exists (same public API, same order book type, demo pairs
available), but the product is young, thin on weekends, estimate-priced off hours, 50 % more
volatile than its stock, and its balance rebasing would trip our fail-closed reconciliation by
design. The right first step is months of log-only data on the 15 liquid names and a design of
everything that must change; trading them is a later, separately approved phase.

### 2.9 Costs and turnover on OKX

- Regular spot fee 0.08 % maker / 0.10 % taker, unchanged by the 2026 fee notices; VIP1 needs
  $100 K of assets or $1 M of 30-day volume, so assume regular fees. Holding OKB buys no discount.
- For 1 K-20 K USDT orders in BTC-USDT and ETH-USDT the spread and book impact are under 0.05 bps:
  the cost of trading is the fee. The top altcoins cost 1-14 bps a side extra for a 20 K market
  order (SOL 1, XRP 2, DOGE 2-3, LINK 6-7, ADA 5-6, TRUMP 9-14).
- Turnover arithmetic at 0.20 % a round trip: a 10 % yearly edge is fully consumed at 50 round
  trips a year, half consumed at 25; a 15 % edge at 75 and 37. A 4H series has 2,190 bars a year
  and a 6H series 1,460: 20 round trips a year is one trade every 18 days.
- Post-only entries save 4 bps a round trip but may not fill, and passive fills carry adverse
  selection (roughly break-even before fees in the one crypto study found); measure before
  counting on it.
- Demo fills come from a separate thin book and are cancelled at the price limit: demo fill prices
  are not evidence of live slippage. OKX publishes a free archive of tick trades (T+2) and 10 ms
  order-book deltas (T+3) for any spot pair: an offline replay can measure real fill costs (R22).
- The research engine today charges 0.10 % fee plus 0.05 % slippage a side (0.30 % a round trip):
  about 50 % above the measured cost for BTC/ETH, about right for altcoins. It stays the gate cost
  (conservative) until R22 measures better. Altcoins carry a further 10 bps a side in every study
  here (0.50 % a round trip).

---

## 3. What we have, and why it feels like a savings account

The paper fleet runs 24 accounts on live public OKX data (20 since 2026-11-04, 24 since the
restart at 2026-11-04 23:00 UTC, 01:00 Beirut time). Five rules survived walk-forward (rules
chosen on past data and judged only on later data they never saw; out of sample 2021-2025) and
their untouched last 12 months (the 2025-26 bear year, whose falling direction was known
beforehand, so each is a hypothesis under forward test, not a result):

| Rule | Market, bars | Walk-forward (out of sample 2021-2025) | The untouched 12 months | Shape |
|---|---|---|---|---|
| S1+S5 (trend vote + funding filter) | BTC-USDT 6H | +5.3 % a year, worst drawdown 8.8 %, Calmar 0.60 (yearly return ÷ worst drawdown), 32 trades a year (139 in 4.3 years), realized volatility 6.2 %, in the market 47 % of the time | +2.3 %, 32 trades, **win rate 28 %, average win 3.8 × average loss**, drawdown 3.9 %, **average 7.9 % of equity at work** | asymmetric, small |
| S1 and S1+S5 | SOL-USDT 6H | pass; 31 and 29 trades a year | +9.5 %, PF 5.5, 12 trades (win rate 50 %, average win 5.5 × average loss) | one signal, short history; S1 carries a 30-day time-stop exit the walk-forward selected |
| S1+VC (trend vote + volume confirmation) | BTC-USDT 4H, regime gate | Calmar 0.55, Sharpe 0.71 | +2.0 %, PF 1.41, 25 trades (win rate 24 %, average win 4.5 × average loss) | clears two gates by a hair |
| S1+VC | DOGE-USDT 4H, regime gate | Calmar 0.83, 67 trades | +1.8 %, PF 1.65, 18 trades, **win rate 33 %, average win 3.3 × average loss**, **average 1.9 % of equity at work** | asymmetric, tiny |

Two things follow.

1. **The rules already have the trader's shape you asked for.** They win 2 to 5 trades in 10 and
   their winners are three to five and a half times their losers. That is a healthy trend system
   (section 2.1).
2. **The size is the savings-account part.** Every single-rule account uses the policy sizing: a
   10 % volatility target (size set so the account would swing about 10 % a year while in a
   trade), halving in a crash, and a ladder that cuts size as losses deepen (the two portfolio
   accounts run a 15 % target with their own ladder). On an asset whose volatility has run about 35-50 % a year (43 % median since mid-2021)
   that means about a quarter of the money at work while in a trade (23 % median for the lead
   sleeve)
   and, over a year, about 8 cents of every dollar (8.4 % over 2021-25, 7.9 % in the quieter
   bear year; the engine's own average while in a trade is about 18 % after the crash halving and
   the ladder). Doubling
   the exposure roughly doubles both the return and the drawdown; it does not change the odds. The
   budget is a choice, and it has been the most cautious one because nothing was proven yet.

Two more facts frame the plan:

- The demo shadow run (`demo-shadow-1h`) is not where the strategy's worth is being judged. Its
  caps are 10 USDT an entry and 1 USDT a day by design, and the R14 analysis shows it has very
  likely been unable to open a position since its one round trip on June 21 (fee dust counted as
  an open position). It proves plumbing. The paper fleet proves rules. Fixing the demo run is an
  owner decision (`docs/PLAN_STATUS.md`, section 2, "From R14", part A).
- The edge is thin and fragile across markets (R12: 10 of 104 configurations passed on seven new
  markets; the holdout rejected 8 of the 10; the lead sleeve's Sharpe after deflating for the 108
  configurations tried is 0.23). Sizing magnifies an edge; it cannot create one. Everything in
  section 4 is therefore built to be judged forward in the fleet before any money touches it.

---

## 4. Trader Policy v1 — the rules

Research-engine and paper-fleet rules (plan row R18). Written so that a fresh chat can build
them without judgment calls; the numbers in brackets are the pre-registered variants.

### 4.1 The risk budget (the owner's dial)

Each tier (a risk-budget level) is one rule. Size comes from a volatility target while in a
trade, as today, and a professional's cap on what one stop may cost. The policy's crash
de-risking (half size after a 15 % fall in 90 days) stays at every tier.

| Tier | Size rule | Drawdown ladder | Roughly, for the lead BTC 6H sleeve | A stopped-out trade costs | Worst year so far (2022, scaled) | A bad stretch (peak to trough) |
|---|---|---|---|---|---|---|
| **Reference** (today) | 10 % volatility target | today's: open positions cut to half at −5 %, sold to flat at −10 % (new entries blocked too) until a new equity high or the cooling-off | +5.3 % a year, 8.8 % worst drawdown (measured) | about 1.2 % of the account (0.6 % while the crash filter halves size) | −5.7 % | 9 % so far; about 16 % as the 1-in-20 case (Sprint 2c Monte Carlo) |
| **Trader** (default) | **20 % volatility target, and never more than 2 % of the account at risk on one stop** | Turtle: size × 0.8 at −10 % from the equity peak, × 0.64 at −20 %, restored on new highs | about 1.7 × today's exposure on this sleeve (the 2 % cap binds here; 2 × on the 4H sleeves where it does not; about 1.1 × on the two SOL 6H sleeves, whose 4-ATR stop is 13-14 % of price, so the cap pins them near today's size, where a stop already costs about 1.8 %): about +8-9 % a year, about 15 % worst drawdown | at most 2 % (about 1.3 % on the 4H sleeves) | about −10 % | about 15 %; about 27 % as the 1-in-20 case |
| **Aggressive** | 25 % volatility target, and never more than 2.5 % at risk on one stop | Turtle, as above | about 2.1 × today's: about +10-11 % a year, about 19 % worst drawdown | at most 2.5 % | about −12 % | about 19 %; about 34 % as the 1-in-20 case, which is beyond the hard stop in 4.3 |

How to read the table. The "roughly" columns scale the lead sleeve's walk-forward record by the
tier's exposure; compounding, the ladder and the caps bend it, so R18 measures the real figures
per sleeve. The per-trade cap is the professionals' rule (1-2 % per trade; section 2.3) laid over
the volatility target; without it a 20 % target would put about 46 % of the account into a BTC
trade and lose 2.4 % at the 3-ATR stop. The cap matters most on the 6H sleeves, whose stops are
3-4 × ATR (the market's average bar-to-bar range) and so wide; on the two 4H sleeves (2 × ATR
stops) the volatility target binds and a stop costs about 1.3 %. Realized yearly volatility is about 60 % of the effective in-trade target because the sleeves are flat
about half the time (6.2 % at today's 10 %). On the lead sleeve the 2 % cap holds the effective
target near 17 %, so the Trader tier should land near 10-11 % (1.7 × 6.2 %), just below the
professionals' 12-15 % band, and the Aggressive tier near 13 %; where the 20 % target binds (the
4H sleeves) the Trader tier lands near 12 %. R18 reports where each lands. The professionals' 16-23 % worst drawdowns were earned at
their 10-15 % realized volatility (section 2.2); the Trader tier's comparable figure is the
15-27 % range in the table.

Why the Reference ladder cannot stay at the higher tiers: it halves size at a 5 % drawdown and
goes flat, open positions included, at 10 %, which would switch a doubled tier off in an ordinary
bad stretch; the
Turtle ladder (section 2.3) is built for that range. R18 also reports the higher tiers with the
Reference ladder so the difference is visible.

Why these tiers and not "1.5 % per trade sized from the stop" (Kovner's rule): the rules' stops
are 2, 3 or 4 × ATR depending on the sleeve and were chosen by the walk-forward at full size, so a
fixed 1.5 % risk rule buys 1.3 × today's exposure on BTC 6H, less than today's on SOL 6H and 2.3 ×
on the 4H sleeves: not one budget but five. R18 still reports that rule, for information, beside
the tiers; it does not enter the fleet.

The hard stop at −30 % (section 4.3) is reached in under 1 case in 20 over four years at the
Trader tier (about 1 in 30, interpolating the Sprint 2c Monte Carlo's 1-in-2 drawdown of 8.7 % and
1-in-20 drawdown of 16.2 % on the lead sleeve, scaled by 1.7) and in roughly 1 in 10 at the
Aggressive tier (scaled by 2.1); R18 computes the exact share from the bootstrap paths at each
tier. The Aggressive tier is tested so that its price is visible; it is not recommended as a demo
candidate.

### 4.2 Each trade

- **Stop.** The rule's own window-selected ATR(14) stop, placed before entry: S1's grid is
  2-4 × ATR and the walk-forward chose 3 × on BTC 6H and 4 × on SOL 6H; S1+VC chose 2 ×; S2's grid
  is 2-3 × and 2 × was selected. Never tightened. Variant: a wider 4-5 × ATR stop, judged on Sharpe
  (size-neutral) and on Calmar after scaling to the base rule's realized volatility, because under
  the per-trade cap a wider stop shrinks the position.
- **Size** = the tier's volatility-target fraction, capped by the tier's per-trade loss limit
  (allocation ≤ cap ÷ stop distance as a fraction of price) and by 100 % of equity (spot, no
  leverage). Only a market calmer than the tier's target could put the whole account in one trade
  (R18 reports how often that happens). Implemented in `research/sizing.py` as a new sizing kind
  that reads the candidate's stop distance, with `research/gated_walkforward.py` accepting a
  per-rule-column fraction matrix; `run_vectorized` itself is unchanged. The per-window selection
  of rule variants (train Sharpe at full size, at least 20 train trades) is unchanged: the tier is
  a policy overlay, exactly as Sprint 2c's.
- **Exit.** The rule's own exit (trend reversal or channel exit), or the stop. Each confirmed
  configuration keeps the exit bracket the walk-forward selected (S1 SOL 6H's 30-day time stop
  included): "no time stops, no breakeven stops, no profit targets, no scaling out" is the rule for
  new variants and new rules, not a retune of the confirmed ones (R18 also runs S1 SOL once without
  its time stop, as a variant). Variant: a wide trailing stop (activate at +1 R, trail 2 R or 3 R
  below the running high; R is the money risked on one trade, entry to initial stop). Variant:
  half scale-out at +2 R measured at a bar close, the remainder keeps its stop, the trade counts
  once with its P&L pooled for every gate (a partial exit otherwise counts as a win by
  construction; section 2.4).
- **Re-entry after a stop-out.** If the rule still says "long" on the next bar, the engine
  re-enters: that is the rule's own behaviour and changing it would be a retune. R18 counts and
  reports re-entries within two bars of a stop-out so the owner sees the whipsaw cost.
- **Adds (the bounded greed).** Variant, default off: one add of half the initial quantity when
  the trade is +1 R at a bar close; the first unit keeps its original stop and the add gets its own
  ATR stop set at the add bar; the worst case for the whole position at the stop prices is 1.5 R
  while ATR is unchanged (the add's own 3-ATR stop then sits at the original entry) and approaches
  2 R only if ATR has doubled by the add bar, plus costs and whatever a gap past the stops adds
  (section 7); the open risk at the moment of the add is 2.5 R of current equity with ATR
  unchanged. R18 reports the realized worst case per add. Never an add after a loss, never
  averaging down (the contract forbids it anyway). The engine does not increase positions
  mid-trade today; this is an engine change behind a flag, default off, with tests that the flag
  off is bit-for-bit today's behaviour. (The Turtle-faithful form, which moves the first unit's
  stop up to the add's stop, is a breakeven stop in disguise and is not built.)
- **Conviction size (the other bounded greed).** Variant, default off: 1.25 × the tier's size when
  the volume confirmation (30-day volume z-score above 1, the condition confirmed in R13 and R16)
  fires at the entry bar and 0.75 × otherwise, never above the tier's per-trade cap, so the
  average risk stays the tier's. Not on the S1+VC sleeves, where the condition is the entry rule
  itself (plain S1 is their comparison). Pre-registered test: expectancy in R of tiered against
  untiered trades, at least 30 trades each; the split may affect fleet size only after it wins that
  test out of sample (Anton-Cohen-Polk is the only support, and it is for skilled professionals'
  committed weights).
- **Turnover.** 15-35 round trips a year per market; the lead sleeve sits at the top (32 a year,
  about 1.2 % of equity a year in fees at the Reference tier, about 2 % at the Trader tier). A new
  rule or variant that trades more than 40 a year fails on costs before it is judged on anything
  else.
- **Costs.** The engine's 0.30 % a round trip for gates; results also reported at the measured
  0.20 % (BTC/ETH) and at 0.50 % (altcoins: 0.30 % plus 10 bps a side).

### 4.3 The account: knowing when to stop (a state machine, not a mood)

All of these act on **new entries only**. An open position is always managed by its own stop and
exit; no brake ever liquidates a winner.

| Brake | Rule | Why this number | Where it can act |
|---|---|---|---|
| Drawdown ladder (Turtle style) | size × 0.8 at −10 % from the equity peak, × 0.64 at −20 %; restored only as equity makes new highs | Turtles: −20 % of size per −10 % of equity; Grossman-Zhou 1993: cut risk with the drawdown, rebuild on recovery | every sleeve and the book |
| Hard stop (the "uncle point") | −30 % from the peak → no new entries until the owner has reviewed | the largest trend funds' worst is 20-23 %; Man AHL shows 32 % is possible at Sharpe 0.6; beyond 30 % the question is whether the edge still exists, which is a human review | every sleeve and the book |
| Entry caps | at most 1 new entry per market per day and 3 per day across the book; no new entry in the same market on the bar after an exit | the shadow run's 3 entries a day; Coval-Shumway's afternoon revenge trades | every sleeve and the book |
| Daily loss limit | realized + unrealized loss over the last 24 hours ≥ 3 % of the equity 24 hours ago → no new entries for the next 24 hours (rolling, not the UTC calendar day) | Trout 4 %, The5ers 3 %, FTMO 3-5 %; at a 20 % target a 3 % day is roughly a 3-sigma move before fat tails; BTC fell far enough for it (about 8 % in a day, a 3 % loss at the Trader allocation of about 38 %) on 8-14 of 1,938 days in 2021-26 depending on the daily close used (1.5-2.6 a year) | the multi-market book only (R20): one sleeve risking 2 % cannot lose 3 % in a day without a second entry, which the entry cap forbids |
| Weekly loss limit | ≥ 6 % from Monday 00:00 UTC equity → no new entries until next Monday | Elder's 6 % heat rule applied to the week; adapted from R5b's weekly limit (entries-only here: no liquidation, no cooldown) | the book only |
| Monthly loss limit | ≥ 10 % from month-start equity → no new entries until next month | Trout's 10 % per month | the book only |
| Heat cap | total current risk (price to current stop, on current equity) across positions ≤ 6 % [variant 8 %]; positions whose trailing 60-day return correlation is ≥ 0.70 count as one bet (the R5b group rule, 50 % of the cap per group); when more signals fire than the cap allows, all open and new positions are sized down equally to the cap, never "first come, first served" | Elder 6 %, Seykota 10 %; the Turtles' 6 units for closely correlated markets against 12 per direction; BTC, ETH, SOL and DOGE move together (daily correlations 0.73-0.82 in 2024-26, 0.63-0.84 since mid-2021; on the 184 days BTC fell 3 % or more since mid-2021 the others fell too 95-98 % of the time) | the book only |
| What is deliberately absent | no streak rules (3 losses → smaller size), no "stop after a losing week" switch, no discretionary override | equity-curve sizing lowers returns for trend systems in every test (Carver, Davey); 3 losses in a row happen 26 % of the time at a 36 % win rate by chance | — |

The brakes are insurance. Today's Reference ladder is the one exception to "new entries only":
it reduces and closes open positions, which is one reason R18 reports the higher tiers with and
without it. On a single sleeve only the ladder, the hard stop and the entry caps can act; R18 reports every brake's trigger count (expected zero for the loss limits and the heat
cap) and the ladder's cost against the same sleeve without it. The loss limits and the heat cap
are judged in R20's nine-market book. A brake that costs more than 0.1 Calmar is flagged for the
owner, not silently kept.

### 4.4 Where "excitement and greed" live, and where they do not

| Human impulse | Where it goes |
|---|---|
| Wanting bigger wins | the risk budget (4.1), chosen once, in writing |
| Pressing a winner | wide stops, the trend's own exit, the bounded add at +1 R (4.2) |
| Confidence in a setup | the conviction split, driven by a pre-registered signal, logged before it sizes (4.2) |
| Growing with success | size is a share of current equity: it grows after wins and shrinks after losses by itself, without a streak counter |
| Wanting more action | breadth (more markets, section 5 and R20), never more trades per market |
| Wanting to get it back | nothing. No add after a loss, no size-up after a losing day, no new entry on the next bar |
| Knowing when to stop | the state machine in 4.3; re-arming is on the calendar (next day, next week, next month, new equity high), because cooling-off rules only work while they are enforced (Hopfgartner et al. 2023) |

### 4.5 How a rule travels from idea to money

1. **Research** (`research/`, R18-R20): pre-registered, walk-forward, the untouched 12 months
   opened once per passer through the ledger, the gates in 4.6.
2. **Paper fleet** (free, live public data): confirmed configurations join as new accounts with a
   source tag; the existing accounts are untouched; 60+ days of forward record (G7).
3. **Owner decision at G7**: which budget, which rules. The fleet's weekly report puts the
   Trader-budget accounts beside the Reference ones and the controls.
4. **Demo, Phase 6a-T** (owner go + independent review): a new demo account name, the Trader
   policy's caps replacing the shadow's 10 USDT / 1 USDT caps, after the R14 part A fix and
   G1/G2. The demo path's stop is a software stop judged on confirmed bar closes, so the per-trade
   loss there is not bounded by construction (section 7). Safety core changes are not delegated to
   the runner.
5. **Live** only through the Master Plan's gates (section 8 there): exchange-side stops (G3),
   position persistence (R14 part B), the migration workflow (R15), 60+ days of demo evidence.

### 4.6 Gates for R18 (pre-registered here, not after results)

The Sprint 2c gates stay as they are (profit factor > 1.2, Sharpe > 0.7, Calmar > 0.5, 75 % of
rolling 12-month windows positive, at least 30 trades, robust to ±30 % parameter changes), with
two changed only for the higher tiers because they scale with size: worst drawdown ≤ 25 % (was
20 %) and worst calendar year ≥ −15 % (was −10 %). Added, because it is the point of this plan:
average win ÷ average loss ≥ 2.0 (the confirmed sleeves show 3.3-5.5). Expectancy in R (R =
quantity × (entry fill − initial stop), per trade; under the add variant the first unit's R) is
reported for every configuration, not gated: the lead sleeve's is about 0.14 R, and a gate set
above the demonstrated edge would only invite its own relaxation. A variant (add, conviction
split, trailing, scale-out, wider stop) counts only if its Sharpe is at least the base rule's and
its Calmar at least the base rule's after scaling to the base's realized volatility (size-neutral
comparisons). The circuit breakers are judged by their trigger counts and cost, not by a gate.
Nothing is swept to find the best budget: the three tiers are fixed above.

---

## 5. The setups to research next (round 3, plan row R19)

New rules, not retunes of S1-S5. Each is pre-registered in the report before the first run.

1. **Trend-pullback continuation (S7).** In an uptrend (close above its 100-day average and the
   50-day above the 100-day), after a pullback that closes below the 20-day average (variant: below
   the 10-day EMA), enter when a close exceeds the previous bar's high while the uptrend holds;
   stop under the pullback low, floored at 2 × ATR (variant 3 ×); exit on a close below the 50-day
   average or the stop; variant: trail 3 R. Expected 10-25 trades a year on daily bars, fewer on
   6H. Why: the only version of dip buying the evidence supports (section 2.6).
2. **Slow breakout with wide stops (S8).** A slow Turtle System 2 breakout: 55-day high entry,
   20-day low exit, Garner's 5 × ATR stop, no adds; variant Garner's own 90/45 channels. Expected
   3-6 trades a year. Why: the fewer-trades, wider-stop direction is the one that kept working in
   futures after 1990 and fits our fee budget. It cannot be judged by the current protocol's
   selection step, which silences any window in which a variant traded fewer than 20 times in
   training (R16's slow rules reached that in 53 and 13 of 180 windows), so R19 uses a
   pre-registered protocol variant for **fixed rules**: the qualification step is skipped because
   there is nothing to select; the walk-forward windows, costs, sizing and ±30 % robustness replay
   are unchanged and the section 4.6 gates at the Trader tier apply (max drawdown ≤ 25 %, worst
   calendar year ≥ −15 %, average win ÷ average loss ≥ 2.0, the other Sprint 2c gates unchanged;
   expectancy in R reported, not gated); minimum 30 trades over the full period.
3. **Bar size after costs.** The S2 breakout and S1 trend families on daily, 6H and 4H bars under
   the Trader tier at the measured and the conservative cost, one table, to test the claim that
   6H is the cost-adjusted sweet spot. No new parameters.

Parked, with the reason written down: opening-range breakout (slippage kills it; needs a wide
stock universe), VCP (no quantitative evidence; a later mechanical definition if ever), naive dip
buying (anti-trend), intraday rules (no profitable intraday trend following in the BTC
literature; fees).

Also in R18, as a free forward control: an "always long above the 200-day average, policy
sizing" account in the fleet, the option (a) of the R16 slow-rule question, so the slow filter's
worth shows beside the hold controls at G7.

---

## 6. Expansion path

### 6.1 Breadth in crypto first (plan row R20)

- One rule family (S1, S1+VC, S1+S5 as the data allows) across the nine liquid OKX USDT markets
  the lake already holds (BTC, ETH, SOL, XRP, DOGE, LINK, TRX, ADA, LTC), each sleeve at the Trader
  tier and the whole book under the 4.3 brakes (the heat cap with its correlation grouping, the
  loss limits, the ladder, the hard stop, the entry caps), as **one portfolio account**. Allocator v2 (R5b) is reused for its
  daily bookkeeping and correlation cap only; its own portfolio volatility target and weekly
  cash-out are switched off so the Trader tier is not sized twice. Judged at the portfolio level
  under the R5b rule (a portfolio is a candidate only when its sleeves pass on their own or its
  holdout confirms it; the holdout is used up for most of these markets, so the paper fleet's
  forward record is the judge). Expected benefit: a smoother curve from imperfectly correlated
  markets, not a bigger edge per market, and less than the market count suggests: the four
  markets with confirmed sleeves move together (daily correlations 0.73-0.82 in 2024-26). Altcoin extra cost:
  +10 bps a side in the model (0.50 % a round trip).
- **One rotation test**, fixed before running: the top 3 of those nine markets by trailing 3-week
  return, equal weight, rebalanced weekly, long only, only while BTC closes above its 200-day
  average, sized by the 20 % volatility target (no per-coin stop; the weekly rebalance and the
  200-day filter are its only exits), 0.30 % a round trip plus the altcoin 10 bps a side; against
  holding BTC with policy sizing. Expected to fail to beat BTC after costs (section 2.7). If it
  passes anyway it enters the fleet as one account; if it fails, the question is closed with our
  own numbers.
- Later (not a row yet): more OKX markets with shorter history (BNB, SUI, HYPE, AVAX, NEAR) once
  they have 3+ years of 1H candles; and the Phase 9 long/short question stays closed as decided
  (R9).

### 6.2 Tokenized US stocks on OKX (plan row R21, then a separate owner decision)

The staged path, each step free until the last:

| Step | What | Who | When |
|---|---|---|---|
| 1 | **Log-only data**: a research-side collector (GET-only public REST, the R12 pattern; never widening `ALLOWED_INSTRUMENTS`) for the 15 most liquid X-pairs: 1H and 1D candles back to listing; order-book snapshots at the US regular-session open and close (09:30 and 16:00 New York time, converted at run time: 14:30 and 21:00 UTC in winter, 13:30 and 20:00 UTC in summer), at 03:00 UTC daily and at 12:00 UTC on Saturdays; per name: spread, depth within 0.5 %, weekend gap to Friday's last US-hours close, Monday-open jump, days since listing, price-band and lot parameters, fee group | runner (R21), then a laptop task like the fleet | now |
| 2 | **Feasibility report** `docs/research/TOKENIZED_STOCKS_FEASIBILITY.md` with the first weeks of data and the facts in section 2.8; **design note** `docs/design/TOKENIZED_STOCKS.md`: everything that must change before one is traded: the instrument allowlist (a reviewed scope change), rebasing-aware position accounting and reconciliation (a balance that changes without a fill must not read as a foreign fill or a wrong scope), lot precision 0.00001 and the flatness rule, a trading-hours rule (entries during US regular hours only; exits always), price-band-aware orders, the weekend reference price, corporate actions, the issuer and venue risk, the 19 demo pairs, the owner's eligibility and fee check | runner (R21) | now |
| 3 | **Owner**: in the OKX app, do you see the X-pairs, and what fee tier applies (two minutes; `docs/OWNER_CHECKLIST.md`, step 9). The collection runs either way; only a trading step waits on the answer | owner | any time |
| 4 | **Decision gate** after 60-90 days of collected data: are spreads, weekend gaps and depth good enough for the Trader policy's stops? If yes, a strategy study on the underlying stocks' history as a proxy (a new row; the data source is to be chosen then) and the design review | owner + review | 2027 Q1 at the earliest |
| 5 | Demo on the 19 demo pairs under a new account name, then the usual gates | owner go + review | after step 4 |

Honest expectation: the near-term "more things" is more coins (6.1). Tokenized stocks are a 2027
item whose main risks today are not strategy risks but product risks (section 2.8).

---

## 7. Honest expectations

These numbers are for the paper fleet and, later, the demo account. No real money is involved
anywhere in this plan; they say what the rules would do if they were ever allowed to trade. They
assume the lead sleeve keeps the walk-forward Sharpe it showed (about 0.85, twice the SG Trend
record of 0.41 and estimated from 4.3 out-of-sample years); at the professionals' Sharpe the Trader tier
earns about +4-5 % a year for the same 15 % drawdown. Basis: the lead sleeve's
walk-forward years (+5.4 %, −5.7 %, +16.2 %, +5.3 %, +2.6 % for 2021-2025 at the Reference tier)
scaled by the Trader tier's 1.7 × exposure.

| What | Expect at the Trader tier |
|---|---|
| Return in a good year | +15 to +30 % (2023 would have been about +27 %) |
| Return in a normal year | +4 to +10 % |
| Return in a bad year | about −10 % (2022 would have been about −10 %; the untouched bear year of 2025-26 gave +2.3 % at the Reference tier, about +4 % at Trader, but the next bear year will not be the same) |
| Worst peak-to-trough over 5 years | 15-25 %, likely once; 30 % possible (under 1 chance in 20), and at 30 % the hard stop switches new entries off until you have reviewed |
| Losing months | roughly half, unmeasured (the fleet report will measure it) |
| Trades per market per year | 15-35; win rate 25-50 % (the confirmed sleeves: 24-50 %); average win 3-5.5 × average loss |
| Where the year's profit comes from | two or three trades; the rest is small losses and small wins |
| Flat stretches | 6-18 months without a new equity high are normal; the professionals had a flat decade |
| What "slight loss when wrong" means | per trade: about 2 % of the account at most by design (the per-trade cap), plus fees and slippage, and more when the price jumps past the stop between two bar closes, which happens in crypto a few times a year (R18 counts and reports every such trade; the demo path's software stop is judged on bar closes, so it is a design limit there, not a guarantee); per month: no; a −6 to −8 % month is plausible under a 15 % worst drawdown but unmeasured (the fleet report will measure it); per year: sometimes |
| How long until we know | the first 60 fleet days (G7) show whether the shape and the plumbing are right, not whether the edge is real; 2-3 years of forward record say whether it is |

The worst thing to do with a trend system is to quit right after a drawdown (9 of the 10 largest
SG Trend drawdowns were followed by a positive year; +31 % after the 2025 trough). The hard stop
in 4.3 exists so that the decision to stop is taken once, calmly, at a level written down in
advance, not in the middle of a bad week.

---

## 8. What stays non-negotiable

The standing safety contract in `CLAUDE.md` applies unchanged: demo only, spot, long only, no
leverage, BTC-USDT and ETH-USDT only in the demo scope, no AI on the order path, fail closed, no
retuning of the running strategy or the 0.60 floor without an owner go and a review, no
martingale or adding to losers, exchange-side stops before any live phase, `main` only through
owner-merged pull requests. This plan raises risk only inside `research/` and the paper fleet;
the adds in 4.2 are allowed only on a winner, with their total risk written down, never after a
loss.

---

## 9. The plan rows (what the runner builds, in order)

The exact row text is in `docs/PLAN_STATUS.md`, section 0, and is the spec a runner chat
follows. In short:

- **R17** — fleet hygiene: a research-side public positioning feed for the R12 markets and plain
  "filter running without data" labels (today the SOL S1+S5 account's funding filter passes for
  lack of data). Small; protects the record before it matters.
- **R18** — Trader Policy v1 in `research/` (the tiers of 4.1, the brakes of 4.3, the variants of
  4.2 behind flags), the pre-registered study at the three tiers
  (`docs/research/TRADER_POLICY_V1_REPORT.md`), the fleet additions (the confirmed sleeves that pass at the
  Trader tier; the 200-day control), the fleet loader's extension so those accounts can be loaded
  without weakening its guard, the runbook paragraph.
- **R19** — research round 3: S7 trend-pullback, S8 slow breakout under the fixed-rule protocol
  variant, the bar-size comparison (`docs/research/RESEARCH_ROUND_3_REPORT.md`).
- **R20** — breadth portfolio across the nine markets and the one rotation test
  (`docs/research/BREADTH_V1_REPORT.md`).
- **R21** — tokenized stocks: collector, feasibility report, design note (the owner's check is
  already checklist step 9).
- **R22** — fill-cost replay from OKX's public archive (`docs/research/FILL_COST_REPLAY.md`),
  with a recommendation for the cost model of future studies (applied to new studies only; no
  finished study is re-judged).

Then the runner stops at R10 (Optional) as before. Each row is research or paper-fleet work:
nothing under `app/`, `config/`, `migrations/` or the deploy units changes; a chat that finds it
cannot build its row without touching those stops and writes the decision into section 2 of
`docs/PLAN_STATUS.md`.

---

## 10. Decisions

Taken under your go of 2026-11-04 and the request of 2026-11-05, and recorded in
`docs/PLAN_STATUS.md`, section 2 ("Decided — the owner, 2026-11-05"): this plan is the plan of
record for research and fleet work; the Trader tier is the default added to the fleet; the R16
slow-rule question is answered both ways (the 200-day control account in R18, a fixed-rule
protocol variant in R19); rotation is tested once, small and pre-registered; tokenized stocks
start as log-only data and a design; the demo shadow run, its caps and the safety core are
untouched by every row.

Still yours: the four items in section 0 ("What only you can decide") and everything in
`docs/OWNER_CHECKLIST.md` that was already yours (checklist steps 1-8: the OKX port change, the GitHub setting and pull request, the VPS update
with the nightly backup and database stamp, the evidence copy, the stop drills, the Telegram
token, the Anthropic key for the news agent, the housekeeping).

---

## 11. Sources (the ones the numbers above rest on)

Payoff shape and professional records: Potters & Bouchaud, "Trend followers lose more often than
they gain", arXiv physics/0508104 (2005); Hurst, Ooi & Pedersen, "A Century of Evidence on
Trend-Following Investing" (AQR); Man AHL, "Trend-following, equity and bond crisis alpha" (2016)
and "Is this time different?" (2025); NilssonHedge, "Honey, you shrunk the skew" (June 2025);
Top Traders Unplugged trend-following performance reports (Dec 2025, Sep 2026); Cambridge
Associates on the 2024-25 trend drawdown; AlphaSimplex/Virtus, "The patience premium" (2026);
Quantica Quarterly Insights Q2 2025; BarclayHedge BTOP50 index page; Meketa, "Trend Following"
(Dec 2025); ATS Trading Solutions, "Rising stars and trend titans" (Feb 2026); Galaxy VisionTrack
indices; Altrady and CoinQuant Donchian backtests (vendor, 2026); Garner, "Tuning up the turtle",
Active Trader (Feb 2010); Gbadebo, crypto TSMOM, Vilnius University Press BATP 2026
(peer-reviewed, gross of costs); Bui & Nguyen, arXiv 2602.11708 (2026, unreviewed).

Risk rules: FTMO trading objectives and the 1-Step Challenge page (2026); Topstep help centre
(Sep 2026) and 2025 statistics; The5ers programmes (June 2026); PropSim pass-rate dataset
(Nov 2026); Forexop pass-rate compilation and Monte Carlo (Oct 2026, weak); FSMA warning on
funded-trader challenges (Mar 2024); Hedgeweek and Net Interest on Millennium's drawdown rules;
the Original Turtle Trading Rules (Faith, 2003, tradingblox.com); Seykota, "Risk Management"
(2003); Market Wizards quotes (Hite, Kovner, Jones, Trout) via secondary compilations; Elder's
2 % and 6 % rules (IncredibleCharts); O'Neil, AAII Journal (1999); Thorp, "The Kelly Criterion in
Blackjack, Sports Betting, and the Stock Market" (1997); MacLean, Thorp & Ziemba, Quantitative
Finance (2010); Baker & McHale, Decision Analysis (2013); Haghani & Dewey, arXiv 1701.01427;
Harvey et al., "The Impact of Volatility Targeting", JPM (2018); Cederburg et al., JFE (2020);
Moreira & Muir, JF (2017); Grossman & Zhou, Mathematical Finance (1993).

Position management: Carver, "Dynamic trend following" (Dec 2020), "Skew and trend following"
(Feb 2019), "Trading the equity curve" (Nov 2015), qoppac.blogspot.com; Davey, KJ Trading exit
and equity-curve studies; Clare, Seaton, Smith & Thomas, Journal of Asset Management (2013);
Kaminski & Lo, Journal of Financial Markets (2014); Han, Zhou & Zhu, "Taming Momentum Crashes"
(via CXO Advisory); Lo & Remorov, Journal of Financial Markets (2017); Alvarez Quant Trading
(2018); Quantpedia Bitcoin studies; quantstrategy.io pyramiding and scaling-out tests (vendor,
weak).

Behaviour: Odean, JF (1998); Ben-David & Hirshleifer, RFS (2012); Coval & Shumway, JF (2005);
Imas, AER (2016); Thaler & Johnson, Management Science (1990); Lo, Repin & Steenbarger, AER
(2005); Coates & Herbert, PNAS (2008); Kandasamy et al., PNAS (2014); Barber & Odean, JF (2000);
Chague, De-Losso & Giovannetti, FGV (2020) and Chague & Giovannetti (2025); Barber, Lee, Liu,
Odean & Zhang, RAPS (2020); Barber, Huang, Odean & Schwarz, JF (2022); Kogan, Makarov, Niessner
& Schoar, JFE (2024); Marinoff, City University thesis (2024); Anton, Cohen & Polk, "Best Ideas"
(2021); Fischbacher, Hoffmann & Schudy, RFS (2017); Hopfgartner et al. (2023); Grove et al.,
Psychological Assessment (2000); Harvey, Rattray, Sinclair & Van Hemert, "Man vs. Machine", JPM
(2017); AQR Alternative Thinking 3Q17; HFR and IASG index data (vendor).

Setups: AQR, "Hold the Dip" (2025 Q4); Estrada (IESE, 2026, via FA Magazine); Bonini, Shohfi &
Simaan, EFM (2024); Liu & Tsyvinski, RFS (2021); Zaremba et al., IRFA (2021); Shen, Urquhart &
Wang, Financial Review (2022); Gerritsen et al., FRL (2020); Hudson & Urquhart, Annals of OR
(2021); Detzel et al., Financial Management (2021); Zarattini, Aziz & Barbon, SSRN 4729284 (2024)
and SSRN 4416622 (2023) with the Brusco (GitHub) and MQL5 replications and Paz (2026);
Bulkowski's pattern statistics; George & Hwang, JF (2004); Fieberg et al., JFQA (2025); Jin, Jung
& Song, JDQS (2024); Grobys, Ahmed & Sapkota, FRL (2020); Rozario et al., arXiv 2009.12155.

Rotation: Liu, Tsyvinski & Wu, JF (2022); Borri, Liu, Tsyvinski & Wu, arXiv 2510.14435 (2026);
Dobrynskaya, JAI (2023); Grobys et al., FMPM (2025); Han, Kang & Ryu (SKKU working paper); Han,
Newton, Platanakis, Sutcliffe & Ye, EFM (2024); Bitwise 10 index pages and the fund's FY2022
10-K; Sila et al., Financial Innovation (2025); CoinGecko 2025 annual report; Blockchaincenter
Altcoin Season Index; Glassnode Week 40 2026; Kaiko (July 2025); CoinPaprika 200-day backtest
(weak); IsaacDodds GitHub backtest (weak); Man Institute, "In Crypto We Trend" (Dec 2024).

Tokenized stocks: OKX listing notices (July-October 2026), the Unified Tokenized Stocks product
page, the risk and compliance disclosure, OKX public API reads (instruments, tickers, books,
candles) on 2026-11-04/05 including the demo-environment instruments read; Payward press release
(16 Jul 2026); Kraken xStocks FAQ and legal pages; Backed legal documentation; CF Benchmarks
xStocks documentation; SEC release 34-106402 and Commissioner Peirce's statement (July 2025);
CoinDesk on OKX-ICE objections (3 Nov 2026); ESMA statements (Sep 2025, Sep 2026); MAS
tokenisation guide (Nov 2025, via Baker McKenzie); IMF GFSR October 2026 chapter 3 (via
CryptoSlate/Decrypt); CoinMarketCap Research, "Tokenized Stocks: The Venue Landscape" (June
2026); Coinpaprika weekend-gap sample (Oct 2026, weak); Bybit, Coinbase/Base, Robinhood, Gemini,
Ondo and Dinari product pages and press.

Costs: OKX fee notices (SG 9 Sep 2026; US 1 Feb 2026; EEA 22 Apr 2026; SG 27 Feb and Aug 2026);
OKX API v5 documentation and changelog (fee groups, set-fee-type, order types, price limits,
public archive endpoint); own order-book and archive reads 2026-11-04/05; CoinGecko OKX exchange
page and 2026 liquidity report; Kaiko Digital Asset Snapshot (Jan 2026) and methodology note;
Albers et al., arXiv 2502.18625; DeLise, arXiv 2407.16527; DaruFinance adverse-selection study
(GitHub, weak); OKX demo-trading help page (Oct 2026).

Research records in this repository: `docs/research/ENSEMBLE_V1C_REPORT.md` and
`ensemble_v1c_results.json`, `REPLICATION_V1D_REPORT.md`, `RESEARCH_ROUND_1_REPORT.md`,
`RESEARCH_ROUND_2_REPORT.md`, `ALLOCATOR_V2_REPORT.md`,
`docs/research/paper_fleet_shortlist_v1c.json`, `docs/design/POSITION_PERSISTENCE.md`,
`docs/PLAN_STATUS.md`; the lake under `data/lake/` for the allocation, stop-distance and
correlation measurements quoted in sections 3, 4.1 and 4.3 (computed 2026-11-05 by the review).
