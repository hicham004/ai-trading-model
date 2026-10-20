"""Parquet lake store: layout safety, merge/dedupe, year partitioning, coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.datalake.layout import LakeLayout, safe_segment
from app.datalake.parquet_store import (
    CANDLE_SCHEMA,
    candle_coverage,
    read_candles,
    to_ms,
    write_candles,
)
from app.okx.client import Candle

T0 = datetime(2023, 12, 31, 20, 0, tzinfo=timezone.utc)


def make_candles(n: int, *, start: datetime = T0, step=timedelta(hours=1), close_offset: float = 0.0):
    out = []
    for i in range(n):
        ts = start + i * step
        price = 100.0 + i
        out.append(
            Candle(
                instrument="BTC-USDT",
                timeframe="1H",
                timestamp=ts,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5 + close_offset,
                volume=10.0,
                confirmed=True,
            )
        )
    return out


def test_safe_segment_rejects_traversal_and_junk():
    assert safe_segment("BTC-USDT", "instrument") == "BTC-USDT"
    for bad in ("../x", "a/b", "", "a b", ".", "x" * 70):
        with pytest.raises(ValueError):
            safe_segment(bad, "instrument")


def test_layout_paths(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    assert layout.candles_file("BTC-USDT", "1H", 2024) == tmp_path / "candles" / "BTC-USDT" / "1H" / "2024.parquet"
    assert layout.series_file("funding_rate", "BTC-USDT-SWAP", "8H", 2024).name == "2024.parquet"
    with pytest.raises(ValueError):
        layout.series_dir("bogus", "BTC-USDT-SWAP", "1H")
    with pytest.raises(ValueError):
        layout.candles_dir("../etc", "1H")
    assert layout.state_file("candles", "BTC-USDT", "1H").name == "candles__BTC-USDT__1H.json"


def test_layout_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATA_LAKE_DIR", str(tmp_path / "lake"))
    assert LakeLayout.from_env().root == tmp_path / "lake"
    monkeypatch.delenv("DATA_LAKE_DIR")
    assert LakeLayout.from_env().root == Path("data/lake")


def test_write_read_roundtrip_and_year_partitioning(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    candles = make_candles(8)  # 20:00 Dec 31 2023 -> 03:00 Jan 1 2024
    result = write_candles(layout, candles)
    assert result.rows_in == 8 and result.added == 8 and result.duplicates_dropped == 0
    assert sorted(p.name for p in result.files) == ["2023.parquet", "2024.parquet"]

    table = read_candles(layout, "BTC-USDT", "1H")
    assert table.schema.equals(CANDLE_SCHEMA)
    assert table.num_rows == 8
    times = table["open_time"].to_pylist()
    assert times == sorted(times) and times[0] == T0

    cov = candle_coverage(layout, "BTC-USDT", "1H")
    assert cov.rows == 8 and cov.files == 2
    assert cov.min_ms == to_ms(T0) and cov.max_ms == to_ms(T0 + timedelta(hours=7))


def test_rewrite_is_idempotent_and_last_write_wins(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    write_candles(layout, make_candles(5))
    again = write_candles(layout, make_candles(5))
    assert again.added == 0 and again.duplicates_dropped == 5
    assert candle_coverage(layout, "BTC-USDT", "1H").rows == 5

    corrected = write_candles(layout, make_candles(5, close_offset=10.0))
    assert corrected.added == 0
    closes = read_candles(layout, "BTC-USDT", "1H")["close"].to_pylist()
    assert all(c > 110 for c in closes)


def test_read_candles_time_window(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    write_candles(layout, make_candles(8))
    start = T0 + timedelta(hours=2)
    end = T0 + timedelta(hours=5)
    table = read_candles(layout, "BTC-USDT", "1H", start=start, end=end)
    assert table["open_time"].to_pylist() == [start, start + timedelta(hours=1), start + timedelta(hours=2)]
    assert read_candles(layout, "ETH-USDT", "1H").num_rows == 0


def test_empty_write_and_coverage(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    assert write_candles(layout, []).added == 0
    cov = candle_coverage(layout, "BTC-USDT", "1H")
    assert cov.rows == 0 and cov.min_ms is None and cov.max_ms is None


def test_to_ms_requires_timezone():
    with pytest.raises(ValueError):
        to_ms(datetime(2024, 1, 1))
