"""Plan row R17: the research-side public positioning feed for the replication markets' swaps (GET only, bounded, app allowlist untouched)."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from app.datalake import derivatives as app_derivatives
from app.datalake.okx_public_rest import OKXPublicRest
from research import positioning_data as pdata
from research.markets import RESEARCH_SWAP_FOR

# Rows copied from the live public endpoints on 2026-11-05 (SOL-USDT-SWAP and DOGE-USDT-SWAP answer in the BTC/ETH format).
SOL_FUNDING_ROWS = [
    {"formulaType": "withRate", "fundingRate": "0.0000758517742653", "fundingTime": "1793836800000", "instId": "SOL-USDT-SWAP",
     "instType": "SWAP", "method": "current_period", "realizedRate": "0.0000758517742653"},
    {"formulaType": "withRate", "fundingRate": "0.0001", "fundingTime": "1793808000000", "instId": "SOL-USDT-SWAP",
     "instType": "SWAP", "method": "current_period", "realizedRate": "0.0001"},
]
SOL_OI_ROWS = [["1793840400000", "3477199.2100000016", "3477199.2100000016", "333915440.136300153648"],
               ["1793836800000", "3462599.61000000114", "3462599.61000000114", "331647790.6458001091892"]]
DOGE_FUNDING_ROWS = [
    {"formulaType": "withRate", "fundingRate": "0.0001", "fundingTime": "1793836800000", "instId": "DOGE-USDT-SWAP",
     "instType": "SWAP", "method": "current_period", "realizedRate": "0.0001"},
    {"formulaType": "withRate", "fundingRate": "0.000093613401878", "fundingTime": "1793808000000", "instId": "DOGE-USDT-SWAP",
     "instType": "SWAP", "method": "current_period", "realizedRate": "0.000093613401878"},
]
DOGE_OI_ROWS = [["1793840400000", "1234581.45999999989", "1234581459.99999989", "95198576.3805999915179"],
                ["1793836800000", "1238977.00999999982", "1238977009.99999982", "95314501.3792999861526"]]


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RecordedSession:
    """Answers the two public endpoints from the recorded rows and records every request made through the real client."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append({"url": url, "params": dict(params or {}), "kwargs": kwargs})
        path = urlsplit(url).path
        inst = params["instId"]
        if path == app_derivatives.FUNDING_PATH:
            rows = {"SOL-USDT-SWAP": SOL_FUNDING_ROWS, "DOGE-USDT-SWAP": DOGE_FUNDING_ROWS}[inst]
        elif path == app_derivatives.OPEN_INTEREST_PATH:
            rows = {"SOL-USDT-SWAP": SOL_OI_ROWS, "DOGE-USDT-SWAP": DOGE_OI_ROWS}[inst]
        else:
            raise AssertionError(f"unexpected path {path}")
        return _Response({"code": "0", "msg": "", "data": rows})

    def post(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("POST is never allowed")


def test_the_feed_is_bounded_to_the_research_markets_swaps():
    assert pdata.RESEARCH_SWAPS == tuple(sorted(RESEARCH_SWAP_FOR.values()))
    assert "SOL-USDT-SWAP" in pdata.RESEARCH_SWAPS and "DOGE-USDT-SWAP" in pdata.RESEARCH_SWAPS
    assert "BTC-USDT-SWAP" not in pdata.RESEARCH_SWAPS and "ETH-USDT-SWAP" not in pdata.RESEARCH_SWAPS
    assert pdata.is_research_swap("SOL-USDT-SWAP") and not pdata.is_research_swap("BTC-USDT-SWAP")
    session = RecordedSession()
    rest = OKXPublicRest(session=session, sleep=lambda s: None)
    # The Sprint 2c pair and anything unknown are refused BEFORE any request: BTC/ETH data only ever comes through the app's path.
    for swap in ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "XYZ-USDT-SWAP", "SOL-USDT", ""):
        with pytest.raises(pdata.PositioningDataError):
            pdata.fetch_research_funding_history(rest, swap)
        with pytest.raises(pdata.PositioningDataError):
            pdata.fetch_research_open_interest_history(rest, swap)
    with pytest.raises(pdata.PositioningDataError):
        pdata.fetch_research_open_interest_history(rest, "SOL-USDT-SWAP", "2H")
    assert session.calls == []
    assert issubclass(pdata.PositioningDataError, ValueError)  # the fleet's refresh logs a ValueError and keeps going


def test_recorded_responses_parse_like_the_app_rows_and_only_public_get_requests_are_made():
    session = RecordedSession()
    rest = OKXPublicRest(session=session, sleep=lambda s: None)
    funding = pdata.fetch_research_funding_history(rest, "SOL-USDT-SWAP", after_ms=1793836800001)
    assert [r["ts"] for r in funding] == [1793836800000, 1793808000000]
    assert funding[0] == {"ts": 1793836800000, "instrument": "SOL-USDT-SWAP", "period": "8H", "funding_rate": pytest.approx(7.58517742653e-05),
                          "realized_rate": pytest.approx(7.58517742653e-05), "method": "current_period", "formula_type": "withRate"}
    oi = pdata.fetch_research_open_interest_history(rest, "DOGE-USDT-SWAP", end_ms=1793840400000)
    assert [r["ts"] for r in oi] == [1793840400000, 1793836800000]
    assert oi[0] == {"ts": 1793840400000, "instrument": "DOGE-USDT-SWAP", "period": "1H", "oi": pytest.approx(1234581.46),
                     "oi_ccy": pytest.approx(1234581459.9999999), "oi_usd": pytest.approx(95198576.3806)}
    # The same shape as the app's parsers give for BTC/ETH, so the fleet lake stores them in the same files and schema.
    assert set(funding[0]) == set(app_derivatives.parse_funding_rows(SOL_FUNDING_ROWS, "SOL-USDT-SWAP")[0])
    assert set(oi[0]) == {f.name for f in app_derivatives.SCHEMAS["open_interest"]}
    assert [urlsplit(c["url"]).path for c in session.calls] == [app_derivatives.FUNDING_PATH, app_derivatives.OPEN_INTEREST_PATH]
    for call in session.calls:
        parts = urlsplit(call["url"])
        assert parts.scheme == "https" and parts.hostname == "www.okx.com"
        assert "headers" not in call["kwargs"] and not any("key" in k.lower() or "sign" in k.lower() for k in call["params"])
    assert session.calls[0]["params"] == {"instId": "SOL-USDT-SWAP", "limit": "100", "after": "1793836800001"}
    assert session.calls[1]["params"] == {"instId": "DOGE-USDT-SWAP", "period": "1H", "end": "1793840400000", "limit": "100"}


def test_a_foreign_instrument_in_a_reply_is_dropped_and_the_app_bound_is_untouched():
    class Mixed(RecordedSession):
        def get(self, url, params=None, timeout=None, **kwargs):
            resp = super().get(url, params, timeout, **kwargs)
            if urlsplit(url).path == app_derivatives.FUNDING_PATH:
                resp._payload["data"] = resp._payload["data"] + [dict(SOL_FUNDING_ROWS[0], instId="BTC-USDT-SWAP")]
            return resp

    rest = OKXPublicRest(session=Mixed(), sleep=lambda s: None)
    rows = pdata.fetch_research_funding_history(rest, "SOL-USDT-SWAP")
    assert all(r["instrument"] == "SOL-USDT-SWAP" for r in rows) and len(rows) == 2
    # The app's collector still refuses the research swaps: the fix lives beside it, not in it.
    assert app_derivatives.SWAP_INSTRUMENTS == ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    with pytest.raises(ValueError, match="not allowed"):
        app_derivatives.fetch_funding_rate_history(rest, "SOL-USDT-SWAP")
    with pytest.raises(ValueError, match="not allowed"):
        app_derivatives.fetch_open_interest_history(rest, "DOGE-USDT-SWAP")
