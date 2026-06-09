"""Optional durable persistence for validated PUBLIC live market data.

Phase 3B persists two bounded data products only:

* confirmed public candles, with bounded public REST backfill when a gap is
  detected against the latest stored candle;
* sampled snapshots of the locally reconstructed, sequence-valid public order
  book.

The worker polls :class:`~app.live.market_state.MarketState`; it is not in the
WebSocket receive path, so database or REST failures cannot block market-data
parsing. No account, order, authentication, strategy, or trading data exists
in this module.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Callable, Deque, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.database import get_session_factory
from app.db.models import Candle as CandleRow
from app.db.models import OrderBookSnapshot as OrderBookSnapshotRow
from app.ingest import store_candles
from app.live.market_state import MarketState
from app.live.schemas import CandleUpdate, OrderBookOut, PersistenceStatus
from app.logging_config import get_logger
from app.okx.client import Candle as ApiCandle
from app.okx.client import OKXPublicClient
from app.strategy.timeframes import parse_timeframe

logger = get_logger(__name__)


@dataclass(frozen=True)
class LivePersistenceConfig:
    """Bounds and sampling intervals for the optional persistence worker."""

    poll_seconds: float = 1.0
    order_book_snapshot_seconds: float = 5.0
    order_book_depth: int = 20
    order_book_retention: int = 10_000
    max_backfill_bars: int = 300
    processed_candle_ids: int = 2_048

    def __post_init__(self) -> None:
        for name, value in (
            ("poll_seconds", self.poll_seconds),
            ("order_book_snapshot_seconds", self.order_book_snapshot_seconds),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        for name, value, maximum in (
            ("order_book_depth", self.order_book_depth, 400),
            ("order_book_retention", self.order_book_retention, None),
            ("max_backfill_bars", self.max_backfill_bars, 300),
            ("processed_candle_ids", self.processed_candle_ids, None),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or (maximum is not None and value > maximum)
            ):
                suffix = f" and no greater than {maximum}" if maximum else ""
                raise ValueError(f"{name} must be a positive integer{suffix}")


class _BoundedKeys:
    """Bounded insertion-ordered key set used for persistence de-duplication."""

    def __init__(self, maxlen: int) -> None:
        self._order: Deque[tuple] = deque()
        self._keys: set[tuple] = set()
        self._maxlen = maxlen

    def __contains__(self, key: tuple) -> bool:
        return key in self._keys

    def add(self, key: tuple) -> None:
        if key in self._keys:
            return
        while len(self._order) >= self._maxlen:
            self._keys.discard(self._order.popleft())
        self._order.append(key)
        self._keys.add(key)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_api_candle(update: CandleUpdate) -> ApiCandle:
    return ApiCandle(
        instrument=update.instrument,
        timeframe=update.timeframe,
        timestamp=update.timestamp,
        open=update.open,
        high=update.high,
        low=update.low,
        close=update.close,
        volume=update.volume,
        confirmed=update.confirmed,
    )


class LiveDataPersistence:
    """Poll and persist validated public data without blocking WebSockets."""

    def __init__(
        self,
        state: MarketState,
        *,
        config: Optional[LivePersistenceConfig] = None,
        client: Optional[OKXPublicClient] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._state = state
        self._config = config or LivePersistenceConfig()
        self._client = client or OKXPublicClient()
        self._session_factory = session_factory or get_session_factory()
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._processed_candles = _BoundedKeys(
            self._config.processed_candle_ids
        )
        self._last_book_sequence: dict[str, int] = {}
        self._last_book_write: dict[str, datetime] = {}
        self._state.configure_persistence(True)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Persist until stopped; failures are reported and retried later."""
        self._state.configure_persistence(True)
        self._state.set_persistence_status(PersistenceStatus.RUNNING)
        try:
            while not stop_event.is_set():
                await asyncio.to_thread(self.flush_once)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._config.poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        finally:
            self._state.set_persistence_status(PersistenceStatus.STOPPED)

    def flush_once(self) -> None:
        """Persist currently available data once (synchronous for testability)."""
        for candle in sorted(
            self._state.recent_confirmed_candles(),
            key=lambda item: item.timestamp,
        ):
            key = (candle.instrument, candle.timeframe, candle.timestamp)
            if key in self._processed_candles:
                continue
            try:
                self._persist_candle(candle)
            except Exception as exc:
                self._state.record_persistence_error(exc)
                logger.error(
                    "live candle persistence failed",
                    extra={
                        "instrument": candle.instrument,
                        "timeframe": candle.timeframe,
                        "error_type": type(exc).__name__,
                    },
                )
            else:
                self._processed_candles.add(key)

        now = _utc(self._clock())
        for book in self._state.latest_order_books(
            depth=self._config.order_book_depth
        ):
            if not self._should_persist_book(book, now):
                continue
            try:
                inserted = self._persist_order_book(book)
            except Exception as exc:
                self._state.record_persistence_error(exc)
                logger.error(
                    "live order-book persistence failed",
                    extra={
                        "instrument": book.instrument,
                        "error_type": type(exc).__name__,
                    },
                )
            else:
                self._last_book_sequence[book.instrument] = book.sequence_id  # type: ignore[assignment]
                self._last_book_write[book.instrument] = now
                if inserted:
                    self._state.record_persisted_order_book()

    def _persist_candle(self, candle: CandleUpdate) -> None:
        if not candle.confirmed:
            return
        interval = parse_timeframe(candle.timeframe)
        current_time = _utc(candle.timestamp)

        session = self._session_factory()
        try:
            previous = session.scalar(
                select(CandleRow.open_time)
                .where(
                    CandleRow.instrument == candle.instrument,
                    CandleRow.timeframe == candle.timeframe,
                    CandleRow.open_time < current_time,
                )
                .order_by(CandleRow.open_time.desc())
                .limit(1)
            )
        finally:
            session.close()

        backfill: list[ApiCandle] = []
        gaps_detected = 0
        unresolved = 0
        if previous is not None:
            previous_time = _utc(previous)
            delta = current_time - previous_time
            if delta > interval:
                gaps_detected = 1
                total_missing, aligned = self._missing_bar_count(delta, interval)
                if not aligned:
                    unresolved = max(1, total_missing)
                else:
                    requested = min(total_missing, self._config.max_backfill_bars)
                    history = self._client.get_history_candles(
                        candle.instrument,
                        timeframe=candle.timeframe,
                        limit=requested,
                        after=current_time,
                        confirmed_only=True,
                    )
                    expected_start = current_time - interval * requested
                    backfill = [
                        item
                        for item in history
                        if expected_start <= _utc(item.timestamp) < current_time
                        and _utc(item.timestamp) > previous_time
                    ]
                    expected = {
                        current_time - interval * offset
                        for offset in range(1, requested + 1)
                    }
                    found = {_utc(item.timestamp) for item in backfill}
                    unresolved = total_missing - len(expected & found)

        session = self._session_factory()
        try:
            backfill_result = store_candles(
                session,
                candle.instrument,
                candle.timeframe,
                backfill,
            )
            current_result = store_candles(
                session,
                candle.instrument,
                candle.timeframe,
                [_as_api_candle(candle)],
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        self._state.record_persisted_candles(
            stored=backfill_result.inserted + current_result.inserted,
            backfilled=backfill_result.inserted,
            gaps_detected=gaps_detected,
            unresolved_gaps=unresolved,
        )

    @staticmethod
    def _missing_bar_count(
        delta: timedelta, interval: timedelta
    ) -> tuple[int, bool]:
        interval_seconds = interval.total_seconds()
        delta_seconds = delta.total_seconds()
        quotient = delta_seconds / interval_seconds
        aligned = quotient.is_integer()
        return max(0, int(quotient) - 1), aligned

    def _should_persist_book(self, book: OrderBookOut, now: datetime) -> bool:
        if (
            not book.synchronized
            or book.timestamp is None
            or book.sequence_id is None
            or not book.bids
            or not book.asks
        ):
            return False
        if self._last_book_sequence.get(book.instrument) == book.sequence_id:
            return False
        last_write = self._last_book_write.get(book.instrument)
        return (
            last_write is None
            or (now - last_write).total_seconds()
            >= self._config.order_book_snapshot_seconds
        )

    def _persist_order_book(self, book: OrderBookOut) -> bool:
        assert book.timestamp is not None
        assert book.sequence_id is not None
        identity = (
            book.instrument,
            _utc(book.timestamp),
            book.sequence_id,
        )
        session = self._session_factory()
        try:
            exists = session.scalar(
                select(OrderBookSnapshotRow.id).where(
                    OrderBookSnapshotRow.instrument == identity[0],
                    OrderBookSnapshotRow.exchange_time == identity[1],
                    OrderBookSnapshotRow.sequence_id == identity[2],
                )
            )
            if exists is not None:
                return False

            bids = [
                [level.price, level.size, level.order_count]
                for level in book.bids
            ]
            asks = [
                [level.price, level.size, level.order_count]
                for level in book.asks
            ]
            session.add(
                OrderBookSnapshotRow(
                    instrument=book.instrument,
                    channel="books",
                    exchange_time=book.timestamp,
                    sequence_id=book.sequence_id,
                    depth=max(len(bids), len(asks)),
                    best_bid=book.bids[0].price,
                    best_ask=book.asks[0].price,
                    bids_json=json.dumps(bids, separators=(",", ":")),
                    asks_json=json.dumps(asks, separators=(",", ":")),
                )
            )
            session.flush()
            stale_ids = session.scalars(
                select(OrderBookSnapshotRow.id)
                .where(OrderBookSnapshotRow.instrument == book.instrument)
                .order_by(OrderBookSnapshotRow.id.desc())
                .offset(self._config.order_book_retention)
            ).all()
            if stale_ids:
                session.execute(
                    delete(OrderBookSnapshotRow).where(
                        OrderBookSnapshotRow.id.in_(stale_ids)
                    )
                )
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def build_persistence_from_settings(
    state: MarketState,
    settings,
) -> LiveDataPersistence:
    """Build the optional worker from application settings."""
    return LiveDataPersistence(
        state,
        config=LivePersistenceConfig(
            poll_seconds=settings.live_persistence_poll_seconds,
            order_book_snapshot_seconds=settings.live_order_book_snapshot_seconds,
            order_book_depth=settings.live_order_book_depth,
            order_book_retention=settings.live_order_book_retention,
            max_backfill_bars=settings.live_backfill_max_bars,
        ),
        client=OKXPublicClient(settings=settings),
    )
