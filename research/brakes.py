"""Trader Policy v1 brakes (plan row R18, ``docs/TRADER_PLAN_2026-11-05.md`` section 4.3), SIMULATION ONLY.

Circuit breakers that act on NEW ENTRIES ONLY: a brake can shrink or block the
next entry, never close, reduce or otherwise touch an open position, whose stop
and exit stay the rule's own. The research engine (:func:`research.engine.run_vectorized`)
consults an :class:`EntryBrakes` state machine once per bar, right before its
entries, and reports it every bar close, every entry and every exit; with no
brakes given the engine is bit-for-bit what it was.

The brakes, each fixed before the first run and never tuned here:

- **Turtle ladder** — the entry size is multiplied by 0.8 once the account is
  10 % below its equity peak and by 0.64 at 20 %; the multiplier is restored
  to 1 only when the equity makes a new high (the Turtles' "−20 % of size per
  −10 % of equity", Grossman-Zhou 1993). Entries only: unlike the Reference
  ladder of :mod:`research.sizing`, it never reduces an open position.
- **Hard stop** — 30 % below the equity peak: no new entry until an owner
  review; in a simulation that means until the simulated account restarts
  (every walk-forward test window starts fresh, so does the paper fleet's
  180-day window).
- **Entry caps** — at most one new entry per market per UTC day and (for a
  multi-market book) three per day; no new entry in a market on the bar after
  an exit there (no revenge trade).
- **Loss limits** (adapted from allocator v2's weekly limit, entries only, no
  liquidation, no cooldown): a 3 % loss over the trailing 24 hours blocks
  entries for the next 24 hours (rolling, not the calendar day); a 6 % loss
  from the equity at Monday 00:00 UTC blocks them until the next Monday; a
  10 % loss from the month's first bar blocks them until the next month.
- **Heat cap** — the total current risk (price to current stop, on current
  equity) across positions may not exceed 6 % (variant 8 %); positions whose
  markets' trailing 60-day return correlation is 0.70 or more count as one bet
  with half of the cap; when more signals fire than the cap allows, all open
  and new positions are sized down equally (:func:`heat_multipliers`), never
  "first come, first served". On one sleeve risking at most 2.5 % per trade it
  can never bind; the multi-market book (plan row R20) is where it acts.

Every count of a brake's triggers is kept per engine column so the study can
report how often each acted and what it cost. Nothing here can reach an
order: it is arithmetic on equity and bar times the engine hands over.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.allocator import asset_groups

Pair = Tuple[str, str]

#: The Turtle ladder: (drawdown from the equity peak, entry-size multiplier), escalating.
TURTLE_STEPS: Tuple[Tuple[float, float], ...] = ((0.10, 0.80), (0.20, 0.64))


@dataclass(frozen=True)
class TurtleLadder:
    """Entry-size multipliers by drawdown from the equity peak; restored to 1 only on a new equity high."""

    steps: Tuple[Tuple[float, float], ...] = TURTLE_STEPS

    def __post_init__(self) -> None:
        steps = tuple((float(dd), float(m)) for dd, m in self.steps)
        if not steps:
            raise ValueError("a ladder needs at least one step")
        last_dd, last_m = 0.0, 1.0
        for dd, m in steps:
            if not (last_dd < dd < 1.0) or not (0.0 < m < last_m):
                raise ValueError("ladder steps must have increasing drawdowns in (0, 1) and decreasing multipliers in (0, 1)")
            last_dd, last_m = dd, m
        object.__setattr__(self, "steps", steps)

    def multiplier(self, drawdown: np.ndarray) -> np.ndarray:
        """The step multiplier for a drawdown (vectorized): 1 above the first threshold, the deepest step reached below it."""
        dd = np.asarray(drawdown, dtype=float)
        out = np.ones_like(dd)
        for threshold, mult in self.steps:
            out = np.where(dd >= threshold - 1e-12, mult, out)
        return out

    @property
    def label(self) -> str:
        return "turtle " + ", ".join(f"x{m:g}@-{dd * 100:g}%" for dd, m in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "turtle", "steps": [[dd, m] for dd, m in self.steps]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TurtleLadder":
        return cls(steps=tuple((float(dd), float(m)) for dd, m in data.get("steps", TURTLE_STEPS)))


BRAKE_NAMES: Tuple[str, ...] = ("ladder", "hard_stop", "entry_cap_market_day", "entry_after_exit", "daily_loss", "weekly_loss",
                                "monthly_loss", "heat_cap")


@dataclass(frozen=True)
class BrakeSpec:
    """Which brakes are on, with their fixed numbers. ``None`` / ``False`` switches a brake off."""

    ladder: Optional[TurtleLadder] = TurtleLadder()
    hard_stop_dd: Optional[float] = 0.30
    max_entries_per_market_per_day: Optional[int] = 1
    max_entries_per_day: Optional[int] = 3  # the book (plan row R20); one sleeve meets the per-market cap first
    no_entry_bar_after_exit: bool = True
    daily_loss_limit: Optional[float] = 0.03
    weekly_loss_limit: Optional[float] = 0.06
    monthly_loss_limit: Optional[float] = 0.10
    heat_cap: Optional[float] = 0.06
    heat_group_share: float = 0.50  # a group of correlated markets may hold at most this share of the heat cap
    corr_threshold: float = 0.70
    corr_lookback_days: int = 60

    def __post_init__(self) -> None:
        for name in ("hard_stop_dd", "daily_loss_limit", "weekly_loss_limit", "monthly_loss_limit", "heat_cap"):
            v = getattr(self, name)
            if v is not None and not (0.0 < float(v) < 1.0):
                raise ValueError(f"{name} must be in (0, 1) or None")
        for name in ("max_entries_per_market_per_day", "max_entries_per_day"):
            v = getattr(self, name)
            if v is not None and int(v) < 1:
                raise ValueError(f"{name} must be at least 1 or None")
        if not (0.0 < float(self.heat_group_share) <= 1.0):
            raise ValueError("heat_group_share must be in (0, 1]")
        if not (0.0 < float(self.corr_threshold) <= 1.0):
            raise ValueError("corr_threshold must be in (0, 1]")
        if int(self.corr_lookback_days) < 2:
            raise ValueError("corr_lookback_days must be at least 2")

    @property
    def active(self) -> bool:
        return any([self.ladder is not None, self.hard_stop_dd is not None, self.max_entries_per_market_per_day is not None,
                    self.max_entries_per_day is not None, self.no_entry_bar_after_exit, self.daily_loss_limit is not None,
                    self.weekly_loss_limit is not None, self.monthly_loss_limit is not None, self.heat_cap is not None])

    @property
    def label(self) -> str:
        parts: List[str] = []
        if self.ladder is not None:
            parts.append(self.ladder.label)
        if self.hard_stop_dd is not None:
            parts.append(f"hard stop -{self.hard_stop_dd * 100:g}%")
        caps = []
        if self.max_entries_per_market_per_day is not None:
            caps.append(f"{self.max_entries_per_market_per_day}/market/day")
        if self.max_entries_per_day is not None:
            caps.append(f"{self.max_entries_per_day}/day")
        if self.no_entry_bar_after_exit:
            caps.append("none on the bar after an exit")
        if caps:
            parts.append("entry caps " + ", ".join(caps))
        limits = []
        if self.daily_loss_limit is not None:
            limits.append(f"{self.daily_loss_limit * 100:g}%/24h")
        if self.weekly_loss_limit is not None:
            limits.append(f"{self.weekly_loss_limit * 100:g}%/week")
        if self.monthly_loss_limit is not None:
            limits.append(f"{self.monthly_loss_limit * 100:g}%/month")
        if limits:
            parts.append("loss limits " + ", ".join(limits))
        if self.heat_cap is not None:
            parts.append(f"heat cap {self.heat_cap * 100:g}% (group {self.heat_group_share * 100:g}%, corr >= {self.corr_threshold:g})")
        return "; ".join(parts) if parts else "no brakes"

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out["ladder"] = None if self.ladder is None else self.ladder.to_dict()
        out["label"] = self.label
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BrakeSpec":
        keys = ("hard_stop_dd", "max_entries_per_market_per_day", "max_entries_per_day", "no_entry_bar_after_exit", "daily_loss_limit",
                "weekly_loss_limit", "monthly_loss_limit", "heat_cap", "heat_group_share", "corr_threshold", "corr_lookback_days")
        kwargs = {k: data[k] for k in keys if k in data}
        lad = data.get("ladder")
        kwargs["ladder"] = None if lad is None else TurtleLadder.from_dict(lad)
        return cls(**kwargs)


#: No brake at all (the engine's default behaviour, expressed as a spec).
BRAKES_OFF = BrakeSpec(ladder=None, hard_stop_dd=None, max_entries_per_market_per_day=None, max_entries_per_day=None,
                       no_entry_bar_after_exit=False, daily_loss_limit=None, weekly_loss_limit=None, monthly_loss_limit=None, heat_cap=None)
#: The Turtle ladder alone (a sizing tier's own ladder, the other brakes off).
TURTLE_LADDER_ONLY = dataclasses.replace(BRAKES_OFF, ladder=TurtleLadder())
#: Every brake of section 4.3 on, with its pre-registered number.
TRADER_BRAKES = BrakeSpec()
#: The heat-cap variant of section 4.3 (8 % instead of 6 %).
TRADER_BRAKES_HEAT8 = dataclasses.replace(TRADER_BRAKES, heat_cap=0.08)


# -- the bar calendar -----------------------------------------------------------------------------

@dataclass(frozen=True)
class BarCalendar:
    """UTC day, Monday-based week and month index of every bar, and how many bars make 24 hours."""

    day: np.ndarray  # days since 1970-01-01 of the bar's open
    week: np.ndarray  # weeks since Monday 1969-12-29 (so a week starts Monday 00:00 UTC)
    month: np.ndarray  # year * 12 + month - 1
    bars_per_day: int

    @classmethod
    def from_times(cls, times) -> "BarCalendar":
        idx = pd.DatetimeIndex(times)
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        if len(idx) == 0:
            raise ValueError("a calendar needs at least one bar")
        # Stored Parquet candles come back with MICROSECOND timestamps and resampled bars with nanoseconds: work in seconds,
        # never in the index's raw integer unit (a unit mix-up here put every 4H bar on one day in the first R18 run).
        seconds = (idx - pd.Timestamp("1970-01-01")).total_seconds().to_numpy(dtype=float)
        day = np.floor(seconds / 86_400.0).astype(np.int64)
        week = (day + 3) // 7  # 1970-01-01 was a Thursday: shifting by 3 days puts Monday at the week boundary
        month = idx.year.to_numpy() * 12 + idx.month.to_numpy() - 1
        if len(seconds) >= 2:
            step = float(np.median(np.diff(seconds)))
            bars_per_day = max(1, int(round(86_400.0 / step))) if step > 0 else 1
        else:
            bars_per_day = 1
        return cls(day=np.asarray(day, dtype=np.int64), week=np.asarray(week, dtype=np.int64), month=np.asarray(month, dtype=np.int64),
                   bars_per_day=int(bars_per_day))

    @property
    def n_bars(self) -> int:
        return int(self.day.size)


# -- the per-column state machine the engine drives -----------------------------------------------

class EntryBrakes:
    """The brakes of one simulation, vectorized over the engine's columns (each column its own account).

    Call order per bar ``i`` (the engine's): :meth:`on_exit` for every exit as it happens, then
    :meth:`entry_multiplier` once before the entries, :meth:`on_entry` for the entries made, and
    :meth:`on_bar_close` with the bar's closing equity. Every brake reads only what happened up
    to the previous bar close plus this bar's own exits, never this bar's close.
    """

    def __init__(self, spec: BrakeSpec, n_cols: int, init_equity: float, calendar: BarCalendar) -> None:
        if n_cols < 1:
            raise ValueError("n_cols must be positive")
        self.spec = spec
        self.C = int(n_cols)
        self.cal = calendar
        C = self.C
        self.peak = np.full(C, float(init_equity))
        self.lad_mult = np.ones(C)
        self.halted = np.zeros(C, dtype=bool)
        self.last_entry_day = np.full(C, np.iinfo(np.int64).min, dtype=np.int64)
        self.last_exit_bar = np.full(C, -10, dtype=np.int64)
        self.equity_hist = np.full((calendar.n_bars, C), np.nan)
        self.init_equity = float(init_equity)
        self.daily_block_until = np.full(C, -1, dtype=np.int64)
        self.week_ref = np.full(C, float(init_equity))
        self.month_ref = np.full(C, float(init_equity))
        self.week_blocked_id = np.full(C, np.iinfo(np.int64).min, dtype=np.int64)  # the week in which the weekly limit tripped
        self.month_blocked_id = np.full(C, np.iinfo(np.int64).min, dtype=np.int64)
        self.cur_week: Optional[int] = None
        self.cur_month: Optional[int] = None
        self.entries_today = np.zeros(C, dtype=np.int64)
        self.counts: Dict[str, np.ndarray] = {name: np.zeros(C, dtype=np.int64) for name in BRAKE_NAMES}
        self.trips: Dict[str, np.ndarray] = {name: np.zeros(C, dtype=np.int64) for name in ("hard_stop", "daily_loss", "weekly_loss", "monthly_loss")}
        self.opportunities = np.zeros(C, dtype=np.int64)
        self.entries_at = {f"x{m:g}": np.zeros(C, dtype=np.int64) for _, m in (spec.ladder.steps if spec.ladder is not None else ())}
        self.bars_blocked = np.zeros(C, dtype=np.int64)  # bars on which at least one brake would have blocked an entry
        self.ladder_bars = {f"x{m:g}": np.zeros(C, dtype=np.int64) for _, m in (spec.ladder.steps if spec.ladder is not None else ())}

    # -- the engine's calls -------------------------------------------------------------------------------

    def entry_multiplier(self, i: int, want: np.ndarray, base_fraction: np.ndarray, stop_pct: np.ndarray) -> np.ndarray:
        """Multiplier (0..1) for the entry fraction of every column at bar ``i`` (0 = the entry is blocked).

        ``want``: columns that would enter at this bar's open; ``base_fraction``: their entry fraction before the
        brakes; ``stop_pct``: the stop distance as a fraction of the decision close (NaN without a stop).
        """
        spec = self.spec
        want = np.asarray(want, dtype=bool) & (np.nan_to_num(np.asarray(base_fraction, dtype=float)) > 0.0)
        mult = np.ones(self.C)
        if not want.any():
            return mult
        self.opportunities += want
        blocked = np.zeros(self.C, dtype=bool)
        if spec.ladder is not None:
            cut = want & (self.lad_mult < 1.0)
            mult = np.where(cut, self.lad_mult, mult)
            self.counts["ladder"] += cut
            for key, (_, m) in zip(self.entries_at, spec.ladder.steps):
                self.entries_at[key] += want & np.isclose(self.lad_mult, m)
        if spec.hard_stop_dd is not None:
            hit = want & self.halted
            self.counts["hard_stop"] += hit
            blocked |= hit
        if spec.max_entries_per_market_per_day is not None:
            # One engine column is one market's sleeve: the entries already made on this UTC day count against the cap.
            today = self.last_entry_day == self.cal.day[i]
            hit = want & today & (self.entries_today >= int(spec.max_entries_per_market_per_day))
            self.counts["entry_cap_market_day"] += hit
            blocked |= hit
        if spec.no_entry_bar_after_exit:
            hit = want & ((i - self.last_exit_bar) == 1)
            self.counts["entry_after_exit"] += hit
            blocked |= hit
        if spec.daily_loss_limit is not None:
            hit = want & (i < self.daily_block_until)
            self.counts["daily_loss"] += hit
            blocked |= hit
        if spec.weekly_loss_limit is not None:
            # Blocked for the rest of the week the limit tripped in; a bar that opens in the next week may enter again.
            hit = want & (self.week_blocked_id == self.cal.week[i])
            self.counts["weekly_loss"] += hit
            blocked |= hit
        if spec.monthly_loss_limit is not None:
            hit = want & (self.month_blocked_id == self.cal.month[i])
            self.counts["monthly_loss"] += hit
            blocked |= hit
        if spec.heat_cap is not None:
            # One sleeve holds one position at a time, so the new entry is the whole heat of this column.
            sp = np.asarray(stop_pct, dtype=float)
            risk = np.where(np.isfinite(sp) & (sp > 0), np.asarray(base_fraction, dtype=float) * mult * sp, 0.0)
            over = want & ~blocked & (risk > float(spec.heat_cap) + 1e-12)
            if over.any():
                mult = np.where(over, mult * float(spec.heat_cap) / np.where(over, risk, 1.0), mult)
                self.counts["heat_cap"] += over
        mult = np.where(blocked, 0.0, mult)
        self.bars_blocked += blocked
        return mult

    def on_entry(self, i: int, mask: np.ndarray) -> None:
        mask = np.asarray(mask, dtype=bool)
        if not mask.any():
            return
        same_day = mask & (self.last_entry_day == self.cal.day[i])
        self.entries_today = np.where(same_day, self.entries_today + 1, np.where(mask, 1, self.entries_today))
        self.last_entry_day = np.where(mask, self.cal.day[i], self.last_entry_day)

    def on_exit(self, i: int, mask: np.ndarray) -> None:
        mask = np.asarray(mask, dtype=bool)
        self.last_exit_bar = np.where(mask, i, self.last_exit_bar)

    def on_bar_close(self, i: int, equity: np.ndarray) -> None:
        spec = self.spec
        eq = np.asarray(equity, dtype=float)
        self.equity_hist[i] = eq
        self.peak = np.maximum(self.peak, eq)
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.where(self.peak > 0, 1.0 - eq / self.peak, 0.0)
        if spec.ladder is not None:
            step = spec.ladder.multiplier(dd)
            # Escalate with the drawdown; never step back up except on a new equity high (drawdown zero).
            self.lad_mult = np.where(dd <= 1e-15, 1.0, np.minimum(self.lad_mult, step))
            for key, (_, m) in zip(self.ladder_bars, spec.ladder.steps):
                self.ladder_bars[key] += np.isclose(self.lad_mult, m)
        if spec.hard_stop_dd is not None:
            new = ~self.halted & (dd >= float(spec.hard_stop_dd) - 1e-12)
            self.trips["hard_stop"] += new
            self.halted |= new
        if spec.daily_loss_limit is not None:
            bpd = self.cal.bars_per_day
            if i >= bpd:
                ref = self.equity_hist[i - bpd]
                with np.errstate(divide="ignore", invalid="ignore"):
                    loss = np.where(ref > 0, eq / ref - 1.0, 0.0)
                tripped = (loss <= -float(spec.daily_loss_limit) + 1e-12) & (i >= self.daily_block_until)
                self.trips["daily_loss"] += tripped
                self.daily_block_until = np.where(tripped, i + 1 + bpd, self.daily_block_until)
        prev = self.equity_hist[i - 1] if i > 0 else np.full(self.C, self.init_equity)
        if spec.weekly_loss_limit is not None:
            week = int(self.cal.week[i])
            if week != self.cur_week:  # the first bar of a week: its reference is the equity at the previous close (Monday 00:00 UTC)
                self.cur_week = week
                self.week_ref = prev.copy()
            already = self.week_blocked_id == week
            tripped = ~already & (eq <= self.week_ref * (1.0 - float(spec.weekly_loss_limit)) + 1e-12)
            self.trips["weekly_loss"] += tripped
            self.week_blocked_id = np.where(tripped, week, self.week_blocked_id)
        if spec.monthly_loss_limit is not None:
            month = int(self.cal.month[i])
            if month != self.cur_month:
                self.cur_month = month
                self.month_ref = prev.copy()
            already = self.month_blocked_id == month
            tripped = ~already & (eq <= self.month_ref * (1.0 - float(spec.monthly_loss_limit)) + 1e-12)
            self.trips["monthly_loss"] += tripped
            self.month_blocked_id = np.where(tripped, month, self.month_blocked_id)

    # -- what happened --------------------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Per-column counts: entry opportunities, how often each brake cut or blocked one, the trips, the ladder's bars."""
        return {
            "spec": self.spec.to_dict(),
            "opportunities": self.opportunities.copy(),
            "counts": {k: v.copy() for k, v in self.counts.items()},
            "trips": {k: v.copy() for k, v in self.trips.items()},
            "entries_at": {k: v.copy() for k, v in self.entries_at.items()},
            "ladder_bars": {k: v.copy() for k, v in self.ladder_bars.items()},
            "bars_blocked": self.bars_blocked.copy(),
            "bars": int(self.cal.n_bars),
        }


def summary_for_column(summary: Mapping[str, Any], column: int) -> Dict[str, Any]:
    """One column's slice of :meth:`EntryBrakes.summary` as plain numbers (JSON-ready)."""
    def pick(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: pick(v) for k, v in value.items()}
        if isinstance(value, np.ndarray):
            return int(value[column])
        return value
    return {k: pick(v) for k, v in summary.items()}


def merge_summaries(parts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Sum the counts of several single-column summaries (the walk-forward's test windows) into one."""
    parts = [p for p in parts if p]
    if not parts:
        return {}
    out: Dict[str, Any] = {"spec": parts[0].get("spec"), "bars": sum(int(p.get("bars", 0)) for p in parts)}
    for key in ("opportunities", "bars_blocked"):
        out[key] = sum(int(p.get(key, 0)) for p in parts)
    for key in ("counts", "trips", "entries_at", "ladder_bars"):
        names = sorted({n for p in parts for n in (p.get(key) or {})})
        out[key] = {n: sum(int((p.get(key) or {}).get(n, 0)) for p in parts) for n in names}
    return out


# -- the book-level heat cap (plan row R20) -------------------------------------------------------------

def heat_groups(asset_of: Mapping[str, str], correlations: Mapping[Pair, Optional[float]], threshold: float) -> List[List[str]]:
    """Positions grouped into bets: the same market always, markets whose correlation is >= ``threshold`` (or unknown) together."""
    out: List[List[str]] = []
    for coins in asset_groups(sorted(set(asset_of.values())), correlations, threshold):
        out.append(sorted(n for n, a in asset_of.items() if a in coins))
    return out


def heat_multipliers(risks: Mapping[str, float], groups: Sequence[Sequence[str]], cap: float, group_share: float = 0.5) -> Dict[str, float]:
    """Scale factors (<= 1) per position that bring every bet under ``group_share x cap`` and the total under ``cap``.

    ``risks`` are the current risks (price to current stop, as a fraction of equity) of the open positions and
    the entries wanted now. Within a bet every position is scaled by the same factor; then, if the total is
    still above the cap, every position is scaled by the same factor again — never first come, first served.
    """
    if not (0.0 < cap < 1.0):
        raise ValueError("cap must be in (0, 1)")
    names = list(risks)
    mult = {n: 1.0 for n in names}
    seen = set()
    for g in groups:
        members = [n for n in g if n in risks]
        seen.update(members)
        total = sum(max(0.0, float(risks[n])) for n in members)
        limit = float(group_share) * float(cap)
        if total > limit + 1e-12:
            f = limit / total
            for n in members:
                mult[n] *= f
    for n in names:  # a position in no listed group is its own bet
        if n not in seen:
            r = max(0.0, float(risks[n]))
            limit = float(group_share) * float(cap)
            if r > limit + 1e-12:
                mult[n] *= limit / r
    total = sum(max(0.0, float(risks[n])) * mult[n] for n in names)
    if total > float(cap) + 1e-12:
        f = float(cap) / total
        for n in names:
            mult[n] *= f
    return mult


def trailing_return_correlations(closes: pd.DataFrame, lookback_days: int, min_days: Optional[int] = None) -> Dict[Pair, pd.Series]:
    """Per market pair, the correlation of daily returns over the trailing window, usable on the NEXT day (shifted by one)."""
    c = closes.astype(float).sort_index()
    rets = c / c.shift(1) - 1.0
    out: Dict[Pair, pd.Series] = {}
    cols = sorted(rets.columns)
    md = int(min_days) if min_days is not None else max(2, int(lookback_days) // 3)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            out[(a, b)] = rets[a].rolling(int(lookback_days), min_periods=md).corr(rets[b]).shift(1)
    return out


def finite_or_none(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
