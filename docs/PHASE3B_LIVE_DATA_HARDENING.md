# Phase 3B - Public Live-Data Hardening

**Status: Accepted on June 9, 2026.** The human owner authorized Phase 3B, an
independent adversarial review (Claude) found no blocker and no required
follow-up, and the human owner then explicitly accepted Phase 3B. See
`docs/PHASE3B_REVIEW_NOTES.md`.

Phase 3B remains strictly public-data-only. It adds integrity, continuity,
optional storage, and read-only observability. It does not evaluate live
strategies or authorize any simulated, paper, demo, or live trade.

## Added behavior

### Public order books

- Subscribes to OKX `books` for `BTC-USDT` and `ETH-USDT`.
- Reconstructs a bounded local book from the initial snapshot and incremental
  updates.
- Requires every update's `prevSeqId` to match the last accepted `seqId`.
- Accepts OKX's documented empty same-sequence keepalive.
- Accepts a documented maintenance sequence reset only when its `prevSeqId`
  still matches the local chain.
- Marks the book unsynchronized and reconnects for a fresh snapshot on a gap,
  malformed book frame, or invalid sequence event.
- Exposes separate `connected`, `stale`, book-synchronization, and aggregate
  `ready` health.

The implementation deliberately does not depend on the `checksum` field. OKX
announced that production JSON order-book checksums will be deprecated on June
23, 2026 and recommends `seqId`/`prevSeqId` continuity validation instead.

### Candle continuity and backfill

When optional persistence sees a confirmed live candle:

1. It compares the candle with the latest earlier stored candle.
2. It derives the expected interval from the timeframe.
3. If bars are missing, it requests older confirmed bars from the public
   `/api/v5/market/history-candles` endpoint.
4. It stores available missing bars and reports any unresolved count.
5. One repair request is bounded to at most 300 bars.

Naive timestamps, incoherent OHLC values, non-finite numbers, unsupported
instruments, and ambiguous pagination are rejected.

### Optional durable writes

Persistence is disabled by default. When enabled it stores:

- confirmed public candles in the existing `candles` table;
- sampled, sequence-valid public books in `order_book_snapshots`.

Stored book depth, sampling interval, and per-instrument retention are bounded.
Database and REST work runs outside the WebSocket receive path. Failures are
reported as degraded persistence health and never make malformed data valid.

## Run

Observation only, no database writes:

```bash
python scripts/run_live_market_data.py --duration 30
```

Observation plus durable public-data writes:

```bash
LIVE_PERSISTENCE_ENABLED=true \
python scripts/run_live_market_data.py --duration 30
```

Read-only API with the stream in-process:

```bash
LIVE_WS_AUTOSTART=true \
LIVE_PERSISTENCE_ENABLED=true \
uvicorn app.api.main:app --reload
```

Useful endpoints:

- `GET /live/health`
- `GET /live/order-books?depth=20`
- `GET /live/persistence`
- `GET /live/order-book-history?instrument=BTC-USDT&limit=100`
- `GET /candles?instrument=BTC-USDT&timeframe=1m`

## Configuration

| Environment variable | Default | Meaning |
|---|---:|---|
| `LIVE_PERSISTENCE_ENABLED` | `false` | enable public-data writes |
| `LIVE_PERSISTENCE_POLL_SECONDS` | `1` | persistence polling interval |
| `LIVE_ORDER_BOOK_SNAPSHOT_SECONDS` | `5` | minimum book sampling interval |
| `LIVE_ORDER_BOOK_DEPTH` | `20` | stored levels per side, maximum 400 |
| `LIVE_ORDER_BOOK_RETENTION` | `10000` | retained samples per instrument |
| `LIVE_BACKFILL_MAX_BARS` | `300` | maximum bars repaired per request |

## Limitations

- Backfill is bounded to one public history page per detected gap. Larger or
  unavailable gaps remain visible as unresolved and are not silently hidden.
- Persisted books are periodic samples, not a complete event-by-event archive.
- SQLAlchemy creates the new table; a formal migration system is not present.
- The current live candle channel is `candle1m`.
- Book synchronization does not imply trading readiness.
- Phase 4 local paper trading remains unauthorized.

## Builder verification

The June 9, 2026 implementation pass completed:

- 290 offline tests, including malformed depth, sequence gaps/resets,
  persistence failures, bounded backfill/retention, and supervised shutdown;
- clean compilation, dependency, whitespace, and forbidden-surface scans;
- a public-only WebSocket smoke with both BTC/ETH books synchronized and zero
  observed sequence gaps;
- an opt-in SQLite persistence smoke with both instruments stored;
- a public history-candle smoke returning validated confirmed bars; and
- an in-process FastAPI smoke proving `ready=true`, read-only live books,
  persistence health, durable history, and graceful shutdown.

This is builder verification, not independent phase acceptance.

The independent adversarial review and finding dispositions are documented in
`docs/PHASE3B_REVIEW_NOTES.md`.

## Official protocol references

- OKX API guide: <https://www.okx.com/docs-v5/en>
- OKX checksum deprecation notice:
  <https://www.okx.com/en-us/help/okx-order-book-channels-checksum-field-deprecation>

## Safety

No private endpoint, login, API key, account access, strategy execution,
paper/demo/live order path, leverage, or withdrawal functionality is added.
Phase 3B was independently reviewed and explicitly accepted by the human owner
on June 9, 2026. Acceptance is limited to public-data observation, integrity,
and optional public-data storage; it authorizes no trading and does not
authorize Phase 4.
