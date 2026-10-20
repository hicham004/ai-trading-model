"""Vectorized, strictly backward-looking features (pandas rolling ops).

Every function uses only bars up to and including the current one. Donchian
channels and anything used as a *breakout reference* are shifted by one bar so
a bar is never compared with itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close).diff()


def realized_vol(close: pd.Series, window: int, bars_per_year: float) -> pd.Series:
    """Annualized close-to-close volatility over ``window`` bars."""
    return log_returns(close).rolling(window, min_periods=window).std(ddof=0) * np.sqrt(bars_per_year)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return true_range(high, low, close).rolling(window, min_periods=window).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def donchian_high(high: pd.Series, window: int) -> pd.Series:
    """Highest high of the PRIOR ``window`` bars (excludes the current bar)."""
    return high.shift(1).rolling(window, min_periods=window).max()


def donchian_low(low: pd.Series, window: int) -> pd.Series:
    return low.shift(1).rolling(window, min_periods=window).min()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (exponential smoothing with alpha = 1/period)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(avg_loss > 0, 100.0).where(avg_gain.notna() & avg_loss.notna())


def zscore(series: pd.Series, window: int) -> pd.Series:
    roll = series.rolling(window, min_periods=window)
    std = roll.std(ddof=0)
    return (series - roll.mean()) / std.replace(0.0, np.nan)


def bollinger_width(close: pd.Series, window: int = 20, k: float = 2.0) -> pd.Series:
    roll = close.rolling(window, min_periods=window)
    mid = roll.mean()
    std = roll.std(ddof=0)
    return (2.0 * k * std) / mid


def bollinger_bands(close: pd.Series, window: int = 20, k: float = 2.0):
    roll = close.rolling(window, min_periods=window)
    mid = roll.mean()
    std = roll.std(ddof=0)
    return mid - k * std, mid, mid + k * std


def percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Rank of the current value within the trailing ``window`` values, in [0, 1]."""

    def _rank(values: np.ndarray) -> float:
        last = values[-1]
        if np.isnan(last):
            return np.nan
        return float((values[:-1] <= last).sum()) / max(1, len(values) - 1)

    return series.rolling(window, min_periods=window).apply(_rank, raw=True)


def momentum(close: pd.Series, lookback: int) -> pd.Series:
    """Simple ``lookback``-bar return."""
    return close / close.shift(lookback) - 1.0


def slope(series: pd.Series, lookback: int) -> pd.Series:
    """Relative change of ``series`` over ``lookback`` bars (trend direction proxy)."""
    return series / series.shift(lookback) - 1.0


def bar_gaps(index: pd.DatetimeIndex, bar_seconds: float) -> pd.Series:
    """Number of missing bars before each bar (0 when continuous)."""
    deltas = pd.Series(index, index=index).diff().dt.total_seconds()
    gaps = (deltas / bar_seconds).round() - 1.0
    return gaps.fillna(0.0).clip(lower=0.0)
