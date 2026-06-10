"""Offline tests for the Phase 5 OKX DEMO execution layer (no network).

Covers signing, secret redaction, demo-only/fail-closed transport, clock drift,
malformed responses, idempotency and ambiguous-timeout recovery, fill/cancel
races, restart recovery, exchange-authoritative reconciliation (foreign orders /
unexplained balances), kill switch + arming + lock, Decimal precision, and the
rejection of margin/leverage/derivative/production paths. Everything uses fake
transports, fixed clocks, and a temporary SQLite database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, DemoOrderIntent
from app.exchange import okx_auth
from app.exchange.credentials import (
    DemoCredentials,
    MissingDemoCredentialsError,
    SecretRedactingFilter,
    load_demo_credentials,
    redact,
)
from app.exchange.instruments import InstrumentError, InstrumentMeta, parse_instrument
from app.exchange.okx_demo_endpoints import (
    EndpointNotAllowedError,
    assert_endpoint_allowed,
    demo_request_headers,
    validate_demo_rest_base_url,
    validate_demo_ws_url,
)
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoRestClient, OKXDemoTransportError
from app.exchange.okx_demo_ws import build_login_args, parse_private_message
from app.execution.ids import derive_client_order_id
from app.execution.lifecycle import INTENT_ENTRY, INTENT_EXIT, OrderLifecycle
from app.execution.precision import (
    PrecisionError,
    floor_size,
    quantize_price,
    validate_buy,
    validate_sell,
)
from app.execution.reconcile import DemoReconciler
from app.execution.runtime import DemoExecutionRuntime, EntryContext
from app.execution.store import (
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_LIVE,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_UNKNOWN,
    DemoStore,
    AccountIdentityMismatch,
)
from app.strategy.base import Signal, SignalAction

T0 = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
CREDS = DemoCredentials("AK-test", "SECRET-test", "PASS-test")


# --------------------------------------------------------------------------
# fixtures / fakes
# --------------------------------------------------------------------------


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


def _settings(**overrides) -> Settings:
    base = dict(
        okx_demo_rest_base_url="https://www.okx.com",
        demo_request_timeout=1.0,
        demo_max_retries=3,
        demo_rate_limit_per_2s=10,
        demo_clock_drift_max_seconds=5.0,
        demo_max_order_notional=100.0,
        demo_max_position_size=0.10,
        demo_max_total_exposure=0.25,
        demo_max_risk_per_trade=0.5,
        demo_min_confidence=0.5,
        demo_price_band=0.002,
        demo_order_type="limit",
        demo_arm_ttl_seconds=900.0,
        demo_max_quote_age_seconds=10.0,
        demo_max_candle_age_seconds=3600.0,
    )
    base.update(overrides)
    return Settings(**base)


class FakeResp:
    def __init__(self, payload, status=200, raise_json=None):
        self._p = payload
        self.status_code = status
        self._raise_json = raise_json

    def json(self):
        if self._raise_json is not None:
            raise self._raise_json
        return self._p


class FakeSession:
    def __init__(self):
        self.queue = []
        self.calls = []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(session, **settings_overrides):
    return OKXDemoRestClient(
        CREDS,
        settings=_settings(**settings_overrides),
        session=session,
        clock=lambda: T0,
        monotonic=lambda: 0.0,
        sleep=lambda s: None,
    )


class FakeRest:
    """In-memory demo exchange for lifecycle/reconcile/runtime tests."""

    def __init__(self):
        self.orders = {}  # clOrdId -> order dict
        self.fills = []
        self.balances = {"details": [{"ccy": "USDT", "availBal": "1000", "eq": "1000"}]}
        self.pending = []
        self.place_error = None
        self.place_calls = []

    def place_order(self, params):
        self.place_calls.append(params)
        if self.place_error is not None:
            err = self.place_error
            self.place_error = None
            raise err
        cl = params["clOrdId"]
        self.orders[cl] = {
            "clOrdId": cl,
            "ordId": "OID-" + cl[-6:],
            "state": "live",
            "accFillSz": "0",
            "sCode": "0",
        }
        return self.orders[cl]

    def get_order(self, instrument, cl_ord_id=None, ord_id=None):
        return self.orders.get(cl_ord_id)

    def cancel_order(self, instrument, cl_ord_id):
        if cl_ord_id in self.orders:
            self.orders[cl_ord_id]["state"] = "canceled"
        return {"sCode": "0"}

    def get_pending_orders(self, instrument=None):
        return list(self.pending)

    def get_fills(self, instrument=None):
        return [f for f in self.fills if instrument is None or f.get("instId") == instrument]

    def get_balances(self):
        return self.balances


SPOT_BTC = InstrumentMeta(
    instrument="BTC-USDT",
    inst_type="SPOT",
    base_ccy="BTC",
    quote_ccy="USDT",
    tick_size=Decimal("0.1"),
    lot_size=Decimal("0.00000001"),
    min_size=Decimal("0.00001"),
    state="live",
)


def _store(session_factory) -> tuple[DemoStore, int]:
    store = DemoStore(session_factory, "demo")
    account_id = store.ensure_account("fp", {"strategy": "ma", "instruments": ["BTC-USDT"]})
    return store, account_id


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------


def test_iso_timestamp_millisecond_z_format():
    ts = okx_auth.iso_timestamp(datetime(2020, 12, 8, 9, 8, 57, 715000, tzinfo=timezone.utc))
    assert ts == "2020-12-08T09:08:57.715Z"


def test_rest_signature_matches_manual_hmac():
    ts = "2026-06-10T12:00:00.000Z"
    pre = okx_auth.rest_prehash(ts, "GET", "/api/v5/account/balance", "")
    expect = base64.b64encode(
        hmac.new(b"SECRET-test", pre.encode(), hashlib.sha256).digest()
    ).decode()
    assert okx_auth.sign_rest("SECRET-test", ts, "GET", "/api/v5/account/balance", "") == expect


def test_ws_login_prehash_and_sign():
    assert okx_auth.ws_login_prehash("1700000000") == "1700000000GET/users/self/verify"
    args = build_login_args(CREDS, "1700000000")
    assert args["op"] == "login"
    assert args["args"][0]["apiKey"] == "AK-test"
    assert args["args"][0]["sign"] == okx_auth.sign_ws_login("SECRET-test", "1700000000")


# --------------------------------------------------------------------------
# secret leakage
# --------------------------------------------------------------------------


def test_credentials_never_appear_in_repr():
    text = repr(CREDS) + str(CREDS)
    assert "SECRET-test" not in text and "AK-test" not in text and "PASS-test" not in text


def test_load_credentials_fail_closed_without_values_in_message():
    with pytest.raises(MissingDemoCredentialsError) as exc:
        load_demo_credentials({"OKX_DEMO_API_KEY": "k", "OKX_DEMO_API_SECRET": ""})
    assert "k" not in str(exc.value).replace("OKX_DEMO_API_KEY", "")


def test_redaction_filter_scrubs_message_and_extras():
    filt = SecretRedactingFilter(CREDS.secret_values())
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "key=%s done", ("AK-test",), None
    )
    record.passphrase = "PASS-test"
    filt.filter(record)
    assert "AK-test" not in (record.args[0] if record.args else "")
    assert record.passphrase == "***REDACTED***"


def test_rest_client_never_puts_secret_in_url_or_body():
    sess = FakeSession()
    sess.queue = [FakeResp({"code": "0", "msg": "", "data": [{"ts": "1700000000000"}]})]
    _client(sess).get_server_time()
    call = sess.calls[-1]
    assert "SECRET-test" not in str(call["url"]) and "SECRET-test" not in str(call["data"])
    assert call["headers"]["OK-ACCESS-SIGN"]  # signature present, but it is not the secret


# --------------------------------------------------------------------------
# wrong environment / header / hostname / account mode
# --------------------------------------------------------------------------


def test_demo_header_is_always_present_and_one():
    headers = demo_request_headers(api_key="AK", sign="S", timestamp="T", passphrase="P")
    assert headers["x-simulated-trading"] == "1"


def test_rest_base_url_allowlist_fail_closed():
    assert validate_demo_rest_base_url("https://www.okx.com") == "https://www.okx.com"
    for bad in [
        "http://www.okx.com",
        "https://evil.com",
        "https://ws.okx.com",
        "https://www.okx.com/api/v5",
        "https://user:pass@www.okx.com",
    ]:
        with pytest.raises(ValueError):
            validate_demo_rest_base_url(bad)


def test_production_ws_host_rejected_demo_required():
    with pytest.raises(ValueError):
        validate_demo_ws_url("wss://ws.okx.com:8443/ws/v5/private")
    assert validate_demo_ws_url("wss://wspap.okx.com:8443/ws/v5/private").endswith("/private")


def test_endpoint_allowlist_rejects_forbidden_and_unknown():
    assert_endpoint_allowed("POST", "/api/v5/trade/order")
    for method, path in [
        ("POST", "/api/v5/asset/withdrawal"),
        ("POST", "/api/v5/asset/transfer"),
        ("POST", "/api/v5/account/set-leverage"),
        ("POST", "/api/v5/account/set-account-level"),
        ("POST", "/api/v5/trade/close-position"),
        ("GET", "/api/v5/some/random"),
    ]:
        with pytest.raises(EndpointNotAllowedError):
            assert_endpoint_allowed(method, path)


def test_order_params_reject_margin_and_leverage():
    sess = FakeSession()
    client = _client(sess)
    for bad in [
        {"instId": "BTC-USDT", "tdMode": "cross", "side": "buy", "ordType": "limit", "sz": "1", "px": "1", "clOrdId": "c"},
        {"instId": "BTC-USDT", "tdMode": "cash", "side": "buy", "ordType": "limit", "sz": "1", "px": "1", "clOrdId": "c", "lever": "5"},
        {"instId": "BTC-USDT", "tdMode": "cash", "side": "short", "ordType": "limit", "sz": "1", "px": "1", "clOrdId": "c"},
    ]:
        with pytest.raises(ValueError):
            client.place_order(bad)
    assert sess.calls == []  # never reached the network


# --------------------------------------------------------------------------
# clock drift / malformed / rate limits
# --------------------------------------------------------------------------


def test_sync_time_fails_closed_on_excessive_drift():
    sess = FakeSession()
    # server time 1 hour ahead of local T0 -> drift >> 5s
    server_ms = int((T0 + timedelta(hours=1)).timestamp() * 1000)
    sess.queue = [FakeResp({"code": "0", "msg": "", "data": [{"ts": str(server_ms)}]})]
    with pytest.raises(OKXDemoError):
        _client(sess).sync_time()


def test_malformed_json_response_raises():
    sess = FakeSession()
    sess.queue = [FakeResp(None, raise_json=ValueError("bad json"))]
    with pytest.raises(OKXDemoError):
        _client(sess).get_balances()


def test_api_error_code_surfaces_without_secret():
    sess = FakeSession()
    sess.queue = [FakeResp({"code": "51000", "msg": "Parameter error", "data": []})]
    with pytest.raises(OKXDemoError) as exc:
        _client(sess).get_balances()
    assert exc.value.code == "51000"


def test_order_mutation_surfaces_per_order_rejection_detail():
    sess = FakeSession()
    sess.queue = [
        FakeResp(
            {
                "code": "1",
                "msg": "All operations failed",
                "data": [{"sCode": "51006", "sMsg": "Order price is not within limits"}],
            }
        )
    ]
    with pytest.raises(OKXDemoError) as exc:
        _client(sess).place_order(
            {
                "instId": "BTC-USDT",
                "tdMode": "cash",
                "side": "buy",
                "ordType": "limit",
                "sz": "0.001",
                "px": "999999",
                "clOrdId": "c",
            }
        )
    assert exc.value.code == "51006"
    assert "Order price is not within limits" in str(exc.value)


def test_rate_limit_status_is_transport_unknown():
    sess = FakeSession()
    sess.queue = [FakeResp({"code": "50011", "msg": "rate", "data": []}, status=429)]
    with pytest.raises(OKXDemoTransportError):
        _client(sess).place_order(
            {"instId": "BTC-USDT", "tdMode": "cash", "side": "buy", "ordType": "limit", "sz": "0.001", "px": "1", "clOrdId": "c"}
        )


def test_get_retried_post_not_retried_on_transport_error():
    sess = FakeSession()
    sess.queue = [requests.ConnectionError(), requests.ConnectionError(), FakeResp({"code": "0", "msg": "", "data": []})]
    # GET retries until success
    _client(sess).get_pending_orders()
    assert len(sess.calls) == 3
    sess2 = FakeSession()
    sess2.queue = [requests.ConnectionError()]
    with pytest.raises(OKXDemoTransportError):
        _client(sess2).place_order(
            {"instId": "BTC-USDT", "tdMode": "cash", "side": "buy", "ordType": "limit", "sz": "0.001", "px": "1", "clOrdId": "c"}
        )
    assert len(sess2.calls) == 1  # POST not retried


# --------------------------------------------------------------------------
# precision / min size / balance / instruments
# --------------------------------------------------------------------------


def test_quantize_and_floor():
    assert quantize_price(Decimal("50000.07"), Decimal("0.1")) == Decimal("50000.1")
    assert floor_size(Decimal("0.123456789"), Decimal("0.0001")) == Decimal("0.1234")


def test_validate_buy_enforces_min_notional_and_balance():
    # below min size
    with pytest.raises(PrecisionError):
        validate_buy(meta=SPOT_BTC, price=Decimal("50000"), desired_size=Decimal("0.000001"),
                     available_quote=Decimal("100"), max_notional=Decimal("100"))
    # notional cap exceeded
    with pytest.raises(PrecisionError):
        validate_buy(meta=SPOT_BTC, price=Decimal("50000"), desired_size=Decimal("1"),
                     available_quote=Decimal("100000"), max_notional=Decimal("100"))
    # insufficient balance
    with pytest.raises(PrecisionError):
        validate_buy(meta=SPOT_BTC, price=Decimal("50000"), desired_size=Decimal("0.001"),
                     available_quote=Decimal("10"), max_notional=Decimal("1000"))
    ok = validate_buy(meta=SPOT_BTC, price=Decimal("50000"), desired_size=Decimal("0.001"),
                      available_quote=Decimal("100"), max_notional=Decimal("100"))
    assert ok.side == "buy" and ok.size == Decimal("0.001")


def test_validate_sell_never_oversells():
    ok = validate_sell(meta=SPOT_BTC, price=Decimal("50000"), base_balance=Decimal("0.005"))
    assert ok.size <= Decimal("0.005")
    with pytest.raises(PrecisionError):
        validate_sell(meta=SPOT_BTC, price=Decimal("50000"), base_balance=Decimal("0"))


def test_instruments_reject_non_spot():
    with pytest.raises(InstrumentError):
        parse_instrument({"instType": "SWAP", "instId": "BTC-USDT-SWAP"})
    meta = parse_instrument(
        {"instType": "SPOT", "instId": "BTC-USDT", "baseCcy": "BTC", "quoteCcy": "USDT",
         "tickSz": "0.1", "lotSz": "0.00000001", "minSz": "0.00001", "state": "live"}
    )
    assert meta.is_tradable()


# --------------------------------------------------------------------------
# store: identity, lock, arming, kill switch, idempotency
# --------------------------------------------------------------------------


def test_account_identity_is_immutable(session_factory):
    store = DemoStore(session_factory, "demo")
    store.ensure_account("fp", {"strategy": "a"})
    with pytest.raises(AccountIdentityMismatch):
        store.ensure_account("fp", {"strategy": "b"})
    with pytest.raises(AccountIdentityMismatch):
        store.ensure_account("different-fp", {"strategy": "a"})


def test_lock_is_atomic_and_not_auto_stolen(session_factory):
    store, aid = _store(session_factory)
    assert store.acquire_lock(aid, "tok-a", now=T0) is True
    assert store.acquire_lock(aid, "tok-b", now=T0 + timedelta(seconds=1)) is False
    # same token re-acquires (idempotent heartbeat)
    assert store.acquire_lock(aid, "tok-a", now=T0 + timedelta(seconds=2)) is True
    # stale lock requires explicit release
    assert store.release_stale_lock(aid, stale_after_seconds=60, now=T0 + timedelta(seconds=5)) is False
    assert store.release_stale_lock(aid, stale_after_seconds=60, now=T0 + timedelta(seconds=120)) is True


def test_arming_expires_and_disarm(session_factory):
    store, aid = _store(session_factory)
    assert store.is_armed(aid, now=T0) is False
    store.arm(aid, ttl_seconds=100, now=T0)
    assert store.is_armed(aid, now=T0 + timedelta(seconds=50)) is True
    assert store.is_armed(aid, now=T0 + timedelta(seconds=200)) is False  # expired
    store.arm(aid, ttl_seconds=100, now=T0)
    store.disarm(aid, now=T0 + timedelta(seconds=10))
    assert store.is_armed(aid, now=T0 + timedelta(seconds=11)) is False


def test_create_intent_idempotent_and_fill_idempotent(session_factory):
    store, aid = _store(session_factory)
    from app.execution.store import IntentInput

    intent = IntentInput("cl1", "sig1", "BTC-USDT", "buy", "entry", "limit", "50000", "0.001")
    assert store.create_intent(aid, intent, now=T0) is True
    assert store.create_intent(aid, intent, now=T0) is False  # duplicate clOrdId
    assert store.record_fill(aid, fill_id="tid1", client_order_id="cl1", exchange_order_id="o1",
                             instrument="BTC-USDT", side="buy", fill_size="0.001", fill_price="50000",
                             fee=None, fee_ccy=None, fill_time=T0, source="ws", now=T0) is True
    assert store.record_fill(aid, fill_id="tid1", client_order_id="cl1", exchange_order_id="o1",
                             instrument="BTC-USDT", side="buy", fill_size="0.001", fill_price="50000",
                             fee=None, fee_ccy=None, fill_time=T0, source="ws", now=T0) is False


def test_order_update_never_regresses_terminal_state(session_factory):
    store, aid = _store(session_factory)
    from app.execution.store import IntentInput

    store.create_intent(aid, IntentInput("cl1", "s", "BTC-USDT", "buy", "entry", "limit", "1", "0.001"), now=T0)
    store.apply_order_update(aid, client_order_id="cl1", exchange_order_id="o1", state="filled",
                             filled_size="0.001", avg_price="1", fee=None, fee_ccy=None,
                             update_time=T0, source="ws", now=T0)
    # a late duplicate "live" must not regress "filled"
    store.apply_order_update(aid, client_order_id="cl1", exchange_order_id="o1", state="live",
                             filled_size="0.001", avg_price="1", fee=None, fee_ccy=None,
                             update_time=T0, source="ws", now=T0)
    assert store.get_intent(aid, "cl1").status == STATUS_FILLED


# --------------------------------------------------------------------------
# lifecycle: ack / unknown / rejection / restart
# --------------------------------------------------------------------------


def _lifecycle(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    return store, aid, rest, OrderLifecycle(store, rest, aid, "demo", clock=lambda: T0)


def test_lifecycle_ack_then_idempotent(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    r = lc.submit(signal_id="s1", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="0.001")
    assert r.status == STATUS_LIVE and r.exchange_order_id
    n = len(rest.place_calls)
    lc.submit(signal_id="s1", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
              ord_type="limit", price="50000", size="0.001")
    assert len(rest.place_calls) == n  # no duplicate economic order


def test_lifecycle_unknown_resolves_to_live_when_exchange_has_it(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    cl = lc.client_order_id("BTC-USDT", INTENT_ENTRY, "s2")
    rest.orders[cl] = {"clOrdId": cl, "ordId": "OID-X", "state": "live", "accFillSz": "0"}
    rest.place_error = OKXDemoTransportError("timeout")
    r = lc.submit(signal_id="s2", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="0.001")
    assert r.status == STATUS_LIVE and r.exchange_order_id == "OID-X"


def test_lifecycle_unknown_not_found_stays_unknown_no_resubmit(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    rest.place_error = OKXDemoTransportError("timeout")
    r = lc.submit(signal_id="s3", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="0.001")
    assert r.status == STATUS_UNKNOWN
    n = len(rest.place_calls)
    again = lc.submit(signal_id="s3", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                      ord_type="limit", price="50000", size="0.001")
    assert again.status == STATUS_UNKNOWN
    assert len(rest.place_calls) == n


def test_lifecycle_rejection_creates_no_order(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    rest.place_error = OKXDemoError("insufficient balance", code="51008")
    r = lc.submit(signal_id="s4", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="9999")
    assert r.status == STATUS_REJECTED and r.code == "51008"
    # A later resolve/query must not regress a definitive rejection to unknown.
    again = lc.resolve(r.client_order_id, "BTC-USDT")
    assert again.status == STATUS_REJECTED
    assert store.get_intent(aid, r.client_order_id).status == STATUS_REJECTED


def test_durable_place_rejection_recovers_unknown_projection(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    rest.place_error = OKXDemoError("price rejected", code="51006")
    r = lc.submit(
        signal_id="rejected-recovery",
        instrument="BTC-USDT",
        intent=INTENT_ENTRY,
        side="buy",
        ord_type="limit",
        price="999999",
        size="0.001",
    )
    assert r.status == STATUS_REJECTED
    # Simulate the pre-fix bad projection while retaining the durable rejection.
    session = session_factory()
    try:
        intent = store.get_intent(aid, r.client_order_id)
        row = session.get(DemoOrderIntent, intent.id)
        row.status = STATUS_UNKNOWN
        session.commit()
    finally:
        session.close()
    recovered = lc.resolve(r.client_order_id, "BTC-USDT")
    assert recovered.status == STATUS_REJECTED
    assert store.get_intent(aid, r.client_order_id).status == STATUS_REJECTED


def test_restart_resolves_open_intents(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    # simulate a crash after persisting a pending intent but before submission
    from app.execution.store import IntentInput

    cl = lc.client_order_id("BTC-USDT", INTENT_ENTRY, "s5")
    store.create_intent(aid, IntentInput(cl, "s5", "BTC-USDT", "buy", "entry", "limit", "1", "0.001"), now=T0)
    # exchange never saw it -> resolve marks failed (no resubmit)
    results = lc.resolve_open_intents()
    assert results and results[0].status == STATUS_FAILED


def test_cancel_then_resolve_canceled(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    r = lc.submit(signal_id="s6", instrument="BTC-USDT", intent=INTENT_ENTRY, side="buy",
                  ord_type="limit", price="50000", size="0.001")
    c = lc.cancel(r.client_order_id, "BTC-USDT")
    assert c.status == STATUS_CANCELED


# --------------------------------------------------------------------------
# reconciliation: foreign orders / fills / baseline
# --------------------------------------------------------------------------


def test_reconcile_foreign_order_is_inconsistent_and_not_cancelled(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.pending = [{"instId": "BTC-USDT", "ordId": "FOREIGN1", "clOrdId": "someoneelse"}]
    rec = DemoReconciler(store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0)
    result = rec.reconcile()
    assert result.consistent is False and result.foreign_orders == 1
    # never auto-cancelled: the foreign order is still pending on the exchange
    assert rest.pending[0]["ordId"] == "FOREIGN1"


def test_reconcile_reserves_preloaded_demo_base_holding_on_first_run(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.balances = {"details": [{"ccy": "USDT", "cashBal": "1000"}, {"ccy": "BTC", "cashBal": "0.5"}]}
    rec = DemoReconciler(store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0)
    result = rec.reconcile()
    assert result.consistent is True and result.unexplained_balances == 0
    # Preloaded BTC is reserved inventory, not a bot-owned position.
    assert store.position_summary(aid, "BTC-USDT")[0] == Decimal("0")

    # A later unexplained change still fails closed.
    rest.balances["details"][1]["cashBal"] = "0.6"
    changed = rec.reconcile()
    assert changed.consistent is False and changed.unexplained_balances == 1


def test_reconcile_flags_delayed_live_order_after_local_terminal_state(session_factory):
    store, aid, rest, lc = _lifecycle(session_factory)
    cl = lc.client_order_id("BTC-USDT", INTENT_ENTRY, "delayed")
    from app.execution.store import IntentInput

    store.create_intent(
        aid,
        IntentInput(cl, "delayed", "BTC-USDT", "buy", "entry", "limit", "1", "0.001"),
        now=T0,
    )
    store.record_submission(
        aid, cl, request_kind="query", attempt=0, outcome="not_found",
        new_status=STATUS_FAILED, now=T0,
    )
    rest.pending = [{"instId": "BTC-USDT", "ordId": "LATE", "clOrdId": cl}]
    rec = DemoReconciler(
        store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0
    )
    result = rec.reconcile()
    assert result.consistent is False
    assert any("conflicts with local status" in issue for issue in result.issues)


def test_reconcile_rejects_foreign_fill(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.fills = [{
        "tradeId": "foreign-trade", "clOrdId": "someoneelse", "ordId": "x",
        "instId": "BTC-USDT", "side": "buy", "fillSz": "0.1", "fillPx": "50000",
    }]
    rec = DemoReconciler(
        store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0
    )
    result = rec.reconcile()
    assert result.consistent is False
    assert any("foreign or mismatched fill" in issue for issue in result.issues)


def test_reconcile_uses_total_cash_not_frozen_available_balance(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.balances = {
        "details": [{"ccy": "BTC", "cashBal": "0", "availBal": "0"}]
    }
    rec = DemoReconciler(
        store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0
    )
    assert rec.reconcile().consistent is True
    rest.balances = {
        "details": [{"ccy": "BTC", "cashBal": "0", "availBal": "-0.1"}]
    }
    assert rec.reconcile().consistent is True


def test_reconcile_checks_quote_cash_and_fees(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.balances = {
        "details": [
            {"ccy": "BTC", "cashBal": "0"},
            {"ccy": "USDT", "cashBal": "1000"},
        ]
    }
    rec = DemoReconciler(
        store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0
    )
    assert rec.reconcile().consistent is True
    from app.execution.store import IntentInput

    store.create_intent(
        aid,
        IntentInput(
            "d5owned", "s", "BTC-USDT", "buy", "entry", "limit",
            "50000", "0.001", "49000",
        ),
        now=T0,
    )
    rest.fills = [{
        "tradeId": "owned-fill",
        "clOrdId": "d5owned",
        "ordId": "o",
        "instId": "BTC-USDT",
        "side": "buy",
        "fillSz": "0.001",
        "fillPx": "50000",
        "fee": "-0.05",
        "feeCcy": "USDT",
    }]
    rest.balances = {
        "details": [
            {"ccy": "BTC", "cashBal": "0.001"},
            {"ccy": "USDT", "cashBal": "949.95"},
        ]
    }
    assert rec.reconcile().consistent is True
    rest.balances["details"][1]["cashBal"] = "900"
    result = rec.reconcile()
    assert result.consistent is False
    assert any("USDT" in issue for issue in result.issues)


def test_reconcile_flags_unexplained_balance_change(session_factory):
    store, aid = _store(session_factory)
    rest = FakeRest()
    rest.balances = {"details": [{"ccy": "BTC", "availBal": "0"}]}
    rec = DemoReconciler(store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0)
    rec.reconcile()  # baseline BTC=0
    rest.balances = {"details": [{"ccy": "BTC", "availBal": "5"}]}  # appeared from nowhere
    result = rec.reconcile()
    assert result.consistent is False and result.unexplained_balances == 1


# --------------------------------------------------------------------------
# runtime: arming / kill switch / risk veto / sizing
# --------------------------------------------------------------------------


def _runtime(session_factory, **settings_overrides):
    store, aid = _store(session_factory)
    assert store.acquire_lock(aid, "tok", now=T0)
    rest = FakeRest()
    lc = OrderLifecycle(store, rest, aid, "demo", clock=lambda: T0)
    rec = DemoReconciler(store, rest, session_factory, aid, instruments=("BTC-USDT",), clock=lambda: T0)
    rt = DemoExecutionRuntime(
        store=store, lifecycle=lc, reconciler=rec, account_id=aid, token="tok",
        settings=_settings(**settings_overrides), clock=lambda: T0,
    )
    return store, aid, rest, lc, rec, rt


def _signal(action=SignalAction.LONG, confidence=0.9, stop_loss=49000.0):
    return Signal(timestamp=T0, instrument="BTC-USDT", action=action, confidence=confidence,
                  reason="t", stop_loss=stop_loss, timeframe="1m")


def _entry_ctx(**overrides):
    from app.paper.execution import FeedStatus, QuoteSnapshot

    base = dict(
        signal=_signal(),
        instrument="BTC-USDT",
        meta=SPOT_BTC,
        quote=QuoteSnapshot("BTC-USDT", bid=Decimal("50000"), ask=Decimal("50001"),
                            timestamp=T0, synchronized=True),
        feed_status=FeedStatus(connected=True, stale=False),
        available_quote=Decimal("1000"),
        equity=Decimal("1000"),
        day_start_equity=Decimal("1000"),
        day_realized_pnl=Decimal("0"),
        now=T0,
        data_time=T0,
    )
    base.update(overrides)
    return EntryContext(**base)


def test_runtime_disarmed_blocks_entry(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now()  # consistent, but NOT armed
    assert rt.consider_entry(_entry_ctx()) is None
    assert rest.place_calls == []


def test_runtime_lost_lock_blocks_entry_and_exit(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now()
    assert rt.arm(ttl_seconds=900) is not None
    store.release_lock(aid, "tok", now=T0)
    assert rt.consider_entry(_entry_ctx()) is None
    from app.paper.execution import FeedStatus, QuoteSnapshot

    assert rt.consider_exit(
        signal_id="exit-lock", instrument="BTC-USDT", meta=SPOT_BTC,
        quote=QuoteSnapshot("BTC-USDT", bid=Decimal("50000"), ask=Decimal("50001"),
                            timestamp=T0, synchronized=True),
        feed_status=FeedStatus(connected=True, stale=False),
        base_balance=Decimal("0.001"), now=T0,
    ) is None
    assert rest.place_calls == []


def test_runtime_arm_refused_when_inconsistent(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rest.pending = [{"instId": "BTC-USDT", "ordId": "F", "clOrdId": "foreign"}]
    rt.reconcile_now()  # inconsistent
    assert rt.arm(ttl_seconds=900) is None  # fail closed


def test_runtime_armed_entry_places_order(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now()
    assert rt.arm(ttl_seconds=900) is not None
    r = rt.consider_entry(_entry_ctx())
    assert r is not None and r.status == STATUS_LIVE
    params = rest.place_calls[-1]
    assert params["tdMode"] == "cash" and params["side"] == "buy"
    # notional capped by demo_max_order_notional (100)
    assert Decimal(params["px"]) * Decimal(params["sz"]) <= Decimal("100")


def test_runtime_blocks_entry_too_small_to_exit_after_base_fee(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(
        session_factory, demo_max_order_notional=Decimal("0.51")
    )
    rt.reconcile_now()
    assert rt.arm(ttl_seconds=900) is not None
    assert rt.consider_entry(_entry_ctx()) is None
    assert rest.place_calls == []


def test_runtime_risk_veto_low_confidence_and_missing_stop(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now(); rt.arm(ttl_seconds=900)
    assert rt.consider_entry(_entry_ctx(signal=_signal(confidence=0.1))) is None
    assert rt.consider_entry(_entry_ctx(signal=_signal(stop_loss=None))) is None
    assert rest.place_calls == []


def test_runtime_stale_quote_blocks_entry(session_factory):
    from app.paper.execution import QuoteSnapshot

    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now(); rt.arm(ttl_seconds=900)
    stale = QuoteSnapshot("BTC-USDT", bid=Decimal("50000"), ask=Decimal("50001"),
                          timestamp=T0 - timedelta(seconds=60), synchronized=True)
    assert rt.consider_entry(_entry_ctx(quote=stale)) is None


def test_runtime_unsynchronized_quote_blocks_entry(session_factory):
    from app.paper.execution import QuoteSnapshot

    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now(); rt.arm(ttl_seconds=900)
    unsync = QuoteSnapshot("BTC-USDT", bid=Decimal("50000"), ask=Decimal("50001"),
                           timestamp=T0, synchronized=False)
    assert rt.consider_entry(_entry_ctx(quote=unsync)) is None


def test_kill_switch_blocks_entry_but_allows_exit_and_cancels_pending(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now(); rt.arm(ttl_seconds=900)
    # open an entry
    entry = rt.consider_entry(_entry_ctx())
    assert entry is not None
    # engage kill switch: cancels the owned pending entry
    cancels = rt.engage_kill_switch()
    assert any(c.status == STATUS_CANCELED for c in cancels)
    # entries now blocked
    assert rt.consider_entry(_entry_ctx(signal=_signal(stop_loss=48000.0))) is None
    # protective exit still allowed (armed); base balance present
    from app.paper.execution import FeedStatus, QuoteSnapshot

    exit_r = rt.consider_exit(
        signal_id="exit1", instrument="BTC-USDT", meta=SPOT_BTC,
        quote=QuoteSnapshot("BTC-USDT", bid=Decimal("50000"), ask=Decimal("50001"), timestamp=T0, synchronized=True),
        feed_status=FeedStatus(connected=True, stale=False),
        base_balance=Decimal("0.001"), now=T0,
    )
    assert exit_r is not None and rest.place_calls[-1]["side"] == "sell"


def test_kill_switch_release_requires_reconcile_and_resolved_entries(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now()
    rt.arm(ttl_seconds=900)
    entry = rt.consider_entry(_entry_ctx())
    assert entry is not None
    store.set_kill_switch(aid, True, now=T0)

    assert rt.release_kill_switch() is False
    assert rt.kill_switch_engaged() is True

    canceled = rt.cancel_pending_entries()
    assert canceled and canceled[0].status == STATUS_CANCELED
    assert rt.reconcile_now().consistent is True
    assert rt.release_kill_switch() is True
    assert rt.kill_switch_engaged() is False


def test_kill_switch_release_requires_exact_runtime_lock(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now()
    store.set_kill_switch(aid, True, now=T0)
    store.release_lock(aid, "tok", now=T0)

    assert rt.release_kill_switch() is False
    assert rt.kill_switch_engaged() is True


def test_no_duplicate_entry_while_open(session_factory):
    store, aid, rest, lc, rec, rt = _runtime(session_factory)
    rt.reconcile_now(); rt.arm(ttl_seconds=900)
    rt.consider_entry(_entry_ctx())
    n = len(rest.place_calls)
    # a second entry signal for the same instrument while one is open is refused
    assert rt.consider_entry(_entry_ctx(signal=_signal(stop_loss=48000.0))) is None
    assert len(rest.place_calls) == n


# --------------------------------------------------------------------------
# private WS parsing
# --------------------------------------------------------------------------


def test_parse_private_login_and_orders():
    assert parse_private_message('{"event":"login","code":"0"}').event == "login"
    assert parse_private_message('{"event":"error","code":"60009"}').code == "60009"
    push = parse_private_message(
        '{"arg":{"channel":"orders","instType":"SPOT"},"data":[{"clOrdId":"d5x","state":"filled"}]}'
    )
    assert push.event == "channel" and push.orders[0]["state"] == "filled"
    assert parse_private_message("pong").ignored
    assert parse_private_message("not json").ignored


def test_deterministic_client_order_id_is_stable_and_alnum():
    a = derive_client_order_id("demo", "BTC-USDT", "entry", "sig-1")
    b = derive_client_order_id("demo", "BTC-USDT", "entry", "sig-1")
    assert a == b and a.isalnum() and len(a) <= 32 and a.startswith("d5")
    assert derive_client_order_id("demo", "BTC-USDT", "exit", "sig-1") != a
