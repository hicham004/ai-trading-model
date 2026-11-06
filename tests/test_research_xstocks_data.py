"""Plan row R21: the log-only tokenized-stocks collector (universe, parameters, candles, the New York snapshot schedule, books, metrics, CLI)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from research import xstocks_data as xs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "xstocks" / "recorded_2026-11-05.json").read_text(encoding="utf-8"))
HOUR = 3_600_000
DAY = 86_400_000


def _ms(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").value // 1_000_000)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeOkx:
    """The six public endpoints answered from the recorded rows and a synthetic candle history per pair, newest first.

    1H candles start at the first full hour after a pair's recorded ``listTime`` (OKX opened trading one hour after
    listing), 1Dutc candles on the listing day; the candle at the clock's current bar is the forming one.
    """

    def __init__(self, now_fn, *, fail_books=()):
        self.now_fn = now_fn
        self.calls = []
        self.fail_books = set(fail_books)
        self.list_time = {i["instId"]: int(i["listTime"]) for i in FIXTURE["instruments"]}

    def _rows(self, pair: str, bar: str):
        step = HOUR if bar == "1H" else DAY
        lt = self.list_time[pair]
        first = (lt // step + 1) * step if bar == "1H" else (lt // step) * step
        forming = (int(self.now_fn().timestamp() * 1000) // step) * step
        rows = []
        for ts in range(first, forming + step, step):
            px = 100.0 + 10.0 * math.sin(ts / (7 * DAY))
            vol = 10.0 if bar == "1H" else 240.0
            rows.append([str(ts), f"{px:.2f}", f"{px + 1:.2f}", f"{px - 1:.2f}", f"{px + 0.5:.2f}", f"{vol}", f"{vol * px:.4f}", f"{vol * px:.4f}",
                         "0" if ts == forming else "1"])
        rows.reverse()
        return rows

    def get(self, url, params=None, timeout=None, **kwargs):
        params = dict(params or {})
        self.calls.append({"url": url, "params": params, "kwargs": kwargs})
        path = urlsplit(url).path
        if path == xs.INSTRUMENTS_PATH:
            data = FIXTURE["instruments"]
        elif path == xs.TICKERS_PATH:
            data = FIXTURE["tickers"]
        elif path == xs.CANDLES_PATH:
            data = self._rows(params["instId"], params["bar"])[: int(params["limit"])]
        elif path == xs.HISTORY_CANDLES_PATH:
            after = int(params["after"])
            data = [r for r in self._rows(params["instId"], params["bar"]) if int(r[0]) < after][: int(params["limit"])]
        elif path == xs.BOOKS_PATH:
            if params["instId"] in self.fail_books:
                return _Response({"code": "51001", "msg": "Instrument ID does not exist", "data": []})
            data = [dict(FIXTURE["books_XNVDA-USDT_50"])]
        elif path == xs.PRICE_LIMIT_PATH:
            data = [dict(FIXTURE["price_limit_XNVDA-USDT"][0], instId=params["instId"])]
        else:
            raise AssertionError(f"unexpected path {path}")
        return _Response({"code": "0", "msg": "", "data": data})

    def post(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("POST is never allowed")


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _rest(session) -> OKXPublicRest:
    return OKXPublicRest(session=session, sleep=lambda s: None)


def _universe(path: Path, pairs=("XNVDA-USDT", "XQQQ-USDT")) -> dict:
    ranking = [{"rank": i + 1, "instId": p, "quote_volume_24h": 1e6 - i, "chosen": True, "list_time_ms": int(FIXTURE["instruments"][0]["listTime"])}
               for i, p in enumerate(pairs)]
    payload = {"version": 1, "selected_at": "2026-11-05T08:00:00Z", "rule": xs.UNIVERSE_RULE, "size": len(pairs), "pairs": list(pairs),
               "ranking": ranking, "summary": {}}
    xs.write_universe(path, payload)
    return xs.load_universe(path)


def _assert_public_get_only(calls, allowed):
    assert calls
    for call in calls:
        parts = urlsplit(call["url"])
        assert parts.scheme == "https" and parts.hostname == "www.okx.com"
        assert parts.path in allowed, parts.path
        assert "headers" not in call["kwargs"]
        assert not any("key" in k.lower() or "sign" in k.lower() for k in call["params"])


# -- universe ----------------------------------------------------------------------------------------------------

def test_universe_selection_applies_the_fixed_rule_on_recorded_data(tmp_path):
    session = FakeOkx(Clock(_utc("2026-11-05T08:00:00")))
    rest = _rest(session)
    payload = xs.select_universe(rest, now=_utc("2026-11-05T08:00:00"))
    assert payload["size"] == 15 and len(payload["pairs"]) == 15 and payload["selected_at"] == "2026-11-05T08:00:00Z"
    assert payload["pairs"][:3] == ["XCRCL-USDT", "XGOOGL-USDT", "XQQQ-USDT"]
    for excluded in ("XRP-USDT", "XLM-USDT", "XAUT-USDT", "BTC-USDT", "XNVDA-USDC"):
        assert excluded not in payload["pairs"] and all(r["instId"] != excluded for r in payload["ranking"])
    volumes = [r["quote_volume_24h"] for r in payload["ranking"]]
    assert volumes == sorted(volumes, reverse=True) and [r["rank"] for r in payload["ranking"]] == list(range(1, len(volumes) + 1))
    assert [r["instId"] for r in payload["ranking"] if r["chosen"]] == payload["pairs"]
    s = payload["summary"]
    assert s["stock_pairs_usdt_x_live"] == len(payload["ranking"]) >= 15 and s["total_quote_volume_24h"] > 0 and 0 < s["top10_share"] <= 1
    assert s["stock_instruments_spot"] >= s["stock_pairs_usdt_x_live"] and s["tickers_ts"].startswith("2026-11-05")
    _assert_public_get_only(session.calls, {xs.INSTRUMENTS_PATH, xs.TICKERS_PATH})
    path = tmp_path / "universe.json"
    xs.write_universe(path, payload)
    loaded = xs.load_universe(path)
    assert loaded["pairs"] == payload["pairs"] and xs.universe_pairs(loaded) == payload["pairs"]
    with pytest.raises(xs.XStocksDataError, match="chosen once"):
        xs.write_universe(path, payload)
    xs.write_universe(path, payload, force=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pairs"][0] = "XZZZ-USDT"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(xs.XStocksDataError, match="differ"):
        xs.load_universe(path)
    with pytest.raises(xs.XStocksDataError, match="no universe file"):
        xs.load_universe(tmp_path / "missing.json")
    with pytest.raises(xs.XStocksDataError):
        xs.select_universe(rest, size=10_000)


def test_rank_xstocks_filters_by_category_state_and_id_and_breaks_ties_by_id():
    instruments = [
        {"instId": "XAAA-USDT", "instType": "SPOT", "instCategory": "3", "state": "live", "listTime": "1784178000000", "lotSz": "0.00001", "minSz": "0.01"},
        {"instId": "XBBB-USDT", "instType": "SPOT", "instCategory": "3", "state": "live", "listTime": "1784178000000", "lotSz": "0.001", "minSz": "1"},
        {"instId": "XCCC-USDT", "instType": "SPOT", "instCategory": "3", "state": "suspend", "listTime": "1784178000000"},
        {"instId": "XRP-USDT", "instType": "SPOT", "instCategory": "1", "state": "live", "listTime": "1"},
        {"instId": "XAAA-USDC", "instType": "SPOT", "instCategory": "3", "state": "live", "listTime": "1"},
        {"instId": "AAPLX-USDT", "instType": "SPOT", "instCategory": "3", "state": "live", "listTime": "1"},
        {"instId": "XDDD-USDT", "instType": "SPOT", "instCategory": "3", "state": "live", "listTime": "1784178000000"},
    ]
    tickers = [{"instId": "XAAA-USDT", "volCcy24h": "5", "vol24h": "1", "last": "5"}, {"instId": "XBBB-USDT", "volCcy24h": "5", "vol24h": "", "last": ""},
               {"instId": "XRP-USDT", "volCcy24h": "999"}, {"instId": "XCCC-USDT", "volCcy24h": "999"}]
    rows = xs.rank_xstocks(instruments, tickers)
    assert [r["instId"] for r in rows] == ["XAAA-USDT", "XBBB-USDT", "XDDD-USDT"]  # ties by id; no ticker ranks last
    assert rows[0]["rank"] == 1 and rows[2]["quote_volume_24h"] is None and rows[1]["base_volume_24h"] is None
    assert rows[0]["list_time"] == "2026-07-16T05:00:00Z"
    assert xs.is_xstock_row(instruments[0]) and not any(xs.is_xstock_row(i) for i in instruments[2:6])


# -- instrument parameters ---------------------------------------------------------------------------------------

def test_instrument_parameters_are_recorded_once_a_day_as_okx_gives_them(tmp_path):
    layout = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake"))
    assert layout.root == tmp_path / "lake" / "xstocks"
    session = FakeOkx(Clock(_utc("2026-11-05T08:00:00")))
    now = _utc("2026-11-05T08:00:00")
    rec = xs.record_instruments(layout, _rest(session), ["XNVDA-USDT", "XAMC-USDT", "XNONE-USDT"], now=now)
    assert rec["day"] == "2026-11-05" and rec["missing"] == ["XNONE-USDT"] and rec["not_live"] == []
    nvda = rec["pairs"]["XNVDA-USDT"]
    assert nvda["lotSz"] == "0.00001" and nvda["minSz"] == "0.01" and nvda["tickSz"] == "0.01" and nvda["initPxLmtPct"] == "0.02"
    assert nvda["floatPxLmtPct"] == "0.01" and nvda["maxPxLmtPct"] == "0.02" and nvda["groupId"] == "12" and nvda["instCategory"] == "3"
    assert nvda["listTime"] == "1784178000000" and nvda["listTime_iso"] == "2026-07-16T05:00:00Z" and nvda["contTdSwTime_iso"] == "2026-07-16T06:00:00Z"
    assert nvda["openType"] == "pre_quote" and nvda["state"] == "live" and isinstance(nvda["upcChg"], list)
    assert rec["pairs"]["XAMC-USDT"]["lotSz"] == "0.001" and rec["pairs"]["XAMC-USDT"]["minSz"] == "1"
    assert layout.instruments_file(date(2026, 11, 5)).exists() and layout.instruments_latest.exists()
    assert xs.instruments_recorded_on(layout, date(2026, 11, 5)) and not xs.instruments_recorded_on(layout, date(2026, 11, 6))
    assert xs.list_times(layout) == {"XNVDA-USDT": 1784178000000, "XAMC-USDT": int(rec["pairs"]["XAMC-USDT"]["listTime"])}
    assert xs.latest_instruments(layout)["recorded_at"] == "2026-11-05T08:00:00Z"
    _assert_public_get_only(session.calls, {xs.INSTRUMENTS_PATH})


# -- candles -----------------------------------------------------------------------------------------------------

def test_candle_rows_parse_on_their_own_grid_and_keep_the_quote_volume():
    rows_1h = xs.parse_xstock_candle_rows(FIXTURE["candles_1H_XNVDA-USDT"], "1H")
    raw = FIXTURE["candles_1H_XNVDA-USDT"]
    assert raw[0][8] == "0" and len(rows_1h) == len(raw) - 1  # the forming candle is dropped
    assert [ms for ms, _ in rows_1h] == sorted(int(r[0]) for r in raw[1:])
    first = dict(rows_1h[-1][1])
    newest = raw[1]
    assert first == {"open": float(newest[1]), "high": float(newest[2]), "low": float(newest[3]), "close": float(newest[4]), "volume": float(newest[5]),
                     "quote_volume": float(newest[6])}
    rows_1d = xs.parse_xstock_candle_rows(FIXTURE["candles_1Dutc_XNVDA-USDT"], "1Dutc")
    assert all(ms % DAY == 0 for ms, _ in rows_1d) and len(rows_1d) == 2
    # a 1D (16:00 UTC) candle is off the 1Dutc grid; malformed, negative and incoherent rows are dropped
    bad = [["1793808000000", "1", "2", "0.5", "1.5", "1", "1", "1", "1"], ["x", "1", "2", "0.5", "1.5", "1", "1", "1", "1"],
           ["1793836800000", "1", "0.5", "0.5", "1.5", "1", "1", "1", "1"], ["1793836800000", "1", "2", "0.5", "1.5", "-1", "1", "1", "1"], "nope"]
    assert xs.parse_xstock_candle_rows(bad, "1Dutc") == []
    with pytest.raises(xs.XStocksDataError):
        xs.parse_xstock_candle_rows([], "1D")


def test_candle_collector_walks_back_to_listing_resumes_and_reads_back(tmp_path):
    layout = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake"))
    clock = Clock(_utc("2026-07-30T10:20:00"))
    session = FakeOkx(clock)
    rest = _rest(session)
    lt = session.list_time["XNVDA-USDT"]
    rep = xs.collect_candles(layout, "XNVDA-USDT", "1H", rest=rest, start_ms=lt, sleep_seconds=0.0)
    expected = (_ms("2026-07-30T10:00:00") - (lt // HOUR + 1) * HOUR) // HOUR  # confirmed hours between the first candle and the forming one
    assert rep.added == expected == rep.stored_rows and rep.walk.complete and rep.walk.exhausted and rep.walk.reason == "exhausted"
    assert rep.stored_min == datetime(2026, 7, 16, 6, tzinfo=timezone.utc) and rep.stored_max == datetime(2026, 7, 30, 9, tzinfo=timezone.utc)
    assert layout.candle_state_file("XNVDA-USDT", "1H").exists() and layout.candles_file("XNVDA-USDT", "1H", 2026).exists()
    paths = [urlsplit(c["url"]).path for c in session.calls]
    assert paths[0] == xs.CANDLES_PATH and set(paths[1:]) == {xs.HISTORY_CANDLES_PATH}
    assert all(c["params"]["instId"] == "XNVDA-USDT" and c["params"]["bar"] == "1H" for c in session.calls)
    again = xs.collect_candles(layout, "XNVDA-USDT", "1H", rest=rest, start_ms=lt, sleep_seconds=0.0)
    assert again.added == 0 and again.walk.pages == 1 and again.walk.complete
    clock.advance(2 * 3600)  # two more hours close
    more = xs.collect_candles(layout, "XNVDA-USDT", "1H", rest=rest, start_ms=lt, sleep_seconds=0.0)
    assert more.added == 2 and more.stored_rows == expected + 2
    daily = xs.collect_candles(layout, "XNVDA-USDT", "1Dutc", rest=rest, start_ms=lt, sleep_seconds=0.0)
    assert daily.added == 14 and daily.stored_min == datetime(2026, 7, 16, tzinfo=timezone.utc) and daily.walk.complete
    bounded = xs.collect_candles(xs.XStocksLayout(tmp_path / "other"), "XNVDA-USDT", "1H", rest=rest, start_ms=lt, max_pages=1, sleep_seconds=0.0)
    assert bounded.walk.reason == "max_pages" and bounded.added == 299 and not bounded.walk.complete  # 300 newest, one forming
    frame = xs.read_xstock_candles(layout, "XNVDA-USDT", "1H")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "quote_volume"] and len(frame) == expected + 2
    assert frame.index.tz is not None and frame.index.is_monotonic_increasing and (frame["quote_volume"] > 0).all()
    assert xs.read_xstock_candles(layout, "XQQQ-USDT", "1H").empty
    for pair, bar in (("BTC-USDT", "1H"), ("XNVDA-USDC", "1H"), ("XNVDA-USDT", "1D"), ("xnvda-usdt", "1H")):
        with pytest.raises(xs.XStocksDataError):
            xs.collect_candles(layout, pair, bar, rest=rest, start_ms=lt, sleep_seconds=0.0)


# -- the schedule -------------------------------------------------------------------------------------------------

def test_the_schedule_follows_the_new_york_clock():
    winter = xs.slots_between(_utc("2026-11-02T00:00:00"), _utc("2026-11-09T00:00:00"))  # Mon-Sun, EST
    by_name = {}
    for s in winter:
        by_name.setdefault(s.name, []).append(s)
    assert [s.scheduled.strftime("%a %H:%M") for s in by_name["us_open"]] == ["Mon 14:30", "Tue 14:30", "Wed 14:30", "Thu 14:30", "Fri 14:30"]
    assert [s.scheduled.strftime("%a %H:%M") for s in by_name["us_close"]] == ["Mon 21:00", "Tue 21:00", "Wed 21:00", "Thu 21:00", "Fri 21:00"]
    assert [s.scheduled.strftime("%a %H:%M") for s in by_name["utc_03"]] == ["Mon 03:00", "Tue 03:00", "Wed 03:00", "Thu 03:00", "Fri 03:00", "Sat 03:00", "Sun 03:00"]
    assert [s.scheduled.strftime("%a %H:%M") for s in by_name["sat_12"]] == ["Sat 12:00"]
    assert len({s.key for s in winter}) == len(winter) == 18 and winter == sorted(winter, key=lambda s: (s.scheduled, s.name))
    summer = xs.slots_between(_utc("2026-07-13T00:00:00"), _utc("2026-07-14T00:00:00"))  # EDT
    assert {s.name: s.scheduled.strftime("%H:%M") for s in summer} == {"utc_03": "03:00", "us_open": "13:30", "us_close": "20:00"}
    assert all(s.ny_date == date(2026, 7, 13) for s in summer if s.name != "utc_03")
    thanksgiving = [s for s in xs.slots_between(_utc("2026-11-26T00:00:00"), _utc("2026-11-27T00:00:00")) if s.name == "us_open"][0]
    assert thanksgiving.us_holiday and thanksgiving.key == "us_open@2026-11-26T14:30Z"
    assert xs.is_us_market_holiday(date(2026, 11, 26)) and not xs.is_us_trading_day(date(2026, 11, 26)) and xs.is_us_trading_day(date(2026, 11, 5))
    assert not xs.is_us_trading_day(date(2026, 11, 7))
    assert len([d for d in xs.US_MARKET_HOLIDAYS if d.startswith("2026")]) == 10 == len([d for d in xs.US_MARKET_HOLIDAYS if d.startswith("2027")])
    assert all(date.fromisoformat(d).weekday() < 5 for d in xs.US_MARKET_HOLIDAYS | xs.US_EARLY_CLOSES)
    # due within the grace window, deduplicated by the taken keys
    now = _utc("2026-11-05T14:40:00")
    due = xs.due_slots(now, set())
    assert [s.key for s in due] == ["us_open@2026-11-05T14:30Z"]
    assert xs.due_slots(now, {"us_open@2026-11-05T14:30Z"}) == []
    assert xs.due_slots(_utc("2026-11-05T15:01:00"), set()) == []  # 31 minutes late: missed
    assert [s.key for s in xs.due_slots(_utc("2026-11-07T12:05:00"), set())] == ["sat_12@2026-11-07T12:00Z"]
    assert xs.next_slot(now).key == "us_close@2026-11-05T21:00Z" and xs.next_slot(_utc("2026-11-07T12:00:00")).key == "utc_03@2026-11-08T03:00Z"
    adhoc = xs.adhoc_slot(_utc("2026-11-05T14:40:12"))
    assert adhoc.name == "adhoc" and adhoc.key == "adhoc@2026-11-05T14:40Z" and adhoc.ny_date == date(2026, 11, 5)
    # the US regular session on the New York clock
    assert xs.us_session_open_at(_utc("2026-11-05T15:00:00")) and not xs.us_session_open_at(_utc("2026-11-05T22:00:00"))
    assert not xs.us_session_open_at(_utc("2026-11-05T14:29:00")) and xs.us_session_open_at(_utc("2026-11-05T14:30:00"))
    assert not xs.us_session_open_at(_utc("2026-11-07T15:00:00")) and not xs.us_session_open_at(_utc("2026-11-26T15:00:00"))
    assert xs.us_session_open_at(_utc("2026-11-27T17:00:00")) and not xs.us_session_open_at(_utc("2026-11-27T18:30:00"))  # early close 13:00 NY
    assert xs.us_session_open_at(_utc("2026-07-13T14:00:00")) and not xs.us_session_open_at(_utc("2026-07-13T20:30:00"))


# -- order books --------------------------------------------------------------------------------------------------

def test_book_parse_metrics_and_trim_on_the_recorded_book():
    book = xs.parse_book([FIXTURE["books_XNVDA-USDT_50"]], "XNVDA-USDT")
    assert book["ts"] == int(FIXTURE["books_XNVDA-USDT_50"]["ts"]) and len(book["asks"]) == 50 == len(book["bids"])
    assert [l[0] for l in book["asks"]] == sorted(l[0] for l in book["asks"]) and [l[0] for l in book["bids"]] == sorted((l[0] for l in book["bids"]), reverse=True)
    assert book["asks"][0][:2] == [198.54, 0.65326] and book["bids"][0][:2] == [198.51, 1.22032] and book["asks"][0][2] == 1
    m = xs.book_metrics(book)
    mid = (198.54 + 198.51) / 2
    assert m["mid"] == pytest.approx(mid) and m["spread_bps"] == pytest.approx((198.54 - 198.51) / mid * 1e4) and not m["empty"]
    assert m["bid_depth_05"] == pytest.approx(sum(px * sz for px, sz, _ in book["bids"] if px >= mid * 0.995))
    assert m["ask_depth_05"] == pytest.approx(sum(px * sz for px, sz, _ in book["asks"] if px <= mid * 1.005))
    assert m["bid_reach_pct"] == pytest.approx((1 - book["bids"][-1][0] / mid) * 100) and m["levels_returned"] == [50, 50]
    assert m["band_covered_bid"] == (m["bid_reach_pct"] >= 0.5) and m["band_covered_ask"] == (m["ask_reach_pct"] >= 0.5)
    trimmed = xs.trim_book(book)
    assert trimmed["levels_kept"] == [50, 50]  # all 50 levels sit within 2 % of mid
    far = dict(book, asks=book["asks"] + [[mid * 1.05, 1.0, 1]], bids=book["bids"] + [[mid * 0.9, 1.0, 1]])
    assert xs.trim_book(far)["levels_kept"] == [50, 50] and xs.book_metrics(far)["band_covered_ask"] and xs.book_metrics(far)["band_covered_bid"]
    assert xs.book_metrics({"asks": [], "bids": book["bids"]}) == {"empty": True, "levels_returned": [50, 0]}
    for bad in ([], [{"asks": [["x", "1"]], "bids": [], "ts": "1"}], [{"asks": [], "bids": [], "ts": ""}], [{"asks": [["-1", "1"]], "bids": [], "ts": "1"}]):
        with pytest.raises(xs.XStocksDataError):
            xs.parse_book(bad, "XNVDA-USDT")
    session = FakeOkx(Clock(_utc("2026-11-05T08:00:00")))
    rest = _rest(session)
    assert xs.fetch_book(rest, "XQQQ-USDT")["instrument"] == "XQQQ-USDT" and session.calls[-1]["params"] == {"instId": "XQQQ-USDT", "sz": "400"}
    limits = xs.fetch_price_limit(rest, "XQQQ-USDT")
    assert limits["buy_limit"] == 200.48 and limits["sell_limit"] == 196.5 and limits["enabled"] is True and limits["ts"] == 1793865418837
    with pytest.raises(xs.XStocksDataError):
        xs.fetch_book(rest, "BTC-USDT")


def test_take_snapshots_writes_one_line_per_pair_marks_the_slot_and_skips_a_failing_pair(tmp_path):
    layout = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake"))
    now = _utc("2026-11-05T14:31:10")
    session = FakeOkx(Clock(now), fail_books={"XBAD-USDT"})
    rest = _rest(session)
    slot = xs.due_slots(now, set())[0]
    rep = xs.take_snapshots(layout, rest, ["XNVDA-USDT", "XBAD-USDT", "XQQQ-USDT"], slot, now=now, sleep_seconds=0.0)
    assert rep.taken == 2 and len(rep.errors) == 1 and rep.errors[0].startswith("XBAD-USDT: PublicRestError") and "2 book(s)" in rep.summary()
    path = layout.books_file("XNVDA-USDT", date(2026, 11, 5))
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    rec = lines[0]
    assert rec["slot"] == "us_open" and rec["slot_key"] == "us_open@2026-11-05T14:30Z" and rec["scheduled_at"] == "2026-11-05T14:30:00Z"
    assert rec["fetched_at"] == "2026-11-05T14:31:10Z" and rec["ny_time"] == "2026-11-05 09:31:10 EST" and rec["us_session_open"] is True
    assert rec["us_trading_day"] and not rec["us_holiday"] and not rec["us_early_close"] and rec["ny_date"] == "2026-11-05"
    assert rec["price_limit"]["buy_limit"] == 200.48 and rec["price_limit_error"] is None and rec["levels_returned"] == [50, 50]
    assert len(rec["asks"]) == 50 and rec["asks"][0] == [198.54, 0.65326, 1] and rec["spread_bps"] > 0 and rec["seq_id"] == 186289522
    state = xs.load_books_state(layout)
    assert state["taken"]["us_open@2026-11-05T14:30Z"]["stored"] == 2 and xs.taken_slot_keys(layout) == {"us_open@2026-11-05T14:30Z"}
    assert xs.due_slots(now, xs.taken_slot_keys(layout)) == []
    # an ad-hoc snapshot is appended to the same day file and never recorded as a taken slot
    adhoc = xs.take_snapshots(layout, rest, ["XNVDA-USDT"], xs.adhoc_slot(now + timedelta(minutes=5)), now=now + timedelta(minutes=5), sleep_seconds=0.0)
    assert adhoc.taken == 1 and len(path.read_text(encoding="utf-8").splitlines()) == 2 and xs.taken_slot_keys(layout) == {"us_open@2026-11-05T14:30Z"}
    snaps = xs.read_snapshots(layout, "XNVDA-USDT")
    assert [s["slot"] for s in snaps] == ["us_open", "adhoc"] and "asks" not in snaps[0] and "bids" not in snaps[0]
    metrics = xs.snapshot_metrics(snaps)
    assert metrics["snapshots"] == 2 and set(metrics["by_slot"]) == {"us_open", "adhoc"} and metrics["by_slot"]["us_open"]["n"] == 1
    assert metrics["by_slot"]["us_open"]["spread_bps_median"] == pytest.approx(rec["spread_bps"]) and metrics["latest"]["slot"] == "adhoc"
    assert metrics["empty_books"] == 0 and xs.read_snapshots(layout, "XBAD-USDT") == []
    # a slot on which every book failed is NOT marked taken, so the loop retries within the grace window
    failing = FakeOkx(Clock(now), fail_books={"XNVDA-USDT", "XQQQ-USDT"})
    other = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake2"))
    rep2 = xs.take_snapshots(other, _rest(failing), ["XNVDA-USDT", "XQQQ-USDT"], slot, now=now, sleep_seconds=0.0)
    assert rep2.taken == 0 and len(rep2.errors) == 2 and xs.taken_slot_keys(other) == set()
    _assert_public_get_only(session.calls, {xs.BOOKS_PATH, xs.PRICE_LIMIT_PATH})
    # the state file is pruned to the last weeks
    old_state = {"version": 1, "taken": {"utc_03@2026-01-01T03:00Z": {"at": "x", "stored": 1, "errors": []}, "utc_03@2026-11-05T03:00Z": {"at": "x", "stored": 1, "errors": []}}}
    xs.save_books_state(layout, old_state, now=now)
    assert xs.taken_slot_keys(layout) == {"utc_03@2026-11-05T03:00Z"}


# -- passes ------------------------------------------------------------------------------------------------------

def test_run_once_collects_everything_through_public_gets_and_is_idempotent(tmp_path):
    lake = LakeLayout(tmp_path / "lake")
    layout = xs.XStocksLayout.from_lake(lake)
    universe = _universe(tmp_path / "universe.json")
    now = _utc("2026-11-05T14:40:00")
    session = FakeOkx(Clock(now))
    rest = _rest(session)
    log = []
    summary = xs.run_once(layout, universe, rest=rest, now=now, sleep_seconds=0.0, log=log.append)
    assert summary["instruments"] == {"day": "2026-11-05", "recorded": 2, "missing": [], "not_live": []}
    assert len(summary["candles"]) == 4 and all(c["complete"] and c["reason"] in ("exhausted", "complete") for c in summary["candles"])
    one_h = [c for c in summary["candles"] if c["bar"] == "1H"]
    assert all(c["added"] == c["stored"] > 2000 and c["min"] == "2026-07-16T06:00:00Z" and c["max"] == "2026-11-05T13:00:00Z" for c in one_h)
    assert [c["stored"] for c in summary["candles"] if c["bar"] == "1Dutc"] == [112, 112]
    assert summary["snapshots"] == [{"slot": "us_open", "key": "us_open@2026-11-05T14:30Z", "stored": 2, "errors": []}] and summary["errors"] == []
    assert any("instruments recorded" in m for m in log) and any("snapshot us_open@2026-11-05T14:30Z: 2 book(s) stored" in m for m in log)
    _assert_public_get_only(session.calls, {xs.INSTRUMENTS_PATH, xs.CANDLES_PATH, xs.HISTORY_CANDLES_PATH, xs.BOOKS_PATH, xs.PRICE_LIMIT_PATH})
    assert not (lake.root / "candles").exists()  # nothing is written into the research lake's own candle tree
    assert layout.candles_file("XNVDA-USDT", "1H", 2026).exists() and layout.books_file("XQQQ-USDT", date(2026, 11, 5)).exists()
    n_calls = len(session.calls)
    again = xs.run_once(layout, universe, rest=rest, now=now + timedelta(minutes=5), sleep_seconds=0.0, snapshot_now=True)
    assert again["instruments"] is None and all(c["added"] == 0 for c in again["candles"]) and [s["slot"] for s in again["snapshots"]] == ["adhoc"]
    assert len(session.calls) - n_calls == 4 + 4  # one newest page per series, a book and a price limit per pair
    status = xs.lake_status(layout, universe)
    assert status["pairs"]["XNVDA-USDT"]["1H"]["rows"] > 2000 and status["pairs"]["XNVDA-USDT"]["snapshots"] == 2 and status["slots_taken"] == ["us_open@2026-11-05T14:30Z"]
    assert status["pairs"]["XQQQ-USDT"]["last_snapshot"]["slot"] == "adhoc" and status["instruments_recorded_at"] == "2026-11-05T14:40:00Z"
    # a pair without a recorded listTime is skipped with an error, not a crash
    universe3 = _universe(tmp_path / "u3.json", ("XNVDA-USDT", "XQQQ-USDT", "XNONE-USDT"))
    other = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake3"))
    s3 = xs.run_once(other, universe3, rest=rest, now=now, sleep_seconds=0.0, max_pages=1)
    assert s3["instruments"]["missing"] == ["XNONE-USDT"] and s3["errors"] == ["XNONE-USDT: no listTime recorded, candles skipped"]
    assert all(c["reason"] == "max_pages" for c in s3["candles"] if c["bar"] == "1H")


def test_run_loop_takes_the_slots_and_tops_the_candles_up_every_hour_on_a_fake_clock(tmp_path):
    layout = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake"))
    universe = _universe(tmp_path / "universe.json")
    clock = Clock(_utc("2026-11-05T14:00:00"))
    session = FakeOkx(clock)
    rest = _rest(session)
    waits = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        clock.advance(seconds)
        return False

    log = []
    stats = xs.run_loop(layout, universe, rest=rest, now_fn=clock, wait=wait, max_minutes=130, poll_seconds=30, sleep_seconds=0.0, log=log.append)
    assert stats["stopped"] == "max_minutes" and stats["started"] == "2026-11-05T14:00:00Z" and stats["ended"] == "2026-11-05T16:10:00Z"
    assert stats["snapshots"] == 2 and stats["topups"] == 2 and stats["passes"] == 3 and stats["errors"] == 0
    assert xs.taken_slot_keys(layout) == {"us_open@2026-11-05T14:30Z"}
    rec = json.loads(layout.books_file("XNVDA-USDT", date(2026, 11, 5)).read_text(encoding="utf-8").splitlines()[0])
    assert rec["fetched_at"] == "2026-11-05T14:30:00Z" and rec["us_session_open"] is True
    assert [m for m in log if m.startswith("top-up")] == ["top-up 2026-11-05T15:01:30Z: bars ['1H'], 2 candle(s) added", "top-up 2026-11-05T16:01:30Z: bars ['1H'], 2 candle(s) added"]
    assert max(waits) <= 1800 and min(waits) >= 1
    frame = xs.read_xstock_candles(layout, "XNVDA-USDT", "1H")
    assert frame.index[-1] == pd.Timestamp("2026-11-05T15:00:00Z")
    # a stop request ends the loop at once; a new UTC day also tops up the daily bars and records the parameters
    clock2 = Clock(_utc("2026-11-05T23:55:00"))
    session2 = FakeOkx(clock2)
    calls = {"n": 0}

    def wait2(seconds: float) -> bool:
        calls["n"] += 1
        clock2.advance(seconds)
        return calls["n"] >= 8

    layout2 = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake2"))
    log2 = []
    stats2 = xs.run_loop(layout2, universe, rest=_rest(session2), now_fn=clock2, wait=wait2, poll_seconds=120, sleep_seconds=0.0, log=log2.append)
    assert stats2["stopped"] == "signal" and stats2["topups"] == 1 and "bars ['1H', '1Dutc']" in [m for m in log2 if m.startswith("top-up")][0]
    assert xs.instruments_recorded_on(layout2, date(2026, 11, 6)) and xs.taken_slot_keys(layout2) == set()


# -- what the data says ------------------------------------------------------------------------------------------

def _constructed_series() -> pd.DataFrame:
    idx_ny = pd.date_range("2026-10-12 00:00", periods=24 * 21, freq="h", tz=xs.NEW_YORK)  # three full weeks, Monday to Sunday
    frame = pd.DataFrame(index=idx_ny.tz_convert("UTC"))
    frame.index.name = "open_time"
    close = pd.Series(100.0, index=frame.index)
    qv = pd.Series(10.0, index=frame.index)
    for t in idx_ny:
        key = t.tz_convert("UTC")
        if t.weekday() >= 5:
            qv[key] = 1.0
        elif 9 <= t.hour < 16:
            qv[key] = 20.0
    def set_close(ny: str, value: float) -> None:
        close[pd.Timestamp(ny, tz=xs.NEW_YORK).tz_convert("UTC")] = value
    set_close("2026-10-17 12:00", 95.0)   # Saturday: the token wanders 5 % below Friday's close
    set_close("2026-10-19 08:00", 102.0)  # Monday pre-open
    set_close("2026-10-19 09:00", 103.0)  # Monday first hour (contains the open)
    set_close("2026-10-26 08:00", 99.0)
    set_close("2026-10-26 09:00", 99.5)
    frame["open"] = close
    frame["high"] = close + 1
    frame["low"] = close - 1
    frame["close"] = close
    frame["volume"] = qv / 100.0
    frame["quote_volume"] = qv
    return frame


def test_history_metrics_on_a_constructed_series():
    frame = _constructed_series()
    m = xs.history_metrics(frame, list_time_ms=_ms("2026-10-01T05:00:00"), now=_utc("2026-11-02T00:00:00"))
    assert m["candles_1h"] == 504 and m["coverage_pct"] == 100.0 and m["listed_at"] == "2026-10-01T05:00:00Z" and m["days_since_listing"] == pytest.approx(31.79, abs=0.01)
    assert m["full_days"] == 21 and m["weekday_days"] == 15 and m["weekend_days"] == 6
    assert m["weekday_volume_mean"] == pytest.approx(7 * 20 + 17 * 10) and m["weekend_volume_mean"] == pytest.approx(24.0)
    assert m["weekend_to_weekday_volume"] == pytest.approx(24 / 310) and m["us_hours_volume_share"] == pytest.approx(140 / 310)
    assert m["weekends"] == 2 and m["zero_volume_hours_pct"] == 0.0
    gaps = [r["gap_pct"] for r in m["weekend_records"]]
    assert gaps == pytest.approx([math.log(1.02) * 100, math.log(0.99) * 100])
    assert m["gap"]["median_abs"] == pytest.approx((abs(gaps[0]) + abs(gaps[1])) / 2) and m["gap"]["max_abs"] == pytest.approx(abs(gaps[0]))
    assert m["jump"]["max_abs"] == pytest.approx(math.log(103 / 102) * 100) and m["jump"]["n"] == 2
    assert m["weekend_dev"]["max_abs"] == pytest.approx(abs(math.log(0.95)) * 100) and m["weekend_records"][1]["weekend_dev_pct"] == pytest.approx(abs(math.log(0.99)) * 100)
    assert m["weekend_fall"]["max_abs"] == pytest.approx(abs(math.log(0.95)) * 100) and m["weekend_records"][1]["weekend_fall_pct"] == pytest.approx(abs(math.log(0.99)) * 100)
    assert m["weekend_fall"]["n"] == 2 and all(r["weekend_fall_pct"] >= 0 for r in m["weekend_records"])
    assert m["weekend_records"][0]["friday"] == "2026-10-16" and m["weekend_records"][0]["next_trading_day"] == "2026-10-19" and m["weekend_records"][0]["closed_hours"] == 64
    empty = xs.history_metrics(xs.read_xstock_candles(xs.XStocksLayout(Path("nowhere")), "XNVDA-USDT", "1H"), list_time_ms=None, now=_utc("2026-11-02T00:00:00"))
    assert empty["candles_1h"] == 0 and empty["weekends"] == 0 and empty["gap"]["n"] == 0 and empty["listed_at"] is None and empty["weekend_fall"]["n"] == 0


def test_feasibility_rows_and_tables_render_from_the_lake(tmp_path):
    layout = xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "lake"))
    universe = _universe(tmp_path / "universe.json")
    now = _utc("2026-11-05T14:40:00")
    xs.run_once(layout, universe, rest=_rest(FakeOkx(Clock(now))), now=now, sleep_seconds=0.0, snapshot_now=True)
    rows = xs.feasibility_rows(layout, universe, now=now)
    assert [r["instrument"] for r in rows] == ["XNVDA-USDT", "XQQQ-USDT"] and rows[0]["rank"] == 1 and rows[0]["candles_1dutc"] == 112
    assert rows[0]["parameters"]["lotSz"] == "0.00001" and rows[0]["history"]["weekends"] >= 15 and rows[0]["snapshots"]["snapshots"] == 2
    assert set(rows[0]["snapshots"]["by_slot"]) == {"us_open", "adhoc"}
    text = xs.render_feasibility_tables(rows, now=now)
    for needle in ("**A. The universe", "**B. History", "**C. Weekend gaps", "**D. Spread and depth", "| 1 | XNVDA-USDT |", "| XQQQ-USDT | us_open | 1 |",
                   "Generated by `scripts/collect_xstocks.py --report` on 2026-11-05T14:40:00Z"):
        assert needle in text, needle
    out = xs.write_feasibility_json(tmp_path / "feas.json", rows, universe, now=now)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["pairs"] == ["XNVDA-USDT", "XQQQ-USDT"] and data["generated_at"] == "2026-11-05T14:40:00Z" and len(data["rows"]) == 2
    empty_rows = xs.feasibility_rows(xs.XStocksLayout.from_lake(LakeLayout(tmp_path / "empty")), universe, now=now)
    assert "| XNVDA-USDT | - | 0 |" in xs.render_feasibility_tables(empty_rows, now=now)


# -- the command line --------------------------------------------------------------------------------------------

def test_cli_modes_refuse_without_a_universe_and_run_through_the_injected_public_client(tmp_path, capsys):
    import scripts.collect_xstocks as cli

    now = _utc("2026-11-05T14:40:00")
    session = FakeOkx(Clock(now))
    rest = _rest(session)
    universe = tmp_path / "universe.json"
    env = {"DATA_LAKE_DIR": str(tmp_path / "lake")}
    assert cli.main(["--once", "--universe", str(universe)], env, rest=rest, now_fn=lambda: now) == cli.EXIT_SETUP
    assert "no universe file" in capsys.readouterr().err
    assert cli.main(["--select-universe", "--universe", str(universe)], env, rest=rest, now_fn=lambda: now) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "universe written" in out and "15 pairs" in out and " 1. XCRCL-USDT" in out
    assert cli.main(["--select-universe", "--universe", str(universe)], env, rest=rest, now_fn=lambda: now) == cli.EXIT_SETUP  # chosen once
    assert cli.main(["--select-universe", "--universe", str(universe), "--force"], env, rest=rest, now_fn=lambda: now) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["--status", "--universe", str(universe)], env) == cli.EXIT_OK
    assert "slots taken: 0" in capsys.readouterr().out
    code = cli.main(["--once", "--universe", str(universe), "--snapshot-now", "--sleep", "0", "--max-pages", "2"], env, rest=rest, now_fn=lambda: now)
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "pass done: 30 candle series" in out and "30 book(s) stored in 2 slot(s)" in out and "0 error(s)" in out
    assert (tmp_path / "lake" / "xstocks" / "books" / "XCRCL-USDT" / "2026-11-05.jsonl").exists()
    assert cli.main(["--status", "--universe", str(universe), "--json"], env) == cli.EXIT_OK
    status = json.loads(capsys.readouterr().out)
    assert status["slots_taken"] == ["us_open@2026-11-05T14:30Z"] and status["pairs"]["XCRCL-USDT"]["snapshots"] == 2
    report_json = tmp_path / "feas.json"
    assert cli.main(["--report", "--universe", str(universe), "--out", str(report_json)], env, now_fn=lambda: now) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "**A. The universe" in out and f"JSON written: {report_json}" in out and report_json.exists()
    code = cli.main(["--loop", "--universe", str(universe), "--sleep", "0", "--max-pages", "1", "--max-minutes", "0.02", "--poll-seconds", "1"], env, rest=rest,
                    now_fn=lambda: datetime.now(tz=timezone.utc))
    assert code == cli.EXIT_OK and "xstocks collector stopped (max_minutes)" in capsys.readouterr().out
    for bad in (["--snapshot-now", "--status"], ["--force", "--once"], ["--once", "--sleep", "-1"], ["--loop", "--max-minutes", "0"], ["--once", "--loop"], []):
        with pytest.raises(SystemExit):
            cli.parse_args(bad)
    _assert_public_get_only(session.calls, {xs.INSTRUMENTS_PATH, xs.TICKERS_PATH, xs.CANDLES_PATH, xs.HISTORY_CANDLES_PATH, xs.BOOKS_PATH, xs.PRICE_LIMIT_PATH})


def test_the_committed_universe_file_is_valid_and_fixed():
    universe = xs.load_universe(xs.DEFAULT_UNIVERSE_PATH)
    assert universe["size"] == 15 and universe["selected_at"] == "2026-11-05T08:11:15Z" and universe["rule"] == xs.UNIVERSE_RULE
    assert universe["pairs"] == ["XCRCL-USDT", "XGOOGL-USDT", "XQQQ-USDT", "XINTC-USDT", "XSOXL-USDT", "XMSTR-USDT", "XSNDK-USDT", "XNVDA-USDT",
                                 "XSPCX-USDT", "XMU-USDT", "XAMD-USDT", "XSKHY-USDT", "XSPY-USDT", "XMRVL-USDT", "XTSLA-USDT"]
    ranking = universe["ranking"]
    assert len(ranking) == universe["summary"]["stock_pairs_usdt_x_live"] == 165
    volumes = [r["quote_volume_24h"] for r in ranking]
    assert volumes == sorted(volumes, reverse=True) and all(r["list_time"] for r in ranking)
    assert all(xs.XSTOCK_ID_RE.match(r["instId"]) for r in ranking) and not any(r["instId"].startswith(("XRP-", "XLM-", "XAUT-")) for r in ranking)
