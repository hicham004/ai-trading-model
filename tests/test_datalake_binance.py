"""Binance public history (research features): allowlists, parsers, zip/checksum safety, resumable backfills, views, loader."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.datalake import binance_public as b
from app.datalake.duckdb_views import connect
from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import coverage
from research.data import load_external_series, positioning_context
from research.strategies.base import FeatureContext
from research.strategies.s5_positioning import positioning_coverage

# Fixtures copied from live public responses (2026-10-20).
FUNDING_ROWS = [
    {"symbol": "BTCUSDT", "fundingTime": 1568102400000, "fundingRate": "0.00010000", "markPrice": "", "rateType": "Regular"},
    {"symbol": "BTCUSDT", "fundingTime": 1568131200000, "fundingRate": "0.00010000", "markPrice": "10234.50000000"},
]
METRICS_HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
                  "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio")
METRICS_CSV = "\n".join([
    METRICS_HEADER,
    "2020-09-01 00:00:00,BTCUSDT,39080.23100000,456144339.23360443,1.17547937,1.23012681,1.35731217,0.78373373",
    "2020-09-01 00:00:00,BTCUSDT,39080.23100000,456144339.23360443,1.17547937,1.23012681,1.35731217,0.78373373",
    "2020-09-01 00:05:00,BTCUSDT,39090.00000000,456200000.00000000,1.17,1.23,1.35,0.78",
    "2020-09-01 00:55:00,BTCUSDT,39100.00000000,456300000.00000000,1.18,1.24,1.36,0.79",
    "2020-09-01 01:00:00,BTCUSDT,39187.19100000,467388971.11357822,1.21184475,1.24628445,1.33229062,0.61414611",
    "",
])


def zipped(csv_text: str, name: str = "BTCUSDT-metrics-2020-09-01.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, csv_text)
    return buf.getvalue()


def checksum_for(content: bytes, filename: str) -> bytes:
    return f"{hashlib.sha256(content).hexdigest()}  {filename}\n".encode()


def test_path_allowlists():
    assert b.assert_fapi_path("/fapi/v1/fundingRate") == "/fapi/v1/fundingRate"
    for bad in ("/fapi/v1/order", "/fapi/v1/account", "/futures/data/openInterestHist", "/fapi/v1/fundingRate?x=1"):
        with pytest.raises(ValueError):
            b.assert_fapi_path(bad)
    ok = b.metrics_file_path("BTCUSDT", date(2020, 9, 1))
    assert ok == "/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2020-09-01.zip"
    b.assert_vision_path(ok)
    b.assert_vision_path(ok + ".CHECKSUM")
    for bad in ("/data/futures/um/daily/klines/BTCUSDT/x.zip", "/data/futures/um/daily/metrics/SOLUSDT/SOLUSDT-metrics-2020-09-01.zip",
                "/data/futures/um/daily/metrics/BTCUSDT/../BTCUSDT-metrics-2020-09-01.zip",
                "/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2020-09-01.csv",
                "/data/futures/um/daily/metrics/BTCUSDT/ETHUSDT-metrics-2020-09-01.zip"):
        with pytest.raises(ValueError):
            b.assert_vision_path(bad)
    with pytest.raises(ValueError):
        b.metrics_file_path("SOLUSDT", date(2020, 9, 1))


def test_funding_parser_matches_live_format():
    rows = b.parse_funding_rows(FUNDING_ROWS, "BTCUSDT")
    assert rows[0]["ts"] == 1568102400000 and rows[0]["funding_rate"] == pytest.approx(1e-4)
    assert rows[0]["mark_price"] != rows[0]["mark_price"]  # NaN for a blank markPrice
    assert rows[1]["mark_price"] == pytest.approx(10234.5) and rows[0]["period"] == "8H" and rows[0]["venue"] == "binance"
    assert b.parse_funding_rows([dict(FUNDING_ROWS[0], symbol="ETHUSDT")], "BTCUSDT") == []
    with pytest.raises(b.BinancePublicError):
        b.parse_funding_rows([{"symbol": "BTCUSDT", "fundingTime": "x", "fundingRate": "0.1"}], "BTCUSDT")
    with pytest.raises(b.BinancePublicError):
        b.parse_funding_rows([{"symbol": "BTCUSDT", "fundingTime": 1, "fundingRate": "inf"}], "BTCUSDT")
    table = b.records_to_table("funding_rate", rows)
    assert table.schema.equals(b.EXTERNAL_SCHEMAS["funding_rate"]) and table.num_rows == 2


def test_metrics_parser_hourly_reduction_and_zip_safety():
    rows = b.parse_metrics_csv(METRICS_CSV, "BTCUSDT")
    assert [r["ts"] for r in rows] == [1598918400000, 1598918700000, 1598921700000, 1598922000000]  # duplicate 00:00 collapsed
    assert rows[0]["oi"] == pytest.approx(39080.231) and rows[0]["oi_usd"] == pytest.approx(456144339.2336)
    hourly = b.hourly_last(rows)
    assert [r["ts"] for r in hourly] == [1598921700000, 1598922000000]  # 00:55 is the hour's last snapshot, then 01:00
    assert hourly[0]["period"] == "1H" and hourly[0]["taker_ls_vol_ratio"] == pytest.approx(0.79)
    with pytest.raises(b.BinancePublicError):
        b.parse_metrics_csv("a,b\n1,2\n", "BTCUSDT")
    with pytest.raises(b.BinancePublicError):
        b.parse_metrics_csv(METRICS_HEADER + "\n2020-09-01 00:00:00,BTCUSDT,nan,1,1,1,1,1\n", "BTCUSDT")
    assert b.unzip_single_csv(zipped(METRICS_CSV)) == METRICS_CSV
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "x")
        z.writestr("b.csv", "y")
    with pytest.raises(b.BinancePublicError):
        b.unzip_single_csv(buf.getvalue())
    with pytest.raises(b.BinancePublicError):
        b.unzip_single_csv(zipped(METRICS_CSV), max_bytes=10)
    with pytest.raises(b.BinancePublicError):
        b.unzip_single_csv(b"not a zip")
    with pytest.raises(b.BinancePublicError):
        b.unzip_single_csv(zipped("x", name="evil.exe"))
    content = zipped(METRICS_CSV)
    b.verify_checksum(content, checksum_for(content, "f.zip").decode(), "f.zip")
    with pytest.raises(b.BinancePublicError):
        b.verify_checksum(content, "deadbeef  f.zip", "f.zip")
    with pytest.raises(b.BinancePublicError):
        b.verify_checksum(content, checksum_for(content, "other.zip").decode(), "f.zip")


class FakeClient:
    """Serves funding pages ascending from startTime and bulk files by path (None = 404)."""

    def __init__(self, funding_rows=None, files=None):
        self.funding_rows = list(funding_rows or [])
        self.files = dict(files or {})
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        assert path == b.FUNDING_PATH
        start = int(params["startTime"])
        limit = int(params["limit"])
        rows = [r for r in self.funding_rows if int(r["fundingTime"]) >= start]
        return rows[:limit]

    def get_file(self, path):
        b.assert_vision_path(path)
        self.calls.append((path, {}))
        return self.files.get(path)


def funding_series(n: int, start_ms: int = 1568102400000):
    return [{"symbol": "BTCUSDT", "fundingTime": start_ms + i * 8 * 3_600_000, "fundingRate": "0.0001", "markPrice": ""} for i in range(n)]


def test_funding_backfill_is_resumable_and_forward_only(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    client = FakeClient(funding_rows=funding_series(1005))
    report = b.backfill_funding(client, layout, "BTCUSDT", sleep_seconds=0)
    assert report.pages == 2 and report.rows_fetched == 1005 and report.added == 1005 and report.reason == "complete"
    assert report.stored_rows == 1005 and report.stored_min == datetime(2019, 9, 10, 8, tzinfo=timezone.utc)
    state = json.loads(layout.state_file("external", "binance", "funding_rate", "BTCUSDT").read_text())
    assert state["cursor_ms"] == funding_series(1005)[-1]["fundingTime"] + 1
    # Re-run: nothing new -> one page, up to date, no rows.
    again = b.backfill_funding(client, layout, "BTCUSDT", sleep_seconds=0)
    assert again.pages == 1 and again.rows_fetched == 0 and again.reason == "up_to_date" and again.complete
    # New settlements appear -> only they are fetched and merged (no duplicates).
    client.funding_rows = funding_series(1008)
    more = b.backfill_funding(client, layout, "BTCUSDT", sleep_seconds=0)
    assert more.rows_fetched == 3 and more.added == 3 and more.stored_rows == 1008
    # Page budget.
    fresh = FakeClient(funding_rows=funding_series(2500))
    budget = b.backfill_funding(fresh, LakeLayout(tmp_path / "b"), "BTCUSDT", max_pages=1, sleep_seconds=0)
    assert budget.reason == "max_pages" and budget.rows_fetched == 1000 and not budget.complete
    with pytest.raises(ValueError):
        b.backfill_funding(fresh, layout, "SOLUSDT")


def test_metrics_backfill_verifies_resumes_and_records_missing_days(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    day1 = b.metrics_file_path("BTCUSDT", date(2020, 9, 1))
    day3 = b.metrics_file_path("BTCUSDT", date(2020, 9, 3))
    csv3 = METRICS_CSV.replace("2020-09-01", "2020-09-03")
    z1, z3 = zipped(METRICS_CSV), zipped(csv3, "BTCUSDT-metrics-2020-09-03.csv")
    files = {day1: z1, day1 + ".CHECKSUM": checksum_for(z1, "BTCUSDT-metrics-2020-09-01.zip"),
             day3: z3, day3 + ".CHECKSUM": b"0000  BTCUSDT-metrics-2020-09-03.zip\n"}
    client = FakeClient(files=files)
    with pytest.raises(b.BinancePublicError):  # day 3 fails sha256 -> stop, state keeps day 2 as done
        b.backfill_metrics(client, layout, "BTCUSDT", end_day=date(2020, 9, 4), sleep_seconds=0)
    state = json.loads(layout.state_file("external", "binance", "metrics", "BTCUSDT").read_text())
    assert state["done_through"] == "2020-09-02" and state["missing_days"] == ["2020-09-02"]
    assert coverage(layout.external_series_dir("binance", "metrics", "BTCUSDT", "1H"), "ts").rows == 2
    client.files[day3 + ".CHECKSUM"] = checksum_for(z3, "BTCUSDT-metrics-2020-09-03.zip")
    report = b.backfill_metrics(client, layout, "BTCUSDT", end_day=date(2020, 9, 4), sleep_seconds=0)
    assert report.days_requested == 2 and report.days_fetched == 1 and report.days_missing == ["2020-09-04"]
    assert report.done_through == "2020-09-04" and report.stored_rows == 4 and report.reason == "complete"
    assert not any(p.startswith(day1) for p, _ in client.calls[-4:])  # days already done are not re-fetched
    # Nothing to do when the cursor is at the end; day budget bounds a run.
    idle = b.backfill_metrics(client, layout, "BTCUSDT", end_day=date(2020, 9, 4), sleep_seconds=0)
    assert idle.days_requested == 0 and idle.reason == "up_to_date"
    budget = b.backfill_metrics(FakeClient(files=files), LakeLayout(tmp_path / "c"), "BTCUSDT", end_day=date(2020, 9, 4), max_days=1, sleep_seconds=0, verify=False)
    assert budget.days_fetched == 1 and budget.reason == "max_days"
    with pytest.raises(b.BinancePublicError):  # checksum file missing
        b.backfill_metrics(FakeClient(files={day1: z1}), LakeLayout(tmp_path / "d"), "BTCUSDT", end_day=date(2020, 9, 1), sleep_seconds=0)


def test_layout_views_and_research_loader(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    assert layout.external_series_file("binance", "metrics", "BTCUSDT", "1H", 2021).as_posix().endswith("external/binance/metrics/BTCUSDT/1H/2021.parquet")
    for bad in (("bybit", "metrics"), ("binance", "candles")):
        with pytest.raises(ValueError):
            layout.external_series_dir(bad[0], bad[1], "BTCUSDT", "1H")
    con = connect(layout)
    assert con.execute("SELECT count(*) FROM binance_funding_rate").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM binance_metrics").fetchone()[0] == 0
    con.close()
    b.write_external_series(layout, "funding_rate", "BTCUSDT", "8H", b.parse_funding_rows(FUNDING_ROWS, "BTCUSDT"))
    b.write_external_series(layout, "metrics", "BTCUSDT", "1H", b.hourly_last(b.parse_metrics_csv(METRICS_CSV, "BTCUSDT")))
    con = connect(layout)
    assert con.execute("SELECT count(*) FROM binance_funding_rate").fetchone()[0] == 2
    assert con.execute("SELECT max(oi_usd) FROM binance_metrics").fetchone()[0] == pytest.approx(467388971.1136)
    con.close()
    frame = load_external_series(layout, "binance", "metrics", "BTCUSDT", "1H", ["oi_usd"])
    assert list(frame.columns) == ["oi_usd"] and frame.index.tz is not None
    ctx = positioning_context(layout, "BTC-USDT", "1H", source="binance")
    assert ctx.funding is not None and ctx.open_interest is not None
    # As-of alignment: a candle sees a snapshot only once its own timestamp is at/after the snapshot time.
    idx = pd.date_range("2020-09-01 00:00", periods=4, freq="h", tz="UTC")
    aligned = ctx.aligned("open_interest", idx, "oi_usd")
    assert pd.isna(aligned.iloc[0]) and aligned.iloc[1] == pytest.approx(467388971.1136)  # 00:55 snapshot visible at 01:00
    assert positioning_coverage(pd.DataFrame(index=idx), ctx) == pytest.approx(1.0)  # funding (2019) covers every candle
    oi_only = FeatureContext("1H", ctx.periods_per_year, open_interest=ctx.open_interest)
    assert positioning_coverage(pd.DataFrame(index=idx), oi_only) == pytest.approx(0.75)
    assert positioning_context(layout, "BTC-USDT", "1H", source="none").funding is None
    assert positioning_context(layout, "SOL-USDT", "1H", source="binance").funding is None
    with pytest.raises(ValueError):
        positioning_context(layout, "BTC-USDT", "1H", source="bybit")
