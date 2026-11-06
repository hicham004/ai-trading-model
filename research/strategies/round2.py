"""Research round 2 (plan row R16): the slow own-market trend filter, SIMULATION ONLY.

Round 1 (plan row R13) tested a FAST cross-market trend condition (BTC's
7/14/30-day momentum vote) and found it changed little; the replication study
(plan row R12) found the breakout family's walk-forward passes contradicted by
the 2025-26 bear year everywhere, with the volatility-regime gate not keeping
it out. Round 2 tests the SLOW trend condition the literature has used since
Faber (2007): the close above its 200-day simple moving average.

- ``S2+TF`` (:class:`SlowTrendGated` over S2) — the Donchian breakout rule with
  Sprint 2c's parameters, grid and brackets untouched, new entries allowed only
  while the market's close is above its 200-day SMA. Entries only: an open
  position is left to the base rule's own exits and stop, as the regime gate,
  the S5 filter and the round-1 conditions do. The 200 days are fixed and never
  in a grid (the round-1 convention for a condition).
- ``TF`` (:class:`SlowTrendExposure`) — the filter as the exposure rule itself:
  long while the close is above its 200-day SMA, flat otherwise, no stop (the
  rule's exit is the cross back below the average), under the same fixed
  policy sizing, S0 filter and regime gate as every candidate. The average's
  length is its only parameter: ``sma_days`` sits in the grid with the single
  value 200, so the walk-forward has nothing to select but the exit bracket,
  while the protocol's robustness replay still perturbs it by +-30 % (140 and
  260 days), as it does for every rule's numeric parameters.

The round-1 volume confirmation (``S1+VC``, :mod:`research.strategies.round1`)
is reused unchanged on the replication markets.

Nothing here can reach an order or an account; every number produced with
these rules is a simulation.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, gate_entries

#: The slow trend filter's length in days (Faber 2007: the 10-month average, about 200 trading days; here 200 calendar days of a
#: 24/7 market). Fixed before the first run; never in a grid as a condition (S2+TF); the single grid value as a rule (TF).
TREND_SMA_DAYS = 200.0


def slow_trend_ok(df: pd.DataFrame, context: FeatureContext, *, sma_days: float = TREND_SMA_DAYS) -> pd.Series:
    """True where the close is above its ``sma_days``-day simple moving average (False while the average is still warming up)."""
    window = max(2, days_to_bars(float(sma_days), context.timeframe))
    close = df["close"].astype(float)
    sma = features.sma(close, window)
    return (close > sma).fillna(False).astype(bool)


def _carry(frame: SignalFrame, desired: pd.Series) -> SignalFrame:
    return SignalFrame(desired=desired, stop_distance=frame.stop_distance, strength=frame.strength.where(desired),
                       target_distance=frame.target_distance, time_stop_bars=frame.time_stop_bars,
                       trail_activate_r=frame.trail_activate_r, trail_r=frame.trail_r)


class SlowTrendGated(ResearchStrategy):
    """H5: the base rule's entries are allowed only while the market's close is above its 200-day moving average."""

    warmup_days = TREND_SMA_DAYS

    def __init__(self, base: ResearchStrategy, *, sma_days: float = TREND_SMA_DAYS) -> None:
        self.base = base
        self.sma_days = float(sma_days)
        self.key = f"{base.key}+TF"
        self.label = f"{base.label} + entries only while the close is above its {sma_days:g}-day moving average"
        self.default_params = dict(base.default_params)
        self.grid = dict(base.grid)

    def trend_ok(self, df: pd.DataFrame, context: FeatureContext) -> pd.Series:
        return slow_trend_ok(df, context, sma_days=self.sma_days)

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        frame = self.base.build(df, p, context)
        return _carry(frame, gate_entries(frame.desired, self.trend_ok(df, context)))


class SlowTrendExposure(ResearchStrategy):
    """H6: long while the close is above its moving average, flat otherwise; no stop (the exit is the cross)."""

    key = "TF"
    label = "slow trend exposure: long while the close is above its 200-day moving average, no stop (Faber 2007)"
    default_params = {"sma_days": TREND_SMA_DAYS}
    grid = {"sma_days": [TREND_SMA_DAYS]}  # one value: nothing to select; the robustness replay perturbs it by +-30 %
    warmup_days = TREND_SMA_DAYS

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        sma_days = float(p["sma_days"])
        window = max(2, days_to_bars(sma_days, context.timeframe))
        close = df["close"].astype(float)
        sma = features.sma(close, window)
        desired = (close > sma).fillna(False).astype(bool)
        strength = finite_or_nan(close / sma.replace(0.0, np.nan) - 1.0).where(desired)
        stop = pd.Series(np.nan, index=df.index, dtype=float)
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength)
