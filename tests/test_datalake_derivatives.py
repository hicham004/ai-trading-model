"""Public derivatives collectors: path allowlist, parsers, pagination semantics, backfill."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.datalake import derivatives as d
from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError, assert_public_path
from app.datalake.parquet_store import coverage

# Fixtures copied from live public responses (2026-10-20).
FUNDING_ROWS = [
    {"formulaType": "withRate", "fundingRate": "0.0000519278180174", "fundingTime": "1792483200000",
     "instId": "BTC-USDT-SWAP", "instType": "SWAP", "method": "current_period", "realizedRate": "0.0000519278180174"},
    {"formulaType": "withRate", "fundingRate": "0.0000821037876006", "fundingTime": "1792454400000",
     "instId": "BTC-USDT-SWAP", "instType": "SWAP", "method": "current_period", "realizedRate": ""},
]
OI_ROWS = [["1792486800000", "3050408.3200000121", "30504.083200000121", "2482870700.8390498487587"],
           ["1792483200000", "3039968.70000001106", "30399.6870000001106", "2476966496.760009011688"]]
LS_ROWS = [["1792486800000", "1.749814710503691"], ["1792483200000", "1.748171058109796"]]
TV_ROWS = [["1792486800000", "53792.550000000000756", "35645.509999999999659"],
           ["1792483200000", "116903.93999999999552", "151994.07999999999995"]]


def test_public_path_allowlist():
    assert_public_path("/api/v5/public/funding-rate-history")
    assert_public_path("/api/v5/rubik/stat/contracts/open-interest-history")
    assert_public_path("/api/v5/market/history-candles")
    assert_public_path("/api/v5/rubik/stat/contracts/long-short-account-ratio-contract")  # "account" inside a segment is fine
    for bad in ("/api/v5/account/balance", "/api/v5/trade/order", "/api/v5/asset/withdrawal",
                "/api/v5/public/../account/balance", "/api/v5/users/subaccount/list", "/api/v5/public/time?x=1"):
        with pytest.raises(ValueError):
            assert_public_path(bad)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_rest_client_envelope_retry_and_errors():
    import requests

    session = FakeSession([
        FakeResponse(None, status=429),
        requests.ConnectionError("boom"),
        FakeResponse({"code": "0", "msg": "", "data": [{"x": 1}]}),
    ])
    slept = []
    rest = OKXPublicRest(session=session, sleep=slept.append, max_retries=3)
    assert rest.get("/api/v5/public/time", {"a": None, "b": 2}) == [{"x": 1}]
    assert session.calls[-1] == ("https://www.okx.com/api/v5/public/time", {"b": "2"})
    assert slept == [1.0, 2.0]

    rest = OKXPublicRest(session=FakeSession([FakeResponse({"code": "51001", "msg": "bad", "data": []})]), sleep=lambda s: None)
    with pytest.raises(PublicRestError):
        rest.get("/api/v5/public/time")
    rest = OKXPublicRest(session=FakeSession([FakeResponse({"code": "0", "data": "nope"})]), sleep=lambda s: None)
    with pytest.raises(PublicRestError):
        rest.get("/api/v5/public/time")
    with pytest.raises(ValueError):
        OKXPublicRest(base_url="https://evil.example")


def test_parsers_match_live_formats():
    f = d.parse_funding_rows(FUNDING_ROWS, "BTC-USDT-SWAP")
    assert f[0]["ts"] == 1792483200000 and f[0]["funding_rate"] == pytest.approx(5.19278180174e-05)
    assert f[0]["period"] == "8H" and f[0]["method"] == "current_period"
    assert f[1]["realized_rate"] != f[1]["realized_rate"]  # NaN for a blank realizedRate
    oi = d.parse_open_interest_rows(OI_ROWS, "BTC-USDT-SWAP", "1H")
    assert oi[0]["oi_usd"] == pytest.approx(2482870700.839)
    ls = d.parse_long_short_rows(LS_ROWS, "BTC-USDT-SWAP", "1H")
    assert ls[1]["ratio"] == pytest.approx(1.748171058109796)
    tv = d.parse_taker_volume_rows(TV_ROWS, "BTC-USDT-SWAP", "1H")
    assert tv[0]["sell_vol"] == pytest.approx(53792.55) and tv[0]["buy_vol"] == pytest.approx(35645.51)
    for kind, rows in (("funding_rate", f), ("open_interest", oi), ("long_short_ratio", ls), ("taker_volume", tv)):
        table = d.records_to_table(kind, rows)
        assert table.schema.equals(d.SCHEMAS[kind]) and table.num_rows == 2


def test_parsers_reject_malformed_rows_and_foreign_instruments():
    with pytest.raises(PublicRestError):
        d.parse_open_interest_rows([["1792486800000", "1"]], "BTC-USDT-SWAP", "1H")
    with pytest.raises(PublicRestError):
        d.parse_taker_volume_rows([["x", "1", "2"]], "BTC-USDT-SWAP", "1H")
    with pytest.raises(PublicRestError):
        d.parse_funding_rows([{"fundingTime": "1", "fundingRate": "nan"}], "BTC-USDT-SWAP")
    rows = [dict(FUNDING_ROWS[0], instId="ETH-USDT-SWAP")]
    assert d.parse_funding_rows(rows, "BTC-USDT-SWAP") == []


class RecordingRest:
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.data


def test_fetchers_send_the_documented_parameters():
    rest = RecordingRest(OI_ROWS)
    d.fetch_open_interest_history(rest, "BTC-USDT-SWAP", "1H", end_ms=123, limit=50)
    assert rest.calls[-1] == (d.OPEN_INTEREST_PATH, {"instId": "BTC-USDT-SWAP", "period": "1H", "end": 123, "limit": 50})
    rest = RecordingRest(FUNDING_ROWS)
    d.fetch_funding_rate_history(rest, "BTC-USDT-SWAP", after_ms=999)
    assert rest.calls[-1] == (d.FUNDING_PATH, {"instId": "BTC-USDT-SWAP", "limit": 100, "after": 999})
    with pytest.raises(ValueError):
        d.fetch_taker_volume(rest, "SOL-USDT-SWAP", "1H")
    with pytest.raises(ValueError):
        d.fetch_long_short_ratio(rest, "BTC-USDT-SWAP", "2H")


class PagedRest:
    """Serves hourly rows for ``kind``; ``end`` is inclusive like the rubik endpoints."""

    HOUR = 3_600_000

    def __init__(self, first_ms, last_ms):
        self.first, self.last = first_ms, last_ms
        self.calls = []

    def get(self, path, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        limit = int(params.get("limit", 100))
        if path == d.FUNDING_PATH:
            upper = self.last if params.get("after") is None else int(params["after"]) - self.HOUR
            return [{"instId": "BTC-USDT-SWAP", "fundingTime": str(ts), "fundingRate": "0.0001", "realizedRate": "0.0001",
                     "method": "current_period", "formulaType": "withRate"}
                    for ts in self._span(upper, limit)]
        upper = self.last if params.get("end") is None else min(self.last, int(params["end"]))
        upper -= upper % self.HOUR
        return [[str(ts), "1", "2", "3"] for ts in self._span(upper, limit)]

    def _span(self, upper, limit):
        out, ts = [], upper
        while ts >= self.first and len(out) < limit:
            out.append(ts)
            ts -= self.HOUR
        return out


def test_series_backfill_is_resumable_and_exclusive_on_the_cursor(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    first = 1_700_000_000_000 - (1_700_000_000_000 % 3_600_000)
    rest = PagedRest(first, first + 349 * 3_600_000)
    start = datetime.fromtimestamp(first / 1000, tz=timezone.utc)
    report = d.backfill_series(rest, layout, "open_interest", "BTC-USDT-SWAP", period="1H", start=start, sleep_seconds=0)
    assert report.walk.complete and report.stored_rows == 350 and report.added == 350
    # Every cursor step asks for strictly older rows (end = cursor - 1 ms).
    ends = [p["end"] for _, p in rest.calls if p.get("end") is not None]
    assert ends and all((e + 1) % 3_600_000 == 0 for e in ends)
    assert coverage(layout.series_dir("open_interest", "BTC-USDT-SWAP", "1H"), "ts").rows == 350
    again = d.backfill_series(rest, layout, "open_interest", "BTC-USDT-SWAP", period="1H", start=start, sleep_seconds=0)
    assert again.added == 0 and again.walk.pages == 1
    assert "open_interest BTC-USDT-SWAP 1H" in again.summary()


def test_funding_backfill_uses_after_and_fixed_period(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    first = 1_700_000_000_000 - (1_700_000_000_000 % 3_600_000)
    rest = PagedRest(first, first + 149 * 3_600_000)
    start = datetime.fromtimestamp(first / 1000, tz=timezone.utc)
    report = d.backfill_series(rest, layout, "funding_rate", "BTC-USDT-SWAP", period="1H", start=start, sleep_seconds=0)
    assert report.period == "8H" and report.stored_rows == 150
    assert all("after" in p or p.get("after") is None for path, p in rest.calls if path == d.FUNDING_PATH)
    assert (layout.series_dir("funding_rate", "BTC-USDT-SWAP", "8H")).exists()
    with pytest.raises(ValueError):
        d.backfill_series(rest, layout, "nope", "BTC-USDT-SWAP")
    with pytest.raises(ValueError):
        d.backfill_series(rest, layout, "taker_volume", "BTC-USDT-SWAP", period="2H")
