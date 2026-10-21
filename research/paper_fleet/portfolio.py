"""The jointly sized BTC+ETH x S1/S2/S4 portfolio run forward as ONE paper account (SIMULATION ONLY).

The research construction (:func:`research.portfolio.combine_sized`), day by day:

1. six FULL-SIZE sleeves (all-in when long, no ladder) run bar by bar, each
   with the rule parameters the research selected;
2. their equity is compounded into UTC calendar-day returns (a bar belongs to
   the day it opens in; a day without bars is a cash day, return 0);
3. weights proportional to 1 / trailing 60-day sleeve volatility (past days
   only), one portfolio vol target of 15 % on the trailing 30-day volatility of
   the weighted return (applied to the next day, capped at 1 = no leverage),
   and one portfolio drawdown ladder (half at 7.5 %, flat at 15 %, 30-day
   cooling-off) on the portfolio's own forward equity.

The weights and the vol scale are computed with the research functions
(:func:`research.portfolio.rolling_inverse_vol_weights`,
:func:`research.portfolio.vol_target_scale`) over the sleeves' whole daily
history, which starts ``warmup_days`` before the fleet so day one is sized like
the research's steady state; the warm-up days are not part of the forward
record. The ladder starts at the first full UTC day after the fleet started,
from 1.0, as the research ladder started at its out-of-sample start. As in the
research, moving money between sleeves each day is assumed to cost nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from research.portfolio import rolling_inverse_vol_weights, vol_target_scale
from research.sizing import LADDER_MULTIPLIERS, ladder_step

from research.paper_fleet.config import PortfolioSpec

DAY = pd.Timedelta(days=1)


def day_of(bar_open: pd.Timestamp) -> str:
    return pd.Timestamp(bar_open).tz_convert("UTC").strftime("%Y-%m-%d")


def _day_ts(day: str) -> pd.Timestamp:
    return pd.Timestamp(day, tz="UTC")


@dataclass
class SleeveDays:
    """One sleeve's UTC-day bookkeeping (research ``to_daily_returns`` on its bar-by-bar equity)."""

    open_day: Optional[str] = None  # UTC day of the bars processed since the last closed day
    day_equity: Optional[float] = None  # equity after the last processed bar of ``open_day``
    prev_close_equity: Optional[float] = None  # equity after the last bar of the previous day that had bars
    done_through: Optional[str] = None  # every day up to and including this one is final for this sleeve
    closed: Dict[str, float] = field(default_factory=dict)  # day -> return, waiting to be moved into the book

    def to_dict(self) -> Dict[str, Any]:
        return {"open_day": self.open_day, "day_equity": self.day_equity, "prev_close_equity": self.prev_close_equity,
                "done_through": self.done_through, "closed": dict(self.closed)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SleeveDays":
        return cls(open_day=data.get("open_day"), day_equity=data.get("day_equity"), prev_close_equity=data.get("prev_close_equity"),
                   done_through=data.get("done_through"), closed={str(k): float(v) for k, v in (data.get("closed") or {}).items()})

    def _mark_done(self, day: str) -> None:
        if self.done_through is None or day > self.done_through:
            self.done_through = day

    def _close_day(self) -> None:
        if self.open_day is None or self.day_equity is None:
            return
        if self.prev_close_equity:
            self.closed[self.open_day] = self.day_equity / self.prev_close_equity - 1.0
        self.prev_close_equity = self.day_equity
        self._mark_done(self.open_day)
        self.open_day = None
        self.day_equity = None

    def on_bar(self, bar_open: pd.Timestamp, bar_close: pd.Timestamp, equity: float, start_equity: float) -> None:
        day = day_of(bar_open)
        if self.prev_close_equity is None:
            self.prev_close_equity = float(start_equity)
        if self.open_day is not None and day != self.open_day:
            self._close_day()
        # Every day before this bar's day is final now (days without bars are cash days).
        self._mark_done(day_of(_day_ts(day) - DAY))
        self.open_day = day
        self.day_equity = float(equity)
        if pd.Timestamp(bar_close) >= _day_ts(day) + DAY:
            self._close_day()


@dataclass
class PortfolioBook:
    """The portfolio's daily history and forward equity (JSON-serialisable)."""

    forward_start_day: str
    daily: Dict[str, Dict[str, float]] = field(default_factory=dict)  # day -> sleeve -> return (warm-up and forward)
    done_days: List[str] = field(default_factory=list)  # forward days already booked
    equity: float = 1.0  # forward equity index, starts at 1.0
    peak: float = 1.0
    lad_level: int = 0
    lad_flat: int = 0
    lad_mult: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"forward_start_day": self.forward_start_day, "daily": self.daily, "done_days": list(self.done_days), "equity": self.equity,
                "peak": self.peak, "lad_level": self.lad_level, "lad_flat": self.lad_flat, "lad_mult": self.lad_mult}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioBook":
        return cls(forward_start_day=data["forward_start_day"], daily={k: {n: float(x) for n, x in v.items()} for k, v in (data.get("daily") or {}).items()},
                   done_days=list(data.get("done_days") or []), equity=float(data.get("equity", 1.0)), peak=float(data.get("peak", 1.0)),
                   lad_level=int(data.get("lad_level", 0)), lad_flat=int(data.get("lad_flat", 0)), lad_mult=float(data.get("lad_mult", 1.0)))

    def absorb(self, name: str, sleeve: SleeveDays) -> None:
        for day, ret in sorted(sleeve.closed.items()):
            self.daily.setdefault(day, {})[name] = float(ret)
        sleeve.closed.clear()

    def days_ready(self, sleeves: Mapping[str, SleeveDays]) -> List[str]:
        """Forward days every sleeve has finished and that are not booked yet, oldest first."""
        through = [s.done_through for s in sleeves.values()]
        if not through or any(t is None for t in through):
            return []
        last = min(through)
        start = max(self.forward_start_day, day_of(_day_ts(self.done_days[-1]) + DAY)) if self.done_days else self.forward_start_day
        if last < start:
            return []
        return [d.strftime("%Y-%m-%d") for d in pd.date_range(_day_ts(start), _day_ts(last), freq="D")]


def daily_frame(book: PortfolioBook, names: List[str], *, through: Optional[str] = None) -> pd.DataFrame:
    """Days x sleeves returns on every calendar day up to ``through`` (a missing sleeve-day is a cash day, 0)."""
    if not book.daily:
        return pd.DataFrame(columns=names, dtype=float)
    first = min(book.daily)
    last = through or max(book.daily)
    days = pd.date_range(_day_ts(first), _day_ts(last), freq="D", name="day")
    rows = [[book.daily.get(d.strftime("%Y-%m-%d"), {}).get(n, 0.0) for n in names] for d in days]
    return pd.DataFrame(rows, index=days, columns=names, dtype=float)


def book_day(book: PortfolioBook, spec: PortfolioSpec, day: str, sleeve_in_position: Mapping[str, bool]) -> Dict[str, Any]:
    """Book one completed forward day: weights, vol scale and ladder exactly as ``combine_sized``; returns the journal record."""
    names = [n for n, _ in spec.sleeves]
    frame = daily_frame(book, names, through=day)
    weights = rolling_inverse_vol_weights(frame, spec.weight_lookback_days)
    raw = (frame * weights).sum(axis=1)
    scale = vol_target_scale(raw, spec.target_vol, spec.vol_lookback_days, cap=spec.cap)
    key = _day_ts(day)
    w = weights.loc[key]
    r_raw = float(raw.loc[key])
    s = float(scale.loc[key])
    mult = float(book.lad_mult)
    port_r = mult * r_raw * s
    book.equity *= 1.0 + port_r
    level_before = book.lad_level
    lvl, flt, pk = ladder_step(np.array([book.lad_level]), np.array([book.lad_flat]), np.array([book.peak]), np.array([book.equity]), spec.ladder)
    book.lad_level, book.lad_flat, book.peak = int(lvl[0]), int(flt[0]), float(pk[0])
    book.lad_mult = float(LADDER_MULTIPLIERS[book.lad_level])
    book.done_days.append(day)
    # Exposure for the next day: next day's weights/scale are only known after it; report today's as an indication.
    exposure = {n: float(w[n]) * s * mult * (1.0 if sleeve_in_position.get(n) else 0.0) for n in names}
    return {
        "type": "portfolio_day", "day": day, "sleeve_returns": {n: float(frame.loc[key, n]) for n in names},
        "weights": {n: float(w[n]) for n in names}, "raw_return": r_raw, "vol_scale": s, "ladder_multiplier": mult,
        "portfolio_return": port_r, "equity_index": book.equity, "ladder_level_after": book.lad_level,
        "ladder_changed": book.lad_level != level_before, "exposure_end_of_day": exposure,
        "gross_exposure_end_of_day": float(sum(exposure.values())),
    }
