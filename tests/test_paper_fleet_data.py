"""Paper-fleet public data: parsing, GET-only public paths, own lake (research lake read only), bars, gaps, positioning."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from research.paper_fleet.data import (
    CANDLES_PATH,
    HISTORY_CANDLES_PATH,
    FleetLake,
    MarketData,
    OkxPublicFeed,
    frame_until,
    parse_candle_rows,
)
from research.paper_fleet.replay import ReplayFeed, synthetic_market

H = 3_600_000


def _row(ts_ms: int, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0, confirm="1"):
    return [str(ts_ms), str(o), str(h), str(l), str(c), str(v), "0", "0", confirm]


def test_parse_keeps_only_confirmed_well_formed_hourly_candles():
    t0 = 1_760_000_400_000 - (1_760_000_400_000 % H)
    rows = [
        _row(t0 + 2 * H),  # newest first, as OKX sends them
        _row(t0 + 3 * H, confirm="0"),  # the forming candle
        _row(t0 + H, h=98.0),  # high below the low: dropped
        _row(t0 + 30 * 60_000),  # off the hour grid: dropped
        ["bad"],
        _row(t0, o=float("nan")),
        _row(t0 - H, l=-1.0),
        _row(t0 - 2 * H),
    ]
    df = parse_candle_rows(rows, "BTC-USDT")
    assert list(df.index.astype("int64") // 1_000_000) == [t0 - 2 * H, t0 + 2 * H]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RecordingSession:
    """Answers like OKX's public endpoints and records every request."""

    def __init__(self, candles: pd.DataFrame):
        self.calls = []
        self.candles = candles

    def _rows(self, df):
        return [[str(int(ts.value // 1_000_000)), *(str(x) for x in r), "0", "0", "1"] for ts, r in zip(df.index[::-1], df.to_numpy()[::-1])]

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append({"method": "GET", "url": url, "params": dict(params or {}), "kwargs": kwargs})
        path = urlsplit(url).path
        if path == CANDLES_PATH:
            return _Resp({"code": "0", "data": self._rows(self.candles.iloc[-int(params["limit"]):])})
        if path == HISTORY_CANDLES_PATH:
            before = pd.Timestamp(int(params["after"]), unit="ms", tz="UTC")
            older = self.candles[self.candles.index < before].iloc[-int(params["limit"]):]
            return _Resp({"code": "0", "data": self._rows(older)})
        if path.endswith("funding-rate-history"):
            return _Resp({"code": "0", "data": [{"instId": params["instId"], "fundingTime": str(1_760_000_000_000 - k * 8 * H), "fundingRate": "0.0001",
                                                 "realizedRate": "0.0001", "method": "current_period", "formulaType": "noRate"} for k in range(5)]})
        if path.endswith("open-interest-history"):
            return _Resp({"code": "0", "data": [[str(1_760_000_000_000 - k * H), "1", "2", "3000000"] for k in range(5)]})
        raise AssertionError(f"unexpected path {path}")

    def post(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("POST is never allowed")


def _hourly(n=1200, seed=1):
    candles, _, _ = synthetic_market(days=n // 24 + 2, seed=seed)
    return candles["BTC-USDT"].iloc[-n:]


def test_the_feed_only_sends_public_get_requests_without_credentials(tmp_path):
    session = RecordingSession(_hourly())
    feed = OkxPublicFeed(OKXPublicRest(session=session, sleep=lambda s: None), sleep_seconds=0)
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT",), history_days=40, positioning="okx")
    md.bootstrap(pd.Timestamp(session.candles.index[-1]).to_pydatetime())
    assert session.calls
    allowed = {CANDLES_PATH, HISTORY_CANDLES_PATH, "/api/v5/public/funding-rate-history", "/api/v5/rubik/stat/contracts/open-interest-history"}
    for call in session.calls:
        parts = urlsplit(call["url"])
        assert call["method"] == "GET" and parts.scheme == "https" and parts.hostname == "www.okx.com"
        assert parts.path in allowed, parts.path
        assert "headers" not in call["kwargs"] and not any("key" in k.lower() or "sign" in k.lower() for k in call["params"])
    # It walked back to the start of the history window and stored the candles in its own lake.
    have = md.candles("BTC-USDT")
    assert have.index[0] <= session.candles.index[-1] - pd.Timedelta(days=39)
    assert (tmp_path / "lake" / "candles" / "BTC-USDT" / "1H").exists()


class FakeFeed:
    def __init__(self, candles):
        self.inner = ReplayFeed({"BTC-USDT": candles}, {}, {})
        self.requests = 0

    @property
    def now(self):
        return self.inner.now

    @now.setter
    def now(self, value):
        self.inner.now = value

    def newest_candles(self, inst):
        self.requests += 1
        return self.inner.newest_candles(inst)

    def candles_before(self, inst, before_ms):
        self.requests += 1
        return self.inner.candles_before(inst, before_ms)

    def funding_history(self, swap, before_ms=None):
        return []

    def open_interest_history(self, swap, end_ms=None):
        return []


def test_seeding_copies_the_research_lake_without_touching_it(tmp_path):
    candles = _hourly(2000)
    seed_root = tmp_path / "research_lake"
    FleetLake(seed_root).write_candles("BTC-USDT", candles.iloc[:1500])
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in seed_root.rglob("*.parquet")}
    feed = FakeFeed(candles)
    feed.now = candles.index[-1] + pd.Timedelta(hours=1)
    md = MarketData(FleetLake(tmp_path / "fleet" / "lake"), feed, instruments=("BTC-USDT",), history_days=60, positioning="none")
    report = md.bootstrap(feed.now.to_pydatetime(), seed=LakeLayout(seed_root))
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in seed_root.rglob("*.parquet")}
    assert before == after  # the research lake is only read
    assert any("seeded" in k for k in report.candles_added)
    have = md.candles("BTC-USDT")
    assert have.index[-1] == candles.index[-1] and have.index.is_unique and have.index.is_monotonic_increasing
    expected = candles[candles.index >= feed.now - pd.Timedelta(days=60)]
    pd.testing.assert_frame_equal(have[have.index >= expected.index[0]], expected, check_freq=False, check_names=False)


def test_refresh_adds_closed_candles_only_and_bars_are_complete_utc_bars(tmp_path):
    candles = _hourly(1500)
    feed = FakeFeed(candles)
    cut = candles.index[-200]
    feed.now = cut + pd.Timedelta(minutes=30)  # the candle that opened at `cut` is still forming
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT",), history_days=50, positioning="none")
    md.bootstrap(feed.now.to_pydatetime())
    assert md.last_candle_open("BTC-USDT") == cut - pd.Timedelta(hours=1)
    feed.now = cut + pd.Timedelta(hours=30, minutes=2)
    rep = md.refresh(feed.now.to_pydatetime())
    assert rep.candles_added["BTC-USDT"] == 30 and md.last_candle_open("BTC-USDT") == cut + pd.Timedelta(hours=29)  # cut .. cut+29h
    for tf, hours in (("4H", 4), ("6H", 6)):
        bars = md.bars("BTC-USDT", tf)
        assert all(ts.hour % hours == 0 for ts in bars.index)
        assert (bars.index + pd.Timedelta(hours=hours) <= feed.now).all()  # never a forming bar
        last = bars.index[-1]
        src = md.candles("BTC-USDT")
        part = src[(src.index >= last) & (src.index < last + pd.Timedelta(hours=hours))]
        assert len(part) == hours and bars.loc[last, "high"] == part["high"].max() and bars.loc[last, "open"] == part["open"].iloc[0]


def test_a_missing_hour_removes_its_bar_and_a_long_gap_is_filled_backwards(tmp_path):
    candles = _hourly(1500)
    hole = candles.index[-50]
    feed = FakeFeed(candles.drop(index=[hole]))
    feed.now = candles.index[-1] + pd.Timedelta(hours=1)
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT",), history_days=55, positioning="none")
    md.bootstrap(feed.now.to_pydatetime())
    bars = md.bars("BTC-USDT", "4H")
    assert hole.floor("4h") not in bars.index  # an incomplete bar is never built
    # Downtime longer than the newest page (300 candles): the refresh pages back to the stored history.
    feed2 = FakeFeed(candles)
    feed2.now = candles.index[-700]
    md2 = MarketData(FleetLake(tmp_path / "lake2"), feed2, instruments=("BTC-USDT",), history_days=55, positioning="none")
    md2.bootstrap(feed2.now.to_pydatetime())
    feed2.now = candles.index[-1] + pd.Timedelta(hours=1)
    md2.refresh(feed2.now.to_pydatetime())
    got = md2.candles("BTC-USDT")
    assert got.index[-1] == candles.index[-1]
    assert not got.index.to_series().diff().dropna().gt(pd.Timedelta(hours=1)).any()


def test_positioning_is_stored_and_exposed_as_of_time(tmp_path):
    candles, funding, oi = synthetic_market(days=80)
    feed = ReplayFeed(candles, funding, oi)
    feed.now = candles["BTC-USDT"].index[-1]
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT", "ETH-USDT"), history_days=60, positioning="okx")
    md.bootstrap(feed.now.to_pydatetime())
    ctx = md.context("BTC-USDT", "4H")
    assert ctx.funding is not None and len(ctx.funding) > 100 and ctx.open_interest is not None
    assert ctx.funding.index.max() <= feed.now and ctx.open_interest.index.max() <= feed.now
    ages = md.positioning_age("BTC-USDT", feed.now)
    assert 0 <= ages["funding"] <= 8 and 0 <= ages["open_interest"] <= 1
    off = MarketData(FleetLake(tmp_path / "lake_none"), feed, instruments=("BTC-USDT",), history_days=60, positioning="none")
    off.bootstrap(feed.now.to_pydatetime())
    ctx_off = off.context("BTC-USDT", "4H")
    assert ctx_off.funding is None and ctx_off.open_interest is None
    with pytest.raises(ValueError):
        MarketData(FleetLake(tmp_path / "x"), feed, instruments=("BTC-USDT",), history_days=60, positioning="binance")


def test_frame_until_never_includes_a_later_bar():
    idx = pd.date_range("2026-01-01", periods=10, freq="4h", tz="UTC")
    df = pd.DataFrame({"close": np.arange(10.0)}, index=idx)
    assert frame_until(df, idx[3]).index[-1] == idx[3]
    assert len(frame_until(df, idx[3] - pd.Timedelta(minutes=1))) == 3
