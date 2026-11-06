"""S4 — volatility-compression (Bollinger squeeze) breakout, mid-band exit, ATR stop."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, state_from_events


class VolCompressionBreakout(ResearchStrategy):
    key = "S4"
    label = "Vol-compression (BB squeeze) breakout"
    default_params = {"bb_window": 20, "bb_k": 2.0, "squeeze_pct": 0.2, "pct_days": 100, "squeeze_lookback": 10,
                      "atr_window": 14, "atr_mult": 2.5}
    grid = {
        "squeeze_pct": [0.1, 0.2, 0.3],
        "bb_window": [20, 30],
        "atr_mult": [2.0, 3.0],
    }

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        close, high, low = df["close"], df["high"], df["low"]
        lower, mid, upper = features.bollinger_bands(close, int(p["bb_window"]), float(p["bb_k"]))
        width = features.bollinger_width(close, int(p["bb_window"]), float(p["bb_k"]))
        width_pct = features.percentile_rank(width, days_to_bars(p["pct_days"], context.timeframe))
        squeezed = (width_pct <= float(p["squeeze_pct"])).fillna(False)
        # Was there a squeeze within the last N bars (including this one's predecessor)?
        squeeze_recent = squeezed.shift(1).rolling(int(p["squeeze_lookback"]), min_periods=1).max().fillna(0) > 0

        entries = (close > upper).fillna(False) & squeeze_recent
        exits = (close < mid).fillna(False)
        desired = state_from_events(entries, exits)

        atr = features.atr(high, low, close, int(p["atr_window"]))
        strength = finite_or_nan((close - upper) / atr.replace(0.0, np.nan) * (1.0 - width_pct)).where(entries)
        stop = finite_or_nan(atr * float(p["atr_mult"]))
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength)
