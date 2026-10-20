"""Research strategy contract: vectorized signal frames + feature context."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from app.strategy.timeframes import parse_timeframe


def bars_per_day(timeframe: str) -> float:
    return 86_400.0 / parse_timeframe(timeframe).total_seconds()


def days_to_bars(days: float, timeframe: str) -> int:
    """Convert a horizon in days to a whole number of bars (at least 1)."""
    return max(1, int(round(days * bars_per_day(timeframe))))


@dataclass
class FeatureContext:
    """Per-run context: timeframe plus optional derivatives frames aligned to the candles."""

    timeframe: str
    periods_per_year: float
    funding: Optional[pd.DataFrame] = None  # index ts (UTC), column funding_rate
    open_interest: Optional[pd.DataFrame] = None  # index ts (UTC), column oi_usd

    def aligned(self, name: str, index: pd.DatetimeIndex, column: str) -> Optional[pd.Series]:
        """As-of align a derivatives series onto the candle index (only past values)."""
        frame = getattr(self, name)
        if frame is None or frame.empty or column not in frame:
            return None
        series = frame[column].sort_index()
        series = series[~series.index.duplicated(keep="last")]
        return pd.Series(series.reindex(series.index.union(index)).ffill().reindex(index).to_numpy(), index=index)


@dataclass
class SignalFrame:
    desired: pd.Series  # bool: want to be long at this bar's close (executes next open)
    stop_distance: pd.Series  # float price distance for the fixed stop; NaN = no stop
    strength: pd.Series  # float raw strength (NaN when no signal); used for calibration
    target_distance: Optional[pd.Series] = None
    time_stop_bars: Optional[int] = None
    trail_activate_r: Optional[float] = None  # trailing stop: activation threshold in R (None = off)
    trail_r: Optional[float] = None  # trailing stop: distance below the running high, in R

    def __post_init__(self) -> None:
        n = len(self.desired)
        for name in ("stop_distance", "strength"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} must align with desired")
        self.desired = self.desired.fillna(False).astype(bool)


class ResearchStrategy(ABC):
    """A candidate strategy family with a default parameter grid."""

    key: str = "S?"
    label: str = "unnamed"
    default_params: Dict[str, Any] = {}
    grid: Dict[str, List[Any]] = {}

    @abstractmethod
    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        """Return the signal frame for ``df`` (OHLCV indexed by UTC open_time)."""

    def params_with_defaults(self, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        merged = dict(self.default_params)
        merged.update(params or {})
        return merged

    def describe(self, params: Mapping[str, Any]) -> str:
        return f"{self.key} " + " ".join(f"{k}={v}" for k, v in sorted(params.items()))


def state_from_events(entries: pd.Series, exits: pd.Series) -> pd.Series:
    """Turn entry/exit events into a desired-long state (exit wins on a tie)."""
    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)
    state = pd.Series(np.nan, index=entries.index, dtype=float)
    state[entries & ~exits] = 1.0
    state[exits] = 0.0
    return state.ffill().fillna(0.0).astype(bool)


def gate_entries(desired: pd.Series, ok: pd.Series) -> pd.Series:
    """Block NEW entries where ``ok`` is False; never force an exit.

    Within each run of consecutive ``desired`` bars the position starts at the
    first bar where ``ok`` is True and then persists until ``desired`` turns off:
    ``out[i] = desired[i] & (ok[i] | out[i-1])``.
    """
    desired = desired.fillna(False).astype(bool)
    ok = ok.reindex(desired.index).fillna(False).astype(bool)
    run_id = (desired != desired.shift(fill_value=False)).cumsum()
    entered = (desired & ok).groupby(run_id).cummax()
    return (desired & entered).astype(bool)


def finite_or_nan(series: pd.Series) -> pd.Series:
    out = series.astype(float).copy()
    out[~np.isfinite(out)] = np.nan
    return out
