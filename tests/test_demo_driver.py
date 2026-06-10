"""Offline adversarial tests for the Phase 5 demo driver and its integration.

Covers the long-running driver's startup gate, account validation, private-WS
subscription/projection, amend lifecycle, kill-switch venue cancellation,
forward-only no-retrospective-trading, feed/lock fail-closed behavior, and clean
supervised shutdown. Fully offline: fake REST/WS transports, a fake clock, a
temporary SQLite database, and an in-memory public MarketState.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import (
    Base,
    DemoDailyBaseline,
    DemoFill,
    DemoOrderIntent,
    DemoRuntimeStatus,
)
from app.exchange.credentials import DemoCredentials
from app.exchange.okx_demo_ws import OKXDemoPrivateWebSocket
from app.execution.account_validation import validate_demo_account
from app.execution.driver import DemoTradingDriver
from app.execution.identity import demo_identity_config
from app.execution.lifecycle import INTENT_ENTRY, OrderLifecycle
from app.execution.reconcile import DemoReconciler
from app.execution.runtime import DemoExecutionRuntime
from app.execution.store import DemoStore, STATUS_CANCELED, STATUS_LIVE, STATUS_UNKNOWN
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoTransportError
from app.live.market_state import MarketState
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    OrderBookAction,
    OrderBookLevel,
    OrderBookUpdate,
)
from scripts.run_demo_trading import _settings_for_account

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


def _connected_state() -> MarketState:
    state = MarketState()
    for fid, subs in [("okx-public", ["books:BTC-USDT"]), ("okx-business", ["candle1m:BTC-USDT"])]:
        state.register_feed(fid, subs)
        state.set_feed_acked(fid, subs)
        state.set_feed_status(fid, ConnectionStatus.CONNECTED)
    return state


def _driver(session_factory, rest=None, state=None, clock_box=None, **settings_overrides):
    clock_box = clock_box if clock_box is not None else {"t": T0}
    return DemoTradingDriver(
        credentials=CREDS, rest=rest or FakeRest(), session_factory=session_factory,
        settings=_settings(**settings_overrides), market_state=state or _connected_state(),
        clock=lambda: clock_box["t"],
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


def test_candle_gap_blocks_processing_for_recovery(session_factory):
    rest = FakeRest()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb)
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
    assert driver._watermark["BTC-USDT"] == T0
    assert not driver._market_continuity_ok
    add(1)
    driver.step(cb["t"])
    # MarketState correctly rejects the late out-of-order bar. The driver
    # remains fail-closed until a supervised feed recovery/restart rebuilds
    # contiguous history.
    assert driver._watermark["BTC-USDT"] == T0
    assert not driver._market_continuity_ok


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
