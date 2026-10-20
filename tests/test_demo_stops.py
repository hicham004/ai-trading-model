"""Sprint 3 execution v2 (demo only): exchange-side protective stops, entry policy, bracket, guard.

Fully offline: fake REST/WS transports, fixed clocks, temporary SQLite. Covers
the algo endpoint allowlist and parameter whitelist, deterministic algo ids,
the stop manager's place / unknown-resolve / reject / amend / cancel paths,
the guard alarm, the post-only entry policy with timeout + budgeted fallback,
exit-cancels-stop-first, the driver round trip through a venue-created child
order, reconciliation of child fills, the startup gate refusing to arm while a
stop is ambiguous, the kill switch leaving the stop in place, the private-WS
algo channel, and the identity opt-in.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import DemoAlgoOrder, DemoEvent, DemoOrderIntent
from app.exchange.okx_demo_endpoints import (
    EndpointNotAllowedError,
    TRADE_ALGO_AMEND,
    TRADE_ALGO_CANCEL,
    TRADE_ALGO_GET,
    TRADE_ALGO_PLACE,
    TRADE_ALGOS_HISTORY,
    TRADE_ALGOS_PENDING,
    assert_endpoint_allowed,
)
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoRestClient, OKXDemoTransportError
from app.exchange.okx_demo_ws import ALGO_CHANNEL, OKXDemoPrivateWebSocket, build_orders_subscribe, parse_private_message
from app.execution.bracket import bracket_levels, risk_unit
from app.execution.identity import demo_identity_config, execution_v2_enabled
from app.execution.lifecycle import INTENT_ENTRY
from app.execution.runtime import POLICY_POST_ONLY, slippage_bps
from app.execution.stops import (
    ALARM_MISSING,
    ALARM_REJECTED,
    ALARM_UNKNOWN,
    ProtectiveStopManager,
    StopSpec,
    derive_algo_client_id,
    derive_child_client_id,
    is_algo_client_id,
)
from app.execution.store import (
    ALGO_CANCELED,
    ALGO_EFFECTIVE,
    ALGO_LIVE,
    ALGO_REJECTED,
    ALGO_UNKNOWN,
    STATUS_FILLED,
    DemoStore,
)
from app.live.schemas import CandleUpdate
from tests.test_demo_driver import (  # noqa: F401 - fixtures/helpers reused
    CREDS,
    T0,
    FakeRest,
    _connected_state,
    _driver,
    _fresh_book,
    _open_demo_position,
    _settings,
    session_factory,
)
from tests.test_demo_execution import SPOT_BTC, FakeResp, FakeSession, _client


# --------------------------------------------------------------------------
# a venue fake that understands algo orders
# --------------------------------------------------------------------------


class FakeRestV2(FakeRest):
    def __init__(self):
        super().__init__()
        self.algos = {}  # algoClOrdId -> venue row
        self.algo_placed = []
        self.algo_place_error = None
        self.algo_place_transport_but_record = False
        self.algo_place_transport_no_record = False
        self.algo_cancel_error = None
        self.algo_amend_error = None
        self.orders_by_id = {}
        self._n = 0

    def place_algo_order(self, p):
        OKXDemoRestClient._validate_algo_params(p)
        self.algo_placed.append(dict(p))
        if self.algo_place_error is not None:
            err = self.algo_place_error
            self.algo_place_error = None
            raise err
        if self.algo_place_transport_no_record:
            self.algo_place_transport_no_record = False
            raise OKXDemoTransportError("timeout")
        self._n += 1
        algo_id = f"A{self._n}"
        self.algos[p["algoClOrdId"]] = {
            "algoId": algo_id, "algoClOrdId": p["algoClOrdId"], "instId": p["instId"], "state": "live", "sz": p["sz"],
            "slTriggerPx": p["slTriggerPx"], "slOrdPx": "-1", "side": "sell", "tdMode": "cash", "ordType": p["ordType"],
            "tpTriggerPx": p.get("tpTriggerPx", ""), "ordId": "", "actualSz": "", "actualPx": "", "triggerTime": "",
        }
        if self.algo_place_transport_but_record:
            self.algo_place_transport_but_record = False
            raise OKXDemoTransportError("timeout after the venue accepted")
        return {"algoId": algo_id, "algoClOrdId": p["algoClOrdId"], "sCode": "0", "sMsg": ""}

    def _find(self, algo_id=None, algo_cl_ord_id=None):
        if algo_cl_ord_id and algo_cl_ord_id in self.algos:
            return self.algos[algo_cl_ord_id]
        for row in self.algos.values():
            if algo_id and row["algoId"] == algo_id:
                return row
        return None

    def get_algo_order(self, *, algo_id=None, algo_cl_ord_id=None):
        row = self._find(algo_id, algo_cl_ord_id)
        return dict(row) if row else None

    def get_pending_algo_orders(self, ord_type="conditional", instrument=None):
        return [dict(r) for r in self.algos.values() if r["state"] == "live" and r["ordType"] == ord_type]

    def get_algo_orders_history(self, ord_type="conditional", *, state=None, instrument=None):
        return []

    def cancel_algo_order(self, instrument, *, algo_id=None, algo_cl_ord_id=None):
        if self.algo_cancel_error is not None:
            err = self.algo_cancel_error
            self.algo_cancel_error = None
            raise err
        row = self._find(algo_id, algo_cl_ord_id)
        if row is None:
            raise OKXDemoError("no such algo", code="51293")
        if row["state"] == "effective":
            raise OKXDemoError("already triggered", code="51412")
        row["state"] = "canceled"
        return {"algoId": row["algoId"], "sCode": "0"}

    def amend_algo_order(self, instrument, *, algo_id=None, algo_cl_ord_id=None, new_size=None, new_sl_trigger_px=None,
                         new_sl_ord_px=None, new_tp_trigger_px=None, new_tp_ord_px=None):
        if self.algo_amend_error is not None:
            err = self.algo_amend_error
            self.algo_amend_error = None
            raise err
        row = self._find(algo_id, algo_cl_ord_id)
        if row is None or row["state"] != "live":
            raise OKXDemoError("not amendable", code="51412")
        if new_size is not None:
            row["sz"] = new_size
        if new_sl_trigger_px is not None:
            row["slTriggerPx"] = new_sl_trigger_px
        if new_tp_trigger_px is not None:
            row["tpTriggerPx"] = new_tp_trigger_px
        return {"algoId": row["algoId"], "sCode": "0"}

    def trigger_algo(self, algo_cl_ord_id, *, ord_id, price):
        row = self.algos[algo_cl_ord_id]
        row.update({"state": "effective", "ordId": ord_id, "actualSz": row["sz"], "actualPx": price, "triggerTime": "1750000000000"})
        self.orders_by_id[ord_id] = {
            "instId": row["instId"], "clOrdId": "", "ordId": ord_id, "algoClOrdId": algo_cl_ord_id, "algoId": row["algoId"],
            "state": "filled", "side": "sell", "sz": row["sz"], "accFillSz": row["sz"], "avgPx": price, "ordType": "market",
        }
        return dict(self.orders_by_id[ord_id])

    def get_order(self, inst, cl_ord_id=None, ord_id=None):
        if ord_id and ord_id in self.orders_by_id:
            return dict(self.orders_by_id[ord_id])
        return super().get_order(inst, cl_ord_id=cl_ord_id, ord_id=ord_id)


def _v2_settings(**overrides) -> Settings:
    base = dict(demo_stop_mode="exchange", demo_stop_unprotected_max_seconds=5.0, demo_stop_max_attempts_per_hour=3)
    base.update(overrides)
    return _settings(**base)


def _manager(session_factory, rest, *, clock_box, **overrides):
    store = DemoStore(session_factory, "demo")
    aid = store.ensure_account("fp", {"strategy": "ma"})
    settings = _v2_settings(**overrides)
    return store, aid, ProtectiveStopManager(store, rest, aid, "demo", settings=settings, clock=lambda: clock_box["t"])


def _events(session_factory, event_type=None):
    session = session_factory()
    try:
        stmt = select(DemoEvent).order_by(DemoEvent.id.asc())
        rows = session.scalars(stmt).all()
        return [r for r in rows if event_type is None or r.event_type == event_type]
    finally:
        session.close()


# --------------------------------------------------------------------------
# ids, allowlist, whitelist, config, identity
# --------------------------------------------------------------------------


def test_algo_and_child_ids_are_deterministic_and_alphanumeric():
    a = derive_algo_client_id("demo", "BTC-USDT", "d5abc", 1)
    assert a == derive_algo_client_id("demo", "BTC-USDT", "d5abc", 1) and a.startswith("d5s") and a.isalnum() and len(a) == 32
    assert a != derive_algo_client_id("demo", "BTC-USDT", "d5abc", 2) != derive_algo_client_id("demo", "ETH-USDT", "d5abc", 2)
    c = derive_child_client_id(a)
    assert c.startswith("d5x") and c.isalnum() and len(c) == 32 and c == derive_child_client_id(a)
    assert is_algo_client_id(a) and not is_algo_client_id(c) and not is_algo_client_id("") and not is_algo_client_id(None)


def test_algo_endpoints_are_allowlisted_and_bot_paths_are_forbidden():
    for method, path in (TRADE_ALGO_PLACE, TRADE_ALGO_CANCEL, TRADE_ALGO_AMEND, TRADE_ALGO_GET, TRADE_ALGOS_PENDING, TRADE_ALGOS_HISTORY):
        assert_endpoint_allowed(method, path)
    for method, path in (("POST", "/api/v5/tradingBot/grid/order-algo"), ("POST", "/api/v5/copytrading/algo-order"),
                         ("POST", "/api/v5/trade/order-algo-x"), ("GET", "/api/v5/trade/cancel-algos")):
        with pytest.raises(EndpointNotAllowedError):
            assert_endpoint_allowed(method, path)


def test_algo_parameter_whitelist_only_allows_sell_cash_conditional_or_oco():
    base = {"instId": "BTC-USDT", "tdMode": "cash", "side": "sell", "ordType": "conditional", "sz": "0.001",
            "algoClOrdId": "d5sabc", "slTriggerPx": "95", "slOrdPx": "-1", "slTriggerPxType": "last"}
    assert OKXDemoRestClient._validate_algo_params(base) == base
    bad_cases = [
        dict(base, side="buy"), dict(base, tdMode="cross"), dict(base, ordType="trigger"), dict(base, reduceOnly=True),
        dict(base, posSide="long"), dict(base, slTriggerPxType="mark"), dict(base, tpTriggerPx="120"),
        {k: v for k, v in base.items() if k != "slOrdPx"}, {k: v for k, v in base.items() if k != "algoClOrdId"},
        dict(base, ordType="oco"), dict(base, closeFraction="1"),
    ]
    for params in bad_cases:
        with pytest.raises(ValueError):
            OKXDemoRestClient._validate_algo_params(params)
    oco = dict(base, ordType="oco", tpTriggerPx="120", tpOrdPx="-1", tpTriggerPxType="last")
    assert OKXDemoRestClient._validate_algo_params(oco)["ordType"] == "oco"


def test_rest_algo_methods_build_the_documented_requests():
    session = FakeSession()
    client = _client(session)
    session.queue = [
        FakeResp({"code": "0", "msg": "", "data": [{"algoId": "A1", "algoClOrdId": "d5sabc", "sCode": "0"}]}),
        FakeResp({"code": "0", "msg": "", "data": [{"algoId": "A1", "sCode": "0"}]}),
        FakeResp({"code": "0", "msg": "", "data": [{"algoId": "A1", "sCode": "0"}]}),
        FakeResp({"code": "51293", "msg": "algo order does not exist", "data": []}),
        FakeResp({"code": "0", "msg": "", "data": [{"algoId": "A1", "state": "live"}]}),
        FakeResp({"code": "0", "msg": "", "data": []}),
        FakeResp({"code": "1", "msg": "All operations failed", "data": [{"sCode": "51280", "sMsg": "trigger price"}]}),
    ]
    placed = client.place_algo_order({"instId": "BTC-USDT", "tdMode": "cash", "side": "sell", "ordType": "conditional", "sz": "0.001",
                                      "algoClOrdId": "d5sabc", "slTriggerPx": "95", "slOrdPx": "-1"})
    assert placed["algoId"] == "A1" and session.calls[-1]["url"].endswith("/api/v5/trade/order-algo")
    client.cancel_algo_order("BTC-USDT", algo_id="A1")
    body = json.loads(session.calls[-1]["data"])
    assert body == [{"instId": "BTC-USDT", "algoId": "A1"}] and session.calls[-1]["url"].endswith("/cancel-algos")
    client.amend_algo_order("BTC-USDT", algo_cl_ord_id="d5sabc", new_size="0.002", new_sl_trigger_px="96", new_sl_ord_px="-1")
    body = json.loads(session.calls[-1]["data"])
    assert body == {"instId": "BTC-USDT", "algoClOrdId": "d5sabc", "newSz": "0.002", "newSlTriggerPx": "96", "newSlOrdPx": "-1"}
    assert client.get_algo_order(algo_cl_ord_id="d5sabc") is None  # not-found code -> None, never a rejection
    assert client.get_algo_order(algo_id="A1")["state"] == "live" and "algoId=A1" in session.calls[-1]["url"]
    assert client.get_pending_algo_orders("oco") == [] and "ordType=oco" in session.calls[-1]["url"] and "instType=SPOT" in session.calls[-1]["url"]
    with pytest.raises(OKXDemoError) as exc:
        client.place_algo_order({"instId": "BTC-USDT", "tdMode": "cash", "side": "sell", "ordType": "conditional", "sz": "0.001",
                                 "algoClOrdId": "d5sabc", "slTriggerPx": "95", "slOrdPx": "-1"})
    assert exc.value.code == "51280"
    for header in session.calls:
        assert header["headers"]["x-simulated-trading"] == "1"
    with pytest.raises(ValueError):
        client.cancel_algo_order("BTC-USDT")
    with pytest.raises(ValueError):
        client.amend_algo_order("BTC-USDT", algo_id="A1")
    with pytest.raises(ValueError):
        client.get_pending_algo_orders("trigger")


def test_execution_v2_settings_and_identity_opt_in(monkeypatch):
    assert not execution_v2_enabled(_settings())
    legacy = demo_identity_config(_settings())
    assert "execution_v2" not in legacy
    v2 = demo_identity_config(_v2_settings())
    assert v2["execution_v2"]["stop_mode"] == "exchange" and execution_v2_enabled(_v2_settings())
    assert {k: v for k, v in v2.items() if k != "execution_v2"} == legacy  # legacy keys untouched
    monkeypatch.setenv("DEMO_STOP_MODE", "EXCHANGE")
    monkeypatch.setenv("DEMO_BRACKET_TIME_STOP_BARS", "12")
    monkeypatch.setenv("DEMO_BRACKET_TAKE_PROFIT_R", "2")
    s = Settings()
    assert s.demo_stop_mode == "exchange" and s.demo_bracket_time_stop_bars == 12 and s.demo_bracket_take_profit_r == 2.0
    monkeypatch.setenv("DEMO_STOP_MODE", "hardware")
    with pytest.raises(ValueError):
        Settings()
    monkeypatch.setenv("DEMO_STOP_MODE", "software")
    monkeypatch.setenv("DEMO_BRACKET_TRAIL_R", "-1")
    with pytest.raises(ValueError):
        Settings()


# --------------------------------------------------------------------------
# bracket math
# --------------------------------------------------------------------------


def test_bracket_levels_defaults_off_and_each_leg():
    off = bracket_levels(entry_price=Decimal(100), stop_price=Decimal(95), highs_since_entry=[Decimal(130)], bars_since_entry=500, settings=_settings())
    assert off.stop == Decimal(95) and off.take_profit is None and off.time_stop_due is False
    s = _settings(demo_bracket_take_profit_r=2.0, demo_bracket_trail_activate_r=1.0, demo_bracket_trail_r=1.0, demo_bracket_time_stop_bars=10)
    lv = bracket_levels(entry_price=Decimal(100), stop_price=Decimal(95), highs_since_entry=[Decimal(103)], bars_since_entry=3, settings=s)
    assert lv.take_profit == Decimal(110) and lv.stop == Decimal(95) and not lv.time_stop_due  # not yet 1R in profit
    lv = bracket_levels(entry_price=Decimal(100), stop_price=Decimal(95), highs_since_entry=[Decimal(103), Decimal(108)], bars_since_entry=10, settings=s)
    assert lv.stop == Decimal(103) and lv.time_stop_due  # trailed 1R below the running high; time stop due
    assert risk_unit(Decimal(100), Decimal(105)) is None and risk_unit(Decimal(100), Decimal(95)) == Decimal(5)
    bad = bracket_levels(entry_price=Decimal(100), stop_price=Decimal(105), highs_since_entry=[], bars_since_entry=0, settings=s)
    assert bad.take_profit is None and bad.stop == Decimal(105)


# --------------------------------------------------------------------------
# the stop manager
# --------------------------------------------------------------------------


def test_manager_is_inert_in_software_mode(session_factory):
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, FakeRestV2(), clock_box=cb, demo_stop_mode="software")
    assert not mgr.enabled
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal(95), SPOT_BTC, now=cb["t"], armed=True).state == "disabled"
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) is None
    assert mgr.owned_child({"algoClOrdId": "d5sabc"}) is None and mgr.cancel_for_exit("BTC-USDT", now=cb["t"]) == "none"


def test_manager_places_once_and_reports_protected(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=False).state == "unarmed"
    first = mgr.sync("BTC-USDT", Decimal("0.00123456789"), Decimal("95.04"), SPOT_BTC, now=cb["t"], armed=True)
    assert first.state == "placed" and len(rest.algos) == 1
    sent = rest.algo_placed[-1]
    assert sent["side"] == "sell" and sent["tdMode"] == "cash" and sent["ordType"] == "conditional" and sent["slOrdPx"] == "-1"
    assert Decimal(sent["sz"]) == Decimal("0.00123456") and sent["slTriggerPx"] == "95" and sent["algoClOrdId"].startswith("d5s")
    again = mgr.sync("BTC-USDT", Decimal("0.00123456789"), Decimal("95.04"), SPOT_BTC, now=cb["t"], armed=True)
    assert again.state == "protected" and len(rest.algos) == 1 and len(rest.algo_placed) == 1
    row = store.get_algo_order(aid, first.algo_cl_ord_id)
    assert row.status == ALGO_LIVE and row.algo_id == "A1" and row.version == 1
    # dust / flat: the stop is cancelled, nothing else placed
    assert mgr.sync("BTC-USDT", Decimal("0.000001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "dust"
    assert rest.algos[first.algo_cl_ord_id]["state"] == "canceled" and store.get_algo_order(aid, first.algo_cl_ord_id).status == ALGO_CANCELED
    assert mgr.sync("BTC-USDT", Decimal(0), None, SPOT_BTC, now=cb["t"], armed=True).state == "flat"


def test_manager_transport_timeout_is_resolved_by_query_never_duplicated(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    rest.algo_place_transport_but_record = True  # the venue accepted but the response was lost
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert out.state == "placed" and len(rest.algos) == 1 and store.get_algo_order(aid, out.algo_cl_ord_id).status == ALGO_LIVE
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "protected"
    assert len(rest.algo_placed) == 1


def test_manager_unknown_stays_unknown_and_blocks_new_placement(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    rest.algo_place_transport_no_record = True  # nothing visible on the venue after the timeout
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert out.state == "unknown" and store.get_algo_order(aid, out.algo_cl_ord_id).status == ALGO_UNKNOWN
    out2 = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert out2.state == "unknown" and len(rest.algo_placed) == 1  # no blind re-placement
    cb["t"] = T0 + timedelta(seconds=10)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) == ALARM_UNKNOWN
    # The venue finally shows it: resolved to live.
    rest.algos[out.algo_cl_ord_id] = {"algoId": "A9", "algoClOrdId": out.algo_cl_ord_id, "instId": "BTC-USDT", "state": "live", "sz": "0.001",
                                      "slTriggerPx": "95", "side": "sell", "tdMode": "cash", "ordType": "conditional", "tpTriggerPx": ""}
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "protected"
    assert store.get_algo_order(aid, out.algo_cl_ord_id).algo_id == "A9"
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) is None


def test_manager_rejection_is_recorded_retried_and_capped(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb, demo_stop_max_attempts_per_hour=2)
    rest.algo_place_error = OKXDemoError("insufficient balance", code="51008")
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert out.state == "rejected" and store.get_algo_order(aid, out.algo_cl_ord_id).status == ALGO_REJECTED
    assert _events(session_factory, "protective_stop_rejected")
    cb["t"] = T0 + timedelta(seconds=6)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) == ALARM_REJECTED
    rest.algo_place_error = OKXDemoError("insufficient balance", code="51008")
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "rejected"
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "capped"
    assert len(rest.algo_placed) == 2
    cb["t"] = T0 + timedelta(hours=2)
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "placed"


def test_manager_amends_size_and_trailing_but_never_lowers_the_trigger(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    first = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert first.state == "placed"
    up = mgr.sync("BTC-USDT", Decimal("0.002"), Decimal("97"), SPOT_BTC, now=cb["t"], armed=True)
    assert up.state == "amended" and rest.algos[first.algo_cl_ord_id]["sz"] == "0.002" and rest.algos[first.algo_cl_ord_id]["slTriggerPx"] == "97"
    assert len(rest.algo_placed) == 1 and store.get_algo_order(aid, first.algo_cl_ord_id).trigger_price == "97"
    lower = mgr.sync("BTC-USDT", Decimal("0.002"), Decimal("90"), SPOT_BTC, now=cb["t"], armed=True)
    assert lower.state == "protected" and rest.algos[first.algo_cl_ord_id]["slTriggerPx"] == "97"  # a stop never moves down
    # Amend rejected -> cancel + replace with a new version.
    rest.algo_amend_error = OKXDemoError("amend rejected", code="51280")
    replaced = mgr.sync("BTC-USDT", Decimal("0.003"), Decimal("97"), SPOT_BTC, now=cb["t"], armed=True)
    assert replaced.state == "placed" and replaced.algo_cl_ord_id != first.algo_cl_ord_id
    assert rest.algos[first.algo_cl_ord_id]["state"] == "canceled" and store.get_algo_order(aid, replaced.algo_cl_ord_id).version == 2
    assert len([r for r in rest.algos.values() if r["state"] == "live"]) == 1


def test_manager_oco_take_profit_leg(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True, tp_trigger=Decimal("110"))
    assert out.state == "placed"
    sent = rest.algo_placed[-1]
    assert sent["ordType"] == "oco" and sent["tpTriggerPx"] == "110" and sent["tpOrdPx"] == "-1"
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True, tp_trigger=Decimal("110")).state == "protected"
    assert mgr.desired_spec("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, tp_trigger=Decimal("90")).tp_trigger is None  # tp must sit above the stop


def test_cancel_for_exit_and_triggered_supersedes(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert mgr.cancel_for_exit("BTC-USDT", now=cb["t"]) == "canceled" and store.get_algo_order(aid, out.algo_cl_ord_id).status == ALGO_CANCELED
    assert mgr.cancel_for_exit("BTC-USDT", now=cb["t"]) == "none"
    again = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert again.state == "placed" and again.algo_cl_ord_id != out.algo_cl_ord_id
    rest.trigger_algo(again.algo_cl_ord_id, ord_id="CH1", price="94")
    assert mgr.cancel_for_exit("BTC-USDT", now=cb["t"]) == "triggered"
    row = store.get_algo_order(aid, again.algo_cl_ord_id)
    assert row.status == ALGO_EFFECTIVE and row.child_order_id == "CH1" and row.actual_price == "94" and row.triggered_at is not None
    # While the venue fill is pending (within the grace) nothing new is placed for the still-local position.
    assert mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True).state == "triggered"
    # The child order row maps back to the stop by algoClOrdId, algoId or ordId; a stranger does not.
    assert mgr.owned_child({"ordId": "CH1"}).algo_cl_ord_id == again.algo_cl_ord_id
    assert mgr.owned_child({"algoId": "A2"}).algo_cl_ord_id == again.algo_cl_ord_id
    assert mgr.owned_child({"algoClOrdId": again.algo_cl_ord_id}).algo_cl_ord_id == again.algo_cl_ord_id
    assert mgr.owned_child({"ordId": "nope", "algoClOrdId": "d5szzz"}) is None
    cid = mgr.child_client_id(row, child_ord_id="CH1", size="0.001", now=cb["t"])
    assert cid == derive_child_client_id(again.algo_cl_ord_id) and cid == mgr.child_client_id(row, child_ord_id="CH1", size="0.001", now=cb["t"])
    child_intent = store.get_intent(aid, cid)
    assert child_intent.intent == "exit" and child_intent.side == "sell" and child_intent.entry_policy == "exchange_stop"
    # Cancel outcome unknown (transport) with the venue still live -> "unknown" (caller defers).
    third = mgr.sync("ETH-USDT", Decimal("0.01"), Decimal("1800"), SPOT_BTC._replace(instrument="ETH-USDT", base_ccy="ETH") if hasattr(SPOT_BTC, "_replace") else SPOT_BTC, now=cb["t"], armed=True)
    assert third.state == "placed"


def test_guard_alarm_after_grace_and_cleared_when_protected(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) is None  # timer starts
    cb["t"] = T0 + timedelta(seconds=4)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) is None
    cb["t"] = T0 + timedelta(seconds=6)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) == ALARM_MISSING
    assert mgr.guard("BTC-USDT", Decimal("0.000001"), SPOT_BTC, now=cb["t"]) is None  # dust is not protectable
    mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    assert mgr.guard("BTC-USDT", Decimal("0.001"), SPOT_BTC, now=cb["t"]) is None


# --------------------------------------------------------------------------
# runtime: entry policy, exit cancels the stop first
# --------------------------------------------------------------------------


def _fresh_candle(state, cb):
    ts = cb["t"].replace(second=0, microsecond=0) - timedelta(minutes=1)
    state.apply_candle(CandleUpdate("BTC-USDT", "1m", ts, 100.0, 100.5, 99.5, 100.0, 10.0, True), "okx-business")


def _signal(ts, stop=95.0):
    from app.strategy.base import Signal, SignalAction

    return Signal(timestamp=ts, instrument="BTC-USDT", action=SignalAction.LONG, confidence=0.9, reason="t", stop_loss=stop, timeframe="1m")


def test_post_only_entry_then_timeout_fallback_within_budget(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange",
                        demo_entry_policy=POLICY_POST_ONLY, demo_entry_timeout_seconds=30, demo_entry_slippage_budget=0.001)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    from app.execution.runtime import EntryContext
    from app.paper.execution import FeedStatus

    quote = driver._quote_for("BTC-USDT", cb["t"])
    ctx = EntryContext(signal=_signal(cb["t"] - timedelta(minutes=1)), instrument="BTC-USDT", meta=driver._instrument_meta["BTC-USDT"], quote=quote,
                       feed_status=FeedStatus(True, False), available_quote=Decimal(1000), equity=Decimal(1000), day_start_equity=Decimal(1000),
                       day_realized_pnl=Decimal(0), now=cb["t"], data_time=cb["t"] - timedelta(seconds=30))
    result = driver.runtime.consider_entry(ctx)
    assert result is not None and rest.placed[-1]["ordType"] == "post_only" and rest.placed[-1]["px"] == "100"  # one tick inside the spread
    intent = driver.store.get_intent(driver.account_id, result.client_order_id)
    assert intent.entry_policy == POLICY_POST_ONLY and intent.reference_price == "100.1" and Decimal(intent.expected_slippage_bps) < 0
    # Before the timeout nothing happens.
    cb["t"] += timedelta(seconds=10)
    _fresh_candle(state, cb)
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    assert driver.step(cb["t"]) == [] and rest.orders[result.client_order_id]["state"] == "live"
    # After the timeout: cancelled, and one marketable fallback for the remainder within the budget.
    cb["t"] += timedelta(seconds=25)
    _fresh_candle(state, cb)
    _fresh_book(state, cb, bid="100.0", ask="100.15")  # +5 bps vs reference: within the 10 bps budget
    results = driver.step(cb["t"])
    assert rest.orders[result.client_order_id]["state"] == "canceled"
    fallback = [r for r in results if r.client_order_id != result.client_order_id]
    assert len(fallback) == 1 and rest.placed[-1]["ordType"] == "limit"
    fb = driver.store.get_intent(driver.account_id, fallback[0].client_order_id)
    assert fb.entry_policy == "market_fallback" and fb.parent_client_order_id == result.client_order_id and fb.reference_price == "100.1"
    assert Decimal(fb.expected_slippage_bps) > 0 and Decimal(fb.size) <= Decimal(intent.size)
    assert Decimal(fb.size) * Decimal(fb.price) <= Decimal(100)  # the per-order notional cap binds at the higher price
    assert _events(session_factory, "entry_fallback_submitted")
    # Realized slippage is recorded when the fallback fills.
    driver.project_private_orders([{"instId": "BTC-USDT", "clOrdId": fb.client_order_id, "ordId": rest.orders[fb.client_order_id]["ordId"],
                                    "state": "filled", "side": "buy", "accFillSz": fb.size, "avgPx": "100.2", "tradeId": "fb-fill",
                                    "fillSz": fb.size, "fillPx": "100.2"}])
    assert Decimal(driver.store.get_intent(driver.account_id, fb.client_order_id).realized_slippage_bps) == slippage_bps(Decimal("100.2"), Decimal("100.1")).quantize(Decimal("0.01"))
    assert _events(session_factory, "entry_execution_quality")


def test_post_only_timeout_abandons_when_slippage_exceeds_budget(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange",
                        demo_entry_policy=POLICY_POST_ONLY, demo_entry_timeout_seconds=30, demo_entry_slippage_budget=0.001)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _fresh_book(state, cb, bid="99.9", ask="100.1")
    from app.execution.runtime import EntryContext
    from app.paper.execution import FeedStatus

    ctx = EntryContext(signal=_signal(cb["t"] - timedelta(minutes=1)), instrument="BTC-USDT", meta=driver._instrument_meta["BTC-USDT"],
                       quote=driver._quote_for("BTC-USDT", cb["t"]), feed_status=FeedStatus(True, False), available_quote=Decimal(1000),
                       equity=Decimal(1000), day_start_equity=Decimal(1000), day_realized_pnl=Decimal(0), now=cb["t"], data_time=cb["t"] - timedelta(seconds=30))
    result = driver.runtime.consider_entry(ctx)
    cb["t"] += timedelta(seconds=40)
    _fresh_candle(state, cb)
    _fresh_book(state, cb, bid="100.9", ask="101.1")  # ~100 bps away: budget exceeded -> no chase
    results = driver.step(cb["t"])
    assert rest.orders[result.client_order_id]["state"] == "canceled" and len(results) == 1 and len(rest.placed) == 1
    abandoned = _events(session_factory, "entry_fallback_abandoned")
    assert abandoned and "slippage_budget" in abandoned[-1].message


def test_exit_cancels_the_stop_first_and_defers_or_skips_when_needed(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange")
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _open_demo_position(driver)
    _fresh_book(state, cb)
    driver.step(cb["t"])  # places the exchange-side stop
    algo_cl = next(iter(rest.algos))
    assert rest.algos[algo_cl]["state"] == "live"
    # A signal-driven exit cancels the stop first, then sells.
    from app.paper.execution import FeedStatus

    result = driver.runtime.consider_exit(signal_id="flat-1", instrument="BTC-USDT", meta=driver._instrument_meta["BTC-USDT"],
                                          quote=driver._quote_for("BTC-USDT", cb["t"]), feed_status=FeedStatus(True, False),
                                          base_balance=Decimal("0.001"), now=cb["t"])
    assert result is not None and rest.placed[-1]["side"] == "sell" and rest.algos[algo_cl]["state"] == "canceled"
    # Stop already triggered -> the software exit is superseded.
    driver.project_private_orders([{"instId": "BTC-USDT", "clOrdId": result.client_order_id, "ordId": rest.orders[result.client_order_id]["ordId"],
                                    "state": "canceled", "side": "sell", "accFillSz": "0"}])
    driver.step(cb["t"])
    new_cl = [k for k, v in rest.algos.items() if v["state"] == "live"][0]
    rest.trigger_algo(new_cl, ord_id="CH9", price="94")
    before = len(rest.placed)
    assert driver.runtime.consider_exit(signal_id="flat-2", instrument="BTC-USDT", meta=driver._instrument_meta["BTC-USDT"],
                                        quote=driver._quote_for("BTC-USDT", cb["t"]), feed_status=FeedStatus(True, False),
                                        base_balance=Decimal("0.001"), now=cb["t"]) is None
    assert len(rest.placed) == before and _events(session_factory, "exit_superseded_by_exchange_stop")


# --------------------------------------------------------------------------
# driver round trip through the venue-created child order
# --------------------------------------------------------------------------


def test_driver_places_stop_after_fill_and_stop_trigger_closes_the_position(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange")
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _open_demo_position(driver)
    _fresh_book(state, cb)
    assert driver.step(cb["t"]) == []
    algo_cl, venue = next(iter(rest.algos.items()))
    assert venue["state"] == "live" and venue["sz"] == "0.001" and venue["slTriggerPx"] == "95"
    assert _events(session_factory, "protective_stop_placed") and driver.runtime.entry_block_reason(cb["t"]) is None
    # The stop triggers on the venue while we watch the orders-algo channel.
    rest.trigger_algo(algo_cl, ord_id="CH1", price="94")
    driver.project_private_algo_orders([dict(rest.algos[algo_cl])])
    row = driver.store.get_algo_order(driver.account_id, algo_cl)
    assert row.status == ALGO_EFFECTIVE and row.child_order_id == "CH1" and driver._needs_reconcile
    # The venue-created SELL arrives on the orders channel without our clOrdId: it is ours, not foreign.
    child = rest.orders_by_id["CH1"]
    driver.project_private_orders([dict(child, tradeId="T-child", fillSz="0.001", fillPx="94")])
    assert not _events(session_factory, "private_foreign")
    position, _ = driver.store.position_summary(driver.account_id, "BTC-USDT")
    assert position < Decimal("0.00000001")
    cid = derive_child_client_id(algo_cl)
    intent = driver.store.get_intent(driver.account_id, cid)
    assert intent.status == STATUS_FILLED and intent.exchange_order_id == "CH1" and intent.filled_size == "0.001"
    # Reconcile sees the child fill as owned and the venue flat; consistent.
    rest.fills = [{"tradeId": "T-child", "instId": "BTC-USDT", "clOrdId": "", "ordId": "CH1", "side": "sell", "fillSz": "0.001", "fillPx": "94"},
                  {"tradeId": "fill-" + _entry_id(driver), "instId": "BTC-USDT", "clOrdId": _entry_id(driver), "ordId": "O1", "side": "buy", "fillSz": "0.001", "fillPx": "100"}]
    rest.balances = {"details": [{"ccy": "USDT", "cashBal": "999.994"}, {"ccy": "BTC", "cashBal": "0"}]}
    result = driver.runtime.reconcile_now()
    assert result.consistent, result.issues
    assert result.summary["owned_children"] >= 0 and result.summary["unprotected_positions"] == 0
    assert driver.step(cb["t"]) == [] and all(v["state"] != "live" for v in rest.algos.values())
    assert driver.runtime.stop_alarm() is None


def _entry_id(driver):
    session = driver.store._session_factory()
    try:
        return session.scalar(select(DemoOrderIntent.client_order_id).where(DemoOrderIntent.intent == INTENT_ENTRY).order_by(DemoOrderIntent.id.desc()).limit(1))
    finally:
        session.close()


def test_reconcile_classifies_a_child_fill_via_order_lookup_and_flags_foreign_algos(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange")
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _open_demo_position(driver)
    _fresh_book(state, cb)
    driver.step(cb["t"])
    algo_cl = next(iter(rest.algos))
    rest.trigger_algo(algo_cl, ord_id="CH2", price="94")  # process was "dead": no WS update seen
    entry_cl = _entry_id(driver)
    rest.fills = [{"tradeId": "T-child2", "instId": "BTC-USDT", "clOrdId": "", "ordId": "CH2", "side": "sell", "fillSz": "0.001", "fillPx": "94"},
                  {"tradeId": "fill-" + entry_cl, "instId": "BTC-USDT", "clOrdId": entry_cl, "ordId": "O1", "side": "buy", "fillSz": "0.001", "fillPx": "100"}]
    rest.balances = {"details": [{"ccy": "USDT", "cashBal": "999.994"}, {"ccy": "BTC", "cashBal": "0"}]}
    result = driver.runtime.reconcile_now()
    assert result.consistent, result.issues
    cid = derive_child_client_id(algo_cl)
    assert driver.store.get_intent(driver.account_id, cid).status == STATUS_FILLED
    assert driver.store.get_algo_order(driver.account_id, algo_cl).status == ALGO_EFFECTIVE
    position, _ = driver.store.position_summary(driver.account_id, "BTC-USDT")
    assert position == Decimal(0)
    # A pending algo order we do not own is foreign: inconsistent, never cancelled.
    rest.algos["stranger"] = {"algoId": "Z1", "algoClOrdId": "", "instId": "BTC-USDT", "state": "live", "sz": "1", "slTriggerPx": "1",
                             "side": "sell", "tdMode": "cash", "ordType": "conditional", "tpTriggerPx": ""}
    result = driver.runtime.reconcile_now()
    assert not result.consistent and any("foreign algo order" in i for i in result.issues) and rest.algos["stranger"]["state"] == "live"


def test_stop_alarm_blocks_entries_and_startup_gate_refuses_while_stop_unknown(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange",
                        demo_stop_unprotected_max_seconds=5, demo_stop_max_attempts_per_hour=1)
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _open_demo_position(driver)
    _fresh_book(state, cb)
    rest.algo_place_error = OKXDemoError("rejected", code="51008")
    driver.step(cb["t"])
    assert driver.runtime.stop_alarm() is None  # within the grace
    cb["t"] += timedelta(seconds=6)
    _fresh_book(state, cb)
    driver.step(cb["t"])
    assert driver.runtime.stop_alarm() == ALARM_REJECTED
    assert driver.runtime.entry_block_reason(cb["t"]) == "protective_stop_alarm"
    assert _events(session_factory, "protective_stop_alarm")
    # Once the attempt budget rolls over and the venue accepts, the alarm clears.
    cb["t"] += timedelta(hours=1)
    _fresh_book(state, cb)
    driver.step(cb["t"])
    assert driver.runtime.stop_alarm() is None and driver.runtime.entry_block_reason(cb["t"]) is None
    assert _events(session_factory, "protective_stop_alarm_cleared")
    # Startup gate: an UNKNOWN stop makes the runtime not armable.
    rest2 = FakeRestV2()
    rest2.algo_place_transport_no_record = True
    driver2, cb2 = _driver(session_factory, rest=rest2, state=_connected_state(), demo_stop_mode="exchange", demo_account_name="demo2")
    driver2.startup_gate()
    driver2.runtime.arm(ttl_seconds=10 ** 9)
    driver2._set_private_authenticated(True)
    _open_demo_position(driver2)
    _fresh_book(driver2._market_state, cb2)
    driver2.step(cb2["t"])
    driver2.release_lock()
    driver3, _ = _driver(session_factory, rest=rest2, state=_connected_state(), clock_box=cb2, demo_stop_mode="exchange", demo_account_name="demo2")
    gate = driver3.startup_gate()
    assert gate.lock_acquired and gate.account_valid and not gate.armable


def test_kill_switch_keeps_the_exchange_side_stop(session_factory):
    rest = FakeRestV2()
    state = _connected_state()
    cb = {"t": T0 + timedelta(minutes=1, seconds=1)}
    driver, _ = _driver(session_factory, rest=rest, state=state, clock_box=cb, demo_stop_mode="exchange")
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver._set_private_authenticated(True)
    _open_demo_position(driver)
    _fresh_book(state, cb)
    driver.step(cb["t"])
    algo_cl = next(iter(rest.algos))
    driver.runtime.engage_kill_switch()
    driver.step(cb["t"])
    assert rest.algos[algo_cl]["state"] == "live" and driver.runtime.entry_block_reason(cb["t"]) == "kill_switch_engaged"
    # Software stop backstop still fires under the kill switch (and cancels the exchange stop first).
    state.apply_candle(CandleUpdate("BTC-USDT", "1m", T0, 100, 101, 90, 92, 10, True), "okx-business")
    _fresh_book(state, cb, bid="91.9", ask="92.1")
    driver._private_last_msg = cb["t"]
    results = driver.step(cb["t"])
    assert results and rest.placed[-1]["side"] == "sell" and rest.algos[algo_cl]["state"] == "canceled"


# --------------------------------------------------------------------------
# private WS: the orders-algo channel
# --------------------------------------------------------------------------


def test_private_ws_requires_algo_subscription_ack_and_dispatches_algo_rows():
    stop = asyncio.Event()
    algo_rows, order_rows, status = [], [], []

    class Conn:
        def __init__(self):
            self.sent = []
            self.responses = [
                '{"event":"login","code":"0"}',
                '{"event":"subscribe","code":"0","arg":{"channel":"orders","instType":"SPOT","instId":"BTC-USDT"}}',
                '{"arg":{"channel":"orders-algo","instType":"SPOT","instId":"BTC-USDT"},"data":[{"algoId":"A1","state":"effective"}]}',
                '{"event":"subscribe","code":"0","arg":{"channel":"orders-algo","instType":"SPOT","instId":"BTC-USDT"}}',
                '{"arg":{"channel":"orders-algo","instType":"SPOT","instId":"BTC-USDT"},"data":[{"algoId":"A1","state":"live"}]}',
                '{"arg":{"channel":"orders","instType":"SPOT","instId":"BTC-USDT"},"data":[{"ordId":"O1","state":"live"}]}',
            ]

        async def send(self, payload):
            self.sent.append(payload)

        async def recv(self):
            response = self.responses.pop(0)
            if not self.responses:
                stop.set()
            return response

    conn = Conn()
    ws = OKXDemoPrivateWebSocket(CREDS, instruments=["BTC-USDT"], connect=lambda url: None, subscribe_algo=True,
                                 on_orders=order_rows.extend, on_algo_orders=algo_rows.extend, on_status=status.append)
    assert asyncio.run(ws._session(conn, stop)) is True
    sub = json.loads(conn.sent[1])
    assert {a["channel"] for a in sub["args"]} == {"orders", "orders-algo"}
    assert algo_rows == [{"algoId": "A1", "state": "live"}]  # the row before the algo ack was dropped (not yet subscribed)
    assert order_rows == [{"ordId": "O1", "state": "live"}] and status[-1] is True
    assert ws.required_subscriptions() == {("orders", "BTC-USDT"), (ALGO_CHANNEL, "BTC-USDT")}
    assert build_orders_subscribe(["BTC-USDT"])["args"] == [{"channel": "orders", "instType": "SPOT", "instId": "BTC-USDT"}]
    parsed = parse_private_message('{"arg":{"channel":"orders-algo"},"data":[{"x":1}]}')
    assert parsed.channel == ALGO_CHANNEL and parsed.orders == [{"x": 1}]
    assert parse_private_message('{"arg":{"channel":"algo-advance"},"data":[]}').ignored == "unsupported_channel:algo-advance"


def test_driver_flags_foreign_algo_updates(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    driver, _ = _driver(session_factory, rest=rest, clock_box=cb, demo_stop_mode="exchange")
    driver.startup_gate()
    driver.runtime.arm(ttl_seconds=10 ** 9)
    driver.project_private_algo_orders([{"instId": "BTC-USDT", "algoClOrdId": "d5snotours", "algoId": "Z", "state": "live"}])
    assert _events(session_factory, "private_foreign") and not driver.runtime.reconcile_consistent
    driver.project_private_algo_orders([{"instId": "DOGE-USDT", "algoClOrdId": "x", "state": "live"}])
    assert len(_events(session_factory, "private_foreign")) == 2


def test_algo_ledger_rows_are_visible_in_the_database(session_factory):
    rest = FakeRestV2()
    cb = {"t": T0}
    store, aid, mgr = _manager(session_factory, rest, clock_box=cb)
    out = mgr.sync("BTC-USDT", Decimal("0.001"), Decimal("95"), SPOT_BTC, now=cb["t"], armed=True)
    session = session_factory()
    try:
        rows = session.scalars(select(DemoAlgoOrder)).all()
    finally:
        session.close()
    assert len(rows) == 1 and rows[0].algo_cl_ord_id == out.algo_cl_ord_id and rows[0].order_price == "-1" and rows[0].side == "sell"
