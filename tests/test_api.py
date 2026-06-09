"""Tests for the read-only FastAPI backend (offline, in-memory SQLite).

We override the app's database dependency so no PostgreSQL connection is made.
We intentionally do NOT use the TestClient as a context manager, so the app's
startup lifespan (which would try to reach PostgreSQL) does not run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app, get_db
from app.db.models import Base, Candle, OrderBookSnapshot


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)

    # Seed two BTC candles.
    seed = TestSession()
    seed.add_all(
        [
            Candle(
                instrument="BTC-USDT",
                timeframe="1H",
                open_time=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=1000.0,
            ),
            Candle(
                instrument="BTC-USDT",
                timeframe="1H",
                open_time=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                open=105.0,
                high=120.0,
                low=100.0,
                close=115.0,
                volume=1200.0,
            ),
        ]
    )
    seed.add(
        OrderBookSnapshot(
            instrument="BTC-USDT",
            channel="books",
            exchange_time=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            sequence_id=123,
            depth=1,
            best_bid=100.0,
            best_ask=101.0,
            bids_json="[[100.0,2.0,1]]",
            asks_json="[[101.0,3.0,2]]",
        )
    )
    seed.commit()
    seed.close()

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_health_endpoint_reports_live_trading_disabled(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Phase 1 safety: live trading must always be reported as disabled.
    assert body["live_trading_enabled"] is False


def test_instruments_endpoint_lists_stored_instruments(client):
    resp = client.get("/instruments")
    assert resp.status_code == 200
    assert resp.json() == ["BTC-USDT"]


def test_candles_endpoint_returns_oldest_first(client):
    resp = client.get("/candles", params={"instrument": "BTC-USDT", "timeframe": "1H"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    times = [c["open_time"] for c in body["candles"]]
    assert times == sorted(times)  # oldest first
    assert body["candles"][0]["close"] == 105.0
    assert body["candles"][-1]["close"] == 115.0


def test_candles_endpoint_empty_for_unknown_instrument(client):
    resp = client.get("/candles", params={"instrument": "ETH-USDT", "timeframe": "1H"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_candles_endpoint_rejects_bad_limit(client):
    resp = client.get("/candles", params={"limit": 0})
    assert resp.status_code == 422  # FastAPI validation error


def test_persisted_order_book_history_is_read_only_and_newest_first(client):
    resp = client.get(
        "/live/order-book-history",
        params={"instrument": "BTC-USDT", "limit": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["snapshots"][0]["sequence_id"] == 123
    assert body["snapshots"][0]["bids"][0] == [100.0, 2.0, 1]
