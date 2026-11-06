"""Reference: the SMA(10/30) crossover that runs in the demo shadow (research copy)."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, finite_or_nan


class MovingAverageCrossoverRef(ResearchStrategy):
    key = "baseline"
    label = "SMA crossover reference (10/30 bars, 2 % stop)"
    default_params = {"short_window": 10, "long_window": 30, "stop_loss_pct": 0.02}
    grid = {"short_window": [5, 10, 20], "long_window": [30, 50, 100], "stop_loss_pct": [0.02, 0.04]}

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        if int(p["short_window"]) >= int(p["long_window"]):
            empty = pd.Series(False, index=df.index)
            nan = pd.Series(float("nan"), index=df.index)
            return SignalFrame(desired=empty, stop_distance=nan, strength=nan)
        close = df["close"]
        short = features.sma(close, int(p["short_window"]))
        long = features.sma(close, int(p["long_window"]))
        desired = (short > long).fillna(False)
        strength = finite_or_nan((short - long) / long).where(desired)
        stop = close * float(p["stop_loss_pct"])
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength)
