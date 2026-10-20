# Research data lake (Sprint 1) — public OKX data in Parquet + DuckDB

Status: research storage only. Public, unauthenticated endpoints. Nothing in
`app/datalake/` is imported by the execution, risk, strategy or exchange
packages; it cannot place, size or veto an order. The runtime PostgreSQL
tables are untouched. Master plan: `docs/MASTER_PLAN_2026-10-20.md` Sprint 1.

## Layout (`data/lake`, git-ignored; override with `DATA_LAKE_DIR`)

```
candles/<instrument>/<timeframe>/<year>.parquet        BTC-USDT, ETH-USDT spot OHLCV (confirmed bars)
derivatives/<kind>/<instrument>/<period>/<year>.parquet  BTC-/ETH-USDT-SWAP statistics (features only)
external/<venue>/<kind>/<symbol>/<period>/<year>.parquet  other venues' PUBLIC statistics (Binance funding / open interest; features only)
liquidations/<instrument>/<YYYY-MM-DD>.jsonl          public liquidation-orders feed (SWAP)
_state/<job>.json                                     resumable cursors
_reports/quality-<date>.{md,json}                     data-quality reports
```

Derivatives kinds: `funding_rate` (8-hourly, period dir `8H`), `open_interest`,
`long_short_ratio`, `taker_volume` (rubik, periods `5m`/`1H`/`1D`). Every
Parquet file is sorted by its timestamp key and de-duplicated; writes are
merges with an atomic replace, so a crash never leaves a half-written file.

## Commands

```bash
# Spot history (resumable; re-run any time; --max-pages bounds a session)
python scripts/backfill_history.py                       # BTC/ETH × 1m 5m 1H 4H 1D from 2020-01-01
python scripts/backfill_history.py --timeframes 1H 4H 1D --quality
python scripts/backfill_history.py --instruments BTC-USDT --timeframes 1m --max-pages 2000

# SWAP statistics as features (resumable)
python scripts/collect_derivatives.py --period 1H

# Binance PUBLIC funding / open-interest history as long-history features (resumable; Sprint 2b)
python scripts/collect_binance_positioning.py                      # BTCUSDT + ETHUSDT, funding + metrics
python scripts/collect_binance_positioning.py --kinds funding_rate # funding only (~1 min)

# Public liquidation feed for one hour (run under cron/systemd for continuity)
python scripts/collect_liquidations.py --duration 3600

# Nightly data-quality report (writes data/lake/_reports/quality-<date>.md/.json)
python scripts/data_quality_report.py --strict
```

Suggested nightly cron on the research host (owner action; not part of
`shadow.service`):

```
7 2 * * *  cd /path/to/repo && .venv/bin/python scripts/backfill_history.py --timeframes 1H 4H 1D --max-pages 400 >> logs/lake.log 2>&1
17 2 * * * cd /path/to/repo && .venv/bin/python scripts/collect_derivatives.py --max-pages 50 >> logs/lake.log 2>&1
27 2 * * * cd /path/to/repo && .venv/bin/python scripts/data_quality_report.py --strict >> logs/lake.log 2>&1
```

## How the backfill resumes

OKX history endpoints page backwards (`after`/`end` cursors return records
older than the cursor, newest first). `app/datalake/paging.py` keeps, per
series, the contiguous covered range `[oldest_ms, newest_ms]` in
`_state/<job>.json`. A session:

1. finishes any interrupted "top fill" (new data that appeared since the last
   run and is being joined to the covered range);
2. fetches the newest page; if it is above `newest_ms` it starts a top fill
   and walks down until it meets the covered range;
3. extends the bottom from `oldest_ms` toward `--start` until it is reached or
   the exchange returns no older data (`exhausted`).

Every page is written before the cursor advances and the Parquet writer
de-duplicates, so any interruption is safe. Candles use the reviewed
`OKXPublicClient` (`get_candles` for the newest page, `get_history_candles`
for history); confirmed bars only.

Rate limits: 0.15 s between candle requests (OKX allows 20 per 2 s), 0.25 s
for rubik statistics. A full 1m history for one instrument from 2020 is
~35k requests (≈1.5–2 h); 1H/4H/1D take minutes.

## Known data properties

- OKX `1D` candles open at 00:00 UTC+8 (16:00 UTC). The lake stores what the
  exchange returns; the quality report checks that the bar *phase* is constant
  and notes the offset instead of assuming midnight UTC.
- The rubik statistics endpoints keep a limited history (months, not years;
  a request 400 days back returned nothing on 2026-10-20). The funding-rate
  history also does not reach back to 2020. The backfill records this as
  `exhausted=True` and the report shows the real span.
- `/market/history-candles` served 1m data back to 2020-01-01 and 1H data
  back to at least 2019-01-01 on 2026-10-20.

## Querying with DuckDB

```python
from app.datalake.duckdb_views import connect, candles_frame
from app.datalake.layout import LakeLayout

con = connect(LakeLayout.from_env())           # read-only views; empty views on a fresh lake
con.sql("SELECT instrument, timeframe, count(*) n, min(open_time), max(open_time) FROM candles GROUP BY 1,2").show()
df = candles_frame(con, "BTC-USDT", "1H")      # pandas frame ordered by open_time
con.sql("SELECT * FROM funding_rate ORDER BY ts DESC LIMIT 5").show()
con.sql("SELECT instrument, count(*) FROM liquidations GROUP BY 1").show()
```

Views: `candles`, `funding_rate`, `open_interest`, `long_short_ratio`,
`taker_volume`, `liquidations`, `binance_funding_rate`, `binance_metrics`.

## Data-quality report

`app/datalake/quality.py` checks each series for missing bars (expected count
from the span and bar size), gaps (listed), duplicates, off-grid timestamps,
unconfirmed bars, incoherent OHLC (high below open/close/low, etc.),
non-positive prices, zero-volume bars and extreme single-bar moves
(|log return| > 0.25, flagged, not failed). A series is `OK` when it has no
missing/duplicate/misaligned/incoherent/unconfirmed rows.

## Evidence — first live run (2026-10-20, local machine, public endpoints)

Candle backfill (`scripts/backfill_history.py --timeframes 1H 4H 1D --quality`):

| Series | Requests | Bars stored | Span (UTC) | Missing | Gaps | Dupes | Misaligned | Zero-volume | Extreme moves |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT 1H | 595 | 59,699 | 2019-12-28 22:00 → 2026-10-20 08:00 | 0 | 0 | 0 | 0 | 12 | 0 |
| BTC-USDT 4H | 148 | 14,999 | 2019-12-16 12:00 → 2026-10-20 04:00 | 0 | 0 | 0 | 0 | 1 | 0 |
| BTC-USDT 1D | 23 | 2,499 | 2019-12-16 16:00 → 2026-10-18 16:00 | 0 | 0 | 0 | 0 | 0 | 0 |
| ETH-USDT 1H | 595 | 59,699 | 2019-12-28 23:00 → 2026-10-20 09:00 | 0 | 0 | 0 | 0 | 12 | 1 |
| ETH-USDT 4H | 148 | 14,999 | 2019-12-16 12:00 → 2026-10-20 04:00 | 0 | 0 | 0 | 0 | 5 | 1 |
| ETH-USDT 1D | 23 | 2,499 | 2019-12-16 16:00 → 2026-10-18 16:00 | 0 | 0 | 0 | 0 | 0 | 3 |

All six series are continuous (zero missing bars) over ≈6.8 years; the
run took about ten minutes. 1D bars open at 16:00 UTC as expected. The 1m
and 5m backfills were not run here (≈35k and ≈7k requests per instrument);
they are resumable and intended for the research host (see the cron example).

Derivatives (`scripts/collect_derivatives.py --period 1H`): taker volume is
served back to 2019-12-28 (59,700 hourly rows per instrument); funding-rate
history only back to 2026-07-13 (297 settlements) and open interest /
long-short ratio only back to 2026-08-21 (1,440 hourly rows) — OKX keeps a
short public history for those, which limits S5-style positioning features to
the recent months. Liquidation feed: a 90-second live run received 10 channel
messages with 0 BTC/ETH-SWAP liquidations in that window (channel working).

## External positioning history (Binance, research features only — Sprint 2b)

OKX keeps only months of public funding-rate and open-interest history (see
the evidence above), so the S5 positioning filter had data for a few percent
of the backtest. `app/datalake/binance_public.py` collects the same two
quantities from Binance's PUBLIC USDT-margined futures data, without any API
key, purely as research features. **This project trades OKX SPOT demo only
and never trades on Binance; nothing here can authenticate or place an order.**

| Series | Source | History | How it is stored |
|---|---|---|---|
| `funding_rate` (period `8H`) | `GET https://fapi.binance.com/fapi/v1/fundingRate` (public, weight 1, ≤ 1000 rows per page, ascending from `startTime`) | BTCUSDT since 2019-09-10, ETHUSDT since 2019-11-27 | one row per settlement: `ts`, `funding_rate`, `mark_price` |
| `metrics` (period `1H`) | daily zips on the public bulk bucket `https://data.binance.vision/data/futures/um/daily/metrics/<SYMBOL>/` with a `.CHECKSUM` (sha256) per file; the REST `openInterestHist` endpoint serves only ~30 days, which is why the bulk files are used | BTCUSDT since 2020-09-01, ETHUSDT since 2021-12-01 (5-minute snapshots) | the last snapshot of every UTC hour: `oi` (contracts), `oi_usd`, top-trader and account long/short ratios, taker buy/sell volume ratio; each row keeps its own snapshot time so as-of alignment onto candles can never see a value before it existed |

Safety and integrity: GET only; hostname + path allowlists (only the funding
endpoint and the metrics prefix for the two symbols); no headers beyond a
User-Agent; downloads capped at 32 MB; zip extraction limited to one CSV
member of ≤ 16 MB; every bulk file is sha256-verified against its published
checksum before parsing (a mismatch stops the run and leaves the cursor on the
last good day); timestamps and numbers validated. Resumable: funding keeps a
forward cursor, metrics keep `done_through` plus the list of missing days in
`_state/external__binance__*.json`; re-runs fetch only new settlements / days.

Terms: public market data published by Binance for its users (Binance API
Terms of Use; "Binance Public Data" on data.binance.vision), used for
internal research only and not redistributed; the files live in the
git-ignored lake. Row formats were confirmed against the live endpoints on
2026-10-20.

Research use: `research.data.positioning_context(layout, instrument, timeframe,
source="binance")` builds the S5 feature context (funding z-score, 1-day
open-interest change) from these series; `source="okx"` uses the OKX series
(short history, kept collecting for the forward period).

Evidence — first live collection (2026-10-20, local machine, public endpoints,
`scripts/collect_binance_positioning.py`):

| Series | Requests | Rows stored | Span (UTC) | Missing days |
|---|---:|---:|---|---:|
| funding_rate BTCUSDT | 8 pages | 7,792 settlements | 2019-09-10 08:00 → 2026-10-20 08:00 | – |
| funding_rate ETHUSDT | 8 pages | 7,558 settlements | 2019-11-27 08:00 → 2026-10-20 08:00 | – |
| metrics BTCUSDT (hourly OI + ratios) | 2,240 days × (zip + checksum) | 53,738 hourly rows | 2020-09-01 00:55 → 2026-10-19 23:55 | 0 |
| metrics ETHUSDT (hourly OI + ratios) | 1,784 days × (zip + checksum) | 42,806 hourly rows | 2021-12-01 00:55 → 2026-10-19 23:55 | 0 |

Funding took about a minute; the metrics files took about 1.5 hours with
sha256 verification (every file verified, no mismatch); the external lake is
5.5 MB. One run stopped on a transient Windows file lock (a concurrent
reader of the state file while it was being replaced) — the writers now retry
the atomic replace and the resumable collector picked up at the last good
day. The OKX series were topped up the same day (`collect_derivatives.py`),
so the forward period keeps both sources.

## Boundaries

- Public data only; no API key is read or sent by anything in this package.
- Swap statistics are research features. This project trades SPOT, long-only,
  demo-only; nothing here changes that.
- The liquidation collector is a separate read-only WebSocket consumer; the
  reviewed market-data client and its channel allowlist are unchanged.
