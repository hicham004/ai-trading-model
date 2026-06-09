"""Offline adverse tests for Phase 3B public-data persistence/backfill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Candle, OrderBookSnapshot
from app.live.market_state import MarketState
from app.live.persistence import LiveDataPersistence, LivePersistenceConfig
from app.live.schemas import (
    CandleUpdate,
    OrderBookAction,
    OrderBookLevel,
    OrderBookUpdate,
    PersistenceStatus,
)
from app.okx.client import Candle as ApiCandle

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


def _live_candle(ts: datetime, *, confirmed: bool = True) -> CandleUpdate:
    return CandleUpdate(
        instrument="BTC-USDT",
        timeframe="1m",
        timestamp=ts,
        open=100,
        high=110,
        low=90,
        close=105,
        volume=12,
        confirmed=confirmed,
    )


def _api_candle(ts: datetime) -> ApiCandle:
    return ApiCandle(
        instrument="BTC-USDT",
        timeframe="1m",
        timestamp=ts,
        open=100,
        high=110,
        low=90,
        close=105,
        volume=12,
        confirmed=True,
    )


def _book(
    *,
    action: OrderBookAction,
    prev: int,
    seq: int,
    ts: datetime,
    bid_size: str,
) -> OrderBookUpdate:
    return OrderBookUpdate(
        instrument="BTC-USDT",
        timestamp=ts,
        action=action,
        bids=(OrderBookLevel(Decimal("100"), Decimal(bid_size), 1),),
        asks=(OrderBookLevel(Decimal("101"), Decimal("3"), 1),),
        previous_sequence_id=prev,
        sequence_id=seq,
    )


class FakeHistoryClient:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def get_history_candles(self, instrument, timeframe, limit, **kwargs):
        self.calls.append(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "limit": limit,
                **kwargs,
            }
        )
        return list(self.candles)


class FakeClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_confirmed_candle_is_persisted_and_missing_bars_are_backfilled(
    session_factory,
):
    seed = session_factory()
    seed.add(
        Candle(
            instrument="BTC-USDT",
            timeframe="1m",
            open_time=T0,
            open=100,
            high=110,
            low=90,
            close=105,
            volume=12,
        )
    )
    seed.commit()
    seed.close()

    state = MarketState()
    state.apply_candle(_live_candle(T0 + timedelta(minutes=3)))
    history = FakeHistoryClient(
        [_api_candle(T0 + timedelta(minutes=2)), _api_candle(T0 + timedelta(minutes=1))]
    )
    worker = LiveDataPersistence(
        state,
        client=history,  # type: ignore[arg-type]
        session_factory=session_factory,
    )

    worker.flush_once()

    session = session_factory()
    times = session.scalars(select(Candle.open_time).order_by(Candle.open_time)).all()
    session.close()
    assert len(times) == 4
    assert history.calls[0]["after"] == T0 + timedelta(minutes=3)
    assert history.calls[0]["limit"] == 2
    health = state.persistence_health()
    assert health.stored_candles == 3
    assert health.backfilled_candles == 2
    assert health.candle_gaps_detected == 1
    assert health.unresolved_candle_gaps == 0


def test_backfill_is_bounded_and_reports_unresolved_missing_bars(session_factory):
    seed = session_factory()
    seed.add(
        Candle(
            instrument="BTC-USDT",
            timeframe="1m",
            open_time=T0,
            open=100,
            high=110,
            low=90,
            close=105,
            volume=12,
        )
    )
    seed.commit()
    seed.close()

    state = MarketState()
    state.apply_candle(_live_candle(T0 + timedelta(minutes=5)))
    history = FakeHistoryClient([_api_candle(T0 + timedelta(minutes=4))])
    worker = LiveDataPersistence(
        state,
        config=LivePersistenceConfig(max_backfill_bars=2),
        client=history,  # type: ignore[arg-type]
        session_factory=session_factory,
    )

    worker.flush_once()

    health = state.persistence_health()
    assert history.calls[0]["limit"] == 2
    assert health.backfilled_candles == 1
    assert health.unresolved_candle_gaps == 3


def test_unconfirmed_candles_are_not_persisted(session_factory):
    state = MarketState()
    state.apply_candle(_live_candle(T0, confirmed=False))
    worker = LiveDataPersistence(
        state,
        client=FakeHistoryClient([]),  # type: ignore[arg-type]
        session_factory=session_factory,
    )
    worker.flush_once()

    session = session_factory()
    count = session.scalar(select(func.count()).select_from(Candle))
    session.close()
    assert count == 0


def test_sequence_valid_order_books_are_sampled_with_bounded_retention(
    session_factory,
):
    clock = FakeClock(T0)
    state = MarketState()
    state.register_feed("okx-public", ["books:BTC-USDT"])
    state.apply_order_book(
        _book(
            action=OrderBookAction.SNAPSHOT,
            prev=-1,
            seq=10,
            ts=T0,
            bid_size="2",
        ),
        "okx-public",
    )
    worker = LiveDataPersistence(
        state,
        config=LivePersistenceConfig(
            order_book_snapshot_seconds=1,
            order_book_retention=2,
        ),
        client=FakeHistoryClient([]),  # type: ignore[arg-type]
        session_factory=session_factory,
        clock=clock,
    )
    worker.flush_once()

    for prev, seq in ((10, 11), (11, 12)):
        clock.now += timedelta(seconds=1)
        state.apply_order_book(
            _book(
                action=OrderBookAction.UPDATE,
                prev=prev,
                seq=seq,
                ts=clock.now,
                bid_size=str(seq),
            ),
            "okx-public",
        )
        worker.flush_once()

    session = session_factory()
    rows = session.scalars(
        select(OrderBookSnapshot).order_by(OrderBookSnapshot.sequence_id)
    ).all()
    session.close()
    assert [row.sequence_id for row in rows] == [11, 12]
    assert all(row.depth == 1 for row in rows)
    assert state.persistence_health().stored_order_books == 3


def test_unsynchronized_order_book_is_never_persisted(session_factory):
    state = MarketState()
    state.register_feed("okx-public", ["books:BTC-USDT"])
    state.apply_order_book(
        _book(
            action=OrderBookAction.SNAPSHOT,
            prev=-1,
            seq=10,
            ts=T0,
            bid_size="2",
        ),
        "okx-public",
    )
    state.mark_feed_order_books_unsynchronized("okx-public")
    worker = LiveDataPersistence(
        state,
        client=FakeHistoryClient([]),  # type: ignore[arg-type]
        session_factory=session_factory,
    )
    worker.flush_once()

    session = session_factory()
    count = session.scalar(select(func.count()).select_from(OrderBookSnapshot))
    session.close()
    assert count == 0


def test_persistence_errors_are_redacted_in_read_only_health():
    state = MarketState()
    state.apply_candle(_live_candle(T0))

    def fail_session():
        raise RuntimeError("postgresql://user:secret@example.invalid/db")

    worker = LiveDataPersistence(
        state,
        client=FakeHistoryClient([]),  # type: ignore[arg-type]
        session_factory=fail_session,
    )
    worker.flush_once()

    health = state.persistence_health()
    assert health.status == PersistenceStatus.DEGRADED
    assert health.last_error == "RuntimeError"
    assert "secret" not in health.last_error


@pytest.mark.parametrize(
    "kwargs",
    [
        {"poll_seconds": 0},
        {"order_book_snapshot_seconds": float("nan")},
        {"order_book_depth": 401},
        {"order_book_retention": 0},
        {"max_backfill_bars": 301},
    ],
)
def test_persistence_config_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError):
        LivePersistenceConfig(**kwargs)
