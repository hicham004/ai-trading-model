"""Tests for the public OKX market-data client (fully offline)."""

from __future__ import annotations

import pytest
import requests

from app.config import Settings
from app.okx.client import OKXClientError, OKXPublicClient
from tests.conftest import make_candle_row


class FakeResponse:
    """Stand-in for a ``requests.Response``."""

    def __init__(self, json_data, status_code=200, raise_exc=None):
        self._json = json_data
        self.status_code = status_code
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._json


class FakeSession:
    """Records calls and returns queued responses (or raises queued errors)."""

    def __init__(self, responses):
        # ``responses`` is a list of FakeResponse or Exception instances.
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings(**overrides) -> Settings:
    base = dict(okx_max_retries=3, okx_request_timeout=1.0, okx_base_url="https://x")
    base.update(overrides)
    # Settings is a frozen dataclass; build via constructor with kwargs.
    return Settings(**base)


def test_get_candles_parses_and_sorts_oldest_first():
    payload = {
        "code": "0",
        "msg": "",
        # OKX returns newest-first; client must sort oldest-first.
        "data": [
            make_candle_row(2_000_000, close="200"),
            make_candle_row(1_000_000, close="100"),
        ],
    }
    session = FakeSession([FakeResponse(payload)])
    client = OKXPublicClient(settings=_settings(), session=session)

    candles = client.get_candles("BTC-USDT", timeframe="1H", limit=2)

    assert len(candles) == 2
    assert candles[0].close == 100.0
    assert candles[1].close == 200.0
    # Timestamps are timezone-aware UTC.
    assert candles[0].timestamp.tzinfo is not None
    assert candles[0].timestamp < candles[1].timestamp
    # Request used the public candles path with the right params.
    assert session.calls[0]["params"] == {
        "instId": "BTC-USDT",
        "bar": "1H",
        "limit": "2",
    }


def test_confirmed_only_filters_unconfirmed_candle():
    payload = {
        "code": "0",
        "data": [
            make_candle_row(2_000_000, confirm="0"),  # still forming
            make_candle_row(1_000_000, confirm="1"),
        ],
    }
    session = FakeSession([FakeResponse(payload)])
    client = OKXPublicClient(settings=_settings(), session=session)

    candles = client.get_candles("BTC-USDT", confirmed_only=True)
    assert len(candles) == 1
    assert candles[0].confirmed is True


def test_disallowed_instrument_raises_value_error():
    client = OKXPublicClient(settings=_settings(), session=FakeSession([]))
    with pytest.raises(ValueError):
        client.get_candles("DOGE-USDT")


def test_invalid_limit_raises_value_error():
    client = OKXPublicClient(settings=_settings(), session=FakeSession([]))
    with pytest.raises(ValueError):
        client.get_candles("BTC-USDT", limit=999)


def test_api_error_code_raises():
    payload = {"code": "50011", "msg": "rate limited", "data": []}
    session = FakeSession([FakeResponse(payload)])
    client = OKXPublicClient(settings=_settings(), session=session)
    with pytest.raises(OKXClientError):
        client.get_candles("BTC-USDT")


def test_malformed_row_raises():
    payload = {"code": "0", "data": [["only", "three", "cols"]]}
    session = FakeSession([FakeResponse(payload)])
    client = OKXPublicClient(settings=_settings(), session=session)
    with pytest.raises(OKXClientError):
        client.get_candles("BTC-USDT")


def test_network_failure_retries_then_raises(monkeypatch):
    # Avoid real backoff sleeps so the test stays fast.
    monkeypatch.setattr("app.okx.client.time.sleep", lambda _s: None)
    # Every attempt raises a connection error; after max retries we give up.
    errors = [requests.ConnectionError("boom")] * 3
    session = FakeSession(errors)
    client = OKXPublicClient(settings=_settings(okx_max_retries=3), session=session)

    with pytest.raises(OKXClientError):
        client.get_candles("BTC-USDT")
    assert len(session.calls) == 3  # retried the configured number of times


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr("app.okx.client.time.sleep", lambda _s: None)
    good = {"code": "0", "data": [make_candle_row(1_000_000)]}
    session = FakeSession([requests.Timeout("slow"), FakeResponse(good)])
    client = OKXPublicClient(settings=_settings(okx_max_retries=3), session=session)

    candles = client.get_candles("BTC-USDT")
    assert len(candles) == 1
    assert len(session.calls) == 2  # failed once, succeeded on the second try
