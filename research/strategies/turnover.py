"""Lower-turnover variants of the candidate rules (Sprint 2c, item 4; SIMULATION ONLY).

None of these change an entry *rule*: they change WHEN a rule's state may be
acted on, which is what fee drag depends on.

- :class:`WeeklyClock` — the base rule's desired state is sampled once a
  week (the first bar at or after Monday 00:00 UTC) and held until the next
  sample: weekly-rebalanced TSMOM. The protective stop still works intrabar.
- :class:`DailyEntryClock` — NEW entries are only taken on the last bar of a
  UTC day (the 1D "entry clock"); exits follow the base rule on every bar
  (4H/6H exits).
- Hysteresis bands live inside S1 (``entry_band`` / ``exit_band``) and are
  exposed as the ``S1h`` candidate.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, bars_per_day, gate_entries


def weekly_decision_bars(index: pd.DatetimeIndex) -> pd.Series:
    """True on the first bar of each ISO week (Monday 00:00 UTC or the first bar after it)."""
    idx = index.tz_convert("UTC")
    iso = idx.isocalendar()
    key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    first = pd.Series(key.to_numpy(), index=index)
    return (first != first.shift(1)).fillna(True).astype(bool)


def daily_close_bars(index: pd.DatetimeIndex, timeframe: str) -> pd.Series:
    """True on the last bar of each UTC day for a timeframe that divides the day; for 1D every bar."""
    per_day = bars_per_day(timeframe)
    idx = index.tz_convert("UTC")
    if per_day <= 1.0:
        return pd.Series(True, index=index)
    bar_hours = 24.0 / per_day
    last_open_hour = 24.0 - bar_hours
    hours = idx.hour + idx.minute / 60.0
    return pd.Series(np.isclose(hours, last_open_hour), index=index)


class WeeklyClock(ResearchStrategy):
    """Hold the base rule's desired state between weekly decision bars."""

    def __init__(self, base: ResearchStrategy, *, suffix: str = "w") -> None:
        self.base = base
        self.key = f"{base.key}{suffix}"
        self.label = f"{base.label} — weekly clock"
        self.default_params = dict(base.default_params)
        self.grid = dict(base.grid)

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        frame = self.base.build(df, params, context)
        decide = weekly_decision_bars(df.index)
        desired = frame.desired.astype(float).where(decide).ffill().fillna(0.0).astype(bool)
        return SignalFrame(desired=desired, stop_distance=frame.stop_distance, strength=frame.strength.where(desired),
                           target_distance=frame.target_distance, time_stop_bars=frame.time_stop_bars,
                           trail_activate_r=frame.trail_activate_r, trail_r=frame.trail_r)


class DailyEntryClock(ResearchStrategy):
    """Entries only at the daily close; exits on every bar."""

    def __init__(self, base: ResearchStrategy, *, suffix: str = "d") -> None:
        self.base = base
        self.key = f"{base.key}{suffix}"
        self.label = f"{base.label} — 1D entry clock"
        self.default_params = dict(base.default_params)
        self.grid = dict(base.grid)

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        frame = self.base.build(df, params, context)
        ok = daily_close_bars(df.index, context.timeframe)
        desired = gate_entries(frame.desired, ok)
        return SignalFrame(desired=desired, stop_distance=frame.stop_distance, strength=frame.strength.where(desired),
                           target_distance=frame.target_distance, time_stop_bars=frame.time_stop_bars,
                           trail_activate_r=frame.trail_activate_r, trail_r=frame.trail_r)
