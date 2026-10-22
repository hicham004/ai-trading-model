# Phase 9 design study — long and short through perpetual swaps, without leverage

Plan row R9 (the owner's go of 2026-10-21 for a paper-only study). Written 2026-10-22.

**Status: a paper study. Phase 9 is not authorized.** Nothing here changes the
safety contract: trading shorts, perpetual swaps, margin and every kind of
derivatives access stay forbidden and unrepresentable in code (`CLAUDE.md`,
`PROJECT_RULES.md`). No code near execution was written. The study's code lives
in `research/`, only simulates, and is kept out of the trading runtime by a test.
No key was used; the only data are public (OKX candles and reference data,
Binance's public funding files).

Where the numbers come from:

- `docs/research/LONG_SHORT_STUDY_REPORT.md` — the generated report (every table),
  `docs/research/long_short_results.json` — the raw numbers;
- `docs/research/okx_swap_reference_2026-10-22.json` — OKX's public contract,
  margin-tier and funding settings for the two swaps on the day of the study;
- `docs/RESEARCH_LAB.md`, last section — how the study is built and run.

## 1. The answer on one page

**The question.** Two research sprints found that the honest product of today's
scope (BTC and ETH spot, long only) is risk-managed exposure: a few percent a
year, drawdowns under 20 %, flat at best in a bear year. A professional trader
can also be short. Would the same trend rules do better if they could short —
through USDT-margined perpetual swaps with collateral at least equal to the
position, so no leverage — after fees, slippage and funding?

**What we did.** We took the four trend families of Sprint 2c (S1 momentum,
S2 Donchian breakout, S4 volatility-compression breakout, and S1 with the S5
positioning filter, the family of the one long-only rule the holdout confirmed)
and gave each its mirror image as a short rule, with the same parameters. The
long side stayed exactly the long-only rule; a short could only use the time the
long rule spends flat. We ran them on BTC and ETH, 4-hour and 6-hour bars, in
two designs — **hybrid** (long on spot, short on the swap) and **all-perp**
(both on the swap) — 32 configurations, with Sprint 2c's walk-forward, sizing
and gates, and real funding history. Everything, including a stricter rule for
what counts as evidence, was written down before the first run. Before any
short ran, the code had to reproduce Sprint 2c's long-only results exactly; it
did, for all 16 rules. An independent review of the code then found one real
bug (a switch from short to long could start the long one bar late) and three
smaller points; they were fixed and the study re-run, with no rule, gate or
setting changed. Both runs' looks at the untouched last 12 months are on
record, and their verdicts agree.

**What we found.**

1. **Adding shorts made these rules worse in most cases.** The risk-adjusted
   result (Calmar: yearly return divided by the worst drawdown) beat the
   long-only rule in only 3 of 16 cases; the median fell from 0.35 to 0.05. With
   the families' fixed default settings over 2020 to October 2025, shorts
   lowered it in 15 of 16 cases.
2. **Shorting BTC lost money.** In 7 of 8 BTC configurations the short side lost
   after costs and funding. On ETH the short side made a little in 6 of 8, but
   most of its trading gains went to fees.
3. **The bear year improved only a little.** Shorts made 2022 better than
   long-only in 13 of 16 cases, but positive in only 4; the median 2022 result
   went from −2.6 % (long-only) to −1.5 % (with shorts). The sizing keeps
   positions small (a 10 % volatility target), and trend shorts in 2022 were
   whipsawed by sharp bear-market rallies.
4. **One rule passed every test — weakly.** S2 (Donchian breakout) on ETH 6-hour
   bars: +4.6 % a year out of sample with a 7.5 % worst drawdown (Calmar 0.61
   against 0.36 long-only), and +2.3 % on the untouched last 12 months. But the
   same rule on ETH 4-hour bars also passed the walk-forward and then LOST 4.8 %
   on those 12 months; we already knew those months were a falling market
   (BTC −26 %, ETH −39 %), which flatters any rule that can be short; and the
   6-hour rule's gain there came from its short side (+6.0 % from 10 trades)
   while its long side lost 3.7 %.
5. **Funding: keep the long side on spot.** Funding mostly flows from longs to
   shorts (about 13 % a year on BTC and 16 % on ETH, 2020–2025). The hybrid's
   shorts received a little (0.3–1.0 % of capital over four years); putting the
   long side on the swap instead cost 1.1–4.7 % of capital in funding, and the
   hybrid beat the all-perp design in 13 of 16 cases.
6. **The risk is real even without leverage.** BTC rose 138 % and ETH 151 %
   within 30 days in December 2020–January 2021; a 1x short without a stop
   would have been wiped out. With the study's ATR stops no simulated short came
   near that: the worst move against an open short was 18 %, the highest account
   leverage 0.84x, no liquidation.

**Recommendation.** Do not authorize a Phase 9 build. The mirrored trend shorts
do not earn their keep, and the one confirmed rule is a hypothesis, not a
result. Keep the Phase 7/8 product as decided — risk-managed long exposure plus
the news brake. Phase 9 deserves another look only with (a) a short rule
designed and pre-registered as a short rule, not a mirror, and (b) evidence from
a period nobody has seen yet (forward paper data), which is also the only honest
holdout now that the last 12 months are known. If the owner wants that evidence,
the cheap way is a paper-only account in the paper fleet (section 7).

## 2. What "long and short without leverage" means here

- **The instrument.** OKX's BTC-USDT-SWAP and ETH-USDT-SWAP are perpetual swaps:
  contracts that follow the coin's price, never expire, and are settled in
  USDT. One contract is 0.01 BTC or 0.1 ETH (OKX public instrument data). You
  can sell one without owning the coin — that is a short: it gains when the
  price falls and loses when it rises.
- **Funding.** By default every 8 hours (00:00, 08:00 and 16:00 UTC) one side
  pays the other: longs pay shorts when the rate is positive, shorts pay longs
  when it is negative; it keeps the swap's price next to the coin's. A position
  pays or receives if it is open at the settlement time (OKX may take up to about
  a minute to charge it), on its value at the mark price, and in isolated margin
  the payment comes out of that position's own margin. While a rate sits at its
  cap or floor OKX settles more often — every 4, then 2, then 1 hours — until it
  calms down. On 22 October 2026 OKX capped one settlement at ±0.375 % (BTC) and
  ±0.75 % (ETH), and it may change the caps at any time. From 2020 to October 2025
  (Binance's public history, the study's stand-in for OKX's), funding was
  positive 88 % of the time and averaged about 13 % a year on BTC and 16 % on
  ETH; 2021 was 31 % and 38 %.
- **Fees.** OKX's regular rates are 0.08 % (maker) / 0.10 % (taker) on spot and
  0.02 % / 0.05 % on USDT perpetual swaps; the study charged the taker rates.
  OKX's EEA users pay other spot rates, and an account's real tier should be
  read from the account itself.
- **"No leverage."** The money set aside for a short (its margin) equals the
  position's value when it opens: isolated margin at leverage 1. That is not
  riskless. A short's loss grows as the price rises, and its effective leverage
  rises with it — position value divided by what is left of its margin is
  `price / (2 x entry - price)`: 1.22x after a 10 % rise, 1.5x after 20 %, 3x
  after 50 %. With OKX's 0.4 % maintenance margin a 1x isolated short is
  liquidated after a rise of about 99 %. Spot longs have none of this: a spot
  long can fall to zero but never owes more than it cost.
- **So every short needs a protective stop that sits on the exchange** (it fires
  even when our program is down), placed the moment the short exists. That is
  the Sprint 3 design, mirrored: a buy stop above the entry.

## 3. The numbers (simulation, 2020 to October 2025; holdout October 2025 – October 2026)

Out of sample, walk-forward test windows from June 2021 to October 2025, after
fees (spot 0.10 %, swap 0.05 %), slippage (0.05 %) and funding. Calmar compares
return with the worst drawdown; above 0.5 is the gate.

| Family | Series | Long-only Calmar | With shorts (hybrid) | Short side on its own (profit factor) | 2022 long-only | 2022 with shorts |
|---|---|---:|---:|---:|---:|---:|
| S1 momentum | BTC 4H | 0.25 | 0.04 | 0.85 | −4.4 % | −0.4 % |
| S1 momentum | BTC 6H | 0.38 | 0.20 | 0.93 | −4.9 % | −3.9 % |
| S1 momentum | ETH 4H | −0.00 | −0.03 | 0.82 | −4.5 % | −3.9 % |
| S1 momentum | ETH 6H | 0.42 | 0.36 | 1.24 | −2.2 % | −1.7 % |
| S1+S5 | BTC 4H | 0.32 | 0.07 | 0.85 | −4.4 % | −0.3 % |
| S1+S5 (the confirmed long-only sleeve) | BTC 6H | 0.60 | 0.25 | 1.25 | −5.7 % | −0.7 % |
| S1+S5 | ETH 4H | 0.01 | −0.02 | 0.80 | −4.6 % | −4.4 % |
| S1+S5 | ETH 6H | 0.38 | 0.36 | 1.39 | −2.3 % | −1.3 % |
| S2 breakout | BTC 4H | 0.38 | −0.04 | 0.62 | −2.4 % | −4.3 % |
| S2 breakout | BTC 6H | 0.07 | −0.13 | 0.50 | −2.8 % | −2.6 % |
| S2 breakout | ETH 4H | 0.41 | **0.66** | 1.01 | −0.5 % | +2.0 % |
| S2 breakout | ETH 6H | 0.36 | **0.61** | 1.18 | −2.1 % | +3.0 % |
| S4 squeeze | BTC 4H | 0.11 | −0.04 | 0.54 | −2.1 % | −3.8 % |
| S4 squeeze | BTC 6H | 0.41 | 0.01 | 0.73 | −3.4 % | +0.2 % |
| S4 squeeze | ETH 4H | −0.14 | −0.13 | 1.02 | −2.3 % | −3.7 % |
| S4 squeeze | ETH 6H | 0.34 | 0.32 | 1.13 | −0.2 % | +0.7 % |

The untouched 12 months were opened only for the configurations that met every
walk-forward condition — the two S2 ETH rules, each in both designs (the two
designs share their trades, so they are two rules, not four results). The table
shows the final run; the first run, before the bug fix, gave the same verdicts
(ETH 6H +4.1 %, ETH 4H −5.0 %) and is kept in the ledger of the report.

| Rule | Walk-forward | Last 12 months | Long side there | Short side there | Verdict |
|---|---|---|---|---|---|
| S2 ETH 6H (hybrid) | +4.6 %/yr, max DD 7.5 % | +2.3 %, 28 trades, PF 1.29 | −3.7 % (18 trades) | +6.0 % (10 trades) | confirmed |
| S2 ETH 4H (hybrid) | +5.5 %/yr, max DD 8.3 % | −4.8 %, 42 trades, PF 0.59 | −5.8 % (22 trades) | +1.0 % (20 trades) | contradicted |

What else the study measured (details in the report):

- **The swap's own prices change nothing that matters.** Replaying the short
  side on OKX's perpetual-swap candles instead of spot moved no Calmar by more
  than 0.05; the swap traded between 0.1 % below and 0.3 % above spot in 98 % of
  hours.
- **The crash filter protects shorts.** The sizing halves positions while the
  price is more than 15 % below its 90-day peak. That looked like it would
  starve the shorts in a falling market, so we checked it after the first test
  run (recorded as an afterthought, never used for a verdict): without it the
  results were worse in 28 of 32 configurations — the sharp rebounds after a
  crash are exactly where shorts get hurt (the "momentum crash" known from the
  literature: Daniel and Moskowitz, 2016).
- **Funding stress.** Doubling every funding payment changes little for the
  hybrid (its shorts receive more); for the all-perp design it costs more.
- **OKX's funding against the proxy.** OKX keeps only months of public funding
  history, so the study used Binance's public history. Where both exist (July to
  October 2026) the two have the same sign 84–89 % of the time and the same level
  within 0.4 % a year.

## 4. The extra safety rules a long/short phase would need

Proposals for a reviewer to accept, change or reject — each must become code
with adverse tests, then pass an independent review and demo drills. They add
to the standing safety contract; nothing in it is relaxed except three items —
derivatives, margin and shorting — and only as far as rule S1 says. "Evidence"
points at this study or at OKX's own rules.

**Scope**

- **S1 — Only what is needed becomes representable.** Allowed in a Phase 9 demo
  scope: SWAP instrument type for exactly BTC-USDT-SWAP and ETH-USDT-SWAP,
  isolated margin, leverage 1, sell-to-open and buy-to-close on those two.
  Every swap order carries `tdMode: isolated` — OKX chooses the margin mode
  order by order, so cross margin must be impossible to send, not just unused.
  Still unrepresentable: production endpoints and `x-simulated-trading: 0`,
  withdrawals and transfers, leverage above 1, cross margin, spot margin and
  borrowing, coin-margined swaps, dated futures, options, other instruments,
  account-mode mutation by code, generic order or endpoint methods, LLM order
  authority, martingale and averaging down.
- **S2 — Longs stay on spot (the hybrid design).** The swap may only be short or
  flat; a buy order on the swap must be reduce-only. Evidence: funding cost the
  all-perp design 1.1–4.7 % of capital, and it did worse in 13 of 16 cases.
- **S3 — One position per coin.** Never long spot and short swap of the same coin
  at once (that is a hedge, not a trade, and doubles fees); a flip is close
  first, confirm flat, then open — never the other way round.

**Account set-up (the operator's job, checked by code)**

- **S4 — The operator sets the account mode, the margin mode and leverage 1 by
  hand; the code only reads them.** Before every entry the program reads the
  account configuration, the position mode and the leverage of the swap, and
  refuses to open a short unless they are exactly as approved; a mismatch
  disarms. OKX's account modes are Spot mode (1), Futures mode (2),
  Multi-currency margin (3) and Portfolio margin (4); swaps need 2, 3 or 4, and
  reduce-only orders work only in Futures mode and Multi-currency margin.
  Proposal: Futures mode, the simplest that offers both; that its spot trades
  stay plain cash trades (no borrowing) must be confirmed in demo.
  Leverage is a per-instrument setting that the program reads and never writes.
  OKX lets the account mode be switched by API once it has been set in the web
  app; the code keeps that switch unrepresentable all the same.
- **S5 — Net position mode.** One signed position per swap, so a long and a short
  can never coexist on it. (OKX switches the position mode only with every
  position closed and no order pending.)

**Sizing and limits**

- **S6 — Collateral at least equal to the position, at all times.** At entry: the
  short's isolated margin equals its notional, and spot long value plus all
  short notionals never exceeds account equity. While open: the short's
  effective leverage (`price / (2 x entry - price)`) must stay at or below 1.25x,
  which is what a stop no more than 11 % above the entry guarantees (rule S8),
  except when the price jumps through the stop.
  Evidence: the study's largest account leverage was 0.84x, but in 10 of the 32
  configurations at least one short moved more than 11 % against it before it
  closed (the worst 18 %), so this cap would have bound; a reviewer should weigh
  it against the strategies' ATR stops.
- **S7 — Shorts count against the same caps as longs, and BTC and ETH shorts are
  one bet.** Per-entry notional cap, open-position cap, entries per day, the
  daily loss lock and the allocator's correlation cap apply to shorts unchanged;
  a short on BTC and one on ETH count as one bet while the two coins move
  together.
- **S8 — No short without a bounded stop.** The stop must sit above the entry and
  no more than a fixed distance above it (proposal: 11 %, derived from rule S6);
  the risk manager rejects a short with no stop or a wider one. Evidence: the
  study requires a stop for every short; the largest one-hour spike was +29 %
  (BTC, 13 March 2020).

**Protection**

- **S9 — An exchange-side buy stop on every short, placed right after the fill.**
  The Sprint 3 contract mirrored: a stand-alone reduce-only conditional buy order
  on the swap, persisted before it is sent, an unknown outcome resolved by
  query, never duplicated; the stop guard alarms and flattens a short that has
  no live stop after N seconds. On OKX this is a stand-alone algo order
  (`order-algo`) that closes the position when it triggers; a stop attached to
  the entry order would only become active after that order fills. Stops that
  depend on a position are cancelled — and not restored — when the position is
  closed some other way, and a reduce-only order larger than the position is
  rejected whole, so the stop must be resized after every partial buy-back
  (the Sprint 3 design keeps the stop in step with the position).
- **S10 — The stop triggers on the swap's last price** (the price the backtest
  used), with the mark price as the documented alternative for the reviewer to
  weigh: mark price ignores brief spikes but can lag a real move. OKX offers
  last, index and mark as trigger prices (last is its default).
- **S11 — A liquidation tripwire.** The exchange reports a liquidation price for
  every position; for a 1x short it sits near twice the entry. If it is ever
  closer than 80 % above the entry, or the mark price comes within 30 % of it,
  the program alarms, buys the short back and disarms — that can only happen if
  leverage or margin is not what rule S4 checked. OKX liquidates on the mark
  price when a position's maintenance-margin ratio reaches 100 %, isolated
  positions in steps, and reports an estimated liquidation price (`liqPx`) for
  each position; its help pages warn that "even 1x leverage can be liquidated
  under extreme market conditions" — funding taken from an isolated margin
  moves the liquidation price too.
- **S12 — Kill switch and exits cover the swap.** The kill switch buys every
  short back (reduce-only market) before it cancels that short's stop, never the
  other way round; exits, stops, the kill switch and reconciliation are never
  delayed by anything new (the news overlay included).

**Funding and reconciliation**

- **S13 — Funding is cash the reconciliation expects.** Funding payments every 8
  hours are booked as their own entries, counted in P&L and in the daily loss
  limit, and reconciled against the exchange's bills; an unexplained balance
  change still fails closed. Which account records OKX writes for funding,
  and when, must be checked in demo before this rule is built; settlements
  every 4, 2 or 1 hours (rates at their cap) must reconcile as well as the
  normal 8-hourly ones.
- **S14 — A funding brake on new shorts.** No new short while the current funding
  rate is below −0.05 % per 8 hours (shorts paying about 55 % a year); 2020–2025
  that happened at about 0.2 % of the settlements on both coins (the 1st
  percentile was about −0.02 %), so the brake costs almost nothing and stops the
  worst crowded-short moments. Funding never closes an open position by itself
  (stops and exits do).

**Foreign events**

- **S15 — Anything the program did not do is foreign.** A position change that no
  own order explains — an auto-deleveraging, a liquidation, a manual trade —
  disarms and alerts, exactly like today's foreign-order rule. OKX can
  auto-deleverage — close profitable positions without warning when its
  insurance fund runs low; a 1x position ranks low in that queue but is not
  exempt, and each position reports its place in it (`adl`, 0 to 5).

**Data**

- **S16 — The swap's data must be as healthy as spot's.** Stale swap prices,
  funding or position data block new shorts (never exits), with the same
  staleness rules as the spot feed; contract sizes are converted with the
  exchange's contract value and lot size, and "flat" means fewer than one lot in
  contracts (the flatness rule of today, in contracts).

## 5. What would change in the system — and what must not

A long/short phase touches the reviewed safety core in every layer. Each item is
a separate, reviewed pull request that only the owner can merge.

| Layer | Change | Why it is risky |
|---|---|---|
| `app/exchange` | the demo endpoint allowlist gains the swap order, algo-order, position, account-configuration and bill paths for two instrument ids; nothing generic | widens what the code can send to OKX |
| `app/execution` | signed positions in contracts, the short protective stop, flips as two orders on two instruments, funding in the ledger and reconciliation, the liquidation tripwire, foreign-change detection | the order path itself |
| `app/risk` | rules S6–S8 and S14 as final-veto checks | the final veto |
| `config/` | per-coin short caps next to today's caps | trading caps |
| operator CLI | status, disarm and kill switch cover the swap | the human's emergency tools |
| governance | `CLAUDE.md`, `PROJECT_RULES.md`, `AGENTS.md` | written and approved by the owner only |

Prerequisites that are open today and must be closed first, whatever the
strategy: exchange-side protective stops independently reviewed and demo-drilled
(plan rows S3 and G3); position persistence across restarts (open item 6 in
`CLAUDE.md` — today a restart closes an open position, for shorts too);
reviewed migrations and backups (open item 7); and the Phase 7 and Phase 8 gates
for the long-only system.

## 6. The review path

1. **This study** (done): numbers, rules, path. It approves nothing.
2. **The owner decides on the evidence.** Recommendation: no Phase 9 build now
   (section 1). If no, stop here; revisit with a new, pre-registered short rule
   and forward evidence.
3. **If yes: the owner amends the safety contract in writing** — a Phase 9 demo
   scope in `CLAUDE.md` and `PROJECT_RULES.md` naming exactly what rule S1
   allows and what stays forbidden. Agents cannot write or approve this.
4. **An independent design review** of sections 4 and 5 (Codex, or a second
   Claude session with `/code-review`), findings resolved in this document.
5. **The prerequisites of section 5 closed**, each with its own evidence.
6. **The build**, in bounded pull requests (exchange allowlist, execution,
   risk, CLI), each with adverse tests and an independent review; the owner
   merges.
7. **Demo validation on a NEW demo account** with the account mode, margin mode
   and leverage set by hand: drills — a short opens and its exchange stop
   appears; the program is killed with a short open and the stop still fires; a
   funding settlement reconciles; the kill switch buys the short back; a
   wrong leverage or account mode refuses entries; a manual change on the account
   disarms. Then at least 60 days of demo running within the expected ranges.
8. **A separate owner decision** before any real money — only after the long-only
   system has passed Phase 8 and run within expectations, with tiny capital and
   a pre-agreed scale ladder.

## 7. Decisions for the owner

- **Phase 9.** Recommendation: do not authorize a build now (section 1).
- **Forward evidence for the one rule that passed.** A paper-only account in the
  paper fleet — S2 on ETH 6-hour bars, long on spot and short on the swap, on
  public prices with OKX's public funding, simulated fills, no derivatives
  access, no key — would test it on months nobody has seen. It is new scope (the
  fleet has no short side today) and its evidence would be thin for years at
  this trade rate (about 25 trades a year). Recommendation: not now; revisit at
  the Phase 7 review (row G7) if the long-only S2 accounts in the fleet hold up.
- **Can you trade perpetual swaps at all?** Whether OKX offers USDT perpetual
  swaps to your account (your country of residence decides, not where the server
  stands) and from the Singapore server is a question for OKX and, if needed, a
  lawyer — this study cannot answer it. What OKX publishes: its restricted
  list (8 July 2026) names Afghanistan, Canada, Cuba, Hong Kong, Iran, India,
  Japan, Malaysia, Nepal, North Korea, Syria, Crimea, Donetsk and Luhansk, parts
  of the United States and Uzbekistan, and limits derivatives in Australia,
  Brazil, South Korea and the UK; Lebanon is not on it. Separately, OKX
  Singapore delisted USDT-margined perpetuals for its users on 20 May 2026
  (replaced by USD-settled "X-Perps"). OKX's own warning: "Trading perpetual
  futures involves substantial risk of loss and is not suitable for all
  investors." Recommendation: ask OKX once, before any Phase 9 work starts.
- **For information — the holdout is used up for long/short questions.** Its
  falling direction was known before it was opened. Recommendation: a future
  long/short study judges itself on forward data only.

## 8. Sources

- This study: `docs/research/LONG_SHORT_STUDY_REPORT.md`, `docs/research/long_short_results.json`,
  `docs/research/okx_swap_reference_2026-10-22.json`, `research/longshort*.py`,
  `research/strategies/shorts.py`.
- Earlier research: `docs/research/ENSEMBLE_V1C_REPORT.md` (Sprint 2c),
  `docs/research/ALLOCATOR_V2_REPORT.md` (R5b), `docs/MASTER_PLAN_2026-10-20.md`
  (strategic note after Sprint 2b).
- Momentum crashes: K. Daniel and T. Moskowitz, "Momentum crashes", Journal of
  Financial Economics 122 (2016). Time-series momentum: T. Moskowitz, Y. H. Ooi
  and L. H. Pedersen, "Time series momentum", Journal of Financial Economics 104
  (2012).
- OKX, public pages read on 22 October 2026 (not legal advice):
  funding — https://www.okx.com/en-us/help/iv-introduction-to-perpetual-swap-funding-fee,
  https://www.okx.com/en-us/help/perps-funding-fee-mechanism,
  https://www.okx.com/en-eu/help/important-update-revision-of-the-funding-rate-formula-for-okx-perpetual;
  fees — https://www.okx.com/en-us/help/trading-fee-rules-faq,
  https://www.okx.com/en-us/learn/what-is-okx-perpetual-futures,
  https://www.okx.com/en-us/help/what-are-the-new-trading-fees-for-eea-users;
  API (account modes, `tdMode`, `set-leverage`, `set-position-mode`, `reduceOnly`, `attachAlgoOrds`, `liqPx`, `adl`, demo
  trading) — https://www.okx.com/docs-v5/en/;
  liquidation — https://www.okx.com/en-us/help/forced-liquidation-faq;
  auto-deleveraging — https://www.okx.com/en-us/help/iv-introduction-to-auto-deleveraging-adl;
  stops after a position closes — https://www.okx.com/en-us/help/how-do-i-modify-take-profit-tp-and-stop-loss-sl;
  demo swaps — https://www.okx.com/en-eu/help/how-to-conduct-contract-simulation-trading-transactions;
  restricted jurisdictions — https://www.okx.com/en-us/help/risk-compliance-disclosure,
  https://www.okx.com/en-us/help/terms-of-service, https://www.okx.com/en-sg/help/x-perps-sg.
  Contract sizes, margin tiers and funding caps: OKX's public API, recorded in
  `docs/research/okx_swap_reference_2026-10-22.json`.
