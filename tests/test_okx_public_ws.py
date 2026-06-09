"""Adversarial offline tests for the public, unauthenticated OKX WS adapter."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.exchange.okx_public_ws import (
    BUSINESS_FEED_ID,
    CANDLE_CHANNEL,
    ORDER_BOOK_CHANNEL,
    OKX_BUSINESS_WS_URL,
    OKX_PUBLIC_WS_URL,
    PUBLIC_FEED_ID,
    OKXPublicWebSocketAdapter,
    _Subscription,
    _SubscriptionSession,
    build_default_adapters,
    build_subscriptions,
    candle_timeframe,
    endpoint_for_channel,
    parse_okx_message,
    run_adapters,
    validate_public_ws_url,
)
from app.live.market_state import MarketState
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    OrderBookAction,
    OrderBookUpdate,
    TickerUpdate,
    TradeUpdate,
)


def _ack(channel: str, instrument: str = "BTC-USDT") -> str:
    return json.dumps(
        {"event": "subscribe", "arg": {"channel": channel, "instId": instrument}}
    )


TICKER_ACK = _ack("tickers")
TRADE_ACK = _ack("trades")
CANDLE_ACK = _ack("candle1m")
BOOK_ACK = _ack("books")
ERROR_EVENT = json.dumps({"event": "error", "code": "60012", "msg": "bad"})
TICKER_MSG = json.dumps(
    {
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [
            {
                "instId": "BTC-USDT",
                "last": "50000",
                "bidPx": "49999",
                "askPx": "50001",
                "ts": "1700000000000",
            }
        ],
    }
)
TRADE_MSG = json.dumps(
    {
        "arg": {"channel": "trades", "instId": "BTC-USDT"},
        "data": [
            {
                "instId": "BTC-USDT",
                "tradeId": "t1",
                "px": "50000",
                "sz": "0.1",
                "side": "buy",
                "ts": "1700000000001",
            }
        ],
    }
)
CANDLE_MSG = json.dumps(
    {
        "arg": {"channel": CANDLE_CHANNEL, "instId": "BTC-USDT"},
        "data": [["1700000000000", "100", "110", "90", "105", "12", "0", "0", "1"]],
    }
)
BOOK_SNAPSHOT = json.dumps(
    {
        "arg": {"channel": ORDER_BOOK_CHANNEL, "instId": "BTC-USDT"},
        "action": "snapshot",
        "data": [
            {
                "bids": [["100", "2", "0", "3"], ["99", "4", "0", "2"]],
                "asks": [["101", "5", "0", "4"], ["102", "6", "0", "1"]],
                "ts": "1700000000000",
                "checksum": 0,
                "prevSeqId": -1,
                "seqId": 10,
            }
        ],
    }
)


def _message(channel: str, row: object, instrument: str = "BTC-USDT") -> str:
    return json.dumps(
        {"arg": {"channel": channel, "instId": instrument}, "data": [row]}
    )


def _public_subs():
    return [
        _Subscription("tickers", "BTC-USDT"),
        _Subscription("trades", "BTC-USDT"),
    ]


class FakeClosed(Exception):
    pass


class ScriptedConn:
    """Return scripted frames, then optionally block or raise closed."""

    def __init__(self, messages=(), *, block_after=False, fail_ping=False):
        self._messages = list(messages)
        self._block_after = block_after
        self._gate = asyncio.Event()
        self.fail_ping = fail_ping
        self.sent = []
        self.closed = False

    async def recv(self):
        if self._messages:
            item = self._messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self._block_after:
            await self._gate.wait()
        raise FakeClosed("exhausted")

    async def send(self, text):
        self.sent.append(text)
        if text == "ping" and self.fail_ping:
            raise ConnectionError("ping failed")

    async def close(self):
        self.closed = True


# -- parser and identity validation -----------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (TICKER_MSG, TickerUpdate),
        (TRADE_MSG, TradeUpdate),
        (CANDLE_MSG, CandleUpdate),
        (BOOK_SNAPSHOT, OrderBookUpdate),
    ],
)
def test_parse_valid_market_updates(raw, kind):
    outcome = parse_okx_message(raw)
    assert len(outcome.updates) == 1
    assert isinstance(outcome.updates[0], kind)


def test_parse_event_metadata():
    ack = parse_okx_message(TICKER_ACK)
    assert ack.event == "subscribe"
    assert ack.event_arg == {"channel": "tickers", "instId": "BTC-USDT"}
    error = parse_okx_message(ERROR_EVENT)
    assert error.event == "error"
    assert error.error_code == "60012"


@pytest.mark.parametrize("raw", ["", "{bad", "[]", b"\xff"])
def test_parse_malformed_frames_fail_closed(raw):
    outcome = parse_okx_message(raw)
    assert outcome.updates == []
    assert outcome.ignored


def test_parse_rejects_unsupported_instrument_and_channel():
    assert parse_okx_message(
        _message("tickers", {}, "DOGE-USDT")
    ).ignored[0].startswith("unsupported_instrument")
    assert parse_okx_message(
        _message("books5", {}, "BTC-USDT")
    ).ignored[0].startswith("unsupported_channel")


def test_parse_rejects_row_instrument_mismatch():
    row = {
        "instId": "ETH-USDT",
        "last": "100",
        "bidPx": "99",
        "askPx": "101",
        "ts": "1700000000000",
    }
    assert parse_okx_message(_message("tickers", row)).updates == []


def test_parse_rejects_trade_row_instrument_mismatch():
    row = {
        "instId": "ETH-USDT",
        "tradeId": "t",
        "px": "100",
        "sz": "1",
        "side": "buy",
        "ts": "1700000000000",
    }
    assert parse_okx_message(_message("trades", row)).updates == []


@pytest.mark.parametrize(
    "row",
    [
        {"instId": "BTC-USDT", "last": "100", "bidPx": "102", "askPx": "101", "ts": "1700000000000"},
        {"instId": "BTC-USDT", "last": "nan", "bidPx": "99", "askPx": "101", "ts": "1700000000000"},
    ],
)
def test_parse_rejects_invalid_ticker_invariants(row):
    assert parse_okx_message(_message("tickers", row)).updates == []


@pytest.mark.parametrize("size", ["0", "-1", "nan"])
def test_parse_requires_positive_finite_trade_size(size):
    row = {
        "instId": "BTC-USDT",
        "tradeId": "t",
        "px": "100",
        "sz": size,
        "side": "buy",
        "ts": "1700000000000",
    }
    assert parse_okx_message(_message("trades", row)).updates == []


@pytest.mark.parametrize(
    "row",
    [
        ["1700000000000", "100", "99", "90", "105", "1"],
        ["1700000000000", "100", "110", "101", "99", "1"],
    ],
)
def test_parse_rejects_incoherent_candles(row):
    assert parse_okx_message(_message(CANDLE_CHANNEL, row)).updates == []


def test_parse_order_book_snapshot_uses_sequence_ids_not_checksum():
    update = parse_okx_message(BOOK_SNAPSHOT).updates[0]
    assert isinstance(update, OrderBookUpdate)
    assert update.action == OrderBookAction.SNAPSHOT
    assert update.previous_sequence_id == -1
    assert update.sequence_id == 10
    assert update.bids[0].price == 100
    assert update.asks[0].size == 5


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.pop("action"),
        lambda body: body.update(action="partial"),
        lambda body: body["data"][0].update(prevSeqId=9),
        lambda body: body["data"][0].update(seqId=-1),
        lambda body: body["data"][0].update(bids=[["100", "-1", "0", "1"]]),
        lambda body: body["data"][0].update(asks=[["nan", "1", "0", "1"]]),
        lambda body: body["data"][0].update(bids=[["100", "1", "0"]]),
        lambda body: body["data"][0].update(
            bids=[["100", "1", "0", "1"], ["100", "2", "0", "2"]]
        ),
    ],
)
def test_parse_rejects_invalid_order_book_messages(mutate):
    body = json.loads(BOOK_SNAPSHOT)
    mutate(body)
    outcome = parse_okx_message(json.dumps(body))
    assert outcome.updates == []
    assert outcome.reconnect_required is True


def test_parse_accepts_empty_same_sequence_order_book_keepalive():
    body = json.loads(BOOK_SNAPSHOT)
    body["action"] = "update"
    body["data"][0].update(bids=[], asks=[], prevSeqId=10, seqId=10)
    update = parse_okx_message(json.dumps(body)).updates[0]
    assert update.action == OrderBookAction.UPDATE
    assert update.bids == ()
    assert update.asks == ()


# -- production scope validation -------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ws://ws.okx.com:8443/ws/v5/public",
        "wss://evil.example/ws/v5/public",
        "wss://ws.okx.com:8443/ws/v5/private",
        "wss://ws.okx.com:8443/ws/v5/public?x=1",
        "wss://user:pass@ws.okx.com:8443/ws/v5/public",
        "not a url",
        "wss://ws.okx.com:bad/ws/v5/public",
    ],
)
def test_validate_public_ws_url_rejects_unapproved_values(url):
    with pytest.raises(ValueError):
        validate_public_ws_url(url)


def test_validate_public_ws_url_enforces_feed_path():
    assert validate_public_ws_url(
        OKX_PUBLIC_WS_URL, expected_path="/ws/v5/public"
    ) == OKX_PUBLIC_WS_URL
    with pytest.raises(ValueError):
        validate_public_ws_url(
            OKX_BUSINESS_WS_URL, expected_path="/ws/v5/public"
        )


def test_channel_helpers_and_subscription_scope():
    assert endpoint_for_channel(
        "tickers", public_url="P", business_url="B"
    ) == "P"
    assert endpoint_for_channel(
        CANDLE_CHANNEL, public_url="P", business_url="B"
    ) == "B"
    assert endpoint_for_channel(
        ORDER_BOOK_CHANNEL, public_url="P", business_url="B"
    ) == "P"
    assert candle_timeframe(CANDLE_CHANNEL) == "1m"
    with pytest.raises(ValueError):
        endpoint_for_channel("books5", public_url="P", business_url="B")
    with pytest.raises(ValueError):
        build_subscriptions(["BTC-USDT"], ["candle-private-looking"])
    with pytest.raises(ValueError):
        build_subscriptions(["DOGE-USDT"], ["tickers"])
    with pytest.raises(ValueError):
        build_subscriptions(["BTC-USDT", "BTC-USDT"], ["tickers"])
    with pytest.raises(ValueError):
        build_subscriptions(["BTC-USDT"], ["tickers", "tickers"])


def test_default_adapters_bind_correct_urls_feeds_and_register_up_front():
    state = MarketState()
    adapters = build_default_adapters(state, connect=lambda _url: None)
    assert [(a.feed_id, a._url) for a in adapters] == [
        (PUBLIC_FEED_ID, OKX_PUBLIC_WS_URL),
        (BUSINESS_FEED_ID, OKX_BUSINESS_WS_URL),
    ]
    assert {feed.feed_id for feed in state.all_feed_health()} == {
        PUBLIC_FEED_ID,
        BUSINESS_FEED_ID,
    }
    public = state.feed_health(PUBLIC_FEED_ID)
    assert "books:BTC-USDT" in public.required_subscriptions
    assert "books:ETH-USDT" in public.required_subscriptions
    assert state.health_snapshot().connected is False


def test_default_adapters_reject_swapped_paths_and_non_candle_channel():
    with pytest.raises(ValueError):
        build_default_adapters(
            MarketState(),
            public_url=OKX_BUSINESS_WS_URL,
            business_url=OKX_PUBLIC_WS_URL,
            connect=lambda _url: None,
        )
    with pytest.raises(ValueError):
        build_default_adapters(
            MarketState(), candle_channel="tickers", connect=lambda _url: None
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ping_interval": 0},
        {"ack_timeout": float("nan")},
        {"initial_backoff": -1},
        {"backoff_factor": 0.5},
        {"initial_backoff": 2, "max_backoff": 1},
    ],
)
def test_adapter_rejects_invalid_runtime_parameters(kwargs):
    with pytest.raises(ValueError):
        OKXPublicWebSocketAdapter(
            MarketState(),
            "ws://fake",
            _public_subs(),
            connect=lambda _url: None,
            **kwargs,
        )


def test_adapter_rejects_duplicate_subscriptions():
    with pytest.raises(ValueError, match="duplicate subscriptions"):
        OKXPublicWebSocketAdapter(
            MarketState(),
            "ws://fake",
            [
                _Subscription("tickers", "BTC-USDT"),
                _Subscription("tickers", "BTC-USDT"),
            ],
            connect=lambda _url: None,
        )


def test_production_adapter_rejects_endpoint_channel_mismatch():
    with pytest.raises(ValueError, match="required"):
        OKXPublicWebSocketAdapter(
            MarketState(),
            OKX_BUSINESS_WS_URL,
            [_Subscription("tickers", "BTC-USDT")],
        )
    with pytest.raises(ValueError, match="cannot mix"):
        OKXPublicWebSocketAdapter(
            MarketState(),
            OKX_PUBLIC_WS_URL,
            [
                _Subscription("tickers", "BTC-USDT"),
                _Subscription(CANDLE_CHANNEL, "BTC-USDT"),
            ],
        )


# -- subscription lifecycle, heartbeat, reconnect --------------------------


def test_run_loop_connects_only_after_all_acks_and_applies_data():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        conn = ScriptedConn(
            [TICKER_ACK, TRADE_ACK, TICKER_MSG, TRADE_MSG, FakeClosed()]
        )

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: asyncio.sleep(0, result=conn),
            on_backoff=lambda _delay: stop.set(),
        )
        await adapter.run(stop)
        return state, conn

    state, conn = asyncio.run(drive())
    feed = state.feed_health(PUBLIC_FEED_ID)
    assert feed.status == ConnectionStatus.STOPPED
    assert feed.acked_subscriptions == ["tickers:BTC-USDT", "trades:BTC-USDT"]
    assert state.latest_tickers()[0].last == 50000
    assert state.recent_trades()[0].trade_id == "t1"
    assert conn.closed


def test_market_data_before_full_ack_is_not_applied_or_fresh():
    async def drive():
        state = MarketState()
        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: None,
        )
        session = _SubscriptionSession(adapter._subscriptions)
        conn = ScriptedConn()
        await adapter._process_frame(conn, TICKER_ACK, session)
        await adapter._process_frame(conn, TICKER_MSG, session)
        return state

    state = asyncio.run(drive())
    assert state.latest_tickers() == []
    assert state.feed_health(PUBLIC_FEED_ID).last_market_data_time is None


def test_partial_ack_is_visible_but_feed_never_connected_before_timeout():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        statuses = []
        conn = ScriptedConn([TICKER_ACK], block_after=True)

        def on_backoff(_delay):
            statuses.append(state.feed_health(PUBLIC_FEED_ID))
            stop.set()

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: asyncio.sleep(0, result=conn),
            ack_timeout=0.02,
            ping_interval=1,
            initial_backoff=0.001,
            on_backoff=on_backoff,
        )
        await adapter.run(stop)
        return statuses[0]

    health = asyncio.run(drive())
    assert health.status == ConnectionStatus.RECONNECTING
    assert health.connected is False
    assert health.acked_subscriptions == ["tickers:BTC-USDT"]


@pytest.mark.parametrize(
    "messages",
    [
        [ERROR_EVENT],
        [_ack("books5")],
        [TICKER_ACK, TICKER_ACK],
    ],
)
def test_error_wrong_or_duplicate_ack_forces_reconnect(messages):
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        observed = []
        conn = ScriptedConn(messages, block_after=True)

        def on_backoff(_delay):
            observed.append(state.feed_health(PUBLIC_FEED_ID).status)
            stop.set()

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: asyncio.sleep(0, result=conn),
            initial_backoff=0.001,
            on_backoff=on_backoff,
        )
        await adapter.run(stop)
        return observed, conn

    observed, conn = asyncio.run(drive())
    assert observed == [ConnectionStatus.RECONNECTING]
    assert conn.closed


def test_heartbeat_sent_only_after_acknowledgements():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        conn = ScriptedConn([TICKER_ACK, TRADE_ACK], block_after=True)
        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: asyncio.sleep(0, result=conn),
            ping_interval=0.01,
        )
        task = asyncio.create_task(adapter.run(stop))
        await asyncio.sleep(0.04)
        stop.set()
        await task
        return conn

    conn = asyncio.run(drive())
    assert "ping" in conn.sent
    assert conn.closed


def test_failed_heartbeat_closes_and_reconnects():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        first = ScriptedConn(
            [TICKER_ACK, TRADE_ACK], block_after=True, fail_ping=True
        )
        second = ScriptedConn(block_after=True)
        calls = []
        reconnect_statuses = []

        async def connect(_url):
            calls.append(1)
            if len(calls) == 1:
                return first
            stop.set()
            return second

        def on_backoff(_delay):
            reconnect_statuses.append(
                state.feed_health(PUBLIC_FEED_ID).status
            )

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=connect,
            ping_interval=0.01,
            initial_backoff=0.001,
            on_backoff=on_backoff,
        )
        await adapter.run(stop)
        return calls, reconnect_statuses, first

    calls, statuses, first = asyncio.run(drive())
    assert len(calls) == 2
    assert statuses[0] == ConnectionStatus.RECONNECTING
    assert first.closed


def test_backoff_is_bounded_exponential():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        delays = []

        async def connect(_url):
            raise ConnectionError("refused")

        def on_backoff(delay):
            delays.append(delay)
            if len(delays) == 4:
                stop.set()

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=connect,
            initial_backoff=0.001,
            backoff_factor=10,
            max_backoff=0.01,
            on_backoff=on_backoff,
        )
        await adapter.run(stop)
        return delays

    assert asyncio.run(drive()) == [0.001, 0.01, 0.01, 0.01]


def test_cancellation_closes_socket_and_marks_stopped():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        conn = ScriptedConn([TICKER_ACK, TRADE_ACK], block_after=True)
        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            _public_subs(),
            connect=lambda _url: asyncio.sleep(0, result=conn),
        )
        task = asyncio.create_task(adapter.run(stop))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return state, conn

    state, conn = asyncio.run(drive())
    assert conn.closed
    assert state.feed_health(PUBLIC_FEED_ID).status == ConnectionStatus.STOPPED


def test_non_market_frames_and_rejected_updates_do_not_refresh_freshness():
    async def drive():
        state = MarketState()
        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            [_Subscription("tickers", "BTC-USDT")],
            connect=lambda _url: None,
        )
        session = _SubscriptionSession(adapter._subscriptions)
        conn = ScriptedConn()
        for frame in ("pong", "ping", "{bad", TICKER_ACK, ERROR_EVENT):
            await adapter._process_frame(conn, frame, session)
        before = state.feed_health(PUBLIC_FEED_ID)
        await adapter._process_frame(conn, TICKER_MSG, session)
        accepted = state.feed_health(PUBLIC_FEED_ID)
        await adapter._process_frame(conn, TICKER_MSG, session)
        older = json.loads(TICKER_MSG)
        older["data"][0]["ts"] = "1699999999999"
        await adapter._process_frame(conn, json.dumps(older), session)
        duplicate = state.feed_health(PUBLIC_FEED_ID)
        return before, accepted, duplicate

    before, accepted, duplicate = asyncio.run(drive())
    assert before.last_transport_time is not None
    assert before.last_market_data_time is None
    assert accepted.last_market_data_time is not None
    assert duplicate.last_market_data_time == accepted.last_market_data_time


def test_import_and_construction_do_not_open_connection(monkeypatch):
    import app.exchange.okx_public_ws as ws
    from fastapi.testclient import TestClient
    from app.api.main import app

    calls = []

    async def tripwire(_url):
        calls.append(1)
        raise AssertionError("network connection opened during import/construction")

    monkeypatch.setattr(ws, "_default_connect", tripwire)
    assert TestClient(app).get("/live/health").status_code == 200
    ws.OKXPublicWebSocketAdapter(
        MarketState(), OKX_PUBLIC_WS_URL, [_Subscription("tickers", "BTC-USDT")]
    )
    assert calls == []


def test_run_adapters_cancels_siblings_when_one_adapter_crashes():
    class CrashingAdapter:
        feed_id = "crashing"

        async def run(self, stop_event):
            raise RuntimeError("offline test failure")

    class BlockingAdapter:
        feed_id = "blocking"

        def __init__(self):
            self.cancelled = False

        async def run(self, stop_event):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def drive():
        blocking = BlockingAdapter()
        with pytest.raises(RuntimeError, match="offline test failure"):
            await run_adapters(
                [blocking, CrashingAdapter()],  # type: ignore[list-item]
                asyncio.Event(),
            )
        return blocking

    assert asyncio.run(drive()).cancelled is True


def test_order_book_sequence_gap_forces_reconnect_and_marks_unsynchronized():
    async def drive():
        state = MarketState()
        stop = asyncio.Event()
        gap = json.loads(BOOK_SNAPSHOT)
        gap["action"] = "update"
        gap["data"][0].update(
            bids=[["100", "3", "0", "2"]],
            asks=[],
            prevSeqId=8,
            seqId=11,
        )
        conn = ScriptedConn(
            [BOOK_ACK, BOOK_SNAPSHOT, json.dumps(gap)],
            block_after=True,
        )

        def on_backoff(_delay):
            stop.set()

        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            [_Subscription(ORDER_BOOK_CHANNEL, "BTC-USDT")],
            connect=lambda _url: asyncio.sleep(0, result=conn),
            initial_backoff=0.001,
            on_backoff=on_backoff,
        )
        await adapter.run(stop)
        return state, conn

    state, conn = asyncio.run(drive())
    book = state.latest_order_books()[0]
    assert book.synchronized is False
    assert book.sequence_gaps == 1
    assert conn.closed is True


def test_malformed_order_book_frame_forces_immediate_reconnect():
    async def drive():
        state = MarketState()
        adapter = OKXPublicWebSocketAdapter(
            state,
            "ws://fake",
            [_Subscription(ORDER_BOOK_CHANNEL, "BTC-USDT")],
            connect=lambda _url: None,
        )
        session = _SubscriptionSession(adapter._subscriptions)
        session.record_ack({"channel": ORDER_BOOK_CHANNEL, "instId": "BTC-USDT"})
        malformed = json.loads(BOOK_SNAPSHOT)
        malformed["data"][0]["bids"] = [["100", "-1", "0", "1"]]
        return await adapter._process_frame(
            ScriptedConn(), json.dumps(malformed), session
        )

    assert asyncio.run(drive()) == "reconnect"
