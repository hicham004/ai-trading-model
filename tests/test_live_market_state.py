"""Tests for bounded live state and fail-closed per-feed health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.live.market_state import MarketState, MarketStateConfig
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    TickerUpdate,
    TradeUpdate,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLIC = "okx-public"
BUSINESS = "okx-business"


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _ticker(ts: datetime, last: float = 100.0) -> TickerUpdate:
    return TickerUpdate("BTC-USDT", ts, last=last, bid=last - 1, ask=last + 1)


def _trade(ts: datetime, trade_id: str, price: float = 100.0) -> TradeUpdate:
    return TradeUpdate(
        "BTC-USDT", ts, price=price, size=0.1, side="buy", trade_id=trade_id
    )


def _candle(ts: datetime, close: float, tf: str = "1m") -> CandleUpdate:
    return CandleUpdate(
        "BTC-USDT", tf, ts, 100.0, 110.0, 90.0, close, 12.0, confirmed=False
    )


def _register_required_feeds(state: MarketState) -> None:
    state.register_feed(PUBLIC, ["tickers:BTC-USDT", "trades:BTC-USDT"])
    state.register_feed(BUSINESS, ["candle1m:BTC-USDT"])


def _connect_feed(state: MarketState, feed_id: str) -> None:
    feed = state.feed_health(feed_id)
    state.set_feed_acked(feed_id, feed.required_subscriptions)
    state.set_feed_status(feed_id, ConnectionStatus.CONNECTED)


def test_ticker_accepts_newer_rejects_older_and_exact_duplicate():
    state = MarketState()
    assert state.apply_ticker(_ticker(T0 + timedelta(seconds=2), 200)) is True
    assert state.apply_ticker(_ticker(T0 + timedelta(seconds=1), 150)) is False
    assert state.apply_ticker(_ticker(T0 + timedelta(seconds=2), 200)) is False
    # Same timestamp with changed content is a legitimate quote refresh.
    assert state.apply_ticker(_ticker(T0 + timedelta(seconds=2), 250)) is True
    assert state.latest_tickers()[0].last == 250


def test_candle_accepts_forming_update_but_rejects_exact_duplicate_and_older():
    state = MarketState()
    candle = _candle(T0 + timedelta(minutes=1), close=105)
    assert state.apply_candle(candle) is True
    assert state.apply_candle(candle) is False
    assert state.apply_candle(_candle(candle.timestamp, close=106)) is True
    assert state.apply_candle(_candle(T0, close=99)) is False
    assert state.latest_candles()[0].close == 106


def test_trade_dedup_and_out_of_order():
    state = MarketState()
    assert state.apply_trade(_trade(T0 + timedelta(seconds=2), "a")) is True
    assert state.apply_trade(_trade(T0 + timedelta(seconds=3), "a")) is False
    assert state.apply_trade(_trade(T0 + timedelta(seconds=1), "b")) is False
    assert state.apply_trade(_trade(T0 + timedelta(seconds=4), "c")) is True
    assert [t.trade_id for t in state.recent_trades()] == ["a", "c"]


def test_trade_and_id_windows_are_bounded():
    state = MarketState(
        MarketStateConfig(
            max_trades_per_instrument=3, max_trade_ids_per_instrument=2
        )
    )
    for i in range(5):
        assert state.apply_trade(_trade(T0 + timedelta(seconds=i), f"id{i}"))
    assert [t.trade_id for t in state.recent_trades()] == ["id2", "id3", "id4"]
    # id2 has left the two-id dedup window and can be reused with a newer time.
    assert state.apply_trade(_trade(T0 + timedelta(seconds=6), "id2"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_trades_per_instrument": 0},
        {"max_trade_ids_per_instrument": -1},
        {"stale_after_seconds": 0},
        {"stale_after_seconds": float("nan")},
        {"stale_after_seconds": float("inf")},
    ],
)
def test_market_state_config_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError):
        MarketStateConfig(**kwargs)


def test_aggregate_health_requires_every_feed_and_retains_all_subscriptions():
    state = MarketState()
    _register_required_feeds(state)
    _connect_feed(state, PUBLIC)

    health = state.health_snapshot()
    assert health.connected is False
    assert health.status == ConnectionStatus.DISCONNECTED
    assert health.subscriptions == [
        "candle1m:BTC-USDT",
        "tickers:BTC-USDT",
        "trades:BTC-USDT",
    ]

    _connect_feed(state, BUSINESS)
    health = state.health_snapshot()
    assert health.connected is True
    assert health.status == ConnectionStatus.CONNECTED
    assert {feed.feed_id for feed in health.feeds} == {PUBLIC, BUSINESS}


@pytest.mark.parametrize("first_connected", [PUBLIC, BUSINESS])
def test_health_fails_closed_regardless_of_feed_update_order(first_connected):
    state = MarketState()
    _register_required_feeds(state)
    other = BUSINESS if first_connected == PUBLIC else PUBLIC
    _connect_feed(state, first_connected)
    state.set_feed_status(other, ConnectionStatus.RECONNECTING)

    health = state.health_snapshot()
    assert health.connected is False
    assert health.status == ConnectionStatus.RECONNECTING


def test_aggregate_stale_if_either_required_feed_is_stale():
    clock = FakeClock(T0)
    state = MarketState(MarketStateConfig(stale_after_seconds=30), clock=clock)
    _register_required_feeds(state)
    _connect_feed(state, PUBLIC)
    _connect_feed(state, BUSINESS)

    assert state.apply_ticker(_ticker(T0), PUBLIC)
    assert state.apply_candle(_candle(T0, 105), BUSINESS)
    assert state.health_snapshot().stale is False

    clock.now = T0 + timedelta(seconds=20)
    assert state.apply_ticker(_ticker(T0 + timedelta(seconds=1), 101), PUBLIC)
    clock.now = T0 + timedelta(seconds=31)

    health = state.health_snapshot()
    assert health.stale is True
    by_id = {feed.feed_id: feed for feed in health.feeds}
    assert by_id[PUBLIC].stale is False
    assert by_id[BUSINESS].stale is True


def test_transport_activity_does_not_refresh_market_data_freshness():
    clock = FakeClock(T0)
    state = MarketState(MarketStateConfig(stale_after_seconds=30), clock=clock)
    state.register_feed(PUBLIC, ["tickers:BTC-USDT"])
    state.mark_feed_transport(PUBLIC)

    feed = state.feed_health(PUBLIC)
    assert feed.last_transport_time == T0
    assert feed.last_market_data_time is None
    assert feed.stale is True


def test_duplicate_and_out_of_order_updates_do_not_refresh_freshness():
    clock = FakeClock(T0)
    state = MarketState(MarketStateConfig(stale_after_seconds=30), clock=clock)
    state.register_feed(PUBLIC, ["tickers:BTC-USDT"])
    ticker = _ticker(T0, 100)
    assert state.apply_ticker(ticker, PUBLIC)

    clock.now = T0 + timedelta(seconds=20)
    assert state.apply_ticker(ticker, PUBLIC) is False
    assert state.apply_ticker(_ticker(T0 - timedelta(seconds=1), 90), PUBLIC) is False
    assert state.feed_health(PUBLIC).last_market_data_time == T0


def test_register_feed_rejects_conflicting_identity():
    state = MarketState()
    state.register_feed(PUBLIC, ["tickers:BTC-USDT"])
    with pytest.raises(ValueError):
        state.register_feed(PUBLIC, ["trades:BTC-USDT"])


def test_unknown_feed_ids_fail_closed_without_mutating_health():
    state = MarketState()

    with pytest.raises(KeyError, match="not registered"):
        state.feed_health("typo-feed")
    with pytest.raises(KeyError, match="not registered"):
        state.set_feed_status("typo-feed", ConnectionStatus.CONNECTED)
    with pytest.raises(KeyError, match="not registered"):
        state.apply_ticker(_ticker(T0), "typo-feed")

    assert state.all_feed_health() == []
    assert state.latest_tickers() == []
    assert state.health_snapshot().connected is False


def test_feed_rejects_acknowledgements_it_did_not_request():
    state = MarketState()
    state.register_feed(PUBLIC, ["tickers:BTC-USDT"])

    with pytest.raises(ValueError, match="unexpected subscriptions"):
        state.set_feed_acked(PUBLIC, ["tickers:BTC-USDT", "orders:BTC-USDT"])

    assert state.feed_health(PUBLIC).acked_subscriptions == []


def test_state_snapshot_shapes():
    state = MarketState()
    state.apply_ticker(_ticker(T0, 100))
    state.apply_trade(_trade(T0, "a"))
    state.apply_candle(_candle(T0, 105))
    snap = state.state_snapshot(trade_limit=10)
    assert len(snap.tickers) == 1
    assert len(snap.candles) == 1
    assert len(snap.recent_trades) == 1
    assert "Public market-data observation only" in snap.health.note
