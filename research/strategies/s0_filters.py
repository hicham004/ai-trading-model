"""S0 — the no-trade filter: stand aside when the market is not tradeable.

Blocks entries (never forces exits) when:

- realized volatility spikes (1-day vol above ``vol_spike_mult`` × its
  trailing 30-day median);
- the bar range is extreme (``(high-low)/close`` above the ``spread_pct_cap``
  percentile of the trailing 30 days — a liquidity/spread proxy);
- the series has a gap (missing bars) within the last ``cooldown_bars`` bars
  (stale/incomplete data);
- the bar falls inside an operator-supplied event window (UTC) — Sprint 2c
  adds a built-in scheduled calendar (FOMC decisions, see
  :mod:`research.events`) switched on by ``scheduled_events=True``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import days_to_bars


@dataclass(frozen=True)
class NoTradeConfig:
    vol_spike_mult: float = 3.0
    vol_window_days: float = 1.0
    vol_median_days: float = 30.0
    spread_pct_cap: float = 0.98
    spread_window_days: float = 30.0
    cooldown_bars: int = 3
    event_windows: Tuple[Tuple[pd.Timestamp, pd.Timestamp], ...] = ()
    # Sprint 2c: block entries around scheduled macro events (built-in FOMC calendar).
    scheduled_events: bool = False
    event_before_hours: float = 6.0
    event_after_hours: float = 6.0

    @property
    def label(self) -> str:
        base = f"S0 vol×{self.vol_spike_mult:g} spread p{self.spread_pct_cap * 100:.0f} gap{self.cooldown_bars}"
        if self.scheduled_events:
            base += f" FOMC±{self.event_before_hours:g}/{self.event_after_hours:g}h"
        if self.event_windows:
            base += f" +{len(self.event_windows)} windows"
        return base


def all_event_windows(cfg: NoTradeConfig) -> Tuple[Tuple[pd.Timestamp, pd.Timestamp], ...]:
    """Operator windows plus the built-in scheduled calendar when enabled."""
    windows = tuple(cfg.event_windows)
    if cfg.scheduled_events:
        from research.events import fomc_windows, windows_as_tuples

        windows += windows_as_tuples(fomc_windows(before_hours=cfg.event_before_hours, after_hours=cfg.event_after_hours))
    return windows


def tradeable_mask(df: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: NoTradeConfig = NoTradeConfig()) -> pd.Series:
    """True where new entries are allowed."""
    idx = df.index
    ok = pd.Series(True, index=idx)
    close = df["close"]

    vol_w = days_to_bars(cfg.vol_window_days, timeframe)
    med_w = days_to_bars(cfg.vol_median_days, timeframe)
    if vol_w >= 2:
        vol = features.realized_vol(close, vol_w, periods_per_year)
        median = vol.rolling(med_w, min_periods=max(2, med_w // 2)).median()
        spike = vol > cfg.vol_spike_mult * median
        ok &= ~spike.fillna(False)

    spread = (df["high"] - df["low"]) / close
    sp_w = days_to_bars(cfg.spread_window_days, timeframe)
    if sp_w >= 5:
        cap = spread.rolling(sp_w, min_periods=max(5, sp_w // 2)).quantile(cfg.spread_pct_cap)
        ok &= ~(spread > cap).fillna(False)

    bar_seconds = 86_400.0 / (periods_per_year / 365.25)
    gaps = features.bar_gaps(idx, bar_seconds)
    if cfg.cooldown_bars > 0:
        recent_gap = gaps.rolling(cfg.cooldown_bars, min_periods=1).max() > 0
        ok &= ~recent_gap.fillna(False)

    for start, end in all_event_windows(cfg):
        ok &= ~((idx >= start) & (idx <= end))
    return ok.astype(bool)


def blocked_share(df: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: NoTradeConfig) -> float:
    """Fraction of bars on which the filter blocks new entries (reporting aid)."""
    mask = tradeable_mask(df, timeframe, periods_per_year, cfg)
    return float((~mask).mean()) if len(mask) else 0.0
