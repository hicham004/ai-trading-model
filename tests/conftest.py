"""Shared pytest fixtures.

Tests run fully offline and never touch the network or a real database. We use
an in-memory SQLite database so the suite is fast and isolated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


@pytest.fixture()
def db_session() -> Session:
    """Yield a SQLAlchemy session backed by a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # keep one shared in-memory connection
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_candle_row(
    ts_ms: int,
    open_: str = "100",
    high: str = "110",
    low: str = "90",
    close: str = "105",
    volume: str = "1000",
    confirm: str = "1",
) -> list[str]:
    """Build a raw OKX-style candle row (list of strings) for tests."""
    # OKX columns: ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm
    return [str(ts_ms), open_, high, low, close, volume, "0", "0", confirm]


def utc(year, month, day, hour=0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)
