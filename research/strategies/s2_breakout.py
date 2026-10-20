"""S2 — Donchian breakout with volume and ATR-regime filters, channel exit, ATR stop."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, state_from_events


class DonchianBreakout(ResearchStrategy):
    key = "S2"
    label = "Donchian breakout + volume/ATR filters"
    default_params = {"entry_days": 20, "exit_days": 10, "vol_mult": 1.2, "volume_window": 20,
                      "atr_window": 14, "atr_mult": 2.5, "atr_pct_max": 0.9, "atr_pct_days": 90}
    grid = {
        "entry_days": [10, 20, 55],
        "exit_days": [5, 10, 20],
        "atr_mult": [2.0, 3.0],
        "vol_mult": [1.0, 1.5],
    }

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
        entry_w = days_to_bars(p["entry_days"], context.timeframe)
        exit_w = days_to_bars(p["exit_days"], context.timeframe)
        dh = features.donchian_high(high, entry_w)
        dl = features.donchian_low(low, exit_w)
        atr = features.atr(high, low, close, int(p["atr_window"]))

        vol_ok = volume > float(p["vol_mult"]) * features.sma(volume, int(p["volume_window"]))
        atr_pct = features.percentile_rank(atr, days_to_bars(p["atr_pct_days"], context.timeframe))
        calm_enough = (atr_pct <= float(p["atr_pct_max"])).fillna(False)

        entries = (close > dh) & vol_ok.fillna(False) & calm_enough
        exits = (close < dl).fillna(False)
        desired = state_from_events(entries, exits)

        strength = finite_or_nan((close - dh) / atr.replace(0.0, np.nan)).where(entries)
        stop = finite_or_nan(atr * float(p["atr_mult"]))
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength)
