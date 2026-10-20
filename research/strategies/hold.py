"""Reference: always long (no stop) — isolates what the sizing overlays alone do to buy-and-hold."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame


class AlwaysLong(ResearchStrategy):
    key = "hold"
    label = "Always-long reference (sizing overlays only, no stop)"
    default_params: dict = {}
    grid: dict = {}

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        desired = pd.Series(True, index=df.index)
        nan = pd.Series(float("nan"), index=df.index)
        return SignalFrame(desired=desired, stop_distance=nan, strength=nan)
