"""Offline tests for the read-only Phase 3A API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.live import get_state
from app.api.main import app
from app.config import get_settings
from app.live.market_state import (
    MarketState,
    get_market_state,
    reset_default_market_state,
)
from app.live.schemas import ConnectionStatus, TickerUpdate, TradeUpdate

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def client_and_state():
    state = MarketState()
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)
    try:
        yield client, state
    finally:
        app.dependency_overrides.clear()


def _connected_public_feed(state: MarketState) -> None:
    required = ["tickers:BTC-USDT", "trades:BTC-USDT"]
    state.register_feed("okx-public", required)
    state.set_feed_acked("okx-public", required)
    state.set_feed_status("okx-public", ConnectionStatus.CONNECTED)


def test_live_health_empty_is_disconnected_and_stale(client_and_state):
    client, _ = client_and_state
    body = client.get("/live/health").json()
    assert body["status"] == ConnectionStatus.DISCONNECTED.value
    assert body["connected"] is False
    assert body["stale"] is True
    assert body["last_message_time"] is None
    assert body["subscriptions"] == []
    assert body["feeds"] == []
    assert "observation only" in body["note"].lower()


def test_live_instruments_endpoint(client_and_state):
    client, _ = client_and_state
    assert client.get("/live/instruments").json() == ["BTC-USDT", "ETH-USDT"]


def test_live_health_and_feeds_expose_per_connection_state(client_and_state):
    client, state = client_and_state
    _connected_public_feed(state)
    state.apply_ticker(
        TickerUpdate("BTC-USDT", T0, last=50000, bid=49999, ask=50001),
        "okx-public",
    )

    health = client.get("/live/health").json()
    feeds = client.get("/live/feeds").json()
    assert health["connected"] is True
    assert health["feeds"][0]["feed_id"] == "okx-public"
    assert feeds[0]["feed_id"] == health["feeds"][0]["feed_id"]
    assert feeds[0]["status"] == health["feeds"][0]["status"]
    assert feeds[0]["required_subscriptions"] == health["feeds"][0][
        "required_subscriptions"
    ]
    assert feeds[0]["acked_subscriptions"] == [
        "tickers:BTC-USDT",
        "trades:BTC-USDT",
    ]


def test_live_state_reflects_applied_updates(client_and_state):
    client, state = client_and_state
    _connected_public_feed(state)
    state.apply_ticker(
        TickerUpdate("BTC-USDT", T0, last=50000, bid=49999, ask=50001),
        "okx-public",
    )
    state.apply_trade(
        TradeUpdate(
            "BTC-USDT", T0, price=50000, size=0.1, side="buy", trade_id="t1"
        ),
        "okx-public",
    )

    body = client.get("/live/state").json()
    assert body["health"]["status"] == ConnectionStatus.CONNECTED.value
    assert body["tickers"][0]["last"] == 50000
    assert body["recent_trades"][0]["trade_id"] == "t1"


def test_live_tickers_and_trades_endpoints(client_and_state):
    client, state = client_and_state
    state.apply_ticker(
        TickerUpdate("ETH-USDT", T0, last=3000, bid=2999, ask=3001)
    )
    state.apply_trade(
        TradeUpdate(
            "ETH-USDT", T0, price=3000, size=1, side="sell", trade_id="x"
        )
    )
    assert client.get("/live/tickers").json()[0]["instrument"] == "ETH-USDT"
    assert client.get("/live/trades", params={"limit": 10}).json()[0]["side"] == "sell"


def test_live_query_limits_are_validated(client_and_state):
    client, _ = client_and_state
    assert client.get("/live/trades", params={"limit": 0}).status_code == 422
    assert client.get("/live/state", params={"trade_limit": 501}).status_code == 422


def test_default_api_state_uses_configured_stale_threshold(monkeypatch):
    monkeypatch.setenv("LIVE_STALE_AFTER_SECONDS", "7")
    get_settings.cache_clear()
    reset_default_market_state()
    try:
        assert get_market_state().stale_after_seconds == 7
    finally:
        get_settings.cache_clear()
        reset_default_market_state()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "not-a-number"])
def test_invalid_stale_threshold_fails_closed(monkeypatch, value):
    monkeypatch.setenv("LIVE_STALE_AFTER_SECONDS", value)
    get_settings.cache_clear()
    reset_default_market_state()
    try:
        with pytest.raises(ValueError, match="positive finite"):
            get_market_state()
    finally:
        get_settings.cache_clear()
        reset_default_market_state()


def test_no_trading_or_order_routes_exist():
    for route in app.routes:
        lowered = route.path.lower()
        assert "order" not in lowered
        assert "account" not in lowered
        assert "withdraw" not in lowered
