"""Load lake candles as pandas frames; holdout split; positioning contexts; conversions for the simulator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

import pandas as pd
import pyarrow.parquet as pq

from app.datalake.binance_public import FUNDING_PERIOD as BINANCE_FUNDING_PERIOD
from app.datalake.binance_public import METRICS_PERIOD as BINANCE_METRICS_PERIOD
from app.datalake.binance_public import SYMBOL_FOR_INSTRUMENT
from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import read_candles
from app.strategy.base import MarketCandle
from app.strategy.timeframes import parse_timeframe
from research.resample import resample_ohlcv
from research.strategies.base import FeatureContext

OHLCV = ("open", "high", "low", "close", "volume")
SECONDS_PER_YEAR = 365.25 * 86_400
POSITIONING_SOURCES = ("none", "okx", "binance")


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


def load_or_resample_candles(layout: LakeLayout, instrument: str, timeframe: str, *, source_timeframe: str = "1H") -> pd.DataFrame:
    """Stored candles for ``timeframe``; when none are stored, resample the stored ``source_timeframe`` bars (UTC-aligned)."""
    df = load_candles(layout, instrument, timeframe)
    if not df.empty:
        return df
    base = load_candles(layout, instrument, source_timeframe)
    if base.empty:
        return df
    return resample_ohlcv(base, timeframe, source_timeframe=source_timeframe)


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


# -- positioning (derivatives) series as research features ----------------------

def _read_series_dir(directory, columns: Sequence[str]) -> Optional[pd.DataFrame]:
    files = sorted(directory.glob("*.parquet")) if directory.exists() else []
    if not files:
        return None
    frames = [pq.read_table(f, columns=["ts", *columns]).to_pandas() for f in files]
    df = pd.concat(frames).set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC") if df.index.tz is not None else pd.DatetimeIndex(df.index, tz="UTC")
    return df


def load_okx_series(layout: LakeLayout, kind: str, instrument: str, period: str, columns: Sequence[str]) -> Optional[pd.DataFrame]:
    """OKX derivatives series (``derivatives/<kind>/<instrument>/<period>``) indexed by UTC ``ts``."""
    return _read_series_dir(layout.series_dir(kind, instrument, period), columns)


def load_external_series(layout: LakeLayout, venue: str, kind: str, symbol: str, period: str, columns: Sequence[str]) -> Optional[pd.DataFrame]:
    """External venue series (``external/<venue>/<kind>/<symbol>/<period>``) indexed by UTC ``ts``."""
    return _read_series_dir(layout.external_series_dir(venue, kind, symbol, period), columns)


def positioning_context(layout: LakeLayout, instrument: str, timeframe: str, *, source: str = "binance") -> FeatureContext:
    """Feature context with funding / open-interest frames from ``source`` (``none`` | ``okx`` | ``binance``).

    Binance is the long-history source (funding since 2019, open interest since
    2020-09 for BTC / 2021-12 for ETH); OKX keeps months and is collected for
    the forward period. Both are research features only.
    """
    if source not in POSITIONING_SOURCES:
        raise ValueError(f"positioning source must be one of {POSITIONING_SOURCES}")
    ctx = FeatureContext(timeframe=timeframe, periods_per_year=bars_per_year(timeframe))
    if source == "okx":
        swap = f"{instrument}-SWAP"
        ctx.funding = load_okx_series(layout, "funding_rate", swap, "8H", ["funding_rate"])
        ctx.open_interest = load_okx_series(layout, "open_interest", swap, "1H", ["oi_usd"])
    elif source == "binance":
        symbol = SYMBOL_FOR_INSTRUMENT.get(instrument)
        if symbol is not None:
            ctx.funding = load_external_series(layout, "binance", "funding_rate", symbol, BINANCE_FUNDING_PERIOD, ["funding_rate"])
            ctx.open_interest = load_external_series(layout, "binance", "metrics", symbol, BINANCE_METRICS_PERIOD, ["oi_usd"])
    return ctx
