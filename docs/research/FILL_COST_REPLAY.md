# Fill-cost replay from OKX's public tick and order-book archive (plan row R22)

**Status: research only; a recommendation for the cost model of FUTURE studies, nothing re-judged.**
Nothing here trades, sizes or approves anything, and nothing here changes the research engine, the
paper fleet or the demo shadow run. Written 2026-11-05 on branch `plan/auto`. Spec:
`docs/TRADER_PLAN_2026-11-05.md`, section 2.9; row R22 of `docs/PLAN_STATUS.md`.

What this report rests on: OKX's own archive of BTC-USDT and ETH-USDT SPOT market data for the ten
UTC days 2026-10-25 to 2026-11-03 — every trade (7.1 million), every 400-level order-book update
(64.2 million, with a full snapshot every 15 minutes) and the 1-minute candles — listed through the
data lake's GET-only public client, fetched by a host-pinned GET-only downloader (60 files, 2,093 MB,
SHA-256 in the per-file manifests) and replayed by `research/fill_replay.py` through
`scripts/run_fill_replay.py`. The numbers are in `docs/research/fill_cost_replay_results.json`
(summaries plus one record per bar boundary); the full tables the script prints are in
`docs/research/fill_cost_replay_tables.md`. The raw files were deleted after the run, as the row asks;
the manifests record what was fetched.

## 1. In short

- **For 1 K to 20 K USDT market orders in BTC-USDT and ETH-USDT, the spread and the book impact
  together are a few hundredths of a basis point at the median and under 2.6 bps in the worst of
  400 replayed fills.** Against the next bar's open, the price the research engine assumes it pays,
  the median cost is 0.01 bps in BTC and 0.04 bps in ETH for every clip; the 20 K clip averages
  0.08 bps (BTC) and 0.33 bps (ETH), its 90th percentile is 0.28 and 1.03 bps, its 99th 0.82 and
  2.09 bps. A 20 K round trip costs 0.15 bps (BTC) and 0.66 bps (ETH) of spread and impact on
  average. The engine charges 5 bps a side, 10 bps a round trip: 15 to 60 times the measured
  average, and above the worst single fill.
- **The fee is the cost.** OKX's regular taker fee is 10 bps a side; the measured spread and impact
  add 0.1 to 7 % of that. The book is one tick wide almost all the time (0.013 bps in BTC, 0.043 bps
  in ETH at the close of the bar), and the touch holds a median 41-57 K USDT (BTC) and 25-28 K
  (ETH); a 20 K clip walks past the first level in 10-28 % of BTC boundaries and 38-52 % of ETH
  boundaries, by a few hundredths of a basis point when it does.
- **Timing costs more than size.** The next bar's first trade prints 0.2-0.3 s after the boundary
  (ETH: 8 % of boundaries later than 1 s, the worst 3.1 s) and the book then is the book at the
  close. One second after the close the mid has moved 0.5 bps (BTC) and 1.0 bps (ETH) at the
  median, 1.8 and 2.9 bps at the 90th percentile, and in one ETH boundary (2026-10-28 18:00 UTC, a
  burst of 2,588 trades within two seconds) a 20 K sell one second late would have cost 15.5 bps
  against the open. An order sent at the close and filled within a second pays the measured book
  cost; an order a few seconds late pays the market's move, which the engine's slippage was never
  meant to cover and no study here needs to.
- **A post-only order at the touch filled within one bar in every one of the 384 bars judged**
  (BTC and ETH, 4H and 6H, both sides, 58 4H bars and 38 6H bars per instrument), nearly always
  because the market traded through the price (within seconds at the median: 1-6 s; 90th percentile
  0.5-9 minutes; the longest wait 174 minutes). Because the fill comes when the price crosses the
  order, the fill is adversely selected by construction; measured at the bar's end the mark-out is
  within ±0.5 bps (BTC 4H) to ±4.6 bps (ETH 4H) at the median and mirrors between buys and sells,
  which is the period's drift (BTC fell about 6 % in the window), not a cost of the order type.
  Ten days are not a guarantee, but they support what Sprint 3's post-only entry policy assumes:
  in these two books a maker entry at the touch is filled within the bar.
- **Recommendation for FUTURE studies (owner's decision, section 7):** for BTC-USDT and ETH-USDT
  with clips up to 20 K USDT, charge 2 bps of slippage a side instead of 5 (fee unchanged at 10 bps
  taker): 0.24 % a round trip instead of 0.30 %. Two bps sits above the 99th percentile of the
  measured next-open cost of the largest clip in the thinner book and above the 90th percentile
  of the one-second latency move. Keep 5 bps plus the altcoin 10 bps for every other market until
  it is measured the same way. Nothing already run is re-judged.
- **Demo fills are not evidence of any of this.** OKX's demo environment matches against a separate,
  thin book and cancels at the price limit; the fill prices the shadow run or the stop drills report
  say nothing about live slippage. This replay is the evidence; the demo is for the plumbing.

## 2. What was measured, and how

**The data.** `GET /api/v5/public/market-data-history` (public, no key) lists one daily file per
instrument and module: module 1 tick-by-tick trades (`<inst>-trades-<day>.zip`, a CSV with
`instrument_name, trade_id, side, price, size, created_time, source`; `side` is the taker side),
module 2 1-minute candles (`<inst>-candlesticks-<day>.zip`), module 4 the 400-level L2 book
(`<inst>-L2orderbook-400lv-<day>.tar.gz`, JSON lines in the public `books` channel format: a
snapshot every 15 minutes, updates in between, a size of 0 removing a level). Two facts of the
archive that the row text anticipated only in part: the listing parameter is `instIdList` (a comma
list of up to 10 instruments; with it the trades module returns per-instrument files of 1-9 MB a day
rather than the 50-150 MB all-SPOT zips), and the day boundaries differ — a trades or candle file
named `<day>` holds the UTC+8 day (16:00 UTC the day before to 16:00 UTC of `<day>`), a book file
holds the UTC day. The replay therefore pools every trades and candle file of an instrument into one
series and walks the book files on the UTC grid; a bar whose trades the files do not fully cover is
not judged (the 16:00-24:00 UTC bars of the last day, 2026-11-03, whose trades sit in the 11-04 file,
not yet published on 2026-11-05).

**The moments.** At every 4H and 6H bar close on the UTC grid (00:00, 04:00, ... and 00:00, 06:00,
...; 60 4H and 40 6H boundaries per instrument) the book is sampled three times: `close`, the state
after the last update before the boundary; `next_open`, the state at the next bar's first trade (the
engine's assumed fill moment; 0.2-0.3 s after the boundary at the median); `plus_1s`, the state one
second after the close. At each moment a market order of 1 K, 5 K, 10 K and 20 K USDT is walked
through the book on both sides (buy against the asks, sell against the bids), giving the average
fill price, the number of levels touched and the share of the clip filled beyond the first level.
Costs are quoted in basis points, positive when worse for the trader, against three references: the
mid at that moment, the candle close (the 1-minute candle ending at the boundary) and the next bar's
open (the 1-minute candle opening at the boundary). The tape's last trade before and first trade
after each boundary equal the archive's candle close and open exactly at all 155 boundaries with
both (table E of the generated tables), so the reference the engine uses is the one measured here.

**The post-only test.** At each close, a post-only order rests at the best bid (buy) or best ask
(sell) behind the displayed queue; from the trades tape alone it counts as filled within the bar
when the market trades through its price (a trade strictly beyond it) or when the taker volume at
exactly its price, on the side that consumes it, reaches the displayed queue plus the order's own
size (FIFO; cancellations ahead of it are ignored, so the fill rate is a lower bound). The mark-out
is the mid at the bar's end against the limit price, positive when the fill was favourable.

**The engine beside it.** `research/engine.py` charges `Costs(fee_rate=0.0010, slippage_rate=0.0005)`:
10 bps fee plus 5 bps slippage a side, 30 bps a round trip; an entry fills at the next bar's open
times 1.0005, an exit at the open times 0.9995. Altcoin studies add 10 bps a side.

## 3. Coverage

| Instrument | Book days (UTC) | Trades pooled | Tape covers (UTC) | Book events | Snapshots | 4H / 6H boundaries | Boundaries with refs | Bars judged post-only (4H / 6H) |
|---|---|---:|---|---:|---:|---|---:|---|
| BTC-USDT | 2026-10-25 to 2026-11-03 (10) | 3,712,601 | 2026-10-24 16:00 to 2026-11-03 15:59 | 31,305,379 | 960 | 60 / 40 | 78 of 80 | 58 / 38 |
| ETH-USDT | 2026-10-25 to 2026-11-03 (10) | 3,418,848 | 2026-10-24 16:00 to 2026-11-03 15:59 | 32,922,093 | 960 | 60 / 40 | 78 of 80 | 58 / 38 |

The 400 levels were never exhausted (0 incomplete fills in 4,800 walks). The first day's 00:00
sample comes from the file's first snapshot three milliseconds after the boundary (flagged in the
records); every later day carries the book over from the day before, with no reset.

## 4. Market orders: the cost of size

**4.1 Against the next bar's open (the engine's fill price), at the `next_open` moment, buys and
sells pooled, 4H and 6H pooled** (bps; n = 194 fills per cell).

| Instrument | Clip | Median | Mean | p90 | p99 | Max | Round trip, mean (buy + sell) | Engine: slippage a side |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1 K | 0.012 | 0.011 | 0.013 | 0.19 | 0.35 | 0.02 | 5 |
| BTC-USDT | 5 K | 0.012 | 0.024 | 0.013 | 0.39 | 0.72 | 0.05 | 5 |
| BTC-USDT | 10 K | 0.012 | 0.046 | 0.13 | 0.53 | 0.77 | 0.09 | 5 |
| BTC-USDT | 20 K | 0.012 | 0.075 | 0.28 | 0.82 | 0.86 | 0.15 | 5 |
| ETH-USDT | 1 K | 0.043 | 0.066 | 0.23 | 0.62 | 1.03 | 0.13 | 5 |
| ETH-USDT | 5 K | 0.043 | 0.165 | 0.61 | 1.36 | 1.51 | 0.33 | 5 |
| ETH-USDT | 10 K | 0.044 | 0.235 | 0.69 | 1.84 | 1.90 | 0.47 | 5 |
| ETH-USDT | 20 K | 0.045 | 0.330 | 1.03 | 2.09 | 2.54 | 0.66 | 5 |

**4.2 Against the mid at the close, by side** (bps; the generated table B has every clip; spread =
the quoted spread at the close, median).

| Instrument | TF | Side | Clip | n | Median | Mean | p90 | Max | Share beyond 1st level (mean) | Clips touching 2+ levels | Spread |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4H | buy | 1 K | 60 | 0.01 | 0.01 | 0.01 | 0.09 | 0.015 | 2 % | 0.01 |
| BTC-USDT | 4H | buy | 20 K | 60 | 0.01 | 0.02 | 0.01 | 0.31 | 0.053 | 12 % | 0.01 |
| BTC-USDT | 4H | sell | 1 K | 60 | 0.01 | 0.02 | 0.01 | 0.40 | 0.028 | 5 % | 0.01 |
| BTC-USDT | 4H | sell | 20 K | 60 | 0.01 | 0.11 | 0.44 | 0.99 | 0.142 | 27 % | 0.01 |
| BTC-USDT | 6H | buy | 20 K | 40 | 0.01 | 0.01 | 0.01 | 0.04 | 0.036 | 10 % | 0.01 |
| BTC-USDT | 6H | sell | 20 K | 40 | 0.01 | 0.10 | 0.43 | 0.93 | 0.147 | 28 % | 0.01 |
| ETH-USDT | 4H | buy | 1 K | 60 | 0.02 | 0.03 | 0.02 | 0.29 | 0.018 | 3 % | 0.04 |
| ETH-USDT | 4H | buy | 20 K | 60 | 0.02 | 0.13 | 0.48 | 1.12 | 0.171 | 38 % | 0.04 |
| ETH-USDT | 4H | sell | 1 K | 60 | 0.02 | 0.04 | 0.02 | 0.43 | 0.043 | 7 % | 0.04 |
| ETH-USDT | 4H | sell | 20 K | 60 | 0.02 | 0.16 | 0.43 | 1.23 | 0.251 | 42 % | 0.04 |
| ETH-USDT | 6H | buy | 20 K | 40 | 0.02 | 0.14 | 0.48 | 1.12 | 0.206 | 38 % | 0.04 |
| ETH-USDT | 6H | sell | 20 K | 40 | 0.04 | 0.23 | 0.57 | 2.41 | 0.320 | 52 % | 0.04 |

**Reading it.** The median cost of every clip is the half spread: one tick. The mean and the tail
come from the boundaries where the touch was thin — the smallest touch seen at a close was 85 USDT
(BTC) and 29 USDT (ETH), the 10th percentile 5 K and 2.8 K on the bid side — and a 20 K clip then
walks several levels; the worst walk (ETH, 2026-10-28 18:00, a 20 K sell into a 0.14 ETH bid during
the burst described below) touched 10-12 levels for 2.4-2.6 bps. Sells cost more than buys in this
window because the bid side was thinner while the market fell. None of it approaches the engine's
5 bps.

## 5. Timing: the close, the next open, one second later

| Instrument | Mid move close to next open (abs, bps): median / p90 / max | Mid move close to +1 s: median / p90 / max | First trade after the boundary: median / p90 / max | Boundaries with the first trade later than 1 s |
|---|---|---|---|---:|
| BTC-USDT | 0.00 / 0.00 / 0.89 | 0.48 / 1.79 / 3.20 | 207 ms / 330 ms / 475 ms | 0 % |
| ETH-USDT | 0.00 / 0.61 / 1.31 | 1.03 / 2.90 / 4.93 | 291 ms / 707 ms / 3,078 ms | 7.8 % |

The `next_open` moment is, in practice, the close: the first trade of the new bar prints within a
third of a second and the book has not moved. One second later the picture changes: the median mid
has moved half a basis point in BTC and a full one in ETH, and the 90th percentile 1.8-2.9 bps —
bar boundaries on the UTC grid are busy moments. The one extreme is instructive: at 2026-10-28
18:00:00 UTC ETH printed 2,588 trades within two seconds; the book one second after the close stood
15 bps below the open (table C of the generated tables, `plus_1s`, ETH 6H sell 20 K, max 2.35-2.45
bps against the mid of that moment but 15.5 bps against the open). A strategy that reacts to a bar
close is exposed to this whether it uses a market order or not; the engine's 5 bps was a slippage
allowance, and a 2 bps allowance still covers the 90th percentile of the one-second move.

## 6. Post-only at the touch

| Instrument | TF | Side | Bars judged | Fill rate within the bar | Traded through | Filled by queue only | Minutes to fill: median / p90 / max | Mark-out at bar end (bps): median / mean | Queue ahead at the touch (median USDT) |
|---|---|---|---:|---:|---:|---:|---|---|---:|
| BTC-USDT | 4H | buy | 58 | 100 % | 100 % | 0 % | 0.06 / 3.2 / 13.7 | -0.5 / -6.6 | 40,975 |
| BTC-USDT | 4H | sell | 58 | 100 % | 100 % | 0-2 % | 0.04 / 7.6 / 173.8 | +0.5 / +6.6 | 54,542 |
| BTC-USDT | 6H | buy | 38 | 100 % | 100 % | 0 % | 0.09 / 1.4 / 47.0 | -2.5 / -12.3 | 38,751 |
| BTC-USDT | 6H | sell | 38 | 100 % | 100 % | 0 % | 0.06 / 8.8 / 173.8 | +2.5 / +12.3 | 55,623 |
| ETH-USDT | 4H | buy | 58 | 100 % | 100 % | 0-3 % | 0.02 / 2.2 / 12.5 | +4.6 / -4.0 | 24,675 |
| ETH-USDT | 4H | sell | 58 | 100 % | 100 % | 0-3 % | 0.02 / 0.5 / 27.7 | -4.6 / +4.0 | 25,677 |
| ETH-USDT | 6H | buy | 38 | 100 % | 100 % | 0-5 % | 0.06 / 1.7 / 9.1 | 0.0 / -10.0 | 18,233 |
| ETH-USDT | 6H | sell | 38 | 100 % | 100 % | 0 % | 0.02 / 1.1 / 27.7 | 0.0 / +10.1 | 27,939 |

The fill rate is the same for every clip from 1 K to 20 K because the fills come from the market
trading through the price, not from the queue draining; the "queue only" column (fills by volume
at the price before any trade through it) is 0-5 % and applies to the 1 K clip only. The mark-out
means mirror between buys and sells (the same bars, the same end-of-bar mid), so they measure the
window's drift; the medians, within ±0.5 bps in BTC 4H and ±4.6 bps in ETH 4H, are the fairer
reading. The missed-move column of the generated table D is empty because nothing went unfilled.
What this does and does not say: in these ten days a maker entry at the touch would have been
filled within the bar every time, usually within seconds, and the saving against a taker order is
the fee difference (8 against 10 bps) plus one tick; a bar in which the price never comes back to
the touch is possible, and a longer sample is needed before any study counts on 100 %.

## 7. Recommendation for the cost model of future studies

Today's gate cost is 0.30 % a round trip (10 bps fee plus 5 bps slippage a side) for BTC-USDT and
ETH-USDT, 0.50 % for altcoins. The measured spread and impact of a 20 K clip at the engine's fill
moment is 0.08 bps (BTC) and 0.33 bps (ETH) on average, 0.28 and 1.03 bps at the 90th percentile,
0.82 and 2.09 bps at the 99th, 2.5 bps at worst; one second of latency adds 0.5-1.0 bps at the
median and 1.8-2.9 bps at the 90th percentile.

- **Recommended: 2 bps of slippage a side for BTC-USDT and ETH-USDT with clips up to 20 K USDT,
  fee unchanged at 10 bps taker — 0.24 % a round trip.** It covers the 99th percentile of the
  largest clip in the thinner book and the 90th percentile of the one-second move, with the 15 bps
  burst left as the tail it is. A 1 bps slippage would be the central estimate; keeping 5 bps keeps
  a margin of 15-60 times the measured average and makes every BTC/ETH study 6 bps a round trip
  harder than the venue is.
- **Altcoins: no change** (5 bps plus the altcoin 10 bps a side) until the same replay is run on
  them; the plan's own estimate (1-14 bps a side for a 20 K order in SOL, XRP, DOGE, LINK, ADA,
  TRUMP) says their cost is real.
- **A maker variant** (8 bps fee plus 2 bps) only for a study that explicitly assumes Sprint 3's
  post-only entry policy, and only after a longer sample of fill rates; the default stays taker.
- **Scope of the change:** future studies only, as a new `Costs` default or a named profile in the
  research engine; no finished study (Sprint 2 to R20) is re-judged, and none of the forward paper
  accounts change. The change is the owner's decision (`docs/PLAN_STATUS.md`, section 2).

## 8. Caveats

- Ten days, one regime: 2026-10-25 to 2026-11-03, which included a fall of about 6 % in BTC and a
  burst at one boundary; a calmer or a more violent fortnight would move the tails, not the medians.
- Bar boundaries only: fills are sampled where the engine fills, on the UTC 4H and 6H grid, which
  are busy moments; costs inside a bar are not measured and are not needed.
- The replay walks the displayed book: hidden or iceberg liquidity, the venue's matching nuances
  (self-trade prevention, price limits) and the trader's own latency are not modelled; the
  `plus_1s` moment stands in for the last of these.
- The post-only model is a lower bound on fills (cancellations ahead of the order are ignored) and
  assumes the order is left alone for the whole bar.
- The archive's trades and candle files are cut at UTC+8 midnight, the book files at UTC midnight;
  the pooling handles it, and the last book day's evening bars are not judged until the next trades
  file is published (T+2 for trades, T+3 for the book).
- Demo fills come from a separate thin book and are not evidence; nothing in this report rests on
  them.

## 9. Reproducing it

```bash
python scripts/run_fill_replay.py --list  --start 2026-10-25 --end 2026-11-03   # the listing only (public, no key)
python scripts/run_fill_replay.py --fetch --start 2026-10-25 --end 2026-11-03   # 60 files, 2.1 GB, resumable
python scripts/run_fill_replay.py --replay --start 2026-10-25 --end 2026-11-03  # writes the JSON and the tables, deletes the raw files (unless --keep)
python scripts/run_fill_replay.py --status                                       # the manifests that remain
```

Any ten-day window from the archive's start (the trades go back at least a year; the 400-level
book is listed from 2025) can be replayed the same way; a different window is a new measurement,
not a re-judgement of this one.
