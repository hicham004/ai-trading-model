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


# -- plan row R17: positioning data for the replication markets, and the "S5 running without data" label ---------------------


def test_a_research_market_gets_its_positioning_data_through_the_research_feed_and_the_error_line_is_gone(tmp_path, monkeypatch):
    """Before R17 the fleet asked the app's BTC/ETH-only collector for SOL-USDT-SWAP and logged ``not allowed`` at every refresh; now the
    Sprint 2c pair keeps the app path and every other fleet market goes through the research-side feed (recorded responses)."""
    from app.datalake.derivatives import SWAP_INSTRUMENTS
    from research.paper_fleet import data as data_mod

    seen_app, seen_research = [], []
    real_app_f, real_app_o = data_mod.fetch_funding_rate_history, data_mod.fetch_open_interest_history
    real_res_f, real_res_o = data_mod.fetch_research_funding_history, data_mod.fetch_research_open_interest_history
    monkeypatch.setattr(data_mod, "fetch_funding_rate_history", lambda rest, swap, **kw: (seen_app.append(swap), real_app_f(rest, swap, **kw))[1])
    monkeypatch.setattr(data_mod, "fetch_open_interest_history",
                        lambda rest, swap, period, **kw: (seen_app.append(swap), real_app_o(rest, swap, period, **kw))[1])
    monkeypatch.setattr(data_mod, "fetch_research_funding_history",
                        lambda rest, swap, **kw: (seen_research.append(swap), real_res_f(rest, swap, **kw))[1])
    monkeypatch.setattr(data_mod, "fetch_research_open_interest_history",
                        lambda rest, swap, period, **kw: (seen_research.append(swap), real_res_o(rest, swap, period, **kw))[1])
    session = RecordingSession(_hourly())  # answers the funding / open-interest paths for any instId
    feed = OkxPublicFeed(OKXPublicRest(session=session, sleep=lambda s: None), sleep_seconds=0)
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT", "SOL-USDT"), history_days=40, positioning="okx")
    report = md.bootstrap(pd.Timestamp(session.candles.index[-1]).to_pydatetime())
    assert report.errors == []  # no "positioning SOL-USDT-SWAP: instrument 'SOL-USDT-SWAP' not allowed" line
    assert report.positioning_added["funding SOL-USDT-SWAP"] > 0 and report.positioning_added["open interest SOL-USDT-SWAP"] > 0
    assert report.positioning_added["funding BTC-USDT-SWAP"] > 0 and report.positioning_added["open interest BTC-USDT-SWAP"] > 0
    assert set(seen_app) == {"BTC-USDT-SWAP"} <= set(SWAP_INSTRUMENTS) and set(seen_research) == {"SOL-USDT-SWAP"}  # SOL never touches the app path
    assert (tmp_path / "lake" / "derivatives" / "funding_rate" / "SOL-USDT-SWAP" / "8H").exists()
    assert (tmp_path / "lake" / "derivatives" / "open_interest" / "SOL-USDT-SWAP" / "1H").exists()
    ctx = md.context("SOL-USDT", "6H")
    assert ctx.funding is not None and len(ctx.funding) == 5 and ctx.open_interest is not None and len(ctx.open_interest) == 5
    positioning_paths = {"/api/v5/public/funding-rate-history", "/api/v5/rubik/stat/contracts/open-interest-history"}
    sol = [c for c in session.calls if c["params"].get("instId") == "SOL-USDT-SWAP"]
    assert sol and {urlsplit(c["url"]).path for c in sol} == positioning_paths
    for call in session.calls:
        assert call["method"] == "GET" and urlsplit(call["url"]).path in positioning_paths | {CANDLES_PATH, HISTORY_CANDLES_PATH}
        assert "headers" not in call["kwargs"]
    newest = md.positioning_newest()
    assert newest["source"] == "okx" and newest["last_errors"] == [] and newest["last_refresh"] is not None
    stamp = pd.Timestamp(1_760_000_000_000, unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    assert newest["markets"]["SOL-USDT"] == {"swap": "SOL-USDT-SWAP", "funding_newest": stamp, "open_interest_newest": stamp}
    # A later refresh keeps going without the series when the research feed refuses or fails: logged, never fatal.
    from research.positioning_data import PositioningDataError

    monkeypatch.setattr(data_mod, "fetch_research_funding_history", lambda rest, swap, **kw: (_ for _ in ()).throw(PositioningDataError("refused")))
    rep2 = md.refresh((pd.Timestamp(session.candles.index[-1]) + pd.Timedelta(hours=1)).to_pydatetime())
    assert rep2.errors == ["positioning SOL-USDT-SWAP: refused"] and md.positioning_newest()["last_errors"] == rep2.errors
    assert "funding BTC-USDT-SWAP" in rep2.positioning_added  # BTC's refresh was not affected


def test_the_positioning_status_label_says_plainly_when_the_s5_filter_runs_without_or_on_stale_data():
    from research.paper_fleet.data import positioning_status

    ok = positioning_status({"funding": 4.0, "open_interest": 0.0})
    assert ok["complete"] and (ok["funding"], ok["open_interest"]) == ("current", "current") and ok["note"] == "S5 data current"
    none = positioning_status({"funding": None, "open_interest": None})
    assert not none["complete"] and (none["funding"], none["open_interest"]) == ("missing", "missing")
    assert none["note"] == "S5 running without data: the filter passes (funding missing, open interest missing)"
    assert positioning_status({})["note"] == none["note"] and positioning_status(None)["note"] == none["note"]
    one = positioning_status({"funding": 2.0, "open_interest": None})
    assert not one["complete"] and one["note"] == "S5 running without open interest data: that leg of the filter passes"
    stale = positioning_status({"funding": 9.0, "open_interest": 0.0})  # funding settles every 8 h, plus the 30-minute refresh window
    assert not stale["complete"] and stale["funding"] == "stale" and stale["open_interest"] == "current"
    assert stale["note"] == "S5 running on stale data: funding 9.0 h old, at most 8.5 h expected (that leg uses the last known value)"
    assert positioning_status({"funding": 8.4, "open_interest": 1.4})["complete"]
    assert positioning_status({"funding": 8.4, "open_interest": 1.6})["open_interest"] == "stale"
    assert positioning_status({"funding": 8.4, "open_interest": 0.0}, refresh_minutes=0)["funding"] == "stale"  # the window is a parameter
    off = positioning_status({"funding": 1.0, "open_interest": 0.0}, source="none")
    assert not off["complete"] and off["note"] == "S5 running without data: the filter passes (positioning source none)"
    both = positioning_status({"funding": None, "open_interest": 5.0})
    assert both["note"] == ("S5 running without funding data: that leg of the filter passes; S5 running on stale data: open interest 5.0 h old, "
                            "at most 1.5 h expected (that leg uses the last known value)")


def test_market_data_labels_each_bar_from_what_it_knew_at_the_bar_open(tmp_path):
    candles, funding, oi = synthetic_market(days=80, instruments=("BTC-USDT", "ETH-USDT", "SOL-USDT"))
    feed = ReplayFeed(candles, {k: v for k, v in funding.items() if k != "SOL-USDT-SWAP"}, {k: v for k, v in oi.items() if k != "SOL-USDT-SWAP"})
    feed.now = candles["BTC-USDT"].index[-1]
    md = MarketData(FleetLake(tmp_path / "lake"), feed, instruments=("BTC-USDT", "SOL-USDT"), history_days=60, positioning="okx")
    md.bootstrap(feed.now.to_pydatetime())
    at = candles["BTC-USDT"].index[-7]
    btc = md.positioning_status("BTC-USDT", at)
    assert btc["complete"] and btc["age_hours"]["open_interest"] == 0.0 and 0.0 <= btc["age_hours"]["funding"] < 8.0
    sol = md.positioning_status("SOL-USDT", at)
    assert not sol["complete"] and sol["age_hours"] == {"funding": None, "open_interest": None}
    assert sol["note"] == "S5 running without data: the filter passes (funding missing, open interest missing)"
    newest = md.positioning_newest()["markets"]
    assert newest["BTC-USDT"]["funding_newest"] is not None
    assert newest["SOL-USDT"] == {"swap": "SOL-USDT-SWAP", "funding_newest": None, "open_interest_newest": None}
    off = MarketData(FleetLake(tmp_path / "lake_none"), feed, instruments=("BTC-USDT",), history_days=60, positioning="none")
    off.bootstrap(feed.now.to_pydatetime())
    assert off.positioning_status("BTC-USDT", at)["note"] == "S5 running without data: the filter passes (positioning source none)"
    assert off.positioning_newest()["markets"]["BTC-USDT"]["funding_newest"] is None
