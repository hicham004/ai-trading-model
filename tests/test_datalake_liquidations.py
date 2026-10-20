"""Public liquidation feed: subscribe message, parsing/filtering, JSONL sink, collector loop."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.datalake import liquidations as liq
from app.datalake.layout import LakeLayout

PUSH = json.dumps({
    "arg": {"channel": "liquidation-orders", "instType": "SWAP"},
    "data": [
        {"instId": "BTC-USDT-SWAP", "instType": "SWAP", "uly": "BTC-USDT", "instFamily": "BTC-USDT",
         "details": [
             {"bkLoss": "0", "bkPx": "81234.5", "ccy": "", "posSide": "long", "side": "sell", "sz": "12", "ts": "1792488600123"},
             {"bkLoss": "1.5", "bkPx": "81300", "ccy": "", "posSide": "short", "side": "buy", "sz": "3", "ts": "1792488601000"},
         ]},
        {"instId": "SOL-USDT-SWAP", "instType": "SWAP", "uly": "SOL-USDT",
         "details": [{"bkPx": "150", "posSide": "long", "side": "sell", "sz": "1", "ts": "1792488602000"}]},
    ],
})


def test_subscribe_message_targets_swap_liquidations_only():
    msg = json.loads(liq.subscribe_message())
    assert msg == {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]}
    with pytest.raises(ValueError):
        liq.subscribe_message("FUTURES")
    assert liq.PUBLIC_WS_URL == "wss://ws.okx.com/ws/v5/public"  # no :8443


def test_parse_flattens_details_and_filters_instruments():
    observed = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    records = liq.parse_liquidation_message(PUSH, observed_at=observed)
    assert len(records) == 2 and {r["instrument"] for r in records} == {"BTC-USDT-SWAP"}
    r = records[0]
    assert r["ts_ms"] == 1792488600123 and r["side"] == "sell" and r["pos_side"] == "long"
    assert r["bankruptcy_px"] == 81234.5 and r["size"] == 12.0 and r["bankruptcy_loss"] == 0.0
    assert r["observed_at"].startswith("2026-10-20T12:00:00")
    assert r["time"].startswith("2026-10-20T")
    assert liq.parse_liquidation_message(PUSH, instruments=("ETH-USDT-SWAP",)) == []


@pytest.mark.parametrize("raw", [
    "pong", "not json", json.dumps({"event": "subscribe", "arg": {"channel": "liquidation-orders"}}),
    json.dumps({"arg": {"channel": "tickers"}, "data": [{"instId": "BTC-USDT-SWAP"}]}),
    json.dumps({"arg": {"channel": "liquidation-orders"}, "data": [{"instId": "BTC-USDT-SWAP", "details": [{"ts": "x"}]}]}),
])
def test_parse_ignores_non_data_messages(raw):
    assert liq.parse_liquidation_message(raw) == []


def test_jsonl_sink_groups_by_instrument_and_utc_day(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    sink = liq.JsonlSink(layout)
    records = liq.parse_liquidation_message(PUSH)
    records.append(dict(records[0], instrument="ETH-USDT-SWAP", ts_ms=1792488600123 + 86_400_000))
    assert sink.write(records) == 3 and sink.records_written == 3
    btc_day = datetime.fromtimestamp(1792488600123 / 1000, tz=timezone.utc).date()
    btc_file = layout.liquidations_file("BTC-USDT-SWAP", btc_day)
    assert btc_file.exists() and len(btc_file.read_text().splitlines()) == 2
    eth_files = list(layout.liquidations_dir("ETH-USDT-SWAP").glob("*.jsonl"))
    assert len(eth_files) == 1 and eth_files[0].stem == date.fromordinal(btc_day.toordinal() + 1).isoformat()
    assert json.loads(btc_file.read_text().splitlines()[0])["instrument"] == "BTC-USDT-SWAP"


class FakeWS:
    def __init__(self, messages):
        self.messages, self.sent = list(messages), []

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.messages:
            return self.messages.pop(0)
        raise ConnectionError("closed by test")


class FakeConnect:
    def __init__(self, ws):
        self.ws, self.urls = ws, []

    def __call__(self, url):
        self.urls.append(url)
        return self

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


def test_collector_subscribes_writes_and_stops_at_deadline(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    sink = liq.JsonlSink(layout)
    ws = FakeWS([json.dumps({"event": "subscribe"}), PUSH, "pong"])
    connect = FakeConnect(ws)
    ticks = iter(range(0, 100_000))
    stats = asyncio.run(
        liq.run_collector(sink, duration_seconds=3, connect=connect, clock=lambda: next(ticks) / 10, max_backoff=0.01)
    )
    assert connect.urls[0] == liq.PUBLIC_WS_URL and len(set(connect.urls)) == 1
    assert json.loads(ws.sent[0])["op"] == "subscribe"
    assert stats.connects >= 2 and stats.reconnects >= 1  # dropped connection -> reconnect with backoff
    assert stats.messages == 3 and stats.records == 2
    assert sink.records_written == 2
    assert stats.errors >= 1 and "ConnectionError" in stats.last_error


def test_collector_validates_url_and_instruments(tmp_path: Path):
    sink = liq.JsonlSink(LakeLayout(tmp_path))
    with pytest.raises(ValueError):
        asyncio.run(liq.run_collector(sink, duration_seconds=1, url="ws://ws.okx.com/ws/v5/public", connect=FakeConnect(FakeWS([]))))
    with pytest.raises(ValueError):
        asyncio.run(liq.run_collector(sink, duration_seconds=1, url="wss://ws.okx.com/ws/v5/private", connect=FakeConnect(FakeWS([]))))
    with pytest.raises(ValueError):
        asyncio.run(liq.run_collector(sink, duration_seconds=1, instruments=("SOL-USDT-SWAP",), connect=FakeConnect(FakeWS([]))))
