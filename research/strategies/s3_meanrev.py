"""S3 — range mean-reversion (RSI + z-score) traded only in non-trending regimes."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, state_from_events


class RangeMeanReversion(ResearchStrategy):
    key = "S3"
    label = "Range mean-reversion (RSI/z-score, range regime only)"
    default_params = {"rsi_period": 14, "rsi_entry": 30.0, "rsi_exit": 55.0, "z_window": 20, "z_entry": -2.0,
                      "trend_days": 100, "range_band": 0.08, "atr_window": 14, "atr_mult": 2.0, "time_stop_days": 2.0}
    grid = {
        "rsi_entry": [25.0, 30.0, 35.0],
        "z_entry": [-1.5, -2.0, -2.5],
        "rsi_exit": [50.0, 55.0, 60.0],
        "atr_mult": [1.5, 2.5],
    }

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        close, high, low = df["close"], df["high"], df["low"]
        rsi = features.rsi(close, int(p["rsi_period"]))
        z = features.zscore(close, int(p["z_window"]))
        trend_w = days_to_bars(p["trend_days"], context.timeframe)
        trend_sma = features.sma(close, trend_w)
        in_range = ((close / trend_sma - 1.0).abs() <= float(p["range_band"])).fillna(False)

        entries = (rsi < float(p["rsi_entry"])) & (z < float(p["z_entry"])) & in_range
        exits = ((rsi > float(p["rsi_exit"])) | (z > 0.0)).fillna(False)
        desired = state_from_events(entries.fillna(False), exits)

        strength = finite_or_nan(-z).where(entries.fillna(False))
        atr = features.atr(high, low, close, int(p["atr_window"]))
        stop = finite_or_nan(atr * float(p["atr_mult"]))
        time_stop = days_to_bars(p["time_stop_days"], context.timeframe) if p.get("time_stop_days") else None
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength, time_stop_bars=time_stop)
