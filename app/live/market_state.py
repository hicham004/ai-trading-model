"""Bounded, thread/async-safe in-memory latest live market state.

This holds the latest observed public market data, bounded recent
trades/confirmed candles, reconstructed public order books, and per-feed
health. It is the in-process source of truth for the read-only API and
dashboard. It performs no I/O; the optional Phase 3B persistence worker polls
immutable snapshots without entering the WebSocket receive path.

Per-feed health (Codex finding 2): each connection (e.g. the public
ticker/trade feed and the business candle feed) has its own status,
subscriptions, and freshness. Aggregate health fails closed - it reports
connected only when every registered feed is connected AND fully acknowledged,
and stale if any feed is stale.

Transport vs market-data freshness (Codex finding 3): a feed tracks two
timestamps. ``last_transport_time`` advances on ANY received frame (including
malformed data, events, ping, and pong). ``last_market_data_time`` advances
ONLY when a valid ticker/trade/candle/order-book update is accepted. Staleness
is based on market-data freshness, so heartbeat or malformed traffic never
keeps a feed falsely fresh.

Concurrency: a single ``threading.RLock`` guards all access; it is never held
across an ``await``.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import Callable, Deque, Dict, List, Optional, Tuple

from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    FeedHealthOut,
    LiveHealthOut,
    LiveStateOut,
    OrderBookAction,
    OrderBookLevel,
    OrderBookLevelOut,
    OrderBookOut,
    OrderBookUpdate,
    PersistenceHealthOut,
    PersistenceStatus,
    TickerUpdate,
    TradeUpdate,
)


@dataclass(frozen=True)
class MarketStateConfig:
    """Bounds and freshness settings for the in-memory state."""

    max_trades_per_instrument: int = 100
    max_trade_ids_per_instrument: int = 512
    max_confirmed_candles: int = 512
    max_order_book_levels: int = 400
    stale_after_seconds: float = 30.0
    source_name: str = "okx-public-ws"

    def __post_init__(self) -> None:
        for name, value in (
            ("max_trades_per_instrument", self.max_trades_per_instrument),
            ("max_trade_ids_per_instrument", self.max_trade_ids_per_instrument),
            ("max_confirmed_candles", self.max_confirmed_candles),
            ("max_order_book_levels", self.max_order_book_levels),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isfinite(self.stale_after_seconds) or self.stale_after_seconds <= 0:
            raise ValueError(
                "stale_after_seconds must be a positive finite number "
                f"(got {self.stale_after_seconds!r})"
            )


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class _BoundedIdSet:
    """A bounded set that forgets the oldest ids once full (for trade dedup)."""

    def __init__(self, maxlen: int) -> None:
        self._order: Deque[str] = deque(maxlen=maxlen)
        self._members: set[str] = set()

    def __contains__(self, value: str) -> bool:
        return value in self._members

    def add(self, value: str) -> None:
        if value in self._members:
            return
        if self._order.maxlen and len(self._order) == self._order.maxlen:
            evicted = self._order[0]
            self._members.discard(evicted)
        self._order.append(value)
        self._members.add(value)


@dataclass
class _FeedHealth:
    """Mutable per-feed health record (guarded by the MarketState lock)."""

    feed_id: str
    required_subscriptions: Tuple[str, ...] = ()
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    acked_subscriptions: set = field(default_factory=set)
    last_transport_time: Optional[datetime] = None
    last_market_data_time: Optional[datetime] = None

    def fully_acked(self) -> bool:
        return bool(self.required_subscriptions) and set(
            self.required_subscriptions
        ) <= self.acked_subscriptions

    def is_connected(self) -> bool:
        # Fail-closed: a feed is only "connected" once its socket is connected
        # AND every required subscription has been acknowledged.
        return self.status == ConnectionStatus.CONNECTED and self.fully_acked()

    def is_stale(self, now: datetime, stale_after: float) -> bool:
        if self.last_market_data_time is None:
            return True
        return (now - self.last_market_data_time).total_seconds() > stale_after


class OrderBookApplyStatus(str, Enum):
    """Result of applying one sequence-checked order-book message."""

    ACCEPTED = "accepted"
    NO_CHANGE = "no_change"
    SEQUENCE_GAP = "sequence_gap"


@dataclass
class _OrderBookState:
    instrument: str
    feed_id: str
    bids: Dict[Decimal, OrderBookLevel] = field(default_factory=dict)
    asks: Dict[Decimal, OrderBookLevel] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    sequence_id: Optional[int] = None
    synchronized: bool = False
    sequence_gaps: int = 0
    sequence_resets: int = 0


@dataclass
class _PersistenceHealth:
    enabled: bool = False
    status: PersistenceStatus = PersistenceStatus.DISABLED
    stored_candles: int = 0
    stored_order_books: int = 0
    backfilled_candles: int = 0
    candle_gaps_detected: int = 0
    unresolved_candle_gaps: int = 0
    write_errors: int = 0
    last_write_time: Optional[datetime] = None
    last_error: Optional[str] = None


class MarketState:
    """Latest live public market data plus per-feed health, bounded + locked."""

    def __init__(
        self,
        config: Optional[MarketStateConfig] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._cfg = config or MarketStateConfig()
        self._clock = clock or _utcnow
        self._lock = threading.RLock()

        self._tickers: Dict[str, TickerUpdate] = {}
        self._candles: Dict[Tuple[str, str], CandleUpdate] = {}
        self._trades: Dict[str, Deque[TradeUpdate]] = {}
        self._recent_trade_ids: Dict[str, _BoundedIdSet] = {}
        self._confirmed_candles: Deque[CandleUpdate] = deque(
            maxlen=self._cfg.max_confirmed_candles
        )
        self._order_books: Dict[str, _OrderBookState] = {}
        self._persistence = _PersistenceHealth()

        # Last accepted timestamp per (instrument, stream-key) for ordering.
        self._last_ts: Dict[Tuple[str, str], datetime] = {}

        # Per-feed health, keyed by feed id (insertion order preserved).
        self._feeds: Dict[str, _FeedHealth] = {}

    @property
    def stale_after_seconds(self) -> float:
        return self._cfg.stale_after_seconds

    # -- feed registration / liveness --------------------------------------

    def register_feed(self, feed_id: str, required_subscriptions: List[str]) -> None:
        if not feed_id.strip():
            raise ValueError("feed_id must not be empty")
        required = tuple(sorted(set(required_subscriptions)))
        if not required:
            raise ValueError("a feed must require at least one subscription")
        with self._lock:
            feed = self._feeds.get(feed_id)
            if feed is None:
                self._feeds[feed_id] = _FeedHealth(
                    feed_id=feed_id, required_subscriptions=required
                )
            else:
                if feed.required_subscriptions and feed.required_subscriptions != required:
                    raise ValueError(
                        f"feed {feed_id!r} was already registered with different "
                        "subscriptions"
                    )
                feed.required_subscriptions = required

    def _require_feed(self, feed_id: str) -> _FeedHealth:
        feed = self._feeds.get(feed_id)
        if feed is None:
            raise KeyError(
                f"feed {feed_id!r} is not registered; call register_feed first"
            )
        return feed

    def set_feed_status(self, feed_id: str, status: ConnectionStatus) -> None:
        with self._lock:
            self._require_feed(feed_id).status = status

    def set_feed_acked(self, feed_id: str, acked_labels: List[str]) -> None:
        with self._lock:
            feed = self._require_feed(feed_id)
            acked = set(acked_labels)
            unexpected = acked - set(feed.required_subscriptions)
            if unexpected:
                raise ValueError(
                    f"feed {feed_id!r} acknowledged unexpected subscriptions: "
                    f"{sorted(unexpected)}"
                )
            feed.acked_subscriptions = acked

    def reset_feed_acks(self, feed_id: str) -> None:
        with self._lock:
            self._require_feed(feed_id).acked_subscriptions = set()

    def mark_feed_transport(self, feed_id: str) -> None:
        """Record that some frame arrived on the feed (transport liveness)."""
        with self._lock:
            self._require_feed(feed_id).last_transport_time = self._clock()

    def mark_feed_market_data(self, feed_id: str) -> None:
        """Record that a valid market-data update was accepted on the feed."""
        with self._lock:
            self._require_feed(feed_id).last_market_data_time = self._clock()

    def mark_feed_order_books_unsynchronized(self, feed_id: str) -> None:
        """Fail closed while a feed reconnects and waits for fresh snapshots."""
        with self._lock:
            self._require_feed(feed_id)
            for book in self._order_books.values():
                if book.feed_id == feed_id:
                    book.synchronized = False

    # -- applying updates (returns True if accepted) -----------------------

    def apply_ticker(self, update: TickerUpdate, feed_id: Optional[str] = None) -> bool:
        with self._lock:
            feed = self._require_feed(feed_id) if feed_id is not None else None
            if self._tickers.get(update.instrument) == update:
                return False
            if not self._accept_ts(update.instrument, "ticker", update.timestamp):
                return False
            self._tickers[update.instrument] = update
            if feed is not None:
                feed.last_market_data_time = self._clock()
            return True

    def apply_candle(self, update: CandleUpdate, feed_id: Optional[str] = None) -> bool:
        with self._lock:
            feed = self._require_feed(feed_id) if feed_id is not None else None
            if self._candles.get((update.instrument, update.timeframe)) == update:
                return False
            key = f"candle:{update.timeframe}"
            if not self._accept_ts(update.instrument, key, update.timestamp):
                return False
            self._candles[(update.instrument, update.timeframe)] = update
            if update.confirmed:
                self._confirmed_candles.append(update)
            if feed is not None:
                feed.last_market_data_time = self._clock()
            return True

    def apply_trade(self, update: TradeUpdate, feed_id: Optional[str] = None) -> bool:
        with self._lock:
            feed = self._require_feed(feed_id) if feed_id is not None else None
            ids = self._recent_trade_ids.setdefault(
                update.instrument, _BoundedIdSet(self._cfg.max_trade_ids_per_instrument)
            )
            if update.trade_id in ids:
                return False  # duplicate
            last = self._last_ts.get((update.instrument, "trade"))
            if last is not None and update.timestamp < last:
                return False  # out-of-order
            buf = self._trades.setdefault(
                update.instrument,
                deque(maxlen=self._cfg.max_trades_per_instrument),
            )
            buf.append(update)
            ids.add(update.trade_id)
            self._last_ts[(update.instrument, "trade")] = update.timestamp
            if feed is not None:
                feed.last_market_data_time = self._clock()
            return True

    def apply_order_book(
        self, update: OrderBookUpdate, feed_id: str
    ) -> OrderBookApplyStatus:
        """Apply a snapshot/update only when its sequence chain is continuous."""
        with self._lock:
            feed = self._require_feed(feed_id)
            book = self._order_books.get(update.instrument)

            if update.action == OrderBookAction.SNAPSHOT:
                if (
                    update.previous_sequence_id != -1
                    or not update.bids
                    or not update.asks
                ):
                    if book is None:
                        book = _OrderBookState(update.instrument, feed_id)
                        self._order_books[update.instrument] = book
                    book.sequence_gaps += 1
                    book.synchronized = False
                    return OrderBookApplyStatus.SEQUENCE_GAP
                book = _OrderBookState(
                    instrument=update.instrument,
                    feed_id=feed_id,
                    sequence_id=update.sequence_id,
                    timestamp=update.timestamp,
                    synchronized=True,
                    sequence_gaps=book.sequence_gaps if book is not None else 0,
                    sequence_resets=book.sequence_resets if book is not None else 0,
                )
                self._replace_book_side(book.bids, update.bids)
                self._replace_book_side(book.asks, update.asks)
                self._prune_book(book)
                self._order_books[update.instrument] = book
                feed.last_market_data_time = self._clock()
                return OrderBookApplyStatus.ACCEPTED

            if book is None or not book.synchronized or book.sequence_id is None:
                if book is None:
                    book = _OrderBookState(update.instrument, feed_id)
                    self._order_books[update.instrument] = book
                book.sequence_gaps += 1
                book.synchronized = False
                return OrderBookApplyStatus.SEQUENCE_GAP

            if book.feed_id != feed_id or update.previous_sequence_id != book.sequence_id:
                book.sequence_gaps += 1
                book.synchronized = False
                return OrderBookApplyStatus.SEQUENCE_GAP
            if (
                update.sequence_id == update.previous_sequence_id
                and (update.bids or update.asks)
            ):
                book.sequence_gaps += 1
                book.synchronized = False
                return OrderBookApplyStatus.SEQUENCE_GAP

            changed = self._merge_book_side(book.bids, update.bids)
            changed = self._merge_book_side(book.asks, update.asks) or changed
            if update.sequence_id < update.previous_sequence_id:
                # OKX documents sequence resets during maintenance. They are
                # valid when prevSeqId still matches our last accepted seqId.
                book.sequence_resets += 1
            book.sequence_id = update.sequence_id
            if changed:
                book.timestamp = update.timestamp
                self._prune_book(book)
                feed.last_market_data_time = self._clock()
                return OrderBookApplyStatus.ACCEPTED
            return OrderBookApplyStatus.NO_CHANGE

    @staticmethod
    def _replace_book_side(
        target: Dict[Decimal, OrderBookLevel],
        levels: Tuple[OrderBookLevel, ...],
    ) -> None:
        target.clear()
        for level in levels:
            if level.size > 0:
                target[level.price] = level

    @staticmethod
    def _merge_book_side(
        target: Dict[Decimal, OrderBookLevel],
        levels: Tuple[OrderBookLevel, ...],
    ) -> bool:
        changed = False
        for level in levels:
            existing = target.get(level.price)
            if level.size == 0:
                if existing is not None:
                    del target[level.price]
                    changed = True
            elif existing != level:
                target[level.price] = level
                changed = True
        return changed

    def _prune_book(self, book: _OrderBookState) -> None:
        max_levels = self._cfg.max_order_book_levels
        if len(book.bids) > max_levels:
            keep = set(sorted(book.bids, reverse=True)[:max_levels])
            book.bids = {price: book.bids[price] for price in keep}
        if len(book.asks) > max_levels:
            keep = set(sorted(book.asks)[:max_levels])
            book.asks = {price: book.asks[price] for price in keep}

    def _accept_ts(self, instrument: str, key: str, ts: datetime) -> bool:
        """Accept newer-or-equal timestamps; reject strictly older ones."""
        last = self._last_ts.get((instrument, key))
        if last is not None and ts < last:
            return False
        self._last_ts[(instrument, key)] = ts
        return True

    # -- optional persistence observability --------------------------------

    def configure_persistence(self, enabled: bool) -> None:
        with self._lock:
            self._persistence.enabled = enabled
            self._persistence.status = (
                PersistenceStatus.STARTING if enabled else PersistenceStatus.DISABLED
            )
            self._persistence.last_error = None

    def set_persistence_status(self, status: PersistenceStatus) -> None:
        with self._lock:
            self._persistence.status = status

    def record_persisted_candles(
        self,
        *,
        stored: int,
        backfilled: int = 0,
        gaps_detected: int = 0,
        unresolved_gaps: int = 0,
    ) -> None:
        with self._lock:
            self._persistence.stored_candles += stored
            self._persistence.backfilled_candles += backfilled
            self._persistence.candle_gaps_detected += gaps_detected
            self._persistence.unresolved_candle_gaps += unresolved_gaps
            if stored or backfilled:
                self._persistence.last_write_time = self._clock()
            self._persistence.last_error = None
            self._persistence.status = PersistenceStatus.RUNNING

    def record_persisted_order_book(self) -> None:
        with self._lock:
            self._persistence.stored_order_books += 1
            self._persistence.last_write_time = self._clock()
            self._persistence.last_error = None
            self._persistence.status = PersistenceStatus.RUNNING

    def record_persistence_error(self, error: Exception) -> None:
        with self._lock:
            self._persistence.write_errors += 1
            # Do not expose connection strings or other potentially sensitive
            # exception text through the read-only API.
            self._persistence.last_error = type(error).__name__
            self._persistence.status = PersistenceStatus.DEGRADED

    def persistence_health(self) -> PersistenceHealthOut:
        with self._lock:
            return PersistenceHealthOut(**vars(self._persistence))

    # -- read snapshots -----------------------------------------------------

    def _feed_health_out(self, feed: _FeedHealth, now: datetime) -> FeedHealthOut:
        since = (
            (now - feed.last_market_data_time).total_seconds()
            if feed.last_market_data_time is not None
            else None
        )
        return FeedHealthOut(
            feed_id=feed.feed_id,
            status=feed.status,
            connected=feed.is_connected(),
            stale=feed.is_stale(now, self._cfg.stale_after_seconds),
            last_transport_time=feed.last_transport_time,
            last_market_data_time=feed.last_market_data_time,
            seconds_since_market_data=since,
            required_subscriptions=sorted(feed.required_subscriptions),
            acked_subscriptions=sorted(feed.acked_subscriptions),
        )

    def feed_health(self, feed_id: str) -> FeedHealthOut:
        with self._lock:
            return self._feed_health_out(self._require_feed(feed_id), self._clock())

    def all_feed_health(self) -> List[FeedHealthOut]:
        """Return stable per-feed health snapshots without creating new feeds."""
        with self._lock:
            now = self._clock()
            return [
                self._feed_health_out(feed, now)
                for feed in self._feeds.values()
            ]

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        with self._lock:
            now = now or self._clock()
            if not self._feeds:
                return True  # fail closed: nothing observed yet
            return any(
                feed.is_stale(now, self._cfg.stale_after_seconds)
                for feed in self._feeds.values()
            )

    def _aggregate_status(self) -> ConnectionStatus:
        feeds = list(self._feeds.values())
        if not feeds:
            return ConnectionStatus.DISCONNECTED
        if all(f.is_connected() for f in feeds):
            return ConnectionStatus.CONNECTED
        if all(f.status == ConnectionStatus.STOPPED for f in feeds):
            return ConnectionStatus.STOPPED
        if any(f.status == ConnectionStatus.RECONNECTING for f in feeds):
            return ConnectionStatus.RECONNECTING
        if any(f.status == ConnectionStatus.CONNECTING for f in feeds):
            return ConnectionStatus.CONNECTING
        return ConnectionStatus.DISCONNECTED

    def health_snapshot(self) -> LiveHealthOut:
        with self._lock:
            now = self._clock()
            feeds = [self._feed_health_out(f, now) for f in self._feeds.values()]

            market_times = [
                f.last_market_data_time
                for f in self._feeds.values()
                if f.last_market_data_time is not None
            ]
            latest = max(market_times) if market_times else None
            since = (now - latest).total_seconds() if latest is not None else None

            subscriptions = sorted(
                {label for f in self._feeds.values() for label in f.required_subscriptions}
            )
            connected = bool(self._feeds) and all(
                f.is_connected() for f in self._feeds.values()
            )
            stale = (not self._feeds) or any(
                f.is_stale(now, self._cfg.stale_after_seconds)
                for f in self._feeds.values()
            )
            required_books = {
                label.split(":", 1)[1]
                for f in self._feeds.values()
                for label in f.required_subscriptions
                if label.startswith("books:")
            }
            books_synchronized = all(
                instrument in self._order_books
                and self._order_books[instrument].synchronized
                for instrument in required_books
            )
            return LiveHealthOut(
                source=self._cfg.source_name,
                status=self._aggregate_status(),
                connected=connected,
                stale=stale,
                order_books_synchronized=books_synchronized,
                ready=connected and not stale and books_synchronized,
                last_message_time=latest,
                seconds_since_last_message=since,
                subscriptions=subscriptions,
                feeds=feeds,
                persistence=PersistenceHealthOut(**vars(self._persistence)),
            )

    def latest_tickers(self) -> List[TickerUpdate]:
        with self._lock:
            return list(self._tickers.values())

    def latest_candles(self) -> List[CandleUpdate]:
        with self._lock:
            return list(self._candles.values())

    def recent_confirmed_candles(self) -> List[CandleUpdate]:
        with self._lock:
            return list(self._confirmed_candles)

    def latest_order_books(self, depth: Optional[int] = None) -> List[OrderBookOut]:
        with self._lock:
            limit = depth or self._cfg.max_order_book_levels
            return [
                self._order_book_out(book, limit)
                for book in self._order_books.values()
            ]

    @staticmethod
    def _order_book_out(book: _OrderBookState, depth: int) -> OrderBookOut:
        bids = sorted(book.bids.values(), key=lambda level: level.price, reverse=True)
        asks = sorted(book.asks.values(), key=lambda level: level.price)
        return OrderBookOut(
            instrument=book.instrument,
            timestamp=book.timestamp,
            synchronized=book.synchronized,
            sequence_id=book.sequence_id,
            sequence_gaps=book.sequence_gaps,
            sequence_resets=book.sequence_resets,
            bids=[
                OrderBookLevelOut(
                    price=float(level.price),
                    size=float(level.size),
                    order_count=level.order_count,
                )
                for level in bids[:depth]
            ],
            asks=[
                OrderBookLevelOut(
                    price=float(level.price),
                    size=float(level.size),
                    order_count=level.order_count,
                )
                for level in asks[:depth]
            ],
        )

    def recent_trades(self, limit: Optional[int] = None) -> List[TradeUpdate]:
        with self._lock:
            out: List[TradeUpdate] = []
            for buf in self._trades.values():
                out.extend(buf)
        out.sort(key=lambda t: t.timestamp)
        if limit is not None:
            out = out[-limit:]
        return out

    def state_snapshot(self, trade_limit: int = 50) -> LiveStateOut:
        from app.live.schemas import CandleOut, TickerOut, TradeOut

        health = self.health_snapshot()
        tickers = [TickerOut(**vars(t)) for t in self.latest_tickers()]
        candles = [CandleOut(**vars(c)) for c in self.latest_candles()]
        trades = [TradeOut(**vars(t)) for t in self.recent_trades(limit=trade_limit)]
        order_books = self.latest_order_books()
        return LiveStateOut(
            health=health,
            tickers=tickers,
            candles=candles,
            recent_trades=trades,
            order_books=order_books,
        )


# Module-level singleton used by the read-only API and the optional in-process
# autostart. Creating it performs no I/O; it is just empty in-memory state. Its
# staleness threshold comes from the application settings (Codex finding 8).
_DEFAULT_STATE: Optional[MarketState] = None
_DEFAULT_LOCK = threading.Lock()


def get_market_state() -> MarketState:
    """Return the process-wide default :class:`MarketState` (lazily created)."""
    global _DEFAULT_STATE
    if _DEFAULT_STATE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_STATE is None:
                from app.config import get_settings

                settings = get_settings()
                _DEFAULT_STATE = MarketState(
                    MarketStateConfig(
                        stale_after_seconds=settings.live_stale_after_seconds
                    )
                )
    return _DEFAULT_STATE


def reset_default_market_state() -> None:
    """Testing helper: drop the cached singleton so config can be re-read."""
    global _DEFAULT_STATE
    with _DEFAULT_LOCK:
        _DEFAULT_STATE = None
