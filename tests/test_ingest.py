"""Tests for storing candles, including duplicate prevention (offline)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.ingest import fetch_and_store, store_candles
from app.db.models import Candle as CandleRow
from app.okx.client import Candle as ApiCandle


def _api_candle(ts: datetime, close: float = 105.0) -> ApiCandle:
    return ApiCandle(
        instrument="BTC-USDT",
        timeframe="1H",
        timestamp=ts,
        open=100.0,
        high=110.0,
        low=90.0,
        close=close,
        volume=1000.0,
        confirmed=True,
    )


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(CandleRow))


def test_store_candles_inserts_rows(db_session):
    t1 = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    result = store_candles(
        db_session, "BTC-USDT", "1H", [_api_candle(t1), _api_candle(t2)]
    )
    db_session.commit()

    assert result.inserted == 2
    assert result.skipped_duplicates == 0
    assert _count(db_session) == 2


def test_store_candles_skips_duplicates(db_session):
    t1 = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)

    store_candles(db_session, "BTC-USDT", "1H", [_api_candle(t1)])
    db_session.commit()

    # Re-ingesting t1 plus a new t2: only t2 should be inserted.
    result = store_candles(
        db_session, "BTC-USDT", "1H", [_api_candle(t1), _api_candle(t2)]
    )
    db_session.commit()

    assert result.fetched == 2
    assert result.inserted == 1
    assert result.skipped_duplicates == 1
    assert _count(db_session) == 2


def test_store_candles_skips_duplicates_within_same_batch(db_session):
    t1 = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)

    result = store_candles(
        db_session, "BTC-USDT", "1H", [_api_candle(t1), _api_candle(t1)]
    )
    db_session.commit()

    assert result.fetched == 2
    assert result.inserted == 1
    assert result.skipped_duplicates == 1
    assert _count(db_session) == 1


def test_store_candles_rejects_mismatched_identity(db_session):
    t1 = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    mismatched = ApiCandle(
        instrument="ETH-USDT",
        timeframe="1H",
        timestamp=t1,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
        confirmed=True,
    )

    with pytest.raises(ValueError):
        store_candles(db_session, "BTC-USDT", "1H", [mismatched])


def test_store_empty_list_is_noop(db_session):
    result = store_candles(db_session, "BTC-USDT", "1H", [])
    assert result.fetched == 0
    assert result.inserted == 0
    assert _count(db_session) == 0


def test_fetch_and_store_uses_client(db_session):
    t1 = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)

    class StubClient:
        def get_candles(self, instrument, timeframe="1H", limit=100):
            assert instrument == "BTC-USDT"
            return [_api_candle(t1)]

    result = fetch_and_store(db_session, StubClient(), "BTC-USDT", "1H", limit=10)
    db_session.commit()

    assert result.inserted == 1
    assert _count(db_session) == 1
