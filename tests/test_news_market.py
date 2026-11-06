"""Public OKX market data for the news shadow: pinned host and paths, no credentials, closed candles only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.news.market import (
    CANDLES_PATH,
    OKX_PUBLIC_REST,
    TIME_PATH,
    MarketDataError,
    PublicMarketData,
    _check_url,
    parse_candles,
    parse_server_time,
)

T0 = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def _row(t: datetime, close: float, *, confirm: str = "1", volume: float = 10.0) -> list:
    ms = str(int(t.timestamp() * 1000))
    return [ms, f"{close - 5}", f"{close + 10}", f"{close - 10}", f"{close}", f"{volume}", "1", "1", confirm]


def _reply(rows) -> str:
    return json.dumps({"code": "0", "msg": "", "data": rows})


def test_parse_candles_keeps_only_confirmed_rows_oldest_first():
    rows = [
        _row(T0 + timedelta(minutes=10), 102, confirm="0"),  # the forming candle (newest first, as OKX sends)
        _row(T0 + timedelta(minutes=5), 101),
        _row(T0, 100),
    ]
    candles = parse_candles(_reply(rows), "5m")
    assert [c.open_time for c in candles] == [T0, T0 + timedelta(minutes=5)]
    assert candles[0].interval == timedelta(minutes=5) and candles[1].close == 101.0
    assert candles[-1].close_time == T0 + timedelta(minutes=10)


def test_parse_candles_skips_malformed_rows_and_rejects_error_replies():
    rows = [
        ["not-a-time", "1", "2", "0.5", "1", "1", "1", "1", "1"],
        [str(int(T0.timestamp() * 1000)), "nan", "2", "0.5", "1", "1", "1", "1", "1"],
        [str(int(T0.timestamp() * 1000)), "1", "0.5", "2", "1", "1", "1", "1", "1"],  # high below low
        ["1"],
        _row(T0, 100),
    ]
    assert len(parse_candles(_reply(rows), "5m")) == 1
    with pytest.raises(MarketDataError):
        parse_candles(json.dumps({"code": "51001", "msg": "bad instrument", "data": []}), "5m")
    with pytest.raises(MarketDataError):
        parse_candles("<html>", "5m")
    with pytest.raises(ValueError):
        parse_candles(_reply([]), "7m")


def test_parse_server_time():
    ms = int(T0.timestamp() * 1000)
    assert parse_server_time(json.dumps({"code": "0", "data": [{"ts": str(ms)}]})) == T0
    with pytest.raises(MarketDataError):
        parse_server_time(json.dumps({"code": "0", "data": []}))


def test_only_the_two_public_paths_on_the_pinned_host_can_be_requested():
    assert _check_url(OKX_PUBLIC_REST + CANDLES_PATH)
    assert _check_url(OKX_PUBLIC_REST + TIME_PATH)
    for url in (
        "http://www.okx.com/api/v5/market/candles",  # not https
        "https://evil.example/api/v5/market/candles",  # another host
        "https://www.okx.com/api/v5/market/books",  # another path
        "https://www.okx.com" + "/api/v5/" + "account/balance",  # never an account path
    ):
        with pytest.raises(ValueError):
            _check_url(url)


class FakeHttp:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, params, json_body, headers):
        self.calls.append((method, url, dict(params or {}), json_body, dict(headers)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_requests_are_plain_public_gets_with_no_credentials():
    http = FakeHttp([(200, _reply([_row(T0, 100)])), (200, _reply([_row(T0, 3000)]))])
    market = PublicMarketData(http)
    results = market.refresh()
    assert [r.ok for r in results] == [True, True]
    for method, url, params, body, headers in http.calls:
        assert method == "GET" and url == OKX_PUBLIC_REST + CANDLES_PATH and body is None
        assert params["bar"] == "5m" and params["limit"] == "300" and params["instId"] in ("BTC-USDT", "ETH-USDT")
        assert set(headers) == {"User-Agent", "Accept"}  # nothing that could carry a key or a signature


def test_refresh_merges_dedupes_prunes_and_survives_failures():
    first = [_row(T0 + timedelta(minutes=5 * i), 100 + i) for i in range(4)][::-1]
    second = [_row(T0 + timedelta(minutes=5 * i), 100 + i) for i in range(2, 6)][::-1]
    http = FakeHttp([(200, _reply(first)), (200, _reply(second)), (503, ""), (200, "garbage"), RuntimeError("down"), (200, _reply(second))])
    market = PublicMarketData(http, instruments=("BTC-USDT",), limit=4, keep=5)
    assert market.refresh()[0].cached == 4
    second_result = market.refresh()[0]
    assert second_result.ok and second_result.cached == 5  # 6 distinct candles, the oldest pruned
    assert [c.open_time for c in market.candles("BTC-USDT")][0] == T0 + timedelta(minutes=5)
    for _ in range(3):  # HTTP error, unparseable reply, network error: cache unchanged, never raised
        result = market.refresh()[0]
        assert not result.ok and result.cached == 5 and result.error
    assert market.refresh()[0].ok


def test_clock_skew_measures_local_minus_exchange_time_at_the_request_midpoint():
    ms = int(T0.timestamp() * 1000)
    http = FakeHttp([(200, json.dumps({"code": "0", "data": [{"ts": str(ms)}]})), (500, "")])
    market = PublicMarketData(http)
    ticks = iter([T0 + timedelta(seconds=40), T0 + timedelta(seconds=42)])
    assert market.clock_skew_seconds(lambda: next(ticks)) == pytest.approx(41.0)
    assert market.clock_skew_seconds(lambda: T0) is None  # unmeasurable is None, never an exception


def test_settings_validation():
    with pytest.raises(ValueError):
        PublicMarketData(FakeHttp([]), bar="2m")
    with pytest.raises(ValueError):
        PublicMarketData(FakeHttp([]), limit=301)
    with pytest.raises(ValueError):
        PublicMarketData(FakeHttp([]), limit=100, keep=50)
