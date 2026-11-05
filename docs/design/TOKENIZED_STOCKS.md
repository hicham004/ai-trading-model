# Design — what must change before a tokenized US stock is traded, even in demo

Plan row R21 (`docs/TRADER_PLAN_2026-11-05.md`, sections 2.8 and 6.2). Written 2026-11-05 on
branch `plan/auto`, beside the feasibility report `docs/research/TOKENIZED_STOCKS_FEASIBILITY.md`
and the log-only collector (`research/xstocks_data.py`, `scripts/collect_xstocks.py`,
`docs/runbooks/XSTOCKS_DATA.md`).

**Status: DESIGN ONLY.** Nothing under `app/`, `config/` or `migrations/` changes with this
document, the app's instrument allowlist stays `BTC-USDT` / `ETH-USDT`, and no order on any
X-pair is authorized by it. Every change below touches the reviewed safety core
(`app/okx`, `app/exchange`, `app/execution`, `app/risk`, `app/shadow`, `config/`), so each needs
the owner's explicit go, its own branch, an independent review and demo validation before it
reaches any account (section 9). The safety contract is unchanged: demo only
(`x-simulated-trading: 1` on every authenticated request), SPOT cash, long only, leverage 1.0,
no LLM anywhere near an order, fail closed on ambiguity, never a blind retry.

Every statement about today's behaviour was checked against the code on `plan/auto` (file
references below). Every statement about the instruments comes from OKX's public pages as read on
2026-11-05 by the collector (parameters, candles, books, price limits) and once by hand with the
demo header (the demo list); the product facts (issuer, rebasing, Reg S, eligibility) come from
the plan's section 2.8 and are not checkable from market data.

## 1. The answer on one page

**What an X-pair is.** `XNVDA-USDT` is a SPOT pair on OKX whose base asset is a token issued by
Backed (the Kraken group's xStocks): a Regulation S price-exposure certificate from a Jersey
issuer, no voting rights, dividends paid as a balance increase of the token ("rebasing") net of
30 % US withholding, redeemable with the issuer only by qualified investors. It trades 24/7
against USDT with a live order book; while the US market is shut its price is OKX's "last close
plus a market estimate" plus whatever the book does. OKX marks it `instCategory` 3, lot size
0.00001 or 0.000001 share, minimum 0.01 or 0.001 share, price band 2 % at the open and 1 %
floating (BTC-USDT: 1 % / 0.5 %), fee group 12 (the same as BTC-USDT; the rate for stock pairs is
not published), `openType` `pre_quote`, `lever` 10 on some rows (margin is forbidden here and
stays unrepresentable). 165 live USDT pairs on the live venue, 19 in the demo environment.

**What the current system assumes that these pairs break.** Nine things, each with the code that
assumes it (section 3): (1) the instrument universe is BTC-USDT and ETH-USDT, in six allowlists,
one config file and the immutable account identity; (2) a balance changes only through our own
fills, so a dividend rebase reads as an unexplained balance, reconciliation goes inconsistent and
the supervisor disarms for good; (3) "flat" in the safety core still means `position > 0` is
open, and these lot sizes are finer than BTC's; (4) the clock has no notion of a session, so a
rule would enter at 03:00 New York on an estimate-priced quote; (5) orders are capped by a 0.2 %
slippage band of our own, not by the venue's 1-2 % band, so an exit in a fast market can be
rejected by the venue's limit; (6) the stop is evaluated on every confirmed candle, weekends
included, on prices the feasibility data shows wandering 1-8 % below Friday's close; (7) nothing
watches an instrument's `state` after arming; (8) the demo rows differ from the live rows (an
opening band of 10 % against 2 %, later listing dates, unknown book depth); (9) the product's
own risks (issuer, redemption, withholding, eligibility, delisting) are not engineering
questions, and the owner's two-minute check (`docs/OWNER_CHECKLIST.md`, step 9) is still open.

**The proposal.** Six reviewed changes (section 4), in an order where each one is small and
testable on its own: the allowlist and identity as one explicit scope change; rebasing-aware
reconciliation that recognises only a documented, bounded balance event and stays inconsistent
on anything else; the lot-precision flatness of the R14 design (its part A is a prerequisite,
not a part of this); a session rule in the risk manager (new entries only while the US regular
session is open, exits always) with the calendar in persisted config; price-band-aware orders
that clamp every exit to the venue's published limit and say so; and an instrument-state watch
that blocks entries, and alerts, the moment a pair is not `live`. Plus the demo validation plan
on the 19 demo pairs under a new account name (section 10).

**What this does not do.** It does not propose a strategy, a timeframe or a size for these pairs;
it does not touch `ma_crossover`, the 0.60 floor or any cap; it does not advance a phase. The
decision gate for all of it is the plan's section 6.2, step 4, after 60-90 days of collected data.

## 2. The product, as the public data shows it (2026-11-05)

| What | Live venue | Demo environment | Why it matters here |
|---|---|---|---|
| Pairs | 165 live X-USDT (194 Stocks instruments with USDC twins); the 15 most traded hold 79 % of 141.7 M USDT a day | 19 X-USDT (XAMD, XASML, XAVGO, XCSCO, XDELL, XGME, XGOOGL, XHIMS, XINTC, XIWM, XLITE, XMRVL, XMSTR, XMU, XNVDA, XPLTR, XQQQ, XSPCX, XTSM) plus AAPLX, AMZNX, TSLAX and USDC/USD variants | nine of the liquid 15 exist in demo (XGOOGL, XQQQ, XINTC, XMSTR, XNVDA, XSPCX, XMU, XAMD, XMRVL); a demo account can only ever rehearse those |
| Lot, minimum, tick | 0.00001 or 0.000001 share; 0.01 or 0.001 share; 0.01 (XSNDK 0.1) | XNVDA: the same | in units the lot is coarser than BTC's (0.00000001 BTC) and the minimum finer than BTC's (0.00001 BTC); the fee is charged in shares at the venue's own precision, so fee dust floors to a sellable lot more often than in BTC, but a remainder below the minimum is still unsellable |
| Price band | `initPxLmtPct` 0.02, `floatPxLmtPct` 0.01, `maxPxLmtPct` 0.02; the public price-limit page gave XNVDA 196.71 / 200.69 around 198.75 (-1 % / +1 %) | XNVDA: `initPxLmtPct` 0.1 (10 %), floating 0.01 | an order outside the band is rejected or not filled; our own 0.2 % cap sits inside it, a deep stop does not |
| Fee group | 12, as BTC-USDT | 12 | the rate for stock pairs is not published; the owner reads it in the app |
| Listing | 2026-07-16 for the 15 chosen; `contTdSwTime` one hour later | XNVDA 2026-07-24 | 112 days of history: a study needs the underlying stocks' history as a proxy (plan 6.2, step 4) |
| State | all `live`; `upcChg` carries scheduled parameter changes (XNVDA: a new `maxMktSz` from 2026-11-06 18:44 UTC) | `live` | the instruments page is the delisting / suspension signal |
| Weekend behaviour | the token trades every weekend hour at 16-36 % of a weekday's volume; it fell more than 2.4 % below Friday's close in 22 % of pair-weekends, more than 5 % in 5 %; the Monday 09:00-10:00 hour moved it by a median 0.1-2.8 % and up to 10.7 % | unknown | a stop evaluated on weekend candles sells on estimate-priced quotes; a position held over the weekend meets the open's re-anchoring |
| Spread and depth | 0.8-8 bps; 3-126 K USDT within 0.5 % per side (one pre-market snapshot) | unknown; demo fills come from a separate thin book (plan 2.9) | fine for 10-100 USDT demo orders; the live sizes of the Trader policy fit only the top names |

## 3. What the code assumes today, and where

| # | Assumption | Where (plan/auto) | What an X-pair does to it |
|---|---|---|---|
| 1 | The tradable universe is BTC-USDT and ETH-USDT | `app/okx/client.py:38` (`ALLOWED_INSTRUMENTS`, the candle client); `app/exchange/okx_public_ws.py:60` (`SUPPORTED_INSTRUMENTS`, the public feed); `app/execution/account_validation.py:75` (the arming gate refuses any other instrument); `app/paper/config.py:70`; `app/news/schema.py:134` (the news agent's `Instrument` literal and asset map); `app/api/main.py:200`; `config/shadow_period.json` (`instrument`); `DEMO_INSTRUMENTS` in `app/config.py:275`; the identity in `app/execution/identity.py` (`instruments` is part of the immutable account identity) | every gate fails closed, by design. Widening is a scope change (section 4.1) and needs a new account name |
| 2 | A base or quote balance changes only through our own fills and fees | `app/execution/reconcile.py:323-340` (`_check_balances`: `expected = baseline + net(fills)`; a difference above `_BALANCE_TOLERANCE` counts as unexplained) and `:230` (`consistent` requires zero unexplained); `app/shadow/supervisor.py` (an inconsistent reconciliation means permanent disarm, `CLAUDE.md`, Phase 6a) | a dividend rebase (a balance increase without a fill) is an unexplained balance: entries blocked, supervisor halted until the operator intervenes. Correct as a default; useless as a steady state for an asset that rebases quarterly (XSPY, XQQQ, most of the 15 pay dividends) |
| 3 | `position > 0` is an open position in the safety core | `app/execution/driver.py:517-523` (the per-candle stop check and the exit gating read `position_summary`), `app/execution/precision.py:131` (`is_flat` floors to the lot but is used by reporting only; `docs/design/POSITION_PERSISTENCE.md`, section 5.4) | the same fee-dust problem as BTC, with other numbers: a 0.05-share entry (10 USDT of XNVDA) pays 0.00005 share in fee, which floors to a sellable lot but below the 0.01 minimum. R14 part A (a sellable position exists only when the lot-floored size is at least the minimum) is a prerequisite |
| 4 | Time has no session: a confirmed candle is actionable whenever it closes | `app/execution/driver.py:500-560` (`step`: every actionable candle may produce an entry); `app/risk/manager.py` (`RiskContext` knows `now` and `data_time`, nothing about a venue session) | a rule would enter at any hour, on a weekend, on a US holiday, on the estimate-priced quote |
| 5 | Our own price band protects the order | `app/execution/runtime.py:331-336` (entry: a marketable limit at `ask x (1 + demo_price_band)`), `:410-414` (exit: `bid x (1 - band)`), `app/config.py:316` (`DEMO_PRICE_BAND`, default 0.002) | the venue's band is 1 % floating / 2 % at the open; an exit whose limit falls below the venue's `sellLmt` is rejected, and the reviewed rule is never to blind-retry, so the position stays until the next candle |
| 6 | The stop is evaluated on every confirmed candle | `app/execution/driver.py:517-534` (`candle.low <= stop_loss` on every confirmed candle, weekends included) | a weekend candle low under the stop sells into a thin, estimate-priced book; the feasibility data says 22 % of pair-weekends fall more than 2.4 % below Friday's close |
| 7 | An instrument validated at arming stays tradable | `app/execution/account_validation.py:77-82` (`is_tradable()` checked once in the startup gate) | a suspension, a delisting notice or a scheduled parameter change (`upcChg`) is not seen until an order is rejected |
| 8 | Demo and live rows describe the same instrument | the arming gate reads the demo instruments page with the demo header | the demo rows differ (10 % opening band, later listing); a demo drill proves the code path, not the live band behaviour |
| 9 | The product is a currency pair with no issuer | everything | voting, dividends, withholding, redemption, delisting, regional eligibility: owner questions, listed in section 4.7 |

## 4. The reviewed changes

Each change: what it does, its invariants, where it lives, the adverse tests it must pass. Order
of building in section 8.

### 4.1 The instrument allowlist and the identity, as one explicit scope change

- A single reviewed change widens the allowlists of row 1 for an explicit list of X-pairs
  (recommendation: the demo subset of the liquid 15, nothing else), with a `config/` entry for
  the demo-xstocks run (its own file, like `config/shadow_period.json`: instrument, timeframe,
  caps that may only tighten, the session calendar of 4.4), and a new account name (the identity
  includes `instruments`, so `demo-shadow-1h` cannot be reused; `demo-xstocks-<timeframe>`).
- Invariants: BTC-USDT and ETH-USDT behaviour is unchanged; every refusal on an unknown
  instrument stays; the news agent's instrument map is NOT widened (log-only, and news gating of
  entries is not authorized); the paper fleet and the research sandbox are untouched; `lever`
  stays 1.0 and the margin-free account level `1` stays required.
- Tests: the account-partition guard, the arming gate and the reconciliation with an X-pair in
  the configured instruments; a mixed configuration (BTC + an X-pair) refused in the shadow
  config; the identity hash changes when the list changes.

### 4.2 Rebasing-aware position accounting and reconciliation

Today a balance that moves without a fill is unexplained, reconciliation is inconsistent and new
entries are blocked; the supervisor halts for good. That must stay the default. The change adds
one explained cause, under strict conditions:

- **A balance event is recognised only from the venue's own record.** The reconciler reads the
  account bills (`GET /api/v5/account/bills`, a read-only endpoint that is NOT on today's demo
  allowlist in `app/exchange/okx_demo_endpoints.py`; adding it is itself a safety-core change,
  read-only, with the same header and host rules) and classifies each bill by its type. A bill of
  the documented rebase/dividend type for a configured X-asset becomes a `rebase` record in the
  ledger (asset, amount, time, bill id, idempotent on the bill id), and `_check_balances` adds
  recorded rebases to the expected balance. Any other bill type, any amount outside a bound
  (recommendation: at most 2 % of the held position per event, at most one event per asset per
  day) and any rebase on an asset we do not hold stays unexplained, so the fail-closed path is
  unchanged for everything but the one documented case.
- **OKX has not documented the bill type.** The feasibility report could not read it from public
  data. Before this change is coded, a demo observation is needed: hold a demo position in a
  dividend-paying pair (XSPY, XQQQ or a dividend stock among the 19) across an ex-dividend date
  and record what the bills page shows and whether the demo environment rebases at all. If demo
  does not rebase, the recognition cannot be validated in demo and the change waits for a later
  phase; the report must say so.
- **The position after a rebase.** The ledger's position is derived from fills; a rebase adds to
  it through the `rebase` record (the same derivation, one more record type), so the stop
  evaluation, the exit size (`base_balance` on the exit path) and the exposure count see the
  venue's true holding. The stop level is unchanged (a cash dividend lowers the stock's price by
  the dividend; the token's price follows and the rebase compensates the holder; the rule's stop
  is a price, so a stop under the ex-dividend drop is an accepted, measured imperfection to be
  reported, not hidden).
- **Never read as foreign or wrong scope.** A rebase is not a fill: the fill matching
  (`reconcile.py:150-200`) is untouched, so a rebase can never create a `foreign` or
  `wrong_scope` count; it can only be `unexplained` (today) or `rebase` (after the change).
- Tests: a rebase bill of the documented type within bounds explains the balance; the same bill
  twice is one record; an unknown bill type, an oversized amount, a rebase on an unheld asset and
  a rebase without a bill all stay unexplained and block entries; a rebase while an exit intent is
  open; the ledger position after a rebase matches the venue balance to the lot.

### 4.3 Lot precision and flatness (prerequisite: R14 part A)

`docs/design/POSITION_PERSISTENCE.md`, section 5.4 (a sellable position exists only when the
lot-floored size is at least the venue minimum; dust and an unsellable remainder are flat)
applies unchanged, with the X-pairs' own numbers: lot 0.00001 or 0.000001 share, minimum 0.01 or
0.001 share, fee charged in the base asset at the venue's own precision. The tests of that design
gain one parametrisation per X lot/minimum pair, including the case where the fee dust floors to
a non-zero lot that is still below the minimum (sellable by lot, unsellable by minimum: flat).
Nothing else is needed here; building R14 part A first is the recommendation of that design and
of this one.

### 4.4 A session rule: new entries only in US regular hours, exits always

- A deterministic veto in the risk manager (`app/risk/manager.py`): `RiskContext` gains
  `session_open: Optional[bool]`; for an instrument with a session calendar, an entry is refused
  unless `session_open` is True. The driver computes it from the exchange clock (never the
  laptop's) against a calendar read from persisted config (the NYSE full-day closures and early
  closes, the same list the collector carries in `research/xstocks_data.py`, moved into
  `config/` as data, never a code constant: the timeframe precedent of Phase 6a). The session is
  09:30-16:00 New York on trading days, 09:30-13:00 on early-close days; a candle that closes
  at 16:00 is outside (an entry at the close is held overnight, which the rule forbids).
- Exits are untouched: the stop check and the FLAT exit run on every confirmed candle as today
  (the plan's "exits always"). The weekend stop behaviour is 4.6.
- With 1H candles the entry decisions inside the session are at 10:00, 11:00, 12:00, 13:00,
  14:00 and 15:00 New York; whether a rule works on that grid is the later study's question.
- A missing or expired calendar fails closed: no entries, an ALERT, the daily report says why.
- Tests: entries refused at 09:00, 16:00, on a Saturday, on Thanksgiving, after 13:00 on the day
  after Thanksgiving, on a date past the calendar's end; allowed at 10:00 on a trading day; exits
  allowed in every case; the DST change weeks (March and November) on the exchange clock.

### 4.5 Price-band-aware orders

- Before every exit the driver reads the venue's price limit (`GET /api/v5/public/price-limit`,
  a public endpoint; through the demo REST client under the same host and header rules, or
  through the public client) and clamps the limit price to `sellLmt` when `bid x (1 - band)` is
  below it. The order is then always inside the venue's band; the event `exit_price_clamped`
  records both prices. Entries are clamped to `buyLmt` the same way (a tightening: never a price
  the venue would refuse).
- When the venue still rejects the order (the band moved between the read and the send), the
  existing rule holds: no blind retry; the rejection is recorded; the next candle tries again
  with a fresh read. The daily report counts clamps and rejections per instrument, which is the
  measure of how often the band bound.
- The exchange-side stop of Sprint 3 (a stand-alone conditional SELL) triggers into the same
  band: its trigger price must sit inside the floating band to be executable at once, and the
  design review of Sprint 3 must add the X-pair case (a gap through the band leaves a triggered
  but unfilled stop; the software path above then does the clamped sell).
- `demo_price_band` (0.2 %) stays as it is; the venue's band is the outer limit, ours the inner.
- Tests: a bid 3 % below the last price with `sellLmt` 1 % below: the exit goes at `sellLmt`;
  a price-limit read that fails: the exit goes unclamped and the failure is recorded (never a
  skipped exit); a rejection by the venue is not retried in the same cycle; a buy clamped to
  `buyLmt`.

### 4.6 The weekend reference price

- The plan's rule stands: exits always, including the stop on weekend candles. The data says
  this will sell on weekends at prices that often reverse on Monday; the right answer is not to
  disable the stop (a position without a stop is the one thing the contract forbids) but to size
  and to choose: the Trader policy's per-trade cap and ATR stop take the weekend wander in as
  volatility, and the later study must measure its rules on these pairs with weekends in the
  data, not on the stock's exchange-hours history alone.
- The driver labels every weekend and holiday candle it acts on (`session_closed: true` in the
  event payload), and the daily report counts exits made while the US market was shut, so the
  cost of the rule is visible from the first demo day.
- No entry can happen outside the session (4.4), so no position is opened on an estimate price.
- Tests: a stop breached on a Saturday candle exits and is labelled; the report counts it.

### 4.7 Corporate actions, instrument state, issuer and venue risk

- **Instrument state.** The driver re-reads the instruments page at each reconciliation
  interval (it already holds the metadata); a configured pair whose `state` is not `live`, or
  whose `upcChg` lists a change to `lotSz`, `minSz`, `tickSz` or the band within 24 hours, blocks
  new entries and raises an ALERT (the shadow supervisor's existing ALERT path). Exits keep
  trying while the venue accepts orders; a `suspend` state leaves the position unmanageable, which
  the ALERT says in words. Tests: `suspend`, `preopen`, a scheduled `lotSz` change, a pair that
  disappears from the page.
- **Splits.** A split rebases the balance by the ratio and divides the price; the ledger's stop
  level and position would be wrong by that ratio. The rebase recognition of 4.2 must refuse an
  event outside its 2 % bound, so a split lands as unexplained: entries blocked, ALERT, operator.
  That is the intended behaviour; a reviewed "instrument event" acknowledgement (the operator
  confirms the ratio, the ledger is rescaled, the stop recomputed) is a later change, after one
  has been seen in demo. Until then a split on a held pair is an operator incident.
- **Delisting, mergers, ticker changes.** OKX's notices are the only source (the changelog watcher
  of R6 can be pointed at the listing notices page as a second feed); the instruments page
  reflects them as `state` changes or a vanished id. The rule: never hold a position into a
  delisting; the operator exits by the operator CLI (`--disarm`, then the exit path) when a notice
  names a held pair. A merger that converts the token into cash or another token arrives as a
  balance event outside the bound: unexplained, ALERT, operator.
- **Issuer and venue risk (owner's questions, not code).** The token is a claim on Backed, not on
  the company; redemption is for qualified investors; dividends arrive net of 30 % withholding;
  the SEC's exemption keeps this product class offshore and ESMA warns about it; OKX restricts the
  product by region, and whether the owner's account (Lebanon) and the Singapore VPS may trade it
  is answered only by the app (`docs/OWNER_CHECKLIST.md`, step 9). None of these has an
  engineering answer; the design assumes the owner has read the plan's section 2.8 and accepts
  them in writing before step 1 of section 8 starts.

## 5. The 19 demo pairs and the demo environment

Read on 2026-11-05 through the public instruments page with the demo header and no key (the same
filter as the live list: `instCategory` 3, an X-prefixed `-USDT` id, `live`): XAMD, XASML, XAVGO,
XCSCO, XDELL, XGME, XGOOGL, XHIMS, XINTC, XIWM, XLITE, XMRVL, XMSTR, XMU, XNVDA, XPLTR, XQQQ,
XSPCX, XTSM; plus AAPLX, AMZNX and TSLAX (older-style ids) and USDC/USD-quoted variants, which the
collector ignores and this design does not consider. The demo category 3 also tags AVAX, BCH and
SCR pairs, which is a demo-side quirk, not a stock. Re-read the list by hand with one public GET
and the demo header before any demo work; the collector never sends that header.

Nine of the liquid 15 are in demo (XGOOGL, XQQQ, XINTC, XMSTR, XNVDA, XSPCX, XMU, XAMD, XMRVL),
so the demo validation can rehearse the real candidates. What demo cannot prove: the live band
(10 % opening band in demo against 2 % live), the live depth (demo books are thin and separate,
plan 2.9), the fee rate, and whether the demo environment rebases dividends at all (4.2).

## 6. What can go wrong, and the fail-closed answer

| Event | Today | After the changes |
|---|---|---|
| Dividend rebase on a held pair | unexplained balance, inconsistent, permanent disarm | recognised from the bill within bounds; otherwise the same as today |
| Split, merger, token swap | unexplained, disarm | unexplained, disarm, ALERT names the pair; operator rescales after a reviewed acknowledgement |
| Weekend crash through the stop | the stop sells at the next confirmed candle | the same, clamped to the venue's band, labelled, counted |
| Venue rejects the exit on the band | rejection recorded, no retry, next candle | clamp first; a rejection is still never retried blind |
| Pair suspended with a position open | orders rejected until the operator notices | entries blocked and ALERT at the next reconciliation; exits attempted; the position is named as unmanaged |
| Session calendar missing, expired, or the clock drifts | no notion of a session | no entries, ALERT; the clock-drift gate of Phase 5 is unchanged |
| The demo header, host or account checks | unchanged | unchanged: a new account name, the same partition guard, the same `x-simulated-trading: 1` on every request |

## 7. Tests (adverse cases first), per change

Listed under each part of section 4; in addition, end to end on the fake REST of
`tests/test_demo_driver.py`: a full round trip on `XNVDA-USDT` with lot 0.00001 and minimum 0.01
at a 10 USDT notional, a dividend bill between entry and exit, a weekend stop breach, a clamped
exit, a suspension, and the identity refusing to reuse `demo-shadow-1h`.

## 8. Order of work (recommendation)

0. The data gate: 60-90 days of the collector's data and the regenerated feasibility report;
   the owner's checklist step 9 answered; the product risks of 4.7 accepted in writing.
1. R14 part A (lot-precision flatness) built, reviewed and deployed on its own, as that design
   recommends; it unblocks Phase 6a's evidence anyway.
2. The demo observation of a dividend (4.2) on a throwaway demo position in a dividend-paying demo
   pair, by the operator, documented; it decides whether 4.2 can be validated in demo.
3. Change 4.1 (allowlist, config file, new account name) with 4.7's state watch: small, one
   review.
4. Change 4.4 (session rule) and 4.6 (labels): small, one review.
5. Change 4.5 (band-aware orders) together with the Sprint 3 stop's X-pair case: one review,
   demo drills.
6. Change 4.2 (rebasing) once step 2 has shown what the bill looks like.
7. The demo validation plan (section 10), then the usual gates for a separately approved phase
   (plan 6.2, step 5). Nothing before step 7 places an order on an X-pair; step 7 places demo
   orders only, under the owner's explicit go.

## 9. Review path

`AGENTS.md` order for every change: safety regressions first (the header, the hosts, the
endpoint allowlist, the caps that may only tighten, the kill switch, the partition guard, the
fail-closed reconciliation), then scope (each change names its row and the owner's go), then
correctness, tests, documentation; the `docs/CODE_REVIEW.md` checklist; an independent reviewer
(Codex or another agent, as for Phase 5 and the R14 design); the owner merges. The runner never
builds any of it: every part touches `app/execution`, `app/risk`, `app/exchange`, `app/okx`,
`app/shadow` or `config/`.

## 10. Demo validation plan

Under a new account name on the demo key, never the shadow account, never while the shadow run
holds a position, on one demo X-pair at a 10 USDT cap: (a) `--gate-check` and the identity;
(b) one armed round trip inside the session, flat at the lot and the minimum afterwards;
(c) an entry attempt outside the session refused; (d) a stop breach on a weekend candle: the exit
is clamped and labelled; (e) an order placed at a price outside the band: rejected by the venue,
recorded, not retried; (f) if demo rebases: the dividend observation of 4.2; (g) 481-style
consistent reconciliations over a weekend. Each drill's log lines go into a validation record
like `docs/PHASE5_VALIDATION.md`.

## 11. The owner's decisions (none needed now)

- Whether to start the collector's laptop task now (free; `docs/runbooks/XSTOCKS_DATA.md`).
  Recommendation: yes; the data gate cannot be reached otherwise.
- Whether, at the data gate, to open the strategy study on the underlying stocks' history and the
  review of this design. Recommendation: decide then, with the regenerated report; and exclude
  leveraged ETF tokens (XSOXL and the like) from any candidate list, as pre-registered here.
- Whether to accept the product risks of 4.7 in writing before any build. Recommendation: read
  the plan's section 2.8 again at the gate; this design assumes "no" until told otherwise.
