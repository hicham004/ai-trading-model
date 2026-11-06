"""6H bars resampled from 1H: UTC alignment, aggregation, completeness, no look-ahead, lake fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import write_candles
from app.okx.client import Candle
from research.data import bars_per_year, load_or_resample_candles
from research.resample import resample_ohlcv
from research.strategies.base import days_to_bars


def hourly(n: int, start: str = "2023-01-01 00:00") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC", name="open_time")
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 0.5, "low": np.minimum(open_, close) - 0.5,
                         "close": close, "volume": np.arange(1, n + 1, dtype=float)}, index=idx)


def test_six_hour_bars_are_utc_aligned_and_aggregated():
    df = hourly(100)
    out = resample_ohlcv(df, "6H")
    assert len(out) == 16  # 100 hours -> 16 complete 6H bars; the trailing 4 hours are dropped
    assert set(out.index.hour) <= {0, 6, 12, 18} and out.index.tz is not None and out.index.name == "open_time"
    first = df.iloc[:6]
    assert out.iloc[0]["open"] == first["open"].iloc[0] and out.iloc[0]["close"] == first["close"].iloc[-1]
    assert out.iloc[0]["high"] == first["high"].max() and out.iloc[0]["low"] == first["low"].min()
    assert out.iloc[0]["volume"] == first["volume"].sum()
    assert out.index[1] - out.index[0] == pd.Timedelta(hours=6)
    assert bars_per_year("6H") == pytest.approx(8766 / 6) and days_to_bars(1, "6H") == 4


def test_incomplete_buckets_are_dropped_unless_asked_for():
    df = hourly(48)
    broken = df.drop(df.index[8])  # a hole inside the second 6H bucket
    out = resample_ohlcv(broken, "6H")
    assert len(out) == 7 and pd.Timestamp("2023-01-01 06:00", tz="UTC") not in out.index
    loose = resample_ohlcv(broken, "6H", require_complete=False)
    assert len(loose) == 8
    late_start = hourly(30, start="2023-01-01 03:00")
    out2 = resample_ohlcv(late_start, "6H")
    assert out2.index[0] == pd.Timestamp("2023-01-01 06:00", tz="UTC")


def test_resampling_a_prefix_gives_a_prefix():
    df = hourly(200)
    full = resample_ohlcv(df, "6H")
    part = resample_ohlcv(df.iloc[:125], "6H")
    pd.testing.assert_frame_equal(part, full.iloc[: len(part)])
    assert len(part) == 20


def test_resample_validation():
    df = hourly(24)
    with pytest.raises(ValueError):
        resample_ohlcv(df, "90m")  # not a multiple of 1H
    with pytest.raises(ValueError):
        resample_ohlcv(df.tz_localize(None), "6H")
    with pytest.raises(ValueError):
        resample_ohlcv(df.drop(columns=["volume"]), "6H")
    same = resample_ohlcv(df, "1H")
    pd.testing.assert_frame_equal(same, df.astype(float))
    assert resample_ohlcv(df.iloc[:0], "6H").empty


def test_lake_fallback_resamples_stored_1h_bars(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    t0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    candles = [Candle("BTC-USDT", "1H", t0 + timedelta(hours=i), 10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i, 1.0, True) for i in range(30)]
    write_candles(layout, candles)
    six = load_or_resample_candles(layout, "BTC-USDT", "6H")
    assert len(six) == 5 and six.index[0] == pd.Timestamp(t0) and six.iloc[0]["high"] == 16.0 and six.iloc[0]["volume"] == 6.0
    assert load_or_resample_candles(layout, "ETH-USDT", "6H").empty
