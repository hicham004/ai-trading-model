"""S5 — positioning filter: do not add longs into crowded funding / open-interest surges.

A *filter*, not a stand-alone strategy: it removes entries from another
candidate's desired mask when the perpetual-swap funding rate z-score is above
``funding_z_max`` (longs paying up = crowded) or open interest rose more than
``oi_change_max`` over the last ``oi_change_window_days`` days. Where
derivatives data are missing the filter passes (no effect) — the report shows
the data coverage so the owner can judge how much of the history the filter
actually touched.

Sprint 2c re-test (``variant="short"``): the funding z-window is 7–14 days
(21–42 eight-hour funding periods) instead of 30 days, and the open-interest
change window is a grid parameter (1 or 3 days).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd

from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, gate_entries


def positioning_mask(df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> pd.Series:
    """True where new longs are allowed by the positioning filter."""
    idx = df.index
    ok = pd.Series(True, index=idx)
    funding = context.aligned("funding", idx, "funding_rate")
    if funding is not None:
        window = int(params.get("funding_z_window", 90))
        roll = funding.rolling(window, min_periods=max(10, window // 3))
        z = (funding - roll.mean()) / roll.std(ddof=0).replace(0.0, np.nan)
        ok &= ~(z > float(params.get("funding_z_max", 2.0))).fillna(False)
    oi = context.aligned("open_interest", idx, "oi_usd")
    if oi is not None:
        day = days_to_bars(float(params.get("oi_change_window_days", 1)), context.timeframe)
        change = oi / oi.shift(day) - 1.0
        ok &= ~(change > float(params.get("oi_change_max", 0.15))).fillna(False)
    return ok.astype(bool)


def positioning_coverage(df: pd.DataFrame, context: FeatureContext) -> float:
    """Fraction of candle bars for which at least one positioning series exists."""
    idx = df.index
    have = pd.Series(False, index=idx)
    for name, col in (("funding", "funding_rate"), ("open_interest", "oi_usd")):
        s = context.aligned(name, idx, col)
        if s is not None:
            have |= s.notna()
    return float(have.mean()) if len(idx) else 0.0


class PositioningFiltered(ResearchStrategy):
    """Wrap a base candidate; entries are additionally gated by the positioning filter."""

    def __init__(self, base: ResearchStrategy, *, variant: str = "default") -> None:
        self.base = base
        self.variant = variant
        if variant == "short":
            self.key = f"{base.key}+S5s"
            self.label = f"{base.label} + positioning filter (7–14d funding window, OI change)"
            self.default_params = dict(base.default_params, funding_z_max=2.0, funding_z_window=42, oi_change_max=0.15,
                                       oi_change_window_days=1)
            self.grid = dict(base.grid)
            self.grid["funding_z_window"] = [21, 42]
            self.grid["funding_z_max"] = [2.0, 3.0]
            self.grid["oi_change_max"] = [0.10, 0.25]
            self.grid["oi_change_window_days"] = [1, 3]
        else:
            self.key = f"{base.key}+S5"
            self.label = f"{base.label} + positioning filter"
            self.default_params = dict(base.default_params, funding_z_max=2.0, funding_z_window=90, oi_change_max=0.15,
                                       oi_change_window_days=1)
            self.grid = dict(base.grid)
            self.grid["funding_z_max"] = [1.5, 2.0, 3.0]

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        frame = self.base.build(df, p, context)
        mask = positioning_mask(df, p, context)
        # Block new entries only: a bar that is desired while blocked stays
        # flat; an already-open position (previous bar desired & allowed) is
        # kept until the base strategy itself turns off.
        desired = gate_entries(frame.desired, mask)
        strength = frame.strength.where(desired)
        return SignalFrame(desired=desired, stop_distance=frame.stop_distance, strength=strength,
                           target_distance=frame.target_distance, time_stop_bars=frame.time_stop_bars)
