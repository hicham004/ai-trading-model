"""Bar-by-bar paper engine for one sleeve (SIMULATION ONLY).

A line-by-line transcription of :func:`research.engine.run_vectorized` for a
single column, so a paper account can advance one closed bar at a time, keep
its state in a JSON file between bars and report every virtual fill as it
happens. ``tests/test_paper_fleet_engine.py`` replays long synthetic series
through both and requires the same equity on every bar and the same trades.

Conventions (identical to the research engine):

- The decision made at the close of bar ``i-1`` (:class:`Decision`) is
  executed on bar ``i``: first the open position is checked against its stop
  on the bar's low (a gap below the stop fills at the worse open), then the
  take-profit target and the time stop; then, if nothing exited on this bar,
  the decision is executed at the bar's OPEN (exit when no longer desired,
  reduce-only de-risking, entry when flat and desired with the stop strictly
  below the open). A position opened at the open can be stopped by the same
  bar's low.
- Fees per side on traded notional; slippage moves every fill against the
  trader.
- ``sized`` accounts take the decision-bar fraction of equity (vol target,
  crash filter, regime scale) times the drawdown-ladder multiplier; reduce-only
  adjustments sell down when the fraction falls by more than the rebalance
  threshold, never add. Full-size accounts put 100 % of their cash in.
- The ladder (if any) reacts to the account's own equity after every bar.
- ``window_bars`` reproduces the walk-forward's test windows: every that many
  bars the sleeve restarts flat, exactly as each research test window did — an
  open position is closed at the last close of the window (fees and slippage,
  the research's ``end_of_data`` exit), the ladder starts again from the
  current equity, the next bar only makes a decision, and the decision made at
  the end of the old window is dropped. Without it a reduce-only position held
  for months could only ever shrink, which the research never did.

Plan row R18b (Trader Policy v1 in the fleet): a sleeve at a higher tier runs
with ``brakes`` — a scalar, resumable transcription of
:class:`research.brakes.EntryBrakes` (the entries-only Turtle ladder, the hard
stop, the entry caps, the rolling loss limits and the one-sleeve heat cap),
consulted once per bar right before an entry exactly where the research engine
consults it, and restarted with every 180-day window as each research test
window started it fresh. A brake only shrinks or blocks the next entry; no
brake closes, reduces or otherwise touches an open position. The per-trade
cap of the tier is not here: it is in the decision's ``fraction``
(:mod:`research.paper_fleet.signals` reads it from the candidate's stop through
``research.sizing.fraction_series``), and the engine is agnostic to how a
fraction was computed. Every entry records the money and the share of equity
at risk at its initial stop; every brake that acts is an event in the
journal. With ``brakes`` off the engine is bit-for-bit what it was.

Nothing here reads market data, talks to a network or can reach an order: it
is arithmetic on numbers it is given.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from research.brakes import BRAKE_NAMES, BrakeSpec
from research.engine import Costs
from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step

_EPS = 1e-12
_TRIP_NAMES = ("hard_stop", "daily_loss", "weekly_loss", "monthly_loss")


def _nan(value: Optional[float]) -> float:
    return float("nan") if value is None else float(value)


def _finite(value: float) -> bool:
    return value is not None and math.isfinite(value)


def _json_float(value: float) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else float(value)


@dataclass(frozen=True)
class EngineConfig:
    """Static rules of one sleeve (all simulation parameters)."""

    costs: Costs = Costs()
    init_cash: float = 10_000.0
    sized: bool = True  # entry = decision fraction x ladder; False = 100 % of cash (research size_fraction=1.0)
    ladder: Optional[LadderConfig] = None
    rebalance_threshold: Optional[float] = None
    time_stop_bars: Optional[int] = None
    trail_activate_r: Optional[float] = None
    trail_r: Optional[float] = None
    window_bars: Optional[int] = None  # restart flat every this many bars, like the walk-forward test windows (None = never)
    brakes: Optional[BrakeSpec] = None  # plan row R18b: the entry brakes of a higher tier (None = the engine as it was)
    bars_per_day: Optional[int] = None  # how many bars make 24 hours (the brakes' daily loss window); required with brakes

    def __post_init__(self) -> None:
        if not (self.init_cash > 0 and math.isfinite(self.init_cash)):
            raise ValueError("init_cash must be positive")
        if self.rebalance_threshold is not None and not (0.0 <= self.rebalance_threshold < 1.0):
            raise ValueError("rebalance_threshold must be in [0, 1) when given")
        if self.time_stop_bars is not None and int(self.time_stop_bars) <= 0:
            raise ValueError("time_stop_bars must be positive when given")
        if (self.trail_activate_r is None) != (self.trail_r is None):
            raise ValueError("trail_activate_r and trail_r go together")
        if self.trail_r is not None and (self.trail_r <= 0 or self.trail_activate_r < 0):
            raise ValueError("trail_activate_r must be >= 0 and trail_r > 0")
        if self.window_bars is not None and int(self.window_bars) < 2:
            raise ValueError("window_bars must be at least 2 when given")
        if self.brakes_on and (self.bars_per_day is None or int(self.bars_per_day) < 1):
            raise ValueError("brakes need bars_per_day (how many bars make 24 hours)")

    @property
    def overlay(self) -> bool:
        """Research ``overlay``: a fraction matrix, a ladder or a rebalance threshold is in use."""
        return self.sized or self.ladder is not None or self.rebalance_threshold is not None

    @property
    def brakes_on(self) -> bool:
        return self.brakes is not None and self.brakes.active


@dataclass(frozen=True)
class Decision:
    """What the strategy decided at the close of one bar (executed on the next bar).

    ``stop_distance`` / ``target_distance`` are price distances from ``close``
    (NaN = none); ``fraction`` is the entry fraction of equity for sized
    accounts (NaN or 0 = no entry; ignored by full-size accounts).
    """

    bar_time: str
    close: float
    desired: bool
    stop_distance: float = float("nan")
    target_distance: float = float("nan")
    fraction: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"bar_time": self.bar_time, "close": float(self.close), "desired": bool(self.desired),
                "stop_distance": _json_float(self.stop_distance), "target_distance": _json_float(self.target_distance),
                "fraction": _json_float(self.fraction)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Decision":
        return cls(bar_time=str(data["bar_time"]), close=float(data["close"]), desired=bool(data["desired"]),
                   stop_distance=_nan(data.get("stop_distance")), target_distance=_nan(data.get("target_distance")),
                   fraction=_nan(data.get("fraction")))


@dataclass
class BrakeState:
    """One sleeve's :class:`research.brakes.EntryBrakes` state between bars (JSON round-trips; plan row R18b).

    The research keeps the whole window's equity path; here only what the brakes read survives: the last
    ``bars_per_day`` closing equities (the daily loss window), the equity peak, the Turtle multiplier, the
    halt, the entry caps' day and bar, the loss limits' references and the period each limit tripped in.
    Counts are kept for the journal and the weekly report; they decide nothing.
    """

    peak: float = 0.0
    lad_mult: float = 1.0
    halted: bool = False
    last_entry_day: Optional[int] = None
    entries_today: int = 0
    last_exit_bar: int = -10
    equity_hist: List[float] = field(default_factory=list)  # closing equities of the last bars_per_day bars of this window
    init_equity: float = 0.0
    daily_block_until: int = -1
    week_ref: float = 0.0
    month_ref: float = 0.0
    week_blocked_id: Optional[int] = None
    month_blocked_id: Optional[int] = None
    cur_week: Optional[int] = None
    cur_month: Optional[int] = None
    opportunities: int = 0
    bars_blocked: int = 0
    counts: Dict[str, int] = field(default_factory=lambda: {name: 0 for name in BRAKE_NAMES})
    trips: Dict[str, int] = field(default_factory=lambda: {name: 0 for name in _TRIP_NAMES})

    @classmethod
    def fresh(cls, init_equity: float) -> "BrakeState":
        eq = float(init_equity)
        return cls(peak=eq, init_equity=eq, week_ref=eq, month_ref=eq)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["equity_hist"] = [float(v) for v in self.equity_hist]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BrakeState":
        kwargs: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name in data:
                kwargs[f.name] = data[f.name]
        out = cls(**kwargs)
        out.counts = {name: int(out.counts.get(name, 0)) for name in BRAKE_NAMES}
        out.trips = {name: int(out.trips.get(name, 0)) for name in _TRIP_NAMES}
        out.equity_hist = [float(v) for v in out.equity_hist]
        return out

    def summary(self) -> Dict[str, Any]:
        """What the brakes hold right now (the bar record and ``--status``)."""
        return {"turtle_multiplier": float(self.lad_mult), "halted": bool(self.halted), "equity_peak": float(self.peak),
                "daily_block_until_bar": int(self.daily_block_until), "week_blocked": self.week_blocked_id is not None and self.week_blocked_id == self.cur_week,
                "month_blocked": self.month_blocked_id is not None and self.month_blocked_id == self.cur_month,
                "opportunities": int(self.opportunities), "bars_blocked": int(self.bars_blocked),
                "counts": dict(self.counts), "trips": dict(self.trips)}


def bar_calendar(bar_time: str) -> Tuple[int, int, int]:
    """``(day, week, month)`` of a bar's open, as :class:`research.brakes.BarCalendar` numbers them (UTC days since 1970-01-01,
    Monday-based weeks, ``year * 12 + month - 1``); seconds-based, never the timestamp's raw integer unit."""
    ts = pd.Timestamp(bar_time)
    if ts is pd.NaT:
        raise ValueError(f"the brakes need a real bar time, got {bar_time!r}")
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    seconds = (ts - pd.Timestamp("1970-01-01", tz="UTC")).total_seconds()
    day = int(math.floor(seconds / 86_400.0))
    return day, (day + 3) // 7, int(ts.year) * 12 + int(ts.month) - 1


@dataclass
class SleeveState:
    """Everything the engine needs to continue after a restart (JSON round-trips)."""

    bar_index: int = -1  # index of the last processed bar (0 = the anchor bar, nothing executes there)
    last_bar_time: Optional[str] = None
    cash: float = 10_000.0
    qty: float = 0.0
    qty0: float = 0.0
    in_pos: bool = False
    entry_px: float = 0.0
    entry_fee: float = 0.0
    entry_i: int = -1
    entry_time: Optional[str] = None
    stop_px: float = float("nan")
    target_px: float = float("nan")
    risk: float = float("nan")
    hh: float = float("nan")
    ll: float = float("nan")
    alloc: float = 0.0
    alloc0: float = 0.0
    realized: float = 0.0
    fees_acc: float = 0.0
    n_red: int = 0
    lad_level: int = 0
    lad_flat: int = 0
    lad_peak: float = 10_000.0
    lad_mult: float = 1.0
    equity: float = 10_000.0
    pending: Optional[Decision] = None
    trades_closed: int = 0
    fees_paid: float = 0.0
    last_close: float = float("nan")  # close of the last processed bar (the window-end exit price)
    window: int = 0  # how many windows have started since the account began (0 = the first)
    brakes: Optional[BrakeState] = None  # plan row R18b: present only for a sleeve whose rules carry brakes

    @classmethod
    def fresh(cls, cfg: EngineConfig) -> "SleeveState":
        return cls(cash=float(cfg.init_cash), lad_peak=float(cfg.init_cash), equity=float(cfg.init_cash),
                   brakes=BrakeState.fresh(cfg.init_cash) if cfg.brakes_on else None)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "pending":
                out[f.name] = None if value is None else value.to_dict()
            elif f.name == "brakes":
                if value is not None:  # absent for a sleeve without brakes, so its state file reads exactly as it always did
                    out[f.name] = value.to_dict()
            elif isinstance(value, float):
                out[f.name] = _json_float(value)
            else:
                out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SleeveState":
        kwargs: Dict[str, Any] = {}
        defaults = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name == "pending":
                kwargs[f.name] = None if value is None else Decision.from_dict(value)
            elif f.name == "brakes":
                kwargs[f.name] = None if value is None else BrakeState.from_dict(value)
            elif isinstance(getattr(defaults, f.name), float):
                kwargs[f.name] = _nan(value)
            else:
                kwargs[f.name] = value
        return cls(**kwargs)

    @property
    def allocation(self) -> float:
        return self.alloc if self.in_pos else 0.0


@dataclass
class BarOutcome:
    """What happened on one bar: fills and state changes, in order."""

    bar_time: str
    bar_index: int
    events: List[Dict[str, Any]] = field(default_factory=list)
    equity: float = 0.0
    cash: float = 0.0
    qty: float = 0.0
    in_position: bool = False
    allocation: float = 0.0
    stop_px: Optional[float] = None
    target_px: Optional[float] = None
    ladder_level: int = 0
    ladder_multiplier: float = 1.0
    brakes: Optional[Dict[str, Any]] = None  # the brakes' state after this bar (plan row R18b; None without brakes)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SleeveEngine:
    """Advance one sleeve by one closed bar at a time (``state`` is mutated in place)."""

    def __init__(self, cfg: EngineConfig, state: Optional[SleeveState] = None) -> None:
        self.cfg = cfg
        self.state = state if state is not None else SleeveState.fresh(cfg)
        if cfg.brakes_on and self.state.brakes is None:
            self.state.brakes = BrakeState.fresh(self.state.cash)
        elif not cfg.brakes_on:
            self.state.brakes = None

    # -- the entry brakes (plan row R18b): research.brakes.EntryBrakes for one column, one bar at a time ----------

    def _brake_multiplier(self, i: int, cal: Tuple[int, int, int], f_entry: float, stop_pct: float, events: List[Dict[str, Any]],
                          bar_time: str) -> float:
        """``EntryBrakes.entry_multiplier`` for this sleeve's one entry opportunity (``f_entry`` > 0 and the stop checked already)."""
        spec, b = self.cfg.brakes, self.state.brakes
        day, week, month = cal
        b.opportunities += 1
        mult = 1.0
        cuts: Dict[str, float] = {}
        blocked: List[str] = []
        if spec.ladder is not None and b.lad_mult < 1.0:
            mult = b.lad_mult
            b.counts["ladder"] += 1
            cuts["ladder"] = float(b.lad_mult)
        if spec.hard_stop_dd is not None and b.halted:
            b.counts["hard_stop"] += 1
            blocked.append("hard_stop")
        if spec.max_entries_per_market_per_day is not None and b.last_entry_day == day and b.entries_today >= int(spec.max_entries_per_market_per_day):
            b.counts["entry_cap_market_day"] += 1
            blocked.append("entry_cap_market_day")
        if spec.no_entry_bar_after_exit and (i - b.last_exit_bar) == 1:
            b.counts["entry_after_exit"] += 1
            blocked.append("entry_after_exit")
        if spec.daily_loss_limit is not None and i < b.daily_block_until:
            b.counts["daily_loss"] += 1
            blocked.append("daily_loss")
        if spec.weekly_loss_limit is not None and b.week_blocked_id is not None and b.week_blocked_id == week:
            b.counts["weekly_loss"] += 1
            blocked.append("weekly_loss")
        if spec.monthly_loss_limit is not None and b.month_blocked_id is not None and b.month_blocked_id == month:
            b.counts["monthly_loss"] += 1
            blocked.append("monthly_loss")
        if spec.heat_cap is not None and not blocked:
            # One sleeve holds one position at a time: the new entry is the whole heat of this account.
            risk = f_entry * mult * stop_pct if (_finite(stop_pct) and stop_pct > 0) else 0.0
            if risk > float(spec.heat_cap) + 1e-12:
                mult = mult * float(spec.heat_cap) / risk
                b.counts["heat_cap"] += 1
                cuts["heat_cap"] = float(spec.heat_cap) / risk
        if blocked:
            mult = 0.0
            b.bars_blocked += 1
        if cuts or blocked:
            events.append({"kind": "brake", "bar_time": bar_time, "multiplier": float(mult), "cuts": cuts, "blocked_by": blocked,
                           "fraction_before": float(f_entry), "fraction_after": float(f_entry * mult)})
        return mult

    def _brake_on_entry(self, cal: Tuple[int, int, int]) -> None:
        b = self.state.brakes
        day = cal[0]
        b.entries_today = b.entries_today + 1 if b.last_entry_day == day else 1
        b.last_entry_day = day

    def _brake_on_exit(self, i: int) -> None:
        if self.cfg.brakes_on and self.state.brakes is not None:
            self.state.brakes.last_exit_bar = int(i)

    def _brake_on_bar_close(self, i: int, cal: Tuple[int, int, int], equity: float, events: List[Dict[str, Any]], bar_time: str) -> None:
        """``EntryBrakes.on_bar_close`` for one column: the peak, the Turtle multiplier, the hard stop and the three loss limits."""
        spec, b = self.cfg.brakes, self.state.brakes
        day, week, month = cal
        bpd = int(self.cfg.bars_per_day)
        eq = float(equity)
        b.peak = max(b.peak, eq)
        dd = (1.0 - eq / b.peak) if b.peak > 0 else 0.0
        if spec.ladder is not None:
            step = float(spec.ladder.multiplier(np.array([dd]))[0])
            before = b.lad_mult
            b.lad_mult = 1.0 if dd <= 1e-15 else min(b.lad_mult, step)
            if b.lad_mult != before:
                events.append({"kind": "turtle_ladder", "bar_time": bar_time, "multiplier_before": float(before), "multiplier_after": float(b.lad_mult),
                               "drawdown": float(dd), "equity": eq, "peak": float(b.peak)})
        if spec.hard_stop_dd is not None and not b.halted and dd >= float(spec.hard_stop_dd) - 1e-12:
            b.trips["hard_stop"] += 1
            b.halted = True
            events.append({"kind": "brake_trip", "brake": "hard_stop", "bar_time": bar_time, "drawdown": float(dd), "equity": eq, "peak": float(b.peak),
                           "note": "no new entry until this window restarts (the research's walk-forward windows restart every 180 days)"})
        if spec.daily_loss_limit is not None and len(b.equity_hist) >= bpd:
            ref = float(b.equity_hist[-bpd])  # the closing equity bars_per_day bars ago (24 hours)
            loss = (eq / ref - 1.0) if ref > 0 else 0.0
            if loss <= -float(spec.daily_loss_limit) + 1e-12 and i >= b.daily_block_until:
                b.trips["daily_loss"] += 1
                b.daily_block_until = i + 1 + bpd
                events.append({"kind": "brake_trip", "brake": "daily_loss", "bar_time": bar_time, "loss_24h": float(loss), "blocked_until_bar": int(b.daily_block_until)})
        prev = float(b.equity_hist[-1]) if b.equity_hist else float(b.init_equity)
        if spec.weekly_loss_limit is not None:
            if week != b.cur_week:  # the first bar of a week: its reference is the equity at the previous close (Monday 00:00 UTC)
                b.cur_week = week
                b.week_ref = prev
            if b.week_blocked_id != week and eq <= b.week_ref * (1.0 - float(spec.weekly_loss_limit)) + 1e-12:
                b.trips["weekly_loss"] += 1
                b.week_blocked_id = week
                events.append({"kind": "brake_trip", "brake": "weekly_loss", "bar_time": bar_time, "loss_week": float(eq / b.week_ref - 1.0) if b.week_ref > 0 else None})
        if spec.monthly_loss_limit is not None:
            if month != b.cur_month:
                b.cur_month = month
                b.month_ref = prev
            if b.month_blocked_id != month and eq <= b.month_ref * (1.0 - float(spec.monthly_loss_limit)) + 1e-12:
                b.trips["monthly_loss"] += 1
                b.month_blocked_id = month
                events.append({"kind": "brake_trip", "brake": "monthly_loss", "bar_time": bar_time, "loss_month": float(eq / b.month_ref - 1.0) if b.month_ref > 0 else None})
        b.equity_hist.append(eq)
        if len(b.equity_hist) > bpd:
            del b.equity_hist[: len(b.equity_hist) - bpd]

    # -- fills ----------------------------------------------------------------

    def _exit(self, price: float, bar_time: str, i: int, reason: str, events: List[Dict[str, Any]]) -> None:
        s, fee, slip = self.state, self.cfg.costs.fee_rate, self.cfg.costs.slippage_rate
        fill = price * (1.0 - slip)
        q, q0 = s.qty, s.qty0
        proceeds = fill * q
        exit_fee = proceeds * fee
        s.cash += proceeds - exit_fee
        share = q / q0
        pnl = s.realized + proceeds - exit_fee - s.entry_px * q - s.entry_fee * share
        fees = s.fees_acc + exit_fee
        outlay = s.entry_px * q0 + s.entry_fee
        events.append({
            "kind": "exit", "reason": reason, "bar_time": bar_time, "reference_price": float(price), "fill_price": fill,
            "quantity": q, "entry_quantity": q0, "entry_price": s.entry_px, "entry_time": s.entry_time,
            "proceeds": proceeds, "fee": exit_fee, "fees_total": fees, "pnl": pnl,
            "return_pct": pnl / outlay if outlay > 0 else 0.0, "bars_held": i - s.entry_i,
            "mfe_pct": s.hh / s.entry_px - 1.0 if _finite(s.hh) else 0.0,
            "mae_pct": s.ll / s.entry_px - 1.0 if _finite(s.ll) else 0.0,
            "size_fraction": s.alloc0, "reductions": s.n_red,
        })
        s.fees_paid += exit_fee
        s.trades_closed += 1
        s.in_pos = False
        self._brake_on_exit(i)
        s.qty = 0.0
        s.qty0 = 0.0
        s.stop_px = float("nan")
        s.target_px = float("nan")
        s.risk = float("nan")
        s.hh = float("nan")
        s.ll = float("nan")
        s.alloc = 0.0
        s.alloc0 = 0.0
        s.realized = 0.0
        s.fees_acc = 0.0
        s.n_red = 0
        s.entry_time = None

    def _reduce(self, price: float, target_alloc: float, bar_time: str, events: List[Dict[str, Any]]) -> None:
        s, fee, slip = self.state, self.cfg.costs.fee_rate, self.cfg.costs.slippage_rate
        fill = price * (1.0 - slip)
        ratio = target_alloc / s.alloc
        dq = s.qty * (1.0 - ratio)
        proceeds = fill * dq
        f = proceeds * fee
        s.cash += proceeds - f
        realized = proceeds - f - s.entry_px * dq - s.entry_fee * (dq / s.qty0)
        s.realized += realized
        s.fees_acc += f
        s.fees_paid += f
        s.qty -= dq
        events.append({"kind": "reduce", "bar_time": bar_time, "reference_price": float(price), "fill_price": fill, "quantity": dq,
                       "proceeds": proceeds, "fee": f, "realized_pnl": realized, "allocation_before": s.alloc,
                       "allocation_after": float(target_alloc), "quantity_left": s.qty})
        s.alloc = float(target_alloc)
        s.n_red += 1

    def _check_stops(self, o: float, h: float, low: float, bar_time: str, i: int, events: List[Dict[str, Any]]) -> bool:
        s = self.state
        if not s.in_pos:
            return False
        if _finite(s.stop_px) and low <= s.stop_px:
            self._exit(o if o < s.stop_px else s.stop_px, bar_time, i, "stop_loss", events)
            return True
        if _finite(s.target_px) and h >= s.target_px:
            self._exit(o if o > s.target_px else s.target_px, bar_time, i, "target", events)
            return True
        ts = self.cfg.time_stop_bars
        if ts is not None and (i - s.entry_i) >= int(ts):
            self._exit(o, bar_time, i, "time_stop", events)
            return True
        return False

    # -- one bar --------------------------------------------------------------

    def step(self, bar_time: str, o: float, h: float, low: float, c: float, decision: Optional[Decision] = None) -> BarOutcome:
        """Process one CLOSED bar. ``decision`` is the next decision (made at this bar's close), stored as pending.

        The pending decision from the previous bar is executed on this bar; the
        very first bar processed is the anchor (index 0): nothing executes there.
        """
        values = (o, h, low, c)
        if not all(math.isfinite(v) for v in values) or low <= 0:
            raise ValueError("OHLC must be finite and positive")
        s, cfg = self.state, self.cfg
        fee, slip = cfg.costs.fee_rate, cfg.costs.slippage_rate
        i = s.bar_index + 1
        events: List[Dict[str, Any]] = []
        cal = bar_calendar(bar_time) if cfg.brakes_on else (0, 0, 0)
        if cfg.window_bars is not None and i >= int(cfg.window_bars):
            # A new test window, as in the walk-forward: close at the old window's last close, start flat.
            if s.in_pos:
                self._exit(s.last_close, bar_time, i - 1, "window_end", events)
            s.equity = s.cash
            s.lad_level, s.lad_flat, s.lad_peak, s.lad_mult = 0, 0, float(s.cash), 1.0
            if cfg.brakes_on:
                s.brakes = BrakeState.fresh(s.cash)  # the brakes start every window fresh, as each research test window did
            s.window += 1
            events.append({"kind": "window_restart", "bar_time": bar_time, "window": s.window, "equity": s.cash,
                           "dropped_decision": None if s.pending is None else s.pending.bar_time})
            s.pending = None
            i = 0
        if i > 0 and s.pending is None:
            # No decision was made at the previous close (a data or signal problem): stops,
            # targets and time stops still apply; nothing else happens (no entry, no signal exit).
            self._check_stops(o, h, low, bar_time, i, events)
            events.append({"kind": "no_decision", "bar_time": bar_time})
        elif i > 0:
            pend = s.pending
            exited = self._check_stops(o, h, low, bar_time, i, events)
            want = bool(pend.desired)
            if s.in_pos and not want and not exited:
                self._exit(o, bar_time, i, "signal", events)
            if cfg.overlay and s.in_pos and not exited:
                if cfg.rebalance_threshold is None:
                    basis = s.alloc0
                else:
                    f_dec = pend.fraction if cfg.sized else 1.0
                    basis = f_dec if _finite(f_dec) else s.alloc0
                target = min(s.alloc, basis * s.lad_mult)
                if target <= _EPS:
                    self._exit(o, bar_time, i, "derisk", events)
                else:
                    thr = 0.0 if cfg.rebalance_threshold is None else float(cfg.rebalance_threshold)
                    if target < s.alloc * (1.0 - thr) - _EPS:
                        self._reduce(o, target, bar_time, events)
            if want and not s.in_pos and not exited:
                f_entry = (pend.fraction if cfg.sized else 1.0) * s.lad_mult
                f_entry = f_entry if _finite(f_entry) else 0.0
                sd = pend.stop_distance
                has_stop = _finite(sd) and sd > 0
                brake_mult = 1.0
                if f_entry <= 0.0:
                    events.append({"kind": "entry_skipped", "bar_time": bar_time, "reason": "no_size",
                                   "fraction": _json_float(pend.fraction), "ladder_multiplier": s.lad_mult})
                elif has_stop and not ((pend.close - sd) < o):
                    events.append({"kind": "entry_skipped", "bar_time": bar_time, "reason": "stop_not_below_open",
                                   "stop_price": pend.close - sd, "open": o})
                else:
                    if cfg.brakes_on:
                        # The research consults the brakes here: after the size and stop checks, before the fill.
                        stop_pct = sd / pend.close if has_stop else float("nan")
                        brake_mult = self._brake_multiplier(i, cal, f_entry, stop_pct, events, bar_time)
                        f_entry = f_entry * brake_mult
                    if f_entry <= 0.0:
                        events.append({"kind": "entry_skipped", "bar_time": bar_time, "reason": "brake",
                                       "blocked_by": list(events[-1].get("blocked_by") or []) if events and events[-1].get("kind") == "brake" else [],
                                       "fraction": _json_float(pend.fraction), "ladder_multiplier": s.lad_mult})
                    else:
                        fill = o * (1.0 + slip)
                        cash_before = s.cash
                        notional = s.cash * f_entry
                        q = notional / (fill * (1.0 + fee))
                        f = fill * q * fee
                        s.cash -= fill * q + f
                        s.qty = q
                        s.qty0 = q
                        s.entry_px = fill
                        s.entry_fee = f
                        s.entry_i = i
                        s.entry_time = bar_time
                        s.in_pos = True
                        s.alloc = f_entry
                        s.alloc0 = f_entry
                        s.realized = 0.0
                        s.fees_acc = f
                        s.fees_paid += f
                        s.n_red = 0
                        s.hh = float("nan")
                        s.ll = float("nan")
                        s.stop_px = pend.close - sd if has_stop else float("nan")
                        s.risk = sd if has_stop else float("nan")
                        td = pend.target_distance
                        s.target_px = pend.close + td if (_finite(td) and td > 0) else float("nan")
                        # Plan row R18: the money and the share of equity at risk at the initial stop (the research's trade columns).
                        risk_money = q * (fill - s.stop_px) if has_stop else float("nan")
                        risk_pct = risk_money / cash_before if (has_stop and cash_before > 0) else float("nan")
                        entry_event = {"kind": "entry", "bar_time": bar_time, "reference_price": float(o), "fill_price": fill,
                                       "quantity": q, "notional": fill * q, "fee": f, "fraction": f_entry,
                                       "stop_price": _json_float(s.stop_px), "target_price": _json_float(s.target_px),
                                       "decision_bar": pend.bar_time, "decision_close": pend.close,
                                       "risk": _json_float(risk_money), "risk_pct": _json_float(risk_pct)}
                        if cfg.brakes_on:
                            entry_event["brake_multiplier"] = float(brake_mult)
                            self._brake_on_entry(cal)
                        events.append(entry_event)
                        if _finite(s.stop_px) and low <= s.stop_px:
                            self._exit(o if o < s.stop_px else s.stop_px, bar_time, i, "stop_loss", events)
        s.equity = s.cash + s.qty * c
        # End-of-bar bookkeeping: excursions and the trailing stop (effective from the next bar).
        if s.in_pos:
            s.hh = float(np.fmax(s.hh, h))
            s.ll = float(np.fmin(s.ll, low))
            if cfg.trail_r is not None and _finite(s.risk) and s.risk > 0 and (s.hh - s.entry_px) >= cfg.trail_activate_r * s.risk:
                new_stop = s.hh - cfg.trail_r * s.risk
                raised = float(np.fmax(s.stop_px, new_stop))
                if not (_finite(s.stop_px) and raised == s.stop_px):
                    events.append({"kind": "stop_raised", "bar_time": bar_time, "old_stop": _json_float(s.stop_px), "new_stop": raised})
                s.stop_px = raised
        if cfg.ladder is not None:
            before = s.lad_level
            lvl, flt, pk = ladder_step(np.array([s.lad_level]), np.array([s.lad_flat]), np.array([s.lad_peak]), np.array([s.equity]), cfg.ladder)
            s.lad_level, s.lad_flat, s.lad_peak = int(lvl[0]), int(flt[0]), float(pk[0])
            s.lad_mult = float(LADDER_MULTIPLIERS[s.lad_level])
            if s.lad_level != before:
                events.append({"kind": "ladder", "bar_time": bar_time, "level_before": before, "level_after": s.lad_level,
                               "multiplier": s.lad_mult, "equity": s.equity, "peak": s.lad_peak})
        if cfg.brakes_on:
            self._brake_on_bar_close(i, cal, s.equity, events, bar_time)
        s.bar_index = i
        s.last_bar_time = bar_time
        s.last_close = float(c)
        s.pending = decision
        return BarOutcome(
            bar_time=bar_time, bar_index=i, events=events, equity=s.equity, cash=s.cash, qty=s.qty, in_position=s.in_pos,
            allocation=s.allocation if cfg.overlay else (1.0 if s.in_pos else 0.0),
            stop_px=_json_float(s.stop_px), target_px=_json_float(s.target_px), ladder_level=s.lad_level, ladder_multiplier=s.lad_mult,
            brakes=s.brakes.summary() if (cfg.brakes_on and s.brakes is not None) else None,
        )

    def mark(self, price: float) -> float:
        """Equity marked at ``price`` (open positions valued, nothing closed)."""
        return self.state.cash + self.state.qty * float(price)
