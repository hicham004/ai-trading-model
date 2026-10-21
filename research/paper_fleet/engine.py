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

Nothing here reads market data, talks to a network or can reach an order: it
is arithmetic on numbers it is given.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from research.engine import Costs
from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step

_EPS = 1e-12


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

    @property
    def overlay(self) -> bool:
        """Research ``overlay``: a fraction matrix, a ladder or a rebalance threshold is in use."""
        return self.sized or self.ladder is not None or self.rebalance_threshold is not None


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

    @classmethod
    def fresh(cls, cfg: EngineConfig) -> "SleeveState":
        return cls(cash=float(cfg.init_cash), lad_peak=float(cfg.init_cash), equity=float(cfg.init_cash))

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "pending":
                out[f.name] = None if value is None else value.to_dict()
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SleeveEngine:
    """Advance one sleeve by one closed bar at a time (``state`` is mutated in place)."""

    def __init__(self, cfg: EngineConfig, state: Optional[SleeveState] = None) -> None:
        self.cfg = cfg
        self.state = state if state is not None else SleeveState.fresh(cfg)

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
        if cfg.window_bars is not None and i >= int(cfg.window_bars):
            # A new test window, as in the walk-forward: close at the old window's last close, start flat.
            if s.in_pos:
                self._exit(s.last_close, bar_time, i - 1, "window_end", events)
            s.equity = s.cash
            s.lad_level, s.lad_flat, s.lad_peak, s.lad_mult = 0, 0, float(s.cash), 1.0
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
                if f_entry <= 0.0:
                    events.append({"kind": "entry_skipped", "bar_time": bar_time, "reason": "no_size",
                                   "fraction": _json_float(pend.fraction), "ladder_multiplier": s.lad_mult})
                elif has_stop and not ((pend.close - sd) < o):
                    events.append({"kind": "entry_skipped", "bar_time": bar_time, "reason": "stop_not_below_open",
                                   "stop_price": pend.close - sd, "open": o})
                else:
                    fill = o * (1.0 + slip)
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
                    events.append({"kind": "entry", "bar_time": bar_time, "reference_price": float(o), "fill_price": fill,
                                   "quantity": q, "notional": fill * q, "fee": f, "fraction": f_entry,
                                   "stop_price": _json_float(s.stop_px), "target_price": _json_float(s.target_px),
                                   "decision_bar": pend.bar_time, "decision_close": pend.close})
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
        s.bar_index = i
        s.last_bar_time = bar_time
        s.last_close = float(c)
        s.pending = decision
        return BarOutcome(
            bar_time=bar_time, bar_index=i, events=events, equity=s.equity, cash=s.cash, qty=s.qty, in_position=s.in_pos,
            allocation=s.allocation if cfg.overlay else (1.0 if s.in_pos else 0.0),
            stop_px=_json_float(s.stop_px), target_px=_json_float(s.target_px), ladder_level=s.lad_level, ladder_multiplier=s.lad_mult,
        )

    def mark(self, price: float) -> float:
        """Equity marked at ``price`` (open positions valued, nothing closed)."""
        return self.state.cash + self.state.qty * float(price)
