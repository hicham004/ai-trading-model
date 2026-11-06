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

A portfolio spec with an allocator (plan row R5b) books its days with allocator
v2 instead (:func:`research.allocator.step_day`, the function the research
study ran): the same weights, vol scale and ladder, plus the correlation cap,
the weekly loss limit and its cooldown, sized from the previous close only.
For that the book also keeps, per day, whether each sleeve was long at the
close and one close per coin; its journal carries the v1 rules on the same
sleeves as a paired reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from research.allocator import (
    AllocatorState,
    DayInputs,
    base_sizing,
    daily_closes_to_returns,
    previous_close_positions,
    step_day,
    trailing_correlations,
)
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
    day_in_position: Optional[bool] = None  # long after the last processed bar of ``open_day``
    day_close: Optional[float] = None  # close of the last processed bar of ``open_day``
    closed_positions: Dict[str, bool] = field(default_factory=dict)  # day -> long at that day's close, waiting for the book
    closed_closes: Dict[str, float] = field(default_factory=dict)  # day -> the coin's close at that day's last bar

    def to_dict(self) -> Dict[str, Any]:
        return {"open_day": self.open_day, "day_equity": self.day_equity, "prev_close_equity": self.prev_close_equity,
                "done_through": self.done_through, "closed": dict(self.closed), "day_in_position": self.day_in_position,
                "day_close": self.day_close, "closed_positions": dict(self.closed_positions), "closed_closes": dict(self.closed_closes)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SleeveDays":
        return cls(open_day=data.get("open_day"), day_equity=data.get("day_equity"), prev_close_equity=data.get("prev_close_equity"),
                   done_through=data.get("done_through"), closed={str(k): float(v) for k, v in (data.get("closed") or {}).items()},
                   day_in_position=data.get("day_in_position"), day_close=data.get("day_close"),
                   closed_positions={str(k): bool(v) for k, v in (data.get("closed_positions") or {}).items()},
                   closed_closes={str(k): float(v) for k, v in (data.get("closed_closes") or {}).items()})

    def _mark_done(self, day: str) -> None:
        if self.done_through is None or day > self.done_through:
            self.done_through = day

    def _close_day(self) -> None:
        if self.open_day is None or self.day_equity is None:
            return
        if self.prev_close_equity:
            self.closed[self.open_day] = self.day_equity / self.prev_close_equity - 1.0
        if self.day_in_position is not None:
            self.closed_positions[self.open_day] = bool(self.day_in_position)
        if self.day_close is not None:
            self.closed_closes[self.open_day] = float(self.day_close)
        self.prev_close_equity = self.day_equity
        self._mark_done(self.open_day)
        self.open_day = None
        self.day_equity = None
        self.day_in_position = None
        self.day_close = None

    def on_bar(self, bar_open: pd.Timestamp, bar_close: pd.Timestamp, equity: float, start_equity: float, *,
               in_position: Optional[bool] = None, close: Optional[float] = None) -> None:
        day = day_of(bar_open)
        if self.prev_close_equity is None:
            self.prev_close_equity = float(start_equity)
        if self.open_day is not None and day != self.open_day:
            self._close_day()
        # Every day before this bar's day is final now (days without bars are cash days).
        self._mark_done(day_of(_day_ts(day) - DAY))
        self.open_day = day
        self.day_equity = float(equity)
        if in_position is not None:
            self.day_in_position = bool(in_position)
        if close is not None:
            self.day_close = float(close)
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
    positions: Dict[str, Dict[str, bool]] = field(default_factory=dict)  # day -> sleeve -> long at that day's close
    prices: Dict[str, Dict[str, float]] = field(default_factory=dict)  # day -> coin -> close of that day's last bar
    alloc: Optional[Dict[str, Any]] = None  # allocator v2's state (``AllocatorState``), None for allocator v1

    def to_dict(self) -> Dict[str, Any]:
        return {"forward_start_day": self.forward_start_day, "daily": self.daily, "done_days": list(self.done_days), "equity": self.equity,
                "peak": self.peak, "lad_level": self.lad_level, "lad_flat": self.lad_flat, "lad_mult": self.lad_mult,
                "positions": self.positions, "prices": self.prices, "alloc": self.alloc}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioBook":
        return cls(forward_start_day=data["forward_start_day"], daily={k: {n: float(x) for n, x in v.items()} for k, v in (data.get("daily") or {}).items()},
                   done_days=list(data.get("done_days") or []), equity=float(data.get("equity", 1.0)), peak=float(data.get("peak", 1.0)),
                   lad_level=int(data.get("lad_level", 0)), lad_flat=int(data.get("lad_flat", 0)), lad_mult=float(data.get("lad_mult", 1.0)),
                   positions={k: {n: bool(x) for n, x in v.items()} for k, v in (data.get("positions") or {}).items()},
                   prices={k: {n: float(x) for n, x in v.items()} for k, v in (data.get("prices") or {}).items()},
                   alloc=data.get("alloc"))

    def absorb(self, name: str, sleeve: SleeveDays, instrument: Optional[str] = None) -> None:
        for day, ret in sorted(sleeve.closed.items()):
            self.daily.setdefault(day, {})[name] = float(ret)
        for day, held in sorted(sleeve.closed_positions.items()):
            self.positions.setdefault(day, {})[name] = bool(held)
        if instrument is not None:
            for day, close in sorted(sleeve.closed_closes.items()):
                self.prices.setdefault(day, {})[instrument] = float(close)
        sleeve.closed.clear()
        sleeve.closed_positions.clear()
        sleeve.closed_closes.clear()

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


def position_frame(book: PortfolioBook, names: List[str]) -> pd.DataFrame:
    """Days with a record x sleeves: long at that day's close (1.0 / 0.0; NaN = no bar of that sleeve that day)."""
    days = sorted(book.positions)
    idx = pd.DatetimeIndex([_day_ts(d) for d in days], name="day")
    rows = [[float(book.positions[d][n]) if n in book.positions[d] else np.nan for n in names] for d in days]
    return pd.DataFrame(rows, index=idx, columns=names, dtype=float)


def price_frame(book: PortfolioBook, coins: List[str], index: pd.DatetimeIndex) -> pd.DataFrame:
    """One close per coin on every day of ``index`` (NaN where no bar closed that day)."""
    rows = [[book.prices.get(d.strftime("%Y-%m-%d"), {}).get(c, np.nan) for c in coins] for d in index]
    return pd.DataFrame(rows, index=index, columns=coins, dtype=float)


def book_day(book: PortfolioBook, spec: PortfolioSpec, day: str, sleeve_in_position: Mapping[str, bool]) -> Dict[str, Any]:
    """Book one completed forward day: weights, vol scale and ladder exactly as ``combine_sized``; returns the journal record."""
    if spec.allocator is not None:
        return book_day_v2(book, spec, day, sleeve_in_position)
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


def book_day_v2(book: PortfolioBook, spec: PortfolioSpec, day: str, sleeve_in_position: Mapping[str, bool]) -> Dict[str, Any]:
    """Book one completed forward day with allocator v2 (``research.allocator.step_day`` on inputs from days before it)."""
    cfg = spec.allocator
    names = [n for n, _ in spec.sleeves]
    assets = spec.sleeve_assets
    frame = daily_frame(book, names, through=day)
    weights, scale = base_sizing(frame, target_vol=spec.target_vol, vol_lookback_days=spec.vol_lookback_days,
                                 weight_lookback_days=spec.weight_lookback_days, cap=spec.cap)
    coins = sorted(set(assets.values()))
    corr = trailing_correlations(daily_closes_to_returns(price_frame(book, coins, frame.index)), cfg.corr_lookback_days, cfg.corr_min_days)
    held = previous_close_positions(position_frame(book, names), frame.index)
    key = _day_ts(day)
    inputs = DayInputs(returns={n: float(frame.loc[key, n]) for n in names}, weights={n: float(weights.loc[key, n]) for n in names},
                       vol_scale=float(scale.loc[key]), positions={n: bool(held.loc[key, n]) for n in names},
                       correlations={p: (None if pd.isna(c.loc[key]) else float(c.loc[key])) for p, c in corr.items()})
    state = AllocatorState.from_dict(book.alloc) if book.alloc else AllocatorState()
    rec = step_day(state, inputs, assets, cfg, spec.ladder)
    book.alloc = state.to_dict()
    book.equity, book.peak, book.lad_level, book.lad_flat, book.lad_mult = state.equity, state.peak, state.lad_level, state.lad_flat, state.lad_mult
    book.done_days.append(day)
    # Exposure after the day (an indication, as for v1): the day's final weights on the sleeves long now.
    exposure = {n: float(rec["final_weights"][n]) * (1.0 if sleeve_in_position.get(n) else 0.0) for n in names}
    out = {"type": "portfolio_day", "allocator": "v2", "day": day, "sleeve_returns": dict(inputs.returns)}
    out.update(rec)
    out.update({"exposure_end_of_day": exposure, "gross_exposure_end_of_day": float(sum(exposure.values()))})
    return out
