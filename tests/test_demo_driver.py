"""Offline adversarial tests for the Phase 5 demo driver and its integration.

Covers the long-running driver's startup gate, account validation, private-WS
subscription/projection, amend lifecycle, kill-switch venue cancellation,
forward-only no-retrospective-trading, feed/lock fail-closed behavior, and clean
supervised shutdown. Fully offline: fake REST/WS transports, a fake clock, a
temporary SQLite database, and an in-memory public MarketState.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import (
    Base,
    DemoDailyBaseline,
    DemoEvent,
    DemoFill,
    DemoOrderIntent,
    DemoRuntimeStatus,
)
from app.exchange.credentials import DemoCredentials
from app.exchange.instruments import parse_instruments
from app.exchange.okx_demo_ws import OKXDemoPrivateWebSocket
from app.execution.account_validation import validate_demo_account
from app.execution.driver import DemoTradingDriver, GapRecoveryState, PositionView
from app.execution.identity import demo_identity_config
from app.execution.lifecycle import INTENT_ENTRY, INTENT_EXIT, OrderLifecycle
from app.execution.precision import PrecisionError, decimal_to_str, floor_size, validate_sell
from app.execution.reconcile import DemoReconciler
from app.execution.runtime import DemoExecutionRuntime
from app.execution.store import DemoStore, STATUS_CANCELED, STATUS_LIVE, STATUS_UNKNOWN
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoTransportError
from app.okx.client import Candle
from app.live.market_state import MarketState
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    OrderBookAction,
    OrderBookLevel,
    OrderBookUpdate,
)
from app.strategy.base import Signal, SignalAction
from scripts.run_demo_trading import _print_positions, _settings_for_account

T0 = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
CREDS = DemoCredentials("AK", "SK", "PP")


def _settings(**o) -> Settings:
    base = dict(
        demo_instruments=("BTC-USDT",), demo_account_name="demo", demo_strategy="ma_crossover",
        demo_timeframe="1m", demo_quote_currency="USDT", demo_order_type="limit",
        demo_max_risk_per_trade=0.5, demo_max_position_size=1.0, demo_max_total_exposure=1.0,
        demo_min_confidence=0.5, demo_max_order_notional=100.0, demo_max_candle_age_seconds=3600,
        demo_max_quote_age_seconds=10.0, demo_allowed_acct_levels=("1", "2"), demo_price_band=0.002,
        demo_private_stale_seconds=300, demo_arm_ttl_seconds=10 ** 9,
        okx_demo_rest_base_url="https://www.okx.com",
    )
    base.update(o)
    return Settings(**base)


def test_cli_account_override_reaches_authenticated_driver_settings():
    original = _settings(demo_account_name="demo")
    selected = _settings_for_account(original, "demo-seeded")
    assert selected.demo_account_name == "demo-seeded"
    assert original.demo_account_name == "demo"


def test_demo_identity_includes_risk_runtime_and_endpoint_settings():
    original = demo_identity_config(_settings())
    assert original != demo_identity_config(_settings(demo_max_daily_loss=0.01))
    assert original != demo_identity_config(_settings(demo_reconcile_interval_seconds=5))
    assert original != demo_identity_config(
        _settings(okx_demo_private_ws_url="wss://wspri.okx.com:8443/ws/v5/private")
    )


class FakeRest:
    def __init__(self):
        self.orders = {}
        self.placed = []
        self.acct = {"acctLv": "1"}
        self.instruments = [{
            "instType": "SPOT", "instId": "BTC-USDT", "baseCcy": "BTC", "quoteCcy": "USDT",
            "tickSz": "0.1", "lotSz": "0.00000001", "minSz": "0.00001", "state": "live",
        }]
        self.balances = {"details": [{"ccy": "USDT", "cashBal": "1000"}]}
        self.pending = []
        self.fills = []
        self.place_error = None
        self.amend_error = None

    def sync_time(self):
        return 0.0

    def get_account_config(self):
        return self.acct

    def get_instruments(self):
        return self.instruments

    def get_balances(self):
        return self.balances

    def get_pending_orders(self, instrument=None):
        return list(self.pending)

    def get_fills(self, instrument=None):
        return list(self.fills)

    def place_order(self, p):
        self.placed.append(p)
        if self.place_error is not None:
            err = self.place_error
            self.place_error = None
            raise err
        cl = p["clOrdId"]
        self.orders[cl] = {"clOrdId": cl, "ordId": "O" + cl[-4:], "state": "live",
                           "accFillSz": "0", "sCode": "0"}
        return self.orders[cl]

    def get_order(self, inst, cl_ord_id=None, ord_id=None):
        return self.orders.get(cl_ord_id)

    def cancel_order(self, inst, cl):
        if cl in self.orders:
            self.orders[cl]["state"] = "canceled"
        return {"sCode": "0"}

    def amend_order(self, inst, cl, *, new_size=None, new_price=None):
        if self.amend_error is not None:
            err = self.amend_error
            self.amend_error = None
            raise err
        return {"sCode": "0"}


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


def _connected_state(timeframe: str = "1m") -> MarketState:
    state = MarketState()
    for fid, subs in [
        ("okx-public", ["books:BTC-USDT"]),
        ("okx-business", [f"candle{timeframe}:BTC-USDT"]),
    ]:
        state.register_feed(fid, subs)
        state.set_feed_acked(fid, subs)
        state.set_feed_status(fid, ConnectionStatus.CONNECTED)
    return state


def _driver(
    session_factory,
    rest=None,
    state=None,
    clock_box=None,
    public_candle_client=None,
    **settings_overrides,
):
    clock_box = clock_box if clock_box is not None else {"t": T0}
    return DemoTradingDriver(
        credentials=CREDS, rest=rest or FakeRest(), session_factory=session_factory,
        settings=_settings(**settings_overrides), market_state=state or _connected_state(),
        clock=lambda: clock_box["t"], public_candle_client=public_candle_client,
    ), clock_box


def _feed_candles(state, clock_box, n=40, start=T0, base=100.0):
    for i in range(n):
        ts = start + timedelta(minutes=i)
        price = base + i * 0.5
        now = ts + timedelta(minutes=1, seconds=1)
        clock_box["t"] = now
        state.apply_candle(CandleUpdate("BTC-USDT", "1m", ts, price - 0.2, price + 0.5,
                                        price - 0.5, price, 10.0, True), "okx-business")
        state.apply_order_book(OrderBookUpdate(
            "BTC-USDT", now - timedelta(milliseconds=200), OrderBookAction.SNAPSHOT,
            (OrderBookLevel(Decimal(str(round(price - 0.01, 2))), Decimal("5"), 1),),
            (OrderBookLevel(Decimal(str(round(price + 0.01, 2))), Decimal("5"), 1),),
            -1, 500 + i), "okx-public")
        yield now


class FakePublicCandleClient:
    def __init__(self, rows=None, error: Optional[Exception] = None):
        self.rows = list(rows or [])
        self.error = error
        self.calls = []

    def get_history_candles(self, instrument, **kwargs):
        self.calls.append((instrument, kwargs))
        if self.error is not None:
            raise self.error
        return list(self.rows)


def _rest_candle(ts: datetime, *, timeframe: str = "1H", close: float = 100.0) -> Candle:
    return Candle(
        instrument="BTC-USDT",
        timeframe=timeframe,
        timestamp=ts,
        open=100.0,
        high=101.0,
        low=99.0,
        close=close,
        volume=10.0,
        confirmed=True,
    )


def _event_types(session_factory) -> list[str]:
    session = session_factory()
    try:
        return list(
            session.scalars(select(DemoEvent.event_type).order_by(DemoEvent.id.asc()))
        )
    finally:
        session.close()


def _open_demo_position(driver: DemoTradingDriver) -> None:
    entry = driver.lifecycle.submit(
        signal_id="seed-open-position",
        instrument="BTC-USDT",
        intent=INTENT_ENTRY,
        side="buy",
        ord_type="limit",
        price="100",
        size="0.001",
        stop_loss="95",
    )
    driver.project_private_orders([{
        "instId": "BTC-USDT",
        "clOrdId": entry.client_order_id,
        "ordId": entry.exchange_order_id,
        "state": "filled",
        "side": "buy",
        "accFillSz": "0.001",
        "tradeId": f"fill-{entry.client_order_id}",
        "fillSz": "0.001",
        "fillPx": "100",
    }])


def _fresh_book(state: MarketState, cb: dict, bid: str = "99.9", ask: str = "100.1") -> None:
    state.apply_order_book(
        OrderBookUpdate(
            "BTC-USDT",
            cb["t"] - timedelta(milliseconds=100),
            OrderBookAction.SNAPSHOT,
            (OrderBookLevel(Decimal(bid), Decimal("5"), 1),),
            (OrderBookLevel(Decimal(ask), Decimal("5"), 1),),
            -1,
            900,
        ),
        "okx-public",
    )


# -- account validation ----------------------------------------------------


def test_account_validation_rejects_margin_mode():
    rest = FakeRest()
    rest.acct = {"acctLv": "3"}  # multi-currency margin
    v = validate_demo_account(rest, instruments=("BTC-USDT",), allowed_acct_levels=("1", "2"), quote_ccy="USDT")
    assert not v.ok and any("account level" in i for i in v.issues)


def test_account_validation_rejects_margin_capable_level_even_if_configured():
    rest = FakeRest()
    rest.acct = {"acctLv": "2"}
    validation = validate_demo_account(
        rest,
        instruments=("BTC-USDT",),
        allowed_acct_levels=("1", "2"),
        quote_ccy="USDT",
    )
    assert not validation.ok


def test_account_validation_rejects_liability_borrow():
    rest = FakeRest()
    rest.balances = {"details": [{"ccy": "USDT", "cashBal": "1000", "liab": "5"}]}
    v = validate_demo_account(rest, instruments=("BTC-USDT",), allowed_acct_levels=("1",), quote_ccy="USDT")
    assert not v.ok and any("liability" in i for i in v.issues)


def test_account_validation_rejects_instrument_mismatch():
    rest = FakeRest()
    rest.instruments = [{"instType": "SPOT", "instId": "BTC-USDT", "baseCcy": "BTC",
                         "quoteCcy": "USDC", "tickSz": "0.1", "lotSz": "0.00000001",
                         "minSz": "0.00001", "state": "live"}]
    v = validate_demo_account(rest, instruments=("BTC-USDT",), allowed_acct_levels=("1",), quote_ccy="USDT")
    assert not v.ok


def test_account_validation_ok():
    v = validate_demo_account(FakeRest(), instruments=("BTC-USDT",), allowed_acct_levels=("1",), quote_ccy="USDT")
    assert v.ok and "BTC-USDT" in v.instruments


# -- startup gate ----------------------------------------------------------


def test_startup_gate_happy_path_armable(session_factory):
    driver, _ = _driver(session_factory)
    gate = driver.startup_gate()
    assert gate.lock_acquired and gate.account_valid and gate.consistent and gate.armable


def test_startup_gate_lock_unavailable(session_factory):
    d1, _ = _driver(session_factory)
    d1.store.acquire_lock(d1.account_id, "other-token", now=T0)
    gate = d1.startup_gate()
    assert not gate.lock_acquired and not gate.armable


def test_startup_gate_blocks_on_account_invalid(session_factory):
    rest = FakeRest()
    rest.acct = {"acctLv": "4"}  # portfolio margin
    driver, _ = _driver(session_factory, rest=rest)
    gate = driver.startup_gate()
    assert gate.lock_acquired and not gate.account_valid and not gate.armable


def test_startup_gate_time_sync_failure(session_factory):
    rest = FakeRest()

    def boom():
        raise OKXDemoTransportError("no time")
    rest.sync_time = boom
    driver, _ = _driver(session_factory, rest=rest)
    gate = driver.startup_gate()
    assert gate.lock_acquired and not gate.account_valid and not gate.armable


def test_startup_gate_blocks_while_ambiguous_unknown_intent(session_factory):
    rest = FakeRest()
    driver, _ = _driver(session_factory, rest=rest)
    # Seed an UNKNOWN intent (ambiguous submission) the exchange does not know.
    from app.execution.store import IntentInput
    cl = driver.lifecycle.client_order_id("BTC-USDT", INTENT_ENTRY, "sX")
    driver.store.create_intent(driver.account_id, IntentInput(cl, "sX", "BTC-USDT", "buy", "entry", "limit", "1", "0.001"), now=T0)
    driver.store.record_submission(driver.account_id, cl, request_kind="place", attempt=1,
                                   outcome="unknown", new_status=STATUS_UNKNOWN, now=T0)
    # The exchange DOES still have it (so resolve keeps it... actually rest has no order -> resolve)
    # Make get_order return it as still live so it stays UNKNOWN->live? We want ambiguous to remain.
    rest.orders.pop(cl, None)  # not found -> resolve keeps UNKNOWN (place was attempted)
    gate = driver.startup_gate()
    # not found but place attempted => stays UNKNOWN => ambiguous => not armable
    assert not gate.armable


# -- forward-only / no retrospective trading -------------------------------


def test_no_retrospective_trading_after_warmup(session_factory):
    from app.db.models import Candle

    # Persisted public history (as if accumulated before/while down).
    s = session_factory()
    try:
        for i in range(40):
            ts = T0 + timedelta(minutes=i)
            price = 100.0 + i * 0.5
            s.add(Candle(instrument="BTC-USDT", timeframe="1m", open_time=ts,
                         open=price - 0.2, high=price + 0.5, low=price - 0.5,
                         close=price, volume=10.0))
        s.commit()
    finally:
        s.close()

    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=41)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)

    seeded = driver.warmup()
    assert seeded == 40
    assert rest.placed == []  # warmup is context only; it never trades

    # Those same historical candles now also appear in the live state; the
    # watermark from warmup must prevent any retrospective trade.
    for i in range(40):
        ts = T0 + timedelta(minutes=i)
        price = 100.0 + i * 0.5
        state.apply_candle(CandleUpdate("BTC-USDT", "1m", ts, price - 0.2, price + 0.5,
                                        price - 0.5, price, 10.0, True), "okx-business")
    state.apply_order_book(OrderBookUpdate(
        "BTC-USDT", cb["t"] - timedelta(milliseconds=200), OrderBookAction.SNAPSHOT,
        (OrderBookLevel(Decimal("119.0"), Decimal("5"), 1),),
        (OrderBookLevel(Decimal("119.5"), Decimal("5"), 1),), -1, 999), "okx-public")
    driver._private_last_msg = cb["t"]
    driver.step(cb["t"])
    assert rest.placed == []  # no retrospective trading of warmed-up candles


def test_step_blocks_entry_on_stale_private_stream(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_private_stale_seconds=5)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = T0  # never refreshed -> goes stale during the run
    placed = 0
    for now in _feed_candles(state, cb, n=40):
        placed += len(driver.step(now))
    assert placed == 0  # stale private stream blocks every entry


def test_step_places_entry_when_all_healthy(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    placed = 0
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        placed += len(driver.step(now))
    assert placed >= 1
    assert rest.placed[-1]["tdMode"] == "cash" and rest.placed[-1]["side"] == "buy"


def test_candle_gap_latches_entries_but_keeps_live_candles_for_exits(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    backfill = FakePublicCandleClient(rows=[])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill,
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)

    def add(minute):
        ts = T0 + timedelta(minutes=minute)
        cb["t"] = ts + timedelta(minutes=1, seconds=1)
        state.apply_candle(
            CandleUpdate("BTC-USDT", "1m", ts, 100, 101, 99, 100, 10, True),
            "okx-business",
        )

    add(0)
    driver.step(cb["t"])
    add(2)
    driver.step(cb["t"])
    assert driver._watermark["BTC-USDT"] == T0 + timedelta(minutes=2)
    assert not driver._market_continuity_ok
    assert backfill.calls
    add(1)
    driver.step(cb["t"])
    # MarketState correctly rejects the late out-of-order bar. The driver
    # keeps processing live candles for exits, but entries remain fail-closed
    # without exact public REST recovery.
    assert driver._watermark["BTC-USDT"] == T0 + timedelta(minutes=2)
    assert not driver._market_continuity_ok
    assert "market_candle_backfill_failed" in _event_types(session_factory)


def test_candle_gap_recovers_after_exact_backfill_and_two_live_closes(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    missing = T0 + timedelta(hours=1)
    observed = T0 + timedelta(hours=2)
    backfill = FakePublicCandleClient(rows=[_rest_candle(missing)])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]

    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", T0, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])
    assert driver._watermark["BTC-USDT"] == T0

    cb["t"] = observed + timedelta(hours=1, seconds=1)
    driver._private_last_msg = cb["t"]
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 102, 103, 101, 102, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    assert driver._watermark["BTC-USDT"] == observed
    assert not driver._market_continuity_ok
    assert driver._gap_recovery["BTC-USDT"].confirmations_remaining == 1
    assert backfill.calls == [
        (
            "BTC-USDT",
            {
                "timeframe": "1H",
                "limit": 1,
                "after": observed,
                "confirmed_only": True,
            },
        )
    ]

    driver.step(cb["t"])
    assert driver._watermark["BTC-USDT"] == observed
    assert not driver._market_continuity_ok
    assert driver._gap_recovery["BTC-USDT"].confirmations_remaining == 1

    third = T0 + timedelta(hours=3)
    cb["t"] = third + timedelta(hours=1, seconds=1)
    driver._private_last_msg = cb["t"]
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", third, 103, 104, 102, 103, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    assert driver._watermark["BTC-USDT"] == third
    assert driver._market_continuity_ok
    events = _event_types(session_factory)
    assert "market_candle_backfill_succeeded" in events
    assert "market_candle_recovery_cleared" in events


def test_candle_gap_preserves_received_prefix_and_observed_batch_candle(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    first = T0
    live_prefix = T0 + timedelta(hours=1)
    missing = T0 + timedelta(hours=2)
    observed = T0 + timedelta(hours=3)
    backfill = FakePublicCandleClient(rows=[_rest_candle(missing)])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]

    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", first, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    cb["t"] = observed + timedelta(hours=1, seconds=1)
    driver._private_last_msg = cb["t"]
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", live_prefix, 101, 102, 100, 101, 10, True),
        "okx-business",
    )
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 103, 104, 102, 103, 10, True),
        "okx-business",
    )

    driver.step(cb["t"])

    assert [c.timestamp for c in driver._windows["BTC-USDT"]] == [
        first,
        live_prefix,
        missing,
        observed,
    ]
    assert driver._watermark["BTC-USDT"] == observed
    assert not driver._market_continuity_ok
    assert driver._gap_recovery["BTC-USDT"].expected_missing == [missing]
    assert driver._gap_recovery["BTC-USDT"].confirmations_remaining == 1
    assert backfill.calls == [
        (
            "BTC-USDT",
            {
                "timeframe": "1H",
                "limit": 1,
                "after": observed,
                "confirmed_only": True,
            },
        )
    ]


def test_gap_latch_blocks_long_entry_on_same_candle_as_successful_backfill(session_factory):
    class AlwaysLong:
        def generate_signals(self, candles):
            return [
                Signal(
                    timestamp=candle.timestamp,
                    instrument=candle.instrument,
                    action=SignalAction.LONG,
                    confidence=1.0,
                    reason="test long",
                    stop_loss=candle.close * 0.98,
                )
                for candle in candles
            ]

    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=3, seconds=1)}
    missing = T0 + timedelta(hours=1)
    observed = T0 + timedelta(hours=2)
    backfill = FakePublicCandleClient(rows=[_rest_candle(missing)])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]
    driver._strategy = AlwaysLong()
    driver._watermark["BTC-USDT"] = T0
    _fresh_book(state, cb)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 102, 103, 101, 102, 10, True),
        "okx-business",
    )

    results = driver.step(cb["t"])

    assert results == []
    assert rest.placed == []
    assert driver._gap_recovery["BTC-USDT"].status == "pending"
    assert driver._gap_recovery["BTC-USDT"].confirmations_remaining == 1
    assert not driver._market_continuity_ok


def test_candle_gap_oversized_stays_latched_without_backfill(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    backfill = FakePublicCandleClient(rows=[_rest_candle(T0 + timedelta(hours=1))])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", T0, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    observed = T0 + timedelta(hours=5)
    cb["t"] = observed + timedelta(hours=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 105, 106, 104, 105, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    assert not driver._market_continuity_ok
    assert backfill.calls == []
    assert "market_candle_gap_too_large" in _event_types(session_factory)


def test_candle_gap_backfill_requires_exact_missing_open_time(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    wrong_slot = T0 + timedelta(hours=1, minutes=5)
    backfill = FakePublicCandleClient(rows=[_rest_candle(wrong_slot)])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", T0, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    observed = T0 + timedelta(hours=2)
    cb["t"] = observed + timedelta(hours=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 102, 103, 101, 102, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    assert not driver._market_continuity_ok
    assert "market_candle_backfill_failed" in _event_types(session_factory)


def test_candle_gap_recovery_cap_blocks_chronic_auto_recovery(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    backfill = FakePublicCandleClient(rows=[_rest_candle(T0 + timedelta(hours=1))])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    for i in range(3):
        driver.store.record_event(
            driver.account_id,
            "market_candle_recovery_cleared",
            "info",
            f"prior recovery {i}",
            now=cb["t"] - timedelta(hours=i),
        )

    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", T0, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])
    observed = T0 + timedelta(hours=2)
    cb["t"] = observed + timedelta(hours=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 102, 103, 101, 102, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    assert not driver._market_continuity_ok
    assert backfill.calls == []
    assert "market_candle_recovery_cap_exceeded" in _event_types(session_factory)


def test_candle_backfill_divergence_stays_latched(session_factory):
    rest = FakeRest()
    state = _connected_state("1H")
    cb = {"t": T0 + timedelta(hours=1, seconds=1)}
    missing = T0 + timedelta(hours=1)
    observed = T0 + timedelta(hours=2)
    backfill = FakePublicCandleClient(rows=[_rest_candle(missing, close=100.0)])
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb,
        public_candle_client=backfill, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", T0, 100, 101, 99, 100, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])
    cb["t"] = observed + timedelta(hours=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1H", observed, 102, 103, 101, 102, 10, True),
        "okx-business",
    )
    driver.step(cb["t"])

    driver._check_recovered_overlap(
        "BTC-USDT",
        CandleUpdate("BTC-USDT", "1H", missing, 100, 101, 99, 100.5, 10, True),
    )

    assert not driver._market_continuity_ok
    assert "market_candle_backfill_divergence" in _event_types(session_factory)


@pytest.mark.parametrize("status", ["failed", "too_large", "cap_exceeded", "diverged"])
@pytest.mark.parametrize("exit_kind", ["stop", "flat"])
def test_terminal_gap_latch_does_not_gate_stop_or_flat_exits(
    session_factory, status, exit_kind
):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=3, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]
    _open_demo_position(driver)

    driver._watermark["BTC-USDT"] = T0
    driver._market_continuity["BTC-USDT"] = False
    driver._gap_recovery["BTC-USDT"] = GapRecoveryState(
        status=status,
        expected_missing=[T0 + timedelta(minutes=1)],
        observed_at=T0 + timedelta(minutes=2),
        last_error=f"test_{status}",
    )
    _fresh_book(state, cb, bid="91.9" if exit_kind == "stop" else "99.9",
                ask="92.1" if exit_kind == "stop" else "100.1")
    candle_ts = T0 + timedelta(minutes=2)
    low = 90 if exit_kind == "stop" else 96
    close = 92 if exit_kind == "stop" else 100
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", candle_ts, 100, 101, low, close, 10, True),
        "okx-business",
    )

    before = len(rest.placed)
    results = driver.step(cb["t"])

    assert results
    assert len(rest.placed) == before + 1
    assert rest.placed[-1]["side"] == "sell"
    assert {p["side"] for p in rest.placed[before:]} == {"sell"}
    assert not driver._market_continuity_ok
    assert not driver._effective_feed_status(cb["t"]).usable
    assert driver._effective_feed_status(
        cb["t"], require_market_continuity=False
    ).usable


def test_market_continuity_gap_blocks_entries_only_not_exit_readiness(session_factory):
    state = _connected_state("1H")
    cb = {"t": T0}
    driver, _ = _driver(
        session_factory, state=state, clock_box=cb, demo_timeframe="1H",
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]
    state.mark_feed_market_data("okx-public")
    state.mark_feed_market_data("okx-business")
    driver._market_continuity["BTC-USDT"] = False

    entry_feed = driver._effective_feed_status(cb["t"])
    exit_feed = driver._effective_feed_status(
        cb["t"], require_market_continuity=False
    )

    assert not entry_feed.usable
    assert exit_feed.usable
    assert driver._market_feed_status(cb["t"]).usable

    async def heartbeat_once():
        stop = asyncio.Event()
        task = asyncio.create_task(driver._heartbeat_loop(stop))
        await asyncio.sleep(0)
        stop.set()
        await task

    asyncio.run(heartbeat_once())
    session = session_factory()
    try:
        status = session.scalar(
            select(DemoRuntimeStatus).where(
                DemoRuntimeStatus.account_id == driver.account_id
            )
        )
        assert status.feed_connected is True
        assert status.feed_stale is False
    finally:
        session.close()


def test_protective_stop_submits_exit_and_daily_baseline_is_immutable(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    entry = driver.lifecycle.submit(
        signal_id="entry-with-stop",
        instrument="BTC-USDT",
        intent=INTENT_ENTRY,
        side="buy",
        ord_type="limit",
        price="100",
        size="0.001",
        stop_loss="95",
    )
    driver.project_private_orders([{
        "instId": "BTC-USDT",
        "clOrdId": entry.client_order_id,
        "ordId": entry.exchange_order_id,
        "state": "filled",
        "side": "buy",
        "accFillSz": "0.001",
        "tradeId": "stop-fill",
        "fillSz": "0.001",
        "fillPx": "100",
    }])
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", T0, 100, 101, 90, 92, 10, True),
        "okx-business",
    )
    state.apply_order_book(
        OrderBookUpdate(
            "BTC-USDT",
            cb["t"] - timedelta(milliseconds=100),
            OrderBookAction.SNAPSHOT,
            (OrderBookLevel(Decimal("91.9"), Decimal("5"), 1),),
            (OrderBookLevel(Decimal("92.1"), Decimal("5"), 1),),
            -1,
            900,
        ),
        "okx-public",
    )
    driver._private_last_msg = cb["t"]
    results = driver.step(cb["t"])
    assert any(rest.orders[r.client_order_id]["state"] == "live" for r in results)
    assert rest.placed[-1]["side"] == "sell"

    baseline = driver.store.get_or_create_daily_baseline(
        driver.account_id, T0.date(), Decimal("1000"), now=T0
    )
    assert baseline == Decimal("1000")
    assert driver.store.get_or_create_daily_baseline(
        driver.account_id, T0.date(), Decimal("1"), now=T0
    ) == Decimal("1000")
    session = session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(DemoDailyBaseline)) == 1
    finally:
        session.close()


# -- lot-precision flatness in the safety core (R14 part A; design section 7, C)


def _armed_driver(session_factory, rest, state, cb, **settings_overrides):
    driver, _ = _driver(
        session_factory, rest=rest, state=state, clock_box=cb, **settings_overrides
    )
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    driver._private_last_msg = cb["t"]
    return driver


def _open_demo_position_with_base_fee(driver: DemoTradingDriver, fee: str) -> None:
    """Like _open_demo_position, with the entry fee charged in BTC (as OKX does).

    A base-currency fee finer than the lot leaves a sub-lot component in the
    fill-derived net, so the lot-floored sellable size differs from the raw net.
    """
    entry = driver.lifecycle.submit(
        signal_id="seed-open-position-base-fee",
        instrument="BTC-USDT",
        intent=INTENT_ENTRY,
        side="buy",
        ord_type="limit",
        price="100",
        size="0.001",
        stop_loss="95",
    )
    driver.project_private_orders([{
        "instId": "BTC-USDT",
        "clOrdId": entry.client_order_id,
        "ordId": entry.exchange_order_id,
        "state": "filled",
        "side": "buy",
        "accFillSz": "0.001",
        "tradeId": f"fill-{entry.client_order_id}",
        "fillSz": "0.001",
        "fillPx": "100",
        "fillFee": fee,
        "fillFeeCcy": "BTC",
    }])


def _exit_demo_position_leaving(
    driver: DemoTradingDriver, residue: str, *, partial_then_cancel: bool = False
) -> None:
    """Project a sell on the 0.001 BTC seed position that leaves ``residue`` BTC.

    Fills are projected as strings and the store sums Decimals, so the ledger
    net becomes exactly ``residue``: sub-lot dust (below one lot) after a full
    exit, or an unsellable remainder (between one lot and the venue minimum)
    after a partially filled then cancelled exit (design section 6, row 13).
    """
    sold = str(Decimal("0.001") - Decimal(residue))
    exit_ = driver.lifecycle.submit(
        signal_id=f"seed-exit-{residue}",
        instrument="BTC-USDT",
        intent=INTENT_EXIT,
        side="sell",
        ord_type="limit",
        price="100",
        size="0.001" if partial_then_cancel else sold,
    )
    row = {
        "instId": "BTC-USDT",
        "clOrdId": exit_.client_order_id,
        "ordId": exit_.exchange_order_id,
        "side": "sell",
        "accFillSz": sold,
    }
    driver.project_private_orders([{
        **row,
        "state": "partially_filled" if partial_then_cancel else "filled",
        "tradeId": f"fill-{exit_.client_order_id}",
        "fillSz": sold,
        "fillPx": "100",
    }])
    if partial_then_cancel:
        driver.project_private_orders([{**row, "state": "canceled"}])
    assert driver.store.position_summary(driver.account_id, "BTC-USDT")[0] == Decimal(residue)


def _events(session_factory, event_type: str) -> list[dict]:
    session = session_factory()
    try:
        return [
            {
                "severity": e.severity,
                "message": e.message,
                # SQLite returns naive UTC datetimes.
                "event_time": e.event_time.replace(tzinfo=e.event_time.tzinfo or timezone.utc),
                "payload": json.loads(e.payload_json),
            }
            for e in session.scalars(
                select(DemoEvent)
                .where(DemoEvent.event_type == event_type)
                .order_by(DemoEvent.id.asc())
            )
        ]
    finally:
        session.close()


def _risk_decision_reasons(session_factory) -> list[str]:
    return [e["payload"]["reason"] for e in _events(session_factory, "risk_decision")]


def test_dust_does_not_block_entry_with_position_already_open(session_factory):
    """Design 7.C item 21 (reproduction A inverted): sub-lot fee dust never blocks an entry."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)
    _exit_demo_position_leaving(driver, "1.2E-10")  # the live June 11, 2026 residue
    seeded = len(rest.placed)
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    reasons = _risk_decision_reasons(session_factory)
    assert reasons, "LONG signals must reach the entry gate"
    assert "position_already_open" not in reasons
    assert "max_open_positions" not in reasons
    assert "ok" in reasons  # the first cleared LONG entered
    assert rest.placed[seeded:] and {p["side"] for p in rest.placed[seeded:]} == {"buy"}
    assert _events(session_factory, "unsellable_remainder") == []  # dust is not a remainder
    view = driver._position_view("BTC-USDT", driver._instrument_meta["BTC-USDT"])
    assert (view.net, view.sellable, view.remainder, view.flat) == (
        Decimal("1.2E-10"), Decimal(0), Decimal(0), True,
    )


def test_dust_does_not_count_as_open_position_for_max_open_positions_or_exposure(
    session_factory,
):
    """Design 7.C item 22: dust is not an open position for the caps; marked equity still includes it."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb, demo_max_open_positions=1)
    _open_demo_position(driver)
    # A sellable position without a usable quote keeps the fail-closed answer...
    assert driver._equity_exposure(cb["t"]) == (Decimal(0), Decimal("Infinity"), 1)
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    # ...and with one it is one open position with its marked exposure.
    assert driver._equity_exposure(cb["t"]) == (
        Decimal("1000") + Decimal("0.001") * Decimal("99.9"),
        Decimal("0.001") * Decimal("99.9"),
        1,
    )
    _exit_demo_position_leaving(driver, "1.2E-10")
    equity, exposure, open_positions = driver._equity_exposure(cb["t"])
    assert open_positions == 0
    assert open_positions < driver._settings.demo_max_open_positions
    assert exposure == Decimal(0)
    assert equity == Decimal("1000") + Decimal("1.2E-10") * Decimal("99.9")


def test_dust_with_stale_stop_skips_stop_check_and_evaluates_strategy(session_factory):
    """Design 7.C item 23 (reproduction C): dust + the old stop + a low under it -> no exit attempt, strategy evaluated."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)  # the stop level 95 stays persisted on the entry intent
    _exit_demo_position_leaving(driver, "1.2E-10")
    assert driver.store.position_summary(driver.account_id, "BTC-USDT") == (
        Decimal("1.2E-10"), Decimal("95"),
    )
    seeded = len(rest.placed)
    # 29 rising candles: the 30-bar rule is still warming up (FLAT); nothing to sell.
    for now in _feed_candles(state, cb, n=29):
        driver._private_last_msg = now
        driver.step(now)
    assert rest.placed[seeded:] == []
    assert _risk_decision_reasons(session_factory) == []
    # The 30th candle spikes under the stale stop (low 90 <= 95) but closes high,
    # so the rule's first computable signal on it is LONG.
    spike_ts = T0 + timedelta(minutes=29)
    cb["t"] = spike_ts + timedelta(minutes=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", spike_ts, 114.3, 115.0, 90.0, 114.5, 10.0, True),
        "okx-business",
    )
    _fresh_book(state, cb, bid="114.4", ask="114.6")
    driver._private_last_msg = cb["t"]
    driver.step(cb["t"])
    assert _events(session_factory, "exit_precision_rejected") == []  # no stop exit attempted
    decisions = _events(session_factory, "risk_decision")
    assert len(decisions) == 1 and decisions[0]["event_time"] == cb["t"]
    assert decisions[0]["payload"]["reason"] == "ok"
    assert [p["side"] for p in rest.placed[seeded:]] == ["buy"]


@pytest.mark.parametrize("exit_kind", ["stop", "flat"])
def test_sellable_position_still_exits_on_stop_breach_and_on_flat(session_factory, exit_kind):
    """Design 7.C item 24: a sellable position still exits on a stop breach and on FLAT; the raw net is passed, validate_sell floors it."""
    rest, state = FakeRest(), _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position_with_base_fee(driver, fee="-0.00000000012")
    net = Decimal("0.001") - Decimal("0.00000000012")
    assert driver.store.position_summary(driver.account_id, "BTC-USDT")[0] == net

    passed: list[Decimal] = []
    original = driver._runtime.consider_exit

    def spy(**kwargs):
        passed.append(kwargs["base_balance"])
        return original(**kwargs)

    driver._runtime.consider_exit = spy
    if exit_kind == "stop":
        candle = CandleUpdate("BTC-USDT", "1m", T0, 100, 101, 90, 92, 10, True)  # low 90 <= 95
        _fresh_book(state, cb, bid="91.9", ask="92.1")
    else:
        candle = CandleUpdate("BTC-USDT", "1m", T0, 100, 101, 96, 100, 10, True)  # warm-up FLAT
        _fresh_book(state, cb, bid="99.9", ask="100.1")
    state.apply_candle(candle, "okx-business")
    seeded = len(rest.placed)
    results = driver.step(cb["t"])
    assert results and [p["side"] for p in rest.placed[seeded:]] == ["sell"]
    assert passed == [net]  # the RAW net reached consider_exit
    assert rest.placed[-1]["sz"] == "0.00099999"  # validate_sell floored it to the lot
    signal_id = driver.store.get_intent(driver.account_id, results[-1].client_order_id).signal_id
    if exit_kind == "stop":
        assert signal_id == f"stop|BTC-USDT|{T0.isoformat()}"
    else:
        assert signal_id.startswith("BTC-USDT|1m|")
    view = driver._position_view("BTC-USDT", driver._instrument_meta["BTC-USDT"])
    assert (view.net, view.sellable, view.remainder, view.flat) == (
        net, Decimal("0.00099999"), Decimal(0), False,
    )


def test_unsellable_remainder_is_reported_not_traded_and_does_not_block_entry(session_factory):
    """Design 7.C item 25 (section 6 row 13): 0 < floored < min_size -> one event, no sell, entry not blocked."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)
    # 100 lots remain after a partially filled then cancelled exit: below the 0.00001 minimum.
    _exit_demo_position_leaving(driver, "0.000001", partial_then_cancel=True)
    seeded = len(rest.placed)

    # Candle 1: low under the stale stop (95) while the rule still says FLAT: nothing is sold.
    cb["t"] = T0 + timedelta(minutes=1, seconds=1)
    state.apply_candle(CandleUpdate("BTC-USDT", "1m", T0, 100, 101, 90, 92, 10, True), "okx-business")
    _fresh_book(state, cb, bid="91.9", ask="92.1")
    driver._private_last_msg = cb["t"]
    assert driver.step(cb["t"]) == []
    events = _events(session_factory, "unsellable_remainder")
    assert len(events) == 1 and events[0]["severity"] == "warning"
    payload = events[0]["payload"]
    assert payload["instrument"] == "BTC-USDT"
    assert Decimal(payload["net"]) == Decimal("0.000001")
    assert Decimal(payload["floored"]) == Decimal("0.000001")
    assert Decimal(payload["min_size"]) == Decimal("0.00001")
    assert _events(session_factory, "exit_precision_rejected") == []

    # Candle 2, same remainder: not reported again, still nothing sold.
    cb["t"] = T0 + timedelta(minutes=2, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", T0 + timedelta(minutes=1), 100, 101, 90, 92, 10, True),
        "okx-business",
    )
    _fresh_book(state, cb, bid="91.9", ask="92.1")
    driver._private_last_msg = cb["t"]
    assert driver.step(cb["t"]) == []
    assert len(_events(session_factory, "unsellable_remainder")) == 1
    assert rest.placed[seeded:] == []

    # Rising candles until the rule says LONG: the remainder does not block the entry.
    for now in _feed_candles(state, cb, n=40, start=T0 + timedelta(minutes=2)):
        driver._private_last_msg = now
        driver.step(now)
    reasons = _risk_decision_reasons(session_factory)
    assert "ok" in reasons
    assert "position_already_open" not in reasons
    assert "max_open_positions" not in reasons
    assert [p["side"] for p in rest.placed[seeded:]] == ["buy"]
    assert len(_events(session_factory, "unsellable_remainder")) == 1
    assert _events(session_factory, "exit_precision_rejected") == []
    view = driver._position_view("BTC-USDT", driver._instrument_meta["BTC-USDT"])
    assert (view.net, view.remainder, view.sellable, view.flat) == (
        Decimal("0.000001"), Decimal("0.000001"), Decimal(0), False,
    )


@pytest.mark.parametrize(
    "residue, partial_then_cancel, without_quote",
    [
        # Sub-lot dust (worth less than one lot) is marked at zero and skipped...
        ("1.2E-10", False, (Decimal("1000"), Decimal(0), 0)),
        # ...an unsellable remainder (worth up to one venue-minimum order) cannot
        # be marked and fails closed exactly as a sellable position does.
        ("0.000001", True, (Decimal(0), Decimal("Infinity"), 1)),
    ],
    ids=["sub_lot_dust", "unsellable_remainder"],
)
def test_equity_includes_residue_value_but_exposure_excludes_it(
    session_factory, residue, partial_then_cancel, without_quote
):
    """Design 7.C item 26: marked equity = cash + residue value; exposure and the open-position count exclude it."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)
    _exit_demo_position_leaving(driver, residue, partial_then_cancel=partial_then_cancel)
    # No usable quote: never looser than before this change (see the parametrization).
    assert driver._equity_exposure(cb["t"]) == without_quote
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    equity, exposure, open_positions = driver._equity_exposure(cb["t"])
    assert equity == Decimal("1000") + Decimal(residue) * Decimal("99.9")
    assert exposure == Decimal(0)
    assert open_positions == 0


@pytest.mark.parametrize(
    "residue, partial_then_cancel, expected",
    [
        (None, False, "position BTC-USDT: 0.001 OPEN (sellable 0.001, stop=95)"),
        ("1.2E-10", False,
         "position BTC-USDT: FLAT at lot precision (sub-lot dust 1.2E-10; sellable 0)"),
        ("0.000001", True,
         "position BTC-USDT: unsellable remainder 0.000001 (below minimum 0.00001; "
         "net 0.000001): reported, not traded, not an open position"),
    ],
    ids=["open", "dust", "remainder"],
)
def test_print_positions_reports_sellable_and_remainder_state(
    session_factory, capsys, residue, partial_then_cancel, expected
):
    """Operator report: the --reconcile/--arm position lines use the driver's PositionView definitions."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)
    if residue is not None:
        _exit_demo_position_leaving(driver, residue, partial_then_cancel=partial_then_cancel)
    _print_positions(driver, driver._settings)
    assert expected in capsys.readouterr().out


def test_sellable_position_blocks_entry_with_position_already_open(session_factory):
    """Regression guard for the rewired entry gate (review finding safety-F2).

    A real sellable position still refuses every LONG with position_already_open,
    reaches the gate as the SELLABLE size and is counted as one open position for
    the max_open_positions cap (a Decimal(0) or open_positions=0 wiring would pass
    the behavioural tests of items 21-26, which only assert the reason's absence).
    """
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    _open_demo_position(driver)
    seeded = len(rest.placed)

    seen: list[tuple[Decimal, int, Decimal, Decimal]] = []
    original = driver._runtime.consider_entry

    def spy(ctx):
        seen.append((
            ctx.instrument_position_size,
            ctx.open_positions,
            ctx.existing_exposure,
            Decimal(str(ctx.quote.bid)),
        ))
        return original(ctx)

    driver._runtime.consider_entry = spy
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    reasons = _risk_decision_reasons(session_factory)
    assert reasons and set(reasons) == {"position_already_open"}
    # The only order is the warm-up FLAT exit (open item 6); the fake venue keeps it
    # live, so the position stays sellable for every later LONG. No second BUY.
    assert [p["side"] for p in rest.placed[seeded:]] == ["sell"]
    assert len(seen) == len(reasons)
    assert {size for size, _, _, _ in seen} == {Decimal("0.001")}  # the sellable size reached the gate
    assert {count for _, count, _, _ in seen} == {1}  # one open position for the cap
    # ...and its exposure is marked at the step's bid.
    assert all(exposure == Decimal("0.001") * bid for _, _, exposure, bid in seen)


@pytest.mark.parametrize(
    "net, expected",
    [
        ("0", (Decimal(0), Decimal(0), True)),
        ("1.2E-10", (Decimal(0), Decimal(0), True)),  # below one lot: flat (dust)
        ("0.00000001", (Decimal(0), Decimal("0.00000001"), False)),  # one lot: remainder
        ("0.00000999999", (Decimal(0), Decimal("0.00000999"), False)),  # largest remainder
        ("0.00001", (Decimal("0.00001"), Decimal(0), False)),  # exactly the minimum: sellable
        ("0.00001000001", (Decimal("0.00001"), Decimal(0), False)),
        ("0.001", (Decimal("0.001"), Decimal(0), False)),
    ],
)
def test_position_view_boundaries_are_exclusive_and_agree_with_validate_sell(net, expected):
    """flat / sellable / remainder are exclusive at every boundary and match validate_sell."""
    meta = parse_instruments(FakeRest().instruments)["BTC-USDT"]
    view = PositionView.from_summary(Decimal(net), None, meta)
    assert (view.sellable, view.remainder, view.flat) == expected
    assert [view.flat, view.sellable > 0, view.remainder > 0].count(True) == 1
    if view.sellable > 0:
        validated = validate_sell(meta=meta, price=Decimal("100"), base_balance=Decimal(net))
        assert validated.size == view.sellable
    else:
        with pytest.raises(PrecisionError):
            validate_sell(meta=meta, price=Decimal("100"), base_balance=Decimal(net))


@pytest.mark.parametrize(
    "residue, partial_then_cancel, without_btc_quote",
    [
        ("1.2E-10", False, (Decimal("1000"), Decimal(0), 0)),
        ("0.000001", True, (Decimal(0), Decimal("Infinity"), 2)),
    ],
    ids=["sub_lot_dust", "unsellable_remainder"],
)
def test_two_instrument_residue_without_quote_dust_is_skipped_remainder_fails_closed(
    session_factory, residue, partial_then_cancel, without_btc_quote
):
    """Phase 5 two-instrument shape: a BTC residue while the BTC book is unusable.

    Sub-lot dust is marked at zero, so it cannot block an ETH entry's equity (G3);
    an unsellable remainder fails closed for every instrument, as before this change.
    """
    rest = FakeRest()
    rest.instruments.append({
        "instType": "SPOT", "instId": "ETH-USDT", "baseCcy": "ETH", "quoteCcy": "USDT",
        "tickSz": "0.01", "lotSz": "0.000001", "minSz": "0.001", "state": "live",
    })
    state, cb = _connected_state(), {"t": T0}
    driver = _armed_driver(
        session_factory, rest, state, cb, demo_instruments=("BTC-USDT", "ETH-USDT")
    )
    assert set(driver._instrument_meta) == {"BTC-USDT", "ETH-USDT"}
    _open_demo_position(driver)
    _exit_demo_position_leaving(driver, residue, partial_then_cancel=partial_then_cancel)
    assert driver._equity_exposure(cb["t"]) == without_btc_quote
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    assert driver._equity_exposure(cb["t"]) == (
        Decimal("1000") + Decimal(residue) * Decimal("99.9"), Decimal(0), 0,
    )


def test_remainder_is_merged_by_the_next_entry_and_a_new_remainder_is_reported_again(
    session_factory,
):
    """Design section 6 row 13: the next entry merges the remainder into ONE sellable
    position whose stop exit sells the whole floored net; the dedupe memory resets with
    it, so a later, new remainder is reported again."""
    rest, state, cb = FakeRest(), _connected_state(), {"t": T0}
    driver = _armed_driver(session_factory, rest, state, cb)
    meta = driver._instrument_meta["BTC-USDT"]
    _open_demo_position(driver)
    _exit_demo_position_leaving(driver, "0.000001", partial_then_cancel=True)
    seeded = len(rest.placed)
    last_ts = None
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
        last_ts = now - timedelta(minutes=1, seconds=1)
    buys = [p for p in rest.placed[seeded:] if p["side"] == "buy"]
    assert len(buys) == 1
    assert len(_events(session_factory, "unsellable_remainder")) == 1
    buy = buys[0]
    intent = driver.store.get_intent(driver.account_id, buy["clOrdId"])
    assert intent.stop_loss is not None

    # The entry fills: remainder + new size is one sellable position, no remainder.
    driver.project_private_orders([{
        "instId": "BTC-USDT",
        "clOrdId": buy["clOrdId"],
        "ordId": intent.exchange_order_id,
        "state": "filled",
        "side": "buy",
        "accFillSz": buy["sz"],
        "tradeId": f"fill-{buy['clOrdId']}",
        "fillSz": buy["sz"],
        "fillPx": buy["px"],
    }])
    net = Decimal("0.000001") + Decimal(buy["sz"])
    view = driver._position_view("BTC-USDT", meta)
    assert (view.net, view.sellable, view.remainder, view.flat) == (
        net, floor_size(net, meta.lot_size), Decimal(0), False,
    )
    assert view.sellable == net  # the merged net is a lot multiple: nothing left over
    assert view.stop == Decimal(intent.stop_loss)  # the NEW entry's stop, not the seed's

    # A candle under that stop sells the whole floored net in one exit.
    stop = float(view.stop)
    ts = last_ts + timedelta(minutes=1)
    cb["t"] = ts + timedelta(minutes=1, seconds=1)
    close = stop - 0.5
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", ts, close + 1.0, close + 1.5, stop - 1.0, close, 10.0, True),
        "okx-business",
    )
    _fresh_book(state, cb, bid=f"{close - 0.1:.2f}", ask=f"{close + 0.1:.2f}")
    driver._private_last_msg = cb["t"]
    driver.step(cb["t"])
    sells = [p for p in rest.placed[seeded:] if p["side"] == "sell"]
    assert len(sells) == 1 and Decimal(sells[0]["sz"]) == view.sellable
    assert len(_events(session_factory, "unsellable_remainder")) == 1  # merged: nothing new

    # That exit partially fills, then is cancelled from outside the code: a NEW
    # remainder of a different value, reported once more.
    sell = sells[0]
    sell_intent = driver.store.get_intent(driver.account_id, sell["clOrdId"])
    sold = decimal_to_str(net - Decimal("0.000002"))
    row = {
        "instId": "BTC-USDT",
        "clOrdId": sell["clOrdId"],
        "ordId": sell_intent.exchange_order_id,
        "side": "sell",
        "accFillSz": sold,
    }
    driver.project_private_orders([{
        **row, "state": "partially_filled", "tradeId": f"fill-{sell['clOrdId']}",
        "fillSz": sold, "fillPx": sell["px"],
    }])
    driver.project_private_orders([{**row, "state": "canceled"}])
    assert driver.store.position_summary(driver.account_id, "BTC-USDT")[0] == Decimal("0.000002")
    ts2 = ts + timedelta(minutes=1)
    cb["t"] = ts2 + timedelta(minutes=1, seconds=1)
    state.apply_candle(
        CandleUpdate("BTC-USDT", "1m", ts2, close, close + 0.5, close - 0.5, close, 10.0, True),
        "okx-business",
    )
    _fresh_book(state, cb, bid=f"{close - 0.1:.2f}", ask=f"{close + 0.1:.2f}")
    driver._private_last_msg = cb["t"]
    driver.step(cb["t"])
    events = _events(session_factory, "unsellable_remainder")
    assert len(events) == 2
    assert Decimal(events[1]["payload"]["floored"]) == Decimal("0.000002")
    assert Decimal(events[1]["payload"]["net"]) == Decimal("0.000002")
    assert len([p for p in rest.placed[seeded:] if p["side"] == "sell"]) == 1  # never sold alone
    assert _events(session_factory, "exit_precision_rejected") == []


# -- private projection -----------------------------------------------------


def test_private_projection_foreign_clordid_fails_closed(session_factory):
    driver, _ = _driver(session_factory)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver.project_private_orders([{"instId": "BTC-USDT", "clOrdId": "stranger", "state": "live"}])
    assert driver.runtime.entry_block_reason(T0) == "reconciliation_inconsistent"


def test_private_projection_foreign_instrument_fails_closed(session_factory):
    driver, _ = _driver(session_factory)
    driver.startup_gate()
    driver.project_private_orders([{"instId": "DOGE-USDT", "clOrdId": "x", "state": "live"}])
    assert not driver.runtime.reconcile_consistent


def test_private_projection_records_fill_idempotently(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    cl = rest.placed[-1]["clOrdId"]
    row = {"instId": "BTC-USDT", "clOrdId": cl,
           "ordId": rest.orders[cl]["ordId"], "state": "filled",
           "accFillSz": rest.placed[-1]["sz"], "tradeId": "TID1",
           "fillSz": rest.placed[-1]["sz"], "fillPx": rest.placed[-1]["px"], "side": "buy"}
    driver.project_private_orders([row])
    driver.project_private_orders([row])
    s = session_factory()
    try:
        assert s.scalar(select(func.count()).select_from(DemoFill)) == 1
    finally:
        s.close()


def test_private_projection_invalid_side_fails_closed(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    cl = rest.placed[-1]["clOrdId"]
    driver.project_private_orders([{"instId": "BTC-USDT", "clOrdId": cl, "state": "filled",
                                    "tradeId": "T", "fillSz": "0.001", "fillPx": "1", "side": "buyy"}])
    assert not driver.runtime.reconcile_consistent


def test_private_ws_valid_frames_refresh_liveness():
    stop = asyncio.Event()
    live = []

    class Conn:
        def __init__(self):
            self.responses = [
                '{"event":"login","code":"0"}',
                '{"event":"subscribe","code":"0","arg":'
                '{"channel":"orders","instType":"SPOT","instId":"BTC-USDT"}}',
            ]

        async def send(self, payload):
            return None

        async def recv(self):
            response = self.responses.pop(0)
            if not self.responses:
                stop.set()
            return response

    ws = OKXDemoPrivateWebSocket(
        CREDS,
        instruments=["BTC-USDT"],
        connect=lambda url: None,
        on_liveness=lambda: live.append(True),
    )
    assert asyncio.run(ws._session(Conn(), stop)) is True
    assert len(live) >= 2


# -- amend lifecycle --------------------------------------------------------


def _lifecycle_with_intent(session_factory, rest):
    store = DemoStore(session_factory, "demo")
    aid = store.ensure_account("fp", {"strategy": "ma"})
    lc = OrderLifecycle(store, rest, aid, "demo", clock=lambda: T0)
    r = lc.submit(signal_id="s1", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="0.001")
    return store, aid, lc, r.client_order_id


def test_amend_ack_resolves_state(session_factory):
    rest = FakeRest()
    _, _, lc, cl = _lifecycle_with_intent(session_factory, rest)
    res = lc.amend(cl, "BTC-USDT", new_price="49000")
    assert res.status == STATUS_LIVE


def test_amend_transport_timeout_resolves_not_rejected(session_factory):
    rest = FakeRest()
    _, _, lc, cl = _lifecycle_with_intent(session_factory, rest)
    rest.amend_error = OKXDemoTransportError("timeout")
    res = lc.amend(cl, "BTC-USDT", new_size="0.0008")
    # resolve finds the order still live; never treated as rejected
    assert res.status == STATUS_LIVE


def test_amend_error_resolves_truth(session_factory):
    rest = FakeRest()
    _, _, lc, cl = _lifecycle_with_intent(session_factory, rest)
    rest.amend_error = OKXDemoError("order already filled", code="51400")
    rest.orders[cl]["state"] = "filled"
    res = lc.amend(cl, "BTC-USDT", new_size="0.0008")
    assert res.status == "filled"


def test_amend_unknown_order_fails(session_factory):
    rest = FakeRest()
    store = DemoStore(session_factory, "demo")
    aid = store.ensure_account("fp", {"strategy": "ma"})
    lc = OrderLifecycle(store, rest, aid, "demo", clock=lambda: T0)
    res = lc.amend("nope", "BTC-USDT", new_price="1")
    assert res.status == "failed"


def test_cancel_and_amend_never_touch_unowned_orders(session_factory):
    rest = FakeRest()
    store = DemoStore(session_factory, "demo")
    aid = store.ensure_account("fp", {"strategy": "ma"})
    lifecycle = OrderLifecycle(store, rest, aid, "demo", clock=lambda: T0)
    assert lifecycle.cancel("foreign", "BTC-USDT").status == "failed"
    assert lifecycle.amend("foreign", "BTC-USDT", new_price="1").status == "failed"
    assert rest.orders == {}


# -- kill switch ------------------------------------------------------------


def test_kill_switch_cancels_pending_entries_and_blocks(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    # open an entry that stays "live" (no fill)
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    assert rest.placed, "expected an entry to have been placed"
    cancels = driver.runtime.engage_kill_switch()
    assert any(c.status == STATUS_CANCELED for c in cancels)
    # entries now blocked
    assert driver.runtime.entry_block_reason(cb["t"]) == "kill_switch_engaged"


def test_driver_step_enforces_externally_engaged_kill_switch(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    for now in _feed_candles(state, cb, n=40):
        driver._private_last_msg = now
        driver.step(now)
    cl = rest.placed[-1]["clOrdId"]
    # engage kill switch externally (persist only), then step
    driver.store.set_kill_switch(driver.account_id, True, now=cb["t"])
    driver.step(cb["t"])
    assert driver.store.get_intent(driver.account_id, cl).status == STATUS_CANCELED


# -- lock loss --------------------------------------------------------------


def test_entry_blocked_when_lock_lost(session_factory):
    driver, _ = _driver(session_factory)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    # another process steals... no: locks are never auto-stolen, but the row may
    # be cleared by an explicit stale-lock release.
    driver.store.release_lock(driver.account_id, driver.token, now=T0)
    assert driver.runtime.entry_block_reason(T0) == "runtime_lock_lost"


# -- supervised async run/shutdown -----------------------------------------


def test_driver_run_starts_and_shuts_down_cleanly(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0}

    async def fake_public(stop_event):
        await stop_event.wait()

    class FakeWS:
        def __init__(self, on_orders, on_status, on_liveness):
            self._on_status = on_status
            self._on_liveness = on_liveness

        async def run(self, stop_event):
            self._on_status(True)
            self._on_liveness()
            await stop_event.wait()
            self._on_status(False)

    driver = DemoTradingDriver(
        credentials=CREDS, rest=rest, session_factory=session_factory, settings=_settings(),
        market_state=state, clock=lambda: cb["t"],
        public_stream_factory=fake_public,
        private_ws_factory=lambda on_orders, on_status, on_liveness: FakeWS(
            on_orders, on_status, on_liveness
        ),
    )

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(driver.run(stop))
        await asyncio.sleep(0.05)
        stop.set()
        return await asyncio.wait_for(task, timeout=5)

    result = asyncio.run(scenario())
    assert result == 0
    # lock released on shutdown
    s = session_factory()
    try:
        row = s.scalar(select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == driver.account_id))
        assert row.lock_token is None and row.status == "stopped"
    finally:
        s.close()


def test_driver_run_refuses_when_account_invalid(session_factory):
    rest = FakeRest()
    rest.acct = {"acctLv": "4"}

    async def fake_public(stop_event):
        await stop_event.wait()

    driver = DemoTradingDriver(
        credentials=CREDS, rest=rest, session_factory=session_factory, settings=_settings(),
        market_state=_connected_state(), clock=lambda: T0,
        public_stream_factory=fake_public,
        private_ws_factory=lambda on_orders, on_status, on_liveness: None,
    )
    result = asyncio.run(driver.run(asyncio.Event()))
    assert result == 1  # invalid account -> driver refuses to run
    session = session_factory()
    try:
        row = session.scalar(
            select(DemoRuntimeStatus).where(
                DemoRuntimeStatus.account_id == driver.account_id
            )
        )
        assert row.lock_token is None
    finally:
        session.close()


def test_driver_run_releases_lock_when_account_validation_errors(session_factory):
    rest = FakeRest()

    def fail_config():
        raise OKXDemoTransportError("account unavailable")

    rest.get_account_config = fail_config
    driver, _ = _driver(session_factory, rest=rest)
    assert asyncio.run(driver.run(asyncio.Event())) == 1
    session = session_factory()
    try:
        row = session.scalar(
            select(DemoRuntimeStatus).where(
                DemoRuntimeStatus.account_id == driver.account_id
            )
        )
        assert row.lock_token is None
    finally:
        session.close()


def test_periodic_reconcile_error_fails_closed(session_factory):
    driver, _ = _driver(
        session_factory, demo_reconcile_interval_seconds=0.01
    )
    driver.startup_gate()
    assert driver.runtime.reconcile_consistent

    def fail():
        raise OKXDemoTransportError("down")

    driver.runtime.reconcile_now = fail

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(driver._reconcile_loop(stop))
        await asyncio.sleep(0.04)
        stop.set()
        await task

    asyncio.run(scenario())
    assert not driver.runtime.reconcile_consistent
