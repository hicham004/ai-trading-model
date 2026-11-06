"""Resumable OKX history-candles backfill into the Parquet lake (public data).

Uses the reviewed public client (``app.okx.client.OKXPublicClient``):
``get_candles`` for the newest page and ``get_history_candles(after=...)`` to
walk backwards. Only confirmed bars are stored. Rate limiting is a plain
sleep between pages (OKX allows 20 requests / 2 s on these endpoints; the
default 0.15 s is comfortably below that).

Daily bars: OKX ``1D`` candles open at 00:00 UTC+8 (16:00 UTC). The lake stores
what the exchange returns; the quality report checks that the *phase* is
constant rather than assuming midnight UTC.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from app.datalake.layout import LakeLayout
from app.datalake.paging import BackwardWalker, Row, WalkReport
from app.datalake.parquet_store import candle_coverage, from_ms, to_ms, write_candles
from app.logging_config import get_logger
from app.okx.client import ALLOWED_INSTRUMENTS, OKXPublicClient
from app.strategy.timeframes import parse_timeframe

logger = get_logger(__name__)

DEFAULT_TIMEFRAMES = ("1m", "5m", "1H", "4H", "1D")
NEWEST_PAGE_LIMIT = 300  # /market/candles maximum
HISTORY_PAGE_LIMIT = 100  # /market/history-candles maximum
DEFAULT_START = datetime(2020, 1, 1, tzinfo=timezone.utc)


class _CandleSource:
    """Adapts the public client to the ``PageSource`` protocol."""

    def __init__(self, client: OKXPublicClient, instrument: str, timeframe: str) -> None:
        self._client = client
        self._instrument = instrument
        self._timeframe = timeframe

    @staticmethod
    def _rows(candles) -> Sequence[Row]:
        return [(to_ms(c.timestamp), c) for c in candles]

    def fetch_newest(self) -> Sequence[Row]:
        return self._rows(
            self._client.get_candles(
                self._instrument, self._timeframe, limit=NEWEST_PAGE_LIMIT, confirmed_only=True
            )
        )

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]:
        return self._rows(
            self._client.get_history_candles(
                self._instrument,
                self._timeframe,
                limit=HISTORY_PAGE_LIMIT,
                after=from_ms(cursor_ms),
                confirmed_only=True,
            )
        )


@dataclass
class BackfillReport:
    instrument: str
    timeframe: str
    walk: WalkReport
    added: int
    duplicates_dropped: int
    stored_rows: int
    stored_min: Optional[datetime]
    stored_max: Optional[datetime]

    def summary(self) -> str:
        span = (
            f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC"
            if self.stored_min and self.stored_max
            else "(empty)"
        )
        return (
            f"{self.instrument} {self.timeframe}: pages={self.walk.pages} "
            f"fetched={self.walk.rows} added={self.added} dupes={self.duplicates_dropped} "
            f"stored={self.stored_rows} span={span} complete={self.walk.complete} "
            f"reason={self.walk.reason}"
        )


def backfill_candles(
    client: OKXPublicClient,
    layout: LakeLayout,
    instrument: str,
    timeframe: str,
    *,
    start: datetime = DEFAULT_START,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillReport:
    """Run one resumable backfill session for ``instrument``/``timeframe``."""
    if instrument not in ALLOWED_INSTRUMENTS:
        raise ValueError(f"instrument {instrument!r} not allowed; allowed: {ALLOWED_INSTRUMENTS}")
    parse_timeframe(timeframe)  # fail closed on unsupported bar sizes
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")

    added = 0
    dupes = 0

    def on_page(rows: Sequence[Row]) -> None:
        nonlocal added, dupes
        result = write_candles(layout, [payload for _, payload in rows])
        added += result.added
        dupes += result.duplicates_dropped

    walker = BackwardWalker(
        _CandleSource(client, instrument, timeframe),
        state_path=layout.state_file("candles", instrument, timeframe),
        start_ms=to_ms(start),
        on_page=on_page,
        max_pages=max_pages,
        sleep_seconds=sleep_seconds,
        sleep=sleep,
    )
    walk = walker.run()
    cov = candle_coverage(layout, instrument, timeframe)
    report = BackfillReport(
        instrument=instrument,
        timeframe=timeframe,
        walk=walk,
        added=added,
        duplicates_dropped=dupes,
        stored_rows=cov.rows,
        stored_min=from_ms(cov.min_ms) if cov.min_ms is not None else None,
        stored_max=from_ms(cov.max_ms) if cov.max_ms is not None else None,
    )
    logger.info("Candle backfill session finished", extra={"summary": report.summary()})
    return report
