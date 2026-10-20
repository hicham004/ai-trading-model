"""Load lake candles as pandas frames; holdout split; conversions for the simulator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd

from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import read_candles
from app.strategy.base import MarketCandle
from app.strategy.timeframes import parse_timeframe

OHLCV = ("open", "high", "low", "close", "volume")
SECONDS_PER_YEAR = 365.25 * 86_400


def bars_per_year(timeframe: str) -> float:
    return SECONDS_PER_YEAR / parse_timeframe(timeframe).total_seconds()


def load_candles(
    layout: LakeLayout,
    instrument: str,
    timeframe: str,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """OHLCV frame indexed by UTC ``open_time`` (sorted, de-duplicated, confirmed bars only)."""
    table = read_candles(layout, instrument, timeframe, start=start, end=end)
    df = table.to_pandas()
    if df.empty:
        return pd.DataFrame(columns=list(OHLCV), index=pd.DatetimeIndex([], tz="UTC", name="open_time"))
    df = df[df["confirmed"]] if "confirmed" in df else df
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.index = pd.DatetimeIndex(df.index, tz="UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df.index.name = "open_time"
    return df[list(OHLCV)].astype(float)


def frame_from_candles(candles: List[MarketCandle]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([c.timestamp for c in candles], tz="UTC", name="open_time")
    return pd.DataFrame(
        {k: [getattr(c, k) for c in candles] for k in OHLCV}, index=idx
    ).astype(float)


def to_market_candles(df: pd.DataFrame, instrument: str, timeframe: str) -> List[MarketCandle]:
    out: List[MarketCandle] = []
    for ts, row in zip(df.index, df[list(OHLCV)].itertuples(index=False)):
        out.append(
            MarketCandle(
                instrument=instrument,
                timestamp=ts.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                timeframe=timeframe,
            )
        )
    return out


def split_holdout(df: pd.DataFrame, *, holdout_months: int = 12, end: Optional[datetime] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(in_sample, holdout)``; the holdout is the last ``holdout_months`` before ``end``.

    The holdout must stay untouched until a strategy has passed walk-forward
    validation; the research runner evaluates it once, at the end.
    """
    if df.empty:
        return df, df
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp(df.index[-1])
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    cutoff = end_ts - pd.DateOffset(months=holdout_months)
    return df[df.index < cutoff], df[(df.index >= cutoff) & (df.index <= end_ts)]


def utc(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)
