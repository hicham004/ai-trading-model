"""Mechanical exit brackets (SIMULATION ONLY): take-profit, trailing stop, time stop.

A bracket is layered on a candidate's signal frame without changing its
entries: the stop distance the strategy already supplies defines ``R`` (the
initial risk per unit); the take-profit is ``take_profit_r x R`` above the
decision close; the trailing stop activates once the position has moved
``trail_activate_r x R`` in its favour (measured on bar highs at bar close,
effective from the next bar) and then follows the running high at
``trail_r x R`` below it, only ever moving up; the time stop closes the trade
after ``time_stop_days`` regardless of price. The fleets paper (arXiv
2609.05663) found a mechanical bracket would have recovered ~39 bps per
position of "give-back"; ``research.metrics.giveback_metrics`` measures that
before/after here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from research.strategies.base import SignalFrame, days_to_bars


@dataclass(frozen=True)
class BracketSpec:
    key: str
    take_profit_r: Optional[float] = None
    trail_activate_r: Optional[float] = None
    trail_r: Optional[float] = None
    time_stop_days: Optional[float] = None

    def __post_init__(self) -> None:
        if self.take_profit_r is not None and self.take_profit_r <= 0:
            raise ValueError("take_profit_r must be positive")
        if (self.trail_activate_r is None) != (self.trail_r is None):
            raise ValueError("trail_activate_r and trail_r go together")
        if self.trail_r is not None and (self.trail_r <= 0 or self.trail_activate_r < 0):
            raise ValueError("trail_r must be positive and trail_activate_r non-negative")
        if self.time_stop_days is not None and self.time_stop_days <= 0:
            raise ValueError("time_stop_days must be positive")

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.take_profit_r, self.trail_r, self.time_stop_days))

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


BRACKETS: Dict[str, BracketSpec] = {
    "none": BracketSpec("none"),
    "tp2": BracketSpec("tp2", take_profit_r=2.0),
    "tp3": BracketSpec("tp3", take_profit_r=3.0),
    "trail1": BracketSpec("trail1", trail_activate_r=1.0, trail_r=1.0),
    "trail2": BracketSpec("trail2", trail_activate_r=1.0, trail_r=2.0),
    "trail1_tp3": BracketSpec("trail1_tp3", take_profit_r=3.0, trail_activate_r=1.0, trail_r=1.0),
    "time30": BracketSpec("time30", time_stop_days=30.0),
}


def get_bracket(key: str) -> BracketSpec:
    try:
        return BRACKETS[key]
    except KeyError:
        raise ValueError(f"unknown bracket {key!r}; available: {sorted(BRACKETS)}") from None


def apply_bracket(frame: SignalFrame, spec: BracketSpec, timeframe: str) -> SignalFrame:
    """Return a new frame with the bracket's exits layered on (entries untouched)."""
    if not spec.active:
        return frame
    target = frame.target_distance
    if spec.take_profit_r is not None:
        stop = frame.stop_distance.astype(float)
        tp = stop * float(spec.take_profit_r)
        tp[~np.isfinite(tp) | (tp <= 0)] = np.nan
        target = tp if target is None else pd.concat([target.astype(float), tp], axis=1).min(axis=1)
    time_stop = frame.time_stop_bars
    if spec.time_stop_days is not None:
        bars = days_to_bars(float(spec.time_stop_days), timeframe)
        time_stop = bars if time_stop is None else min(int(time_stop), bars)
    return SignalFrame(
        desired=frame.desired,
        stop_distance=frame.stop_distance,
        strength=frame.strength,
        target_distance=target,
        time_stop_bars=time_stop,
        trail_activate_r=spec.trail_activate_r if spec.trail_r is not None else frame.trail_activate_r,
        trail_r=spec.trail_r if spec.trail_r is not None else frame.trail_r,
    )
