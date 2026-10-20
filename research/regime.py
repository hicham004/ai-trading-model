"""Regime v1 (rules): volatility tercile × trend state, for reporting and gating."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research import features
from research.metrics import sharpe
from research.strategies.base import days_to_bars

VOL_LABELS = ("lowvol", "midvol", "highvol")
TREND_LABELS = ("down", "range", "up")


def regime_labels(
    df: pd.DataFrame,
    timeframe: str,
    periods_per_year: float,
    *,
    vol_window_days: float = 7.0,
    vol_lookback_days: float = 365.0,
    trend_days: float = 100.0,
    slope_days: float = 10.0,
    band: float = 0.03,
) -> pd.Series:
    """Label each bar ``"<vol>_<trend>"`` using only past data."""
    close = df["close"]
    vol = features.realized_vol(close, days_to_bars(vol_window_days, timeframe), periods_per_year)
    pct = features.percentile_rank(vol, days_to_bars(vol_lookback_days, timeframe))
    vol_label = pd.Series(np.select([pct <= 1 / 3, pct <= 2 / 3], ["lowvol", "midvol"], default="highvol"), index=df.index)
    vol_label[pct.isna()] = "unknown"

    trend_sma = features.sma(close, days_to_bars(trend_days, timeframe))
    slope = features.slope(trend_sma, days_to_bars(slope_days, timeframe))
    rel = close / trend_sma - 1.0
    up = (rel > band) & (slope > 0)
    down = (rel < -band) & (slope < 0)
    trend_label = pd.Series(np.select([up, down], ["up", "down"], default="range"), index=df.index)
    trend_label[trend_sma.isna() | slope.isna()] = "unknown"
    return vol_label + "_" + trend_label


def metrics_by_regime(bar_returns: pd.Series, regimes: pd.Series, periods_per_year: float) -> pd.DataFrame:
    """Per-regime bar count, share of time, total return and annualized Sharpe."""
    aligned = regimes.reindex(bar_returns.index).fillna("unknown")
    rows = []
    for label, group in bar_returns.groupby(aligned):
        rows.append({
            "regime": label,
            "bars": int(len(group)),
            "share": float(len(group) / len(bar_returns)) if len(bar_returns) else 0.0,
            "total_return": float(np.prod(1.0 + group.to_numpy()) - 1.0),
            "sharpe": sharpe(group.to_numpy(), periods_per_year),
            "hit_rate": float((group > 0).mean()) if len(group) else 0.0,
        })
    return pd.DataFrame(rows).sort_values("regime").reset_index(drop=True)
