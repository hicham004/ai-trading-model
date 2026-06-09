"""Tests for the Candle ORM model and its uniqueness constraint (offline)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Candle


def _candle(**overrides) -> Candle:
    base = dict(
        instrument="BTC-USDT",
        timeframe="1H",
        open_time=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
    )
    base.update(overrides)
    return Candle(**base)


def test_can_insert_and_read_candle(db_session):
    db_session.add(_candle())
    db_session.commit()

    stored = db_session.query(Candle).one()
    assert stored.instrument == "BTC-USDT"
    assert stored.close == 105.0
    assert stored.created_at is not None


def test_unique_constraint_blocks_exact_duplicate(db_session):
    db_session.add(_candle())
    db_session.commit()

    # Same instrument + timeframe + open_time must be rejected by the DB.
    db_session.add(_candle(close=999.0))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_different_timeframe_is_allowed(db_session):
    db_session.add(_candle(timeframe="1H"))
    db_session.add(_candle(timeframe="15m"))
    db_session.commit()

    assert db_session.query(Candle).count() == 2
