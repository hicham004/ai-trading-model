"""Resample lake candles to a coarser, UTC-aligned timeframe (e.g. 1H -> 6H). SIMULATION ONLY.

OKX serves 6H/12H/1D bars aligned to UTC+8; the research lab wants bars
aligned to the Unix epoch in UTC (00:00, 06:00, 12:00, 18:00) so every
timeframe shares the same clock. Aggregation: open = first, high = max,
low = min, close = last, volume = sum. A target bar is kept only when every
constituent source bar is present (``require_complete``), so a trailing
partial bar or a gap never yields a bar built from fewer sources than it
should. Only bars up to and including a target bar's last source bar
contribute to it, so resampling a prefix of the source gives a prefix of the
result (no look-ahead).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from app.strategy.timeframes import parse_timeframe

OHLCV = ("open", "high", "low", "close", "volume")


def resample_ohlcv(
    df: pd.DataFrame,
    timeframe: str,
    *,
    source_timeframe: Optional[str] = None,
    require_complete: bool = True,
) -> pd.DataFrame:
    """Aggregate OHLCV bars indexed by tz-aware UTC ``open_time`` into ``timeframe`` bars."""
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"frame lacks columns {missing}")
    if df.empty:
        out = df[list(OHLCV)].astype(float).copy()
        out.index.name = "open_time"
        return out
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or idx.tz is None:
        raise ValueError("index must be a tz-aware DatetimeIndex (UTC open_time)")
    df = df.sort_index()
    idx = df.index.tz_convert("UTC")
    target_s = int(parse_timeframe(timeframe).total_seconds())
    if source_timeframe is not None:
        src_s = int(parse_timeframe(source_timeframe).total_seconds())
    else:
        deltas = pd.Series(idx).diff().dt.total_seconds().dropna()
        src_s = int(deltas.min()) if len(deltas) else target_s
    if src_s <= 0 or target_s % src_s != 0:
        raise ValueError(f"target {timeframe} must be a whole multiple of the source bar ({src_s}s)")
    ratio = target_s // src_s
    if ratio < 1:
        raise ValueError("target timeframe must be coarser than the source")
    # Whole seconds since the epoch, independent of the index resolution (the lake stores milliseconds).
    epoch_s = ((idx - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(dtype="int64")
    if np.any(epoch_s % src_s != 0):
        raise ValueError("source bars are not aligned to their own grid")
    if ratio == 1:
        out = df[list(OHLCV)].astype(float).copy()
        out.index = idx
        out.index.name = "open_time"
        return out
    bucket = (epoch_s // target_s) * target_s
    g = df.groupby(bucket)
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    })
    if require_complete:
        count = g["close"].size()
        out = out[count == ratio]
    out.index = pd.to_datetime(out.index.to_numpy(dtype="int64"), unit="s", utc=True)
    out.index.name = "open_time"
    return out.astype(float)
