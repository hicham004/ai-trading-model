"""S1 — time-series momentum (multi-lookback vote, vol-scaled strength, ATR stop).

Sprint 2c adds optional hysteresis bands (``entry_band`` / ``exit_band``, in
units of vol-scaled momentum): with both at 0 the rule is bit-for-bit the
Sprint 2 rule. With bands, the state machine enters when the vote passes AND
the vol-scaled momentum exceeds ``entry_band``, and exits only when the vote
fails OR the vol-scaled momentum falls below ``-exit_band`` — fewer flips,
lower fee drag. Exposed as the ``S1h`` candidate; ``S1`` itself is untouched.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, state_from_events


class TimeSeriesMomentum(ResearchStrategy):
    key = "S1"
    label = "TSMOM multi-lookback (vol-scaled)"
    default_params = {"lookbacks_days": (7, 14, 30), "vote": 2, "atr_window": 14, "atr_mult": 3.0, "vol_window_days": 30,
                      "entry_band": 0.0, "exit_band": 0.0}
    grid = {
        "lookbacks_days": [(7, 14, 30), (14, 30, 60), (7, 30, 90), (30, 60, 90)],
        "vote": [1, 2, 3],
        "atr_mult": [2.0, 3.0, 4.0],
    }

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        close = df["close"]
        lookbacks = [days_to_bars(d, context.timeframe) for d in p["lookbacks_days"]]
        vote = int(min(max(1, p["vote"]), len(lookbacks)))
        vol_w = days_to_bars(p["vol_window_days"], context.timeframe)
        vol = features.realized_vol(close, max(2, vol_w), context.periods_per_year)

        moms = pd.concat([features.momentum(close, L) for L in lookbacks], axis=1)
        positive = (moms > 0).sum(axis=1)
        ready = moms.notna().all(axis=1)
        votes_ok = (positive >= vote) & ready

        # Risk-adjusted strength: average momentum per unit of annualized vol.
        scaled = finite_or_nan(moms.mean(axis=1) / vol.replace(0.0, np.nan))
        entry_band = float(p.get("entry_band", 0.0) or 0.0)
        exit_band = float(p.get("exit_band", 0.0) or 0.0)
        if entry_band > 0.0 or exit_band > 0.0:
            entries = votes_ok & (scaled > entry_band).fillna(False)
            exits = (~votes_ok) | (scaled < -exit_band).fillna(False)
            desired = state_from_events(entries, exits)
        else:
            desired = votes_ok
        strength = scaled.where(desired)

        atr = features.atr(df["high"], df["low"], close, int(p["atr_window"]))
        stop = finite_or_nan(atr * float(p["atr_mult"]))
        return SignalFrame(desired=desired, stop_distance=stop, strength=strength)


class TimeSeriesMomentumHysteresis(TimeSeriesMomentum):
    """S1 with hysteresis bands as grid parameters (Sprint 2c lower-turnover variant)."""

    key = "S1h"
    label = "TSMOM multi-lookback — hysteresis bands"
    default_params = dict(TimeSeriesMomentum.default_params, entry_band=0.25, exit_band=0.25)
    grid = {
        "lookbacks_days": [(7, 14, 30), (14, 30, 60), (30, 60, 90)],
        "vote": [2, 3],
        "atr_mult": [2.0, 3.0],
        "entry_band": [0.1, 0.25, 0.5],
    }
