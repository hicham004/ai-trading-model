"""Vectorized long-only backtester for parameter sweeps (SIMULATION ONLY).

Execution conventions mirror ``app/backtest/simulator.py`` so a candidate that
looks good here behaves the same in the event-driven check:

- A decision made on bar ``i-1`` (``desired[i-1]``) is executed at bar ``i``'s
  **open** (no look-ahead).
- Per bar: (1) an open position is checked against its stop on the bar's low
  first — a gap below the stop fills at the (worse) open, otherwise at the stop
  price; the time stop and the optional target are checked next; (2) only if
  nothing exited on this bar, the previous bar's decision is executed (enter if
  flat and desired; exit at the open if long and not desired); a position
  opened at the open can still be stopped by the same bar's low.
- Fees are charged on traded notional per side; slippage moves the fill
  against the trader per side.
- The stop is a PRICE fixed at decision time, exactly like the ``Signal.stop_loss``
  of the production contract: ``close[signal bar] - stop_distance[signal bar]``.
  An entry whose stop is not below the execution open is skipped (the risk
  manager rejects such a signal with ``stop_loss_not_below_entry``).

Sprint 2b overlays (all optional; with none of them the engine is bit-for-bit
the Sprint 2 engine, which is parity-tested against the reviewed simulator):

- ``size_fraction`` may be a per-bar (and per-combo) matrix of entry
  fractions of equity (vol targeting, crash-state de-risking); the value of
  the decision bar ``i-1`` sizes the entry at bar ``i``. NaN or 0 = no entry.
- ``ladder`` (drawdown ladder on the strategy's own equity) scales entries
  and reduces or closes open positions when its level changes.
- ``rebalance_threshold`` enables REDUCE-ONLY mid-trade adjustments: when
  the decision-bar fraction falls below the allocated fraction by more than
  the threshold the position is sold down at the next open; a fraction of
  zero closes it (``derisk``). Positions are never increased mid-trade (no
  averaging down, no pyramiding).
- ``trail_activate_r`` / ``trail_r`` add a trailing stop in units of the
  initial risk ``R = decision close - stop price``: once the running high is
  ``trail_activate_r x R`` above the entry fill (measured at bar close) the
  stop follows the running high at ``trail_r x R`` below it, only ever moving
  up and effective from the next bar.
- Every trade records its maximum favourable / adverse excursion (``mfe_pct``,
  ``mae_pct``, from bar highs/lows while the position was open, excluding the
  exit bar) for the give-back analysis.

All combos (columns) are simulated together: one Python loop over bars with
numpy operations across combos, which is fast enough for 1H/4H/6H/1D research.

Trader Policy v1 (plan row R18) adds three optional pieces, each off by default
and each leaving the engine bit-for-bit what it was when off:

- ``brakes`` (:class:`research.brakes.BrakeSpec`, with the bars' ``bar_times``):
  entry-only circuit breakers (the Turtle ladder, the hard stop, the entry caps,
  the loss limits, the heat cap) consulted once per bar right before the
  entries; a brake never closes or reduces a position.
- ``variants`` (:class:`EngineVariants`): ONE add of ``add_size`` x the initial
  quantity decided at a bar close once the close is ``add_at_r`` R above the
  entry fill (R = entry fill - initial stop), executed at the next open; the
  first unit keeps its stop, the add gets the candidate's own stop distance of
  the decision bar; never after a loss, never averaging down. And a half
  scale-out decided at a bar close once the close is ``scale_out_at_r`` R up,
  sold at the next open through the reduce-only path; the remainder keeps its
  stop; the trade stays one trade with its P&L pooled.
- extra trade columns (``stop_price``, ``risk`` = quantity x (entry fill -
  initial stop), ``risk_pct`` of the equity at entry, ``adds``,
  ``add_worst_case_r``, ``scale_outs``) for the expectancy-in-R, gap and
  re-entry statistics; the Sprint 2 columns are unchanged.

Named cost profiles (plan row R24, the owner's decision of 2026-11-05 from the
R22 fill-cost replay): :data:`COST_PROFILES` names the per-side costs a study
may charge, ``"gate"`` (today's :class:`Costs` default, every stored study's
cost), ``"measured_btc_eth_2026_11"`` (BTC-USDT and ETH-USDT only) and
``"altcoin"``. ``Costs()`` keeps the gate numbers, so every stored study
reproduces bit for bit; a profile is chosen by name (``Costs.named``) and each
``Costs`` carries the name of the profile its numbers are, for reports.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from research.brakes import BarCalendar, BrakeSpec, EntryBrakes
from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step

# -- named cost profiles (plan row R24) -------------------------------------------------------------------------------
#
# NEVER edit a profile's numbers in place: a study pre-registers a profile by its name AND its numbers, so an edited
# profile would change every study that named it; a new measurement gets a new name (the date is in the name for that).

GATE_PROFILE = "gate"
MEASURED_BTC_ETH_PROFILE = "measured_btc_eth_2026_11"
ALTCOIN_PROFILE = "altcoin"
CUSTOM_PROFILE = "custom"  # the label of per-side numbers no profile has (a hand-given --fee / --slippage); never a registry name
_PROFILE_RATES: Mapping[str, Tuple[float, float]] = MappingProxyType({
    GATE_PROFILE: (0.0010, 0.0005),  # OKX's regular 0.10 % taker fee + 0.05 % slippage a side: 0.30 % a round trip
    MEASURED_BTC_ETH_PROFILE: (0.0010, 0.0002),  # the same fee + 0.02 % slippage a side: 0.24 % a round trip
    ALTCOIN_PROFILE: (0.0010, 0.0015),  # the same fee + 0.05 % slippage + the altcoin 0.10 % a side: 0.50 % a round trip
})
#: What each profile is for and where its numbers come from (written into pre-registrations and reports).
COST_PROFILE_NOTES: Mapping[str, str] = MappingProxyType({
    GATE_PROFILE: ("the Sprint 2c gate cost and the research engine's default: OKX's regular 0.10 % taker fee plus 0.05 % slippage a side "
                   "(0.30 % a round trip); every study finished by 2026-11-05 ran it, and the paper fleet charges it"),
    MEASURED_BTC_ETH_PROFILE: ("BTC-USDT and ETH-USDT only, clips up to 20 K USDT: the 0.10 % taker fee plus 0.02 % slippage a side "
                               "(0.24 % a round trip), measured on OKX's public tick and order-book archive "
                               "(docs/research/FILL_COST_REPLAY.md, section 7); the owner's decision of 2026-11-05 for studies "
                               "pre-registered after that day"),
    ALTCOIN_PROFILE: ("every other OKX market: the 0.10 % taker fee plus 0.05 % slippage plus the altcoin 0.10 % a side "
                      "(0.50 % a round trip; docs/TRADER_PLAN_2026-11-05.md, section 4.2), until altcoins are measured the same way"),
})
#: The markets a profile was measured on (a profile not listed here applies to any market).
COST_PROFILE_INSTRUMENTS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    MEASURED_BTC_ETH_PROFILE: ("BTC-USDT", "ETH-USDT"),
})
_RATE_TOLERANCE = 1e-12


def _same_rate(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= _RATE_TOLERANCE
    except (TypeError, ValueError):
        return False


def cost_profile_for(fee_rate: float, slippage_rate: float) -> Optional[str]:
    """The name of the profile whose per-side numbers these are, or None when no profile has them."""
    for name, (fee, slip) in _PROFILE_RATES.items():
        if _same_rate(fee_rate, fee) and _same_rate(slippage_rate, slip):
            return name
    return None


@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.0010  # 0.10 % per side (OKX regular spot taker tier)
    slippage_rate: float = 0.0005  # 0.05 % per side
    # Plan row R24: the named profile these numbers are (inferred when not given; None for numbers no profile has). Not part of
    # equality or the hash, so ``Costs()`` == ``Costs.named("gate")`` and every comparison of numbers behaves as before.
    profile: Optional[str] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        for name in ("fee_rate", "slippage_rate"):
            v = getattr(self, name)
            if not (0.0 <= v < 0.1):
                raise ValueError(f"{name} must be in [0, 0.1)")
        if self.profile is None:
            object.__setattr__(self, "profile", cost_profile_for(self.fee_rate, self.slippage_rate))
            return
        rates = _PROFILE_RATES.get(self.profile)
        if rates is None:
            raise ValueError(f"unknown cost profile {self.profile!r}; known: {sorted(_PROFILE_RATES)}")
        if not (_same_rate(self.fee_rate, rates[0]) and _same_rate(self.slippage_rate, rates[1])):
            raise ValueError(f"the cost profile {self.profile!r} is fee {rates[0]:g} + slippage {rates[1]:g} a side, "
                             f"not {self.fee_rate:g} + {self.slippage_rate:g}")

    @classmethod
    def named(cls, name: str) -> "Costs":
        """The registry's costs of one named profile (plan row R24); an unknown name is refused."""
        try:
            return COST_PROFILES[name]
        except (KeyError, TypeError):
            raise ValueError(f"unknown cost profile {name!r}; known: {sorted(COST_PROFILES)}") from None

    @property
    def round_trip(self) -> float:
        """Fee plus slippage on both sides of one trade (rounded to 12 decimals for records and labels)."""
        return round(2.0 * (self.fee_rate + self.slippage_rate), 12)

    @property
    def profile_label(self) -> str:
        """The profile's name, or ``"custom"`` for numbers no profile has (for reports and results)."""
        return self.profile or CUSTOM_PROFILE

    @property
    def label(self) -> str:
        return (f"{self.profile_label}: fee {self.fee_rate * 100:.2f} % + slippage {self.slippage_rate * 100:.2f} % a side "
                f"({self.round_trip * 100:.2f} % a round trip)")

    def covers(self, instrument: str) -> bool:
        """Whether the profile was measured for this market (a profile without a market list covers every market)."""
        markets = COST_PROFILE_INSTRUMENTS.get(self.profile or "")
        return markets is None or instrument in markets

    def to_dict(self) -> Dict[str, Any]:
        return {"profile": self.profile_label, "fee_rate": float(self.fee_rate), "slippage_rate": float(self.slippage_rate),
                "round_trip": float(self.round_trip)}


#: The named profiles, read-only. ``Costs()`` is the ``"gate"`` profile's numbers.
COST_PROFILES: Mapping[str, Costs] = MappingProxyType({name: Costs(fee, slip, profile=name) for name, (fee, slip) in _PROFILE_RATES.items()})


TRADE_COLUMNS = (
    "combo", "entry_i", "exit_i", "entry_price", "exit_price", "quantity",
    "fees", "pnl", "return_pct", "bars_held", "exit_reason",
    "mfe_pct", "mae_pct", "size_fraction", "reductions",
)
#: Plan row R18: the initial stop price, the money and the share of equity at risk at the initial stop, the add and scale-out counts.
EXTRA_TRADE_COLUMNS = ("stop_price", "risk", "risk_pct", "adds", "add_worst_case_r", "scale_outs")
ALL_TRADE_COLUMNS = TRADE_COLUMNS + EXTRA_TRADE_COLUMNS
_OBJECT_COLUMNS = ("exit_reason",)
_INT_COLUMNS = ("combo", "entry_i", "exit_i", "bars_held", "reductions", "adds", "scale_outs")


@dataclass(frozen=True)
class EngineVariants:
    """The two position-management variants of Trader Policy v1 (plan row R18), both off by default."""

    add_at_r: Optional[float] = None  # one add once the close is this many R above the entry fill (decided at a bar close)
    add_size: float = 0.5  # the add's quantity as a share of the initial quantity
    scale_out_at_r: Optional[float] = None  # sell ``scale_out_share`` of the position once the close is this many R up
    scale_out_share: float = 0.5

    def __post_init__(self) -> None:
        if self.add_at_r is not None and not (float(self.add_at_r) > 0):
            raise ValueError("add_at_r must be positive when given")
        if not (0.0 < float(self.add_size) <= 1.0):
            raise ValueError("add_size must be in (0, 1]")
        if self.scale_out_at_r is not None and not (float(self.scale_out_at_r) > 0):
            raise ValueError("scale_out_at_r must be positive when given")
        if not (0.0 < float(self.scale_out_share) < 1.0):
            raise ValueError("scale_out_share must be in (0, 1)")

    @property
    def active(self) -> bool:
        return self.add_at_r is not None or self.scale_out_at_r is not None

    @property
    def label(self) -> str:
        parts = []
        if self.add_at_r is not None:
            parts.append(f"add {self.add_size:g}x at +{self.add_at_r:g}R")
        if self.scale_out_at_r is not None:
            parts.append(f"scale-out {self.scale_out_share:g} at +{self.scale_out_at_r:g}R")
        return ", ".join(parts) or "no variant"

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["label"] = self.label
        return out


@dataclass
class SweepResult:
    equity: np.ndarray  # (n, C) equity marked at each bar close
    position: np.ndarray  # (n, C) bool, long during the bar's close
    trades: pd.DataFrame  # one row per closed trade
    init_cash: float
    n_bars: int
    n_combos: int
    exposure: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (C,) fraction of bars long
    allocation: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))  # (n, C) allocated fraction of equity (0 when flat)
    brakes: Optional[Dict[str, Any]] = None  # the brakes' per-column counts (plan row R18), None when no brakes ran

    def trades_for(self, combo: int) -> pd.DataFrame:
        return self.trades[self.trades["combo"] == combo]

    @property
    def avg_allocation(self) -> np.ndarray:
        """Mean allocated fraction over all bars (exposure weighted by size)."""
        if self.allocation.size == 0:
            return np.zeros(self.n_combos)
        return self.allocation.mean(axis=0)


def _as_matrix(values, n: int, C: int, name: str, dtype) -> np.ndarray:
    arr = np.asarray(values, dtype=dtype)
    if arr.ndim == 1:
        arr = np.repeat(arr[:, None], C, axis=1)
    if arr.shape != (n, C):
        raise ValueError(f"{name} must have shape ({n}, {C}) or ({n},), got {arr.shape}")
    return arr


def _per_column(values, C: int, name: str) -> np.ndarray:
    """Scalar / sequence (None = NaN) -> float array (C,)."""
    if values is None:
        return np.full(C, np.nan)
    if np.isscalar(values):
        return np.full(C, float(values))
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
    if arr.shape != (C,):
        raise ValueError(f"{name} must be a scalar or have one value per combo ({C}), got {arr.shape}")
    return arr


def _empty_trades() -> pd.DataFrame:
    cols = {}
    for k in ALL_TRADE_COLUMNS:
        if k in _OBJECT_COLUMNS:
            cols[k] = pd.Series(dtype=object)
        elif k in _INT_COLUMNS:
            cols[k] = pd.Series(dtype=np.int64)
        else:
            cols[k] = pd.Series(dtype=float)
    return pd.DataFrame(cols)


def run_vectorized(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    desired: np.ndarray,
    stop_distance: Optional[np.ndarray] = None,
    *,
    costs: Costs = Costs(),
    time_stop_bars: Union[None, int, Sequence[Optional[int]]] = None,
    target_distance: Optional[np.ndarray] = None,
    size_fraction: Union[float, np.ndarray] = 1.0,
    init_cash: float = 10_000.0,
    trail_activate_r: Union[None, float, Sequence[Optional[float]]] = None,
    trail_r: Union[None, float, Sequence[Optional[float]]] = None,
    ladder: Optional[LadderConfig] = None,
    ladder_mask: Optional[np.ndarray] = None,
    rebalance_threshold: Optional[float] = None,
    brakes: Optional[BrakeSpec] = None,
    bar_times=None,
    variants: Optional[EngineVariants] = None,
) -> SweepResult:
    """Simulate every column of ``desired`` (bool, shape (n, C)) on the same OHLC path.

    ``brakes`` (with ``bar_times``, one timestamp per bar) and ``variants`` are the plan-row-R18 options; both
    default to off, and off is bit-for-bit the engine as it was.
    """
    o, h, l, c = (np.asarray(x, dtype=float) for x in (open_, high, low, close))
    n = len(c)
    if not (len(o) == len(h) == len(l) == n):
        raise ValueError("OHLC arrays must have the same length")
    desired = np.asarray(desired, dtype=bool)
    if desired.ndim == 1:
        desired = desired[:, None]
    if desired.shape[0] != n:
        raise ValueError("desired must have one row per bar")
    C = desired.shape[1]
    if init_cash <= 0:
        raise ValueError("init_cash must be positive")
    stops = None if stop_distance is None else _as_matrix(stop_distance, n, C, "stop_distance", float)
    targets = None if target_distance is None else _as_matrix(target_distance, n, C, "target_distance", float)
    if np.any(~np.isfinite(np.stack([o, h, l, c]))) or np.any(l <= 0):
        raise ValueError("OHLC must be finite and positive")

    # -- time stops: scalar or per column (NaN = none) ----------------------------
    if time_stop_bars is None:
        ts_arr = np.full(C, np.nan)
    elif np.isscalar(time_stop_bars):
        if int(time_stop_bars) <= 0:
            raise ValueError("time_stop_bars must be positive when given")
        ts_arr = np.full(C, float(int(time_stop_bars)))
    else:
        ts_arr = _per_column(time_stop_bars, C, "time_stop_bars")
        if np.any(ts_arr[np.isfinite(ts_arr)] <= 0):
            raise ValueError("time_stop_bars must be positive when given")
    use_time_stop = bool(np.isfinite(ts_arr).any())

    # -- sizing: scalar (Sprint 2 behaviour) or per-bar matrix ------------------
    frac: Optional[np.ndarray]
    if np.isscalar(size_fraction):
        frac_scalar = float(size_fraction)
        if not (0.0 < frac_scalar <= 1.0):
            raise ValueError("size_fraction must be in (0, 1]")
        frac = None
    else:
        frac = _as_matrix(size_fraction, n, C, "size_fraction", float)
        finite = frac[np.isfinite(frac)]
        if finite.size and (finite.min() < 0.0 or finite.max() > 1.0 + 1e-12):
            raise ValueError("size_fraction values must be in [0, 1] (long-only spot, no leverage)")
        frac_scalar = 1.0

    # -- trailing stop (per column, NaN = off) -------------------------------------
    act = _per_column(trail_activate_r, C, "trail_activate_r")
    dist = _per_column(trail_r, C, "trail_r")
    if np.any(np.isfinite(act) != np.isfinite(dist)):
        raise ValueError("trail_activate_r and trail_r go together")
    trail_on = np.isfinite(act) & np.isfinite(dist)
    if np.any(trail_on & ((act < 0) | (dist <= 0))):
        raise ValueError("trail_activate_r must be >= 0 and trail_r > 0")
    use_trail = bool(trail_on.any())

    # -- drawdown ladder -------------------------------------------------------------
    if ladder is not None:
        lmask = np.ones(C, dtype=bool) if ladder_mask is None else np.asarray(ladder_mask, dtype=bool)
        if lmask.shape != (C,):
            raise ValueError(f"ladder_mask must have shape ({C},)")
    else:
        lmask = np.zeros(C, dtype=bool)
    use_ladder = bool(lmask.any())
    if rebalance_threshold is not None and not (0.0 <= rebalance_threshold < 1.0):
        raise ValueError("rebalance_threshold must be in [0, 1) when given")
    overlay = frac is not None or use_ladder or rebalance_threshold is not None

    # -- plan row R18: entry brakes and the add / scale-out variants (all off by default) ------------
    brake_state: Optional[EntryBrakes] = None
    if brakes is not None and brakes.active:
        if bar_times is None:
            raise ValueError("brakes need bar_times (one timestamp per bar)")
        cal = BarCalendar.from_times(bar_times)
        if cal.n_bars != n:
            raise ValueError("bar_times must have one timestamp per bar")
        brake_state = EntryBrakes(brakes, C, float(init_cash), cal)
    var = variants if variants is not None else EngineVariants()
    use_add = var.add_at_r is not None
    use_so = var.scale_out_at_r is not None
    overlay = overlay or use_add or use_so  # the allocation matrix is tracked when a variant changes a position's size
    if use_add and stops is None:
        raise ValueError("the add variant needs the candidate's stop distances (the add gets its own stop)")

    fee, slip = costs.fee_rate, costs.slippage_rate
    cash = np.full(C, float(init_cash))
    qty = np.zeros(C)
    qty0 = np.zeros(C)
    in_pos = np.zeros(C, dtype=bool)
    entry_px = np.zeros(C)
    entry_fee = np.zeros(C)
    entry_i = np.full(C, -1, dtype=np.int64)
    stop_px = np.full(C, np.nan)
    target_px = np.full(C, np.nan)
    risk = np.full(C, np.nan)  # R = decision close - stop price
    hh = np.full(C, np.nan)  # running high since entry (bar closes)
    ll = np.full(C, np.nan)  # running low since entry
    alloc = np.zeros(C)  # allocated fraction of equity (entry, then reduce-only)
    alloc0 = np.zeros(C)
    realized = np.zeros(C)  # realized pnl of partial reductions within the open trade
    fees_acc = np.zeros(C)
    n_red = np.zeros(C, dtype=np.int64)
    lad_level = np.zeros(C, dtype=np.int64)
    lad_flat = np.zeros(C, dtype=np.int64)
    lad_peak = np.full(C, float(init_cash))
    lad_mult = np.ones(C)
    # R18 bookkeeping (constant zeros / NaN unless a variant is on).
    stop0 = np.full(C, np.nan)  # the initial stop price of the open trade
    risk_money = np.full(C, np.nan)  # quantity x (entry fill - initial stop)
    risk_pct = np.full(C, np.nan)  # ... as a share of the equity at entry
    n_add = np.zeros(C, dtype=np.int64)
    add_qty = np.zeros(C)  # quantity of the add unit still held
    add_qty0 = np.zeros(C)
    add_px = np.zeros(C)
    add_fee = np.zeros(C)
    add_stop = np.full(C, np.nan)
    add_alloc = np.zeros(C)  # the add unit's share of equity (so the reduce-only overlay does not sell a deliberate add back)
    add_wc = np.full(C, np.nan)  # worst case at the stop prices, in first-unit R, at the moment of the add
    add_pending = np.zeros(C, dtype=bool)
    n_so = np.zeros(C, dtype=np.int64)
    so_pending = np.zeros(C, dtype=bool)
    equity = np.empty((n, C))
    position = np.zeros((n, C), dtype=bool)
    allocation = np.zeros((n, C))
    combos = np.arange(C)

    trade_chunks: List[dict] = []

    def _exit(mask: np.ndarray, price: np.ndarray, i: int, reason: str) -> None:
        """Close positions for ``mask`` at ``price`` (pre-slippage reference)."""
        if not mask.any():
            return
        fill = price[mask] * (1.0 - slip)
        q = qty[mask]
        q0 = qty0[mask]
        if use_add:
            aq = add_qty[mask]
            proceeds = fill * (q + aq)
        else:
            proceeds = fill * q
        exit_fee = proceeds * fee
        cash[mask] += proceeds - exit_fee
        share = q / q0
        ep = entry_px[mask]
        pnl = realized[mask] + proceeds - exit_fee - ep * q - entry_fee[mask] * share
        fees = fees_acc[mask] + exit_fee
        outlay = ep * q0 + entry_fee[mask]
        if use_add:
            held_add = add_qty0[mask] > 0
            add_cost = np.where(held_add, add_px[mask] * aq + add_fee[mask] * np.where(held_add, aq / np.where(held_add, add_qty0[mask], 1.0), 0.0), 0.0)
            pnl = pnl - add_cost
            outlay = outlay + np.where(held_add, add_px[mask] * add_qty0[mask] + add_fee[mask], 0.0)
        count = int(mask.sum())
        trade_chunks.append(
            {
                "combo": combos[mask],
                "entry_i": entry_i[mask],
                "exit_i": np.full(count, i, dtype=np.int64),
                "entry_price": ep.copy(),
                "exit_price": fill,
                "quantity": q0.copy(),
                "fees": fees,
                "pnl": pnl,
                "return_pct": pnl / outlay,
                "bars_held": np.full(count, i, dtype=np.int64) - entry_i[mask],
                "exit_reason": np.full(count, reason, dtype=object),
                "mfe_pct": np.where(np.isfinite(hh[mask]), hh[mask] / ep - 1.0, 0.0),
                "mae_pct": np.where(np.isfinite(ll[mask]), ll[mask] / ep - 1.0, 0.0),
                "size_fraction": alloc0[mask].copy(),
                "reductions": n_red[mask].copy(),
                "stop_price": stop0[mask].copy(),
                "risk": risk_money[mask].copy(),
                "risk_pct": risk_pct[mask].copy(),
                "adds": n_add[mask].copy(),
                "add_worst_case_r": add_wc[mask].copy(),
                "scale_outs": n_so[mask].copy(),
            }
        )
        in_pos[mask] = False
        qty[mask] = 0.0
        qty0[mask] = 0.0
        stop_px[mask] = np.nan
        target_px[mask] = np.nan
        risk[mask] = np.nan
        hh[mask] = np.nan
        ll[mask] = np.nan
        alloc[mask] = 0.0
        alloc0[mask] = 0.0
        realized[mask] = 0.0
        fees_acc[mask] = 0.0
        n_red[mask] = 0
        stop0[mask] = np.nan
        risk_money[mask] = np.nan
        risk_pct[mask] = np.nan
        n_add[mask] = 0
        add_qty[mask] = 0.0
        add_qty0[mask] = 0.0
        add_px[mask] = 0.0
        add_fee[mask] = 0.0
        add_stop[mask] = np.nan
        add_alloc[mask] = 0.0
        add_wc[mask] = np.nan
        add_pending[mask] = False
        n_so[mask] = 0
        so_pending[mask] = False
        if brake_state is not None:
            brake_state.on_exit(i, mask)

    def _exit_add_unit(mask: np.ndarray, price: np.ndarray, i: int) -> None:
        """The add unit's own stop: sell only that unit (the first unit and its stop stay)."""
        if not mask.any():
            return
        fill = price[mask] * (1.0 - slip)
        aq = add_qty[mask]
        proceeds = fill * aq
        f = proceeds * fee
        cash[mask] += proceeds - f
        realized[mask] += proceeds - f - add_px[mask] * aq - add_fee[mask] * (aq / add_qty0[mask])
        fees_acc[mask] += f
        add_qty[mask] = 0.0
        add_stop[mask] = np.nan
        # The allocation falls back by the add's share (an estimate, as every allocation after a fill is).
        alloc[mask] = np.maximum(alloc[mask] - add_alloc[mask], 0.0)
        add_alloc[mask] = 0.0

    def _reduce(mask: np.ndarray, price: np.ndarray, target_alloc: np.ndarray) -> None:
        """Sell part of the open positions in ``mask`` down to ``target_alloc`` (reduce-only)."""
        if not mask.any():
            return
        fill = price[mask] * (1.0 - slip)
        ratio = target_alloc[mask] / alloc[mask]
        if use_add:
            total = qty[mask] + add_qty[mask]
            dq_total = total * (1.0 - ratio)
            from_add = np.minimum(add_qty[mask], dq_total)  # the add unit (the most recent, dearest unit) goes first
            dq = dq_total - from_add
            proceeds = fill * dq_total
            f = proceeds * fee
            cash[mask] += proceeds - f
            add_share = np.where(add_qty0[mask] > 0, from_add / np.where(add_qty0[mask] > 0, add_qty0[mask], 1.0), 0.0)
            realized[mask] += proceeds - f - entry_px[mask] * dq - entry_fee[mask] * (dq / qty0[mask]) - add_px[mask] * from_add - add_fee[mask] * add_share
            fees_acc[mask] += f
            qty[mask] -= dq
            before_add = add_qty[mask]
            add_qty[mask] -= from_add
            add_alloc[mask] = np.where(before_add > 0, add_alloc[mask] * add_qty[mask] / np.where(before_add > 0, before_add, 1.0), 0.0)
            add_stop[mask] = np.where(add_qty[mask] > 1e-15, add_stop[mask], np.nan)
        else:
            dq = qty[mask] * (1.0 - ratio)
            proceeds = fill * dq
            f = proceeds * fee
            cash[mask] += proceeds - f
            realized[mask] += proceeds - f - entry_px[mask] * dq - entry_fee[mask] * (dq / qty0[mask])
            fees_acc[mask] += f
            qty[mask] -= dq
        alloc[mask] = target_alloc[mask]
        n_red[mask] += 1

    def _check_stops(i: int) -> np.ndarray:
        """Apply stop / target / time stop for bar ``i``; return mask of exits."""
        exited = np.zeros(C, dtype=bool)
        if not in_pos.any():
            return exited
        if use_add:
            # The add unit's own stop, when it sits ABOVE the whole-position stop: a bar falling from the open reaches
            # it first, so the add is sold at its own stop before the first unit's stop can close the rest.
            above = ~np.isfinite(stop_px) | (add_stop > stop_px)
            hit_a = in_pos & (add_qty > 0) & np.isfinite(add_stop) & above & (l[i] <= add_stop)
            if hit_a.any():
                ref = np.where(o[i] < add_stop, o[i], add_stop)
                _exit_add_unit(hit_a, ref, i)
        # Stop first (worst case if both stop and target are touched). The whole-position stop closes the first unit
        # and any add still held (an add whose stop sits at or below it, e.g. under a trailing stop, goes with it).
        hit = in_pos & np.isfinite(stop_px) & (l[i] <= stop_px)
        if hit.any():
            ref = np.where(o[i] < stop_px, o[i], stop_px)
            _exit(hit, ref, i, "stop_loss")
            exited |= hit
        if targets is not None:
            hit_t = in_pos & ~exited & np.isfinite(target_px) & (h[i] >= target_px)
            if hit_t.any():
                ref = np.where(o[i] > target_px, o[i], target_px)
                _exit(hit_t, ref, i, "target")
                exited |= hit_t
        if use_time_stop:
            aged = in_pos & ~exited & np.isfinite(ts_arr) & ((i - entry_i) >= ts_arr)
            if aged.any():
                _exit(aged, np.full(C, o[i]), i, "time_stop")
                exited |= aged
        return exited

    for i in range(n):
        if i > 0:
            want = desired[i - 1]
            # Plan row R18 add, decided at the previous close, bought at THIS OPEN before the bar's stops are checked
            # (independent review of PR #13): an add filled at the open lives through the bar like a new entry, so the
            # bar's low can stop it out, and a whole-position stop, trailing stop or target reached later in the bar
            # closes it with the first unit. Never on a position that leaves at this very open: the decision turned
            # off, the time stop is due, the open gapped through the stop or the target, or the drawdown ladder is
            # flat (the overlay closes the position at this open).
            if use_add and add_pending.any():
                leaves_at_open = ~want | (lad_mult <= 0) | (np.isfinite(stop_px) & (o[i] <= stop_px)) | (
                    np.isfinite(target_px) & (o[i] >= target_px))
                if use_time_stop:
                    leaves_at_open |= np.isfinite(ts_arr) & ((i - entry_i) >= ts_arr)
                do = add_pending & in_pos & ~leaves_at_open & (add_qty0 == 0) & ((c[i - 1] - stops[i - 1]) < o[i])
                if do.any():
                    fill = o[i] * (1.0 + slip)
                    q_add = qty0[do] * float(var.add_size)
                    affordable = cash[do] / (fill * (1.0 + fee))
                    q_add = np.minimum(q_add, np.maximum(affordable, 0.0))  # never on margin: at most the cash left
                    f = fill * q_add * fee
                    equity_before = cash[do] + (qty[do] + add_qty[do]) * o[i]
                    cash[do] -= fill * q_add + f
                    add_qty[do] = q_add
                    add_qty0[do] = q_add
                    add_px[do] = fill
                    add_fee[do] = f
                    add_stop[do] = c[i - 1] - stops[i - 1][do]
                    fees_acc[do] += f
                    n_add[do] += 1
                    add_alloc[do] = np.where(equity_before > 0, fill * q_add / equity_before, 0.0)
                    alloc[do] = alloc[do] + add_alloc[do]
                    first_risk = qty[do] * (entry_px[do] - stop_px[do])
                    add_risk = q_add * (fill - add_stop[do])
                    add_wc[do] = np.where(risk_money[do] > 0, (first_risk + add_risk) / risk_money[do], np.nan)
                add_pending[:] = False
            exited = _check_stops(i)
            # Exit at the open when the decision turned off.
            to_exit = in_pos & ~want & ~exited
            if to_exit.any():
                _exit(to_exit, np.full(C, o[i]), i, "signal")
            # Reduce-only de-risking of positions still open (ladder / fraction overlays).
            if overlay and in_pos.any():
                still = in_pos & ~exited
                # Basis for the target: the decision-bar fraction when rebalancing is on,
                # otherwise the entry allocation; the ladder scales the basis, and the
                # target can only be lower than the current allocation (reduce-only).
                if rebalance_threshold is None:
                    basis = alloc0
                else:
                    f_dec = frac[i - 1] if frac is not None else np.full(C, frac_scalar)
                    basis = np.where(np.isfinite(f_dec), f_dec, alloc0)
                if use_add:
                    basis = basis + add_alloc  # a held add is a deliberate increase, not an over-allocation to sell back
                target = np.minimum(alloc, basis * lad_mult)
                kill = still & (target <= 1e-12)
                if kill.any():
                    _exit(kill, np.full(C, o[i]), i, "derisk")
                thr = 0.0 if rebalance_threshold is None else float(rebalance_threshold)
                red = still & ~kill & (target < alloc * (1.0 - thr) - 1e-12)
                if red.any():
                    _reduce(red, np.full(C, o[i]), target)
            # Plan row R18 variants, decided at the previous close, executed at this open on positions still open.
            if use_so and so_pending.any():
                do = so_pending & in_pos
                if do.any():
                    _reduce(do, np.full(C, o[i]), alloc * (1.0 - float(var.scale_out_share)))
                    n_so[do] += 1
                so_pending[:] = False
            # Enter at the open when flat and desired (stop must sit below the open).
            to_enter = want & ~in_pos & ~exited
            if to_enter.any():
                f_entry = (frac[i - 1] if frac is not None else np.full(C, frac_scalar)) * lad_mult
                f_entry = np.where(np.isfinite(f_entry), f_entry, 0.0)
                to_enter &= f_entry > 0.0
                if stops is not None and to_enter.any():
                    sd_prev = stops[i - 1]
                    has_stop = np.isfinite(sd_prev) & (sd_prev > 0)
                    to_enter &= ~has_stop | ((c[i - 1] - sd_prev) < o[i])
                if brake_state is not None and to_enter.any():
                    if stops is not None:
                        sd_prev = stops[i - 1]
                        stop_pct = np.where(np.isfinite(sd_prev) & (sd_prev > 0), sd_prev / c[i - 1], np.nan)
                    else:
                        stop_pct = np.full(C, np.nan)
                    f_entry = f_entry * brake_state.entry_multiplier(i, to_enter, f_entry, stop_pct)
                    to_enter &= f_entry > 0.0
                if to_enter.any():
                    fill = o[i] * (1.0 + slip)
                    cash_before = cash[to_enter].copy()
                    notional = cash[to_enter] * f_entry[to_enter]
                    q = notional / (fill * (1.0 + fee))
                    f = fill * q * fee
                    cash[to_enter] -= fill * q + f
                    qty[to_enter] = q
                    qty0[to_enter] = q
                    entry_px[to_enter] = fill
                    entry_fee[to_enter] = f
                    entry_i[to_enter] = i
                    in_pos[to_enter] = True
                    alloc[to_enter] = f_entry[to_enter]
                    alloc0[to_enter] = f_entry[to_enter]
                    realized[to_enter] = 0.0
                    fees_acc[to_enter] = f
                    n_red[to_enter] = 0
                    hh[to_enter] = np.nan
                    ll[to_enter] = np.nan
                    if stops is not None:
                        sd = stops[i - 1][to_enter]
                        has = np.isfinite(sd) & (sd > 0)
                        stop_px[to_enter] = np.where(has, c[i - 1] - sd, np.nan)
                        risk[to_enter] = np.where(has, sd, np.nan)
                        stop0[to_enter] = stop_px[to_enter]
                        rm = np.where(has, q * (fill - stop_px[to_enter]), np.nan)
                        risk_money[to_enter] = rm
                        risk_pct[to_enter] = np.where(has & (cash_before > 0), rm / cash_before, np.nan)
                    if targets is not None:
                        td = targets[i - 1][to_enter]
                        target_px[to_enter] = np.where(np.isfinite(td) & (td > 0), c[i - 1] + td, np.nan)
                    if brake_state is not None:
                        brake_state.on_entry(i, to_enter)
                    # Same-bar stop for a position just opened at the open.
                    hit = to_enter & np.isfinite(stop_px) & (l[i] <= stop_px)
                    if hit.any():
                        ref = np.where(o[i] < stop_px, o[i], stop_px)
                        _exit(hit, ref, i, "stop_loss")
        if use_add:
            equity[i] = cash + (qty + add_qty) * c[i]
        else:
            equity[i] = cash + qty * c[i]
        position[i] = in_pos
        if overlay:
            allocation[i] = np.where(in_pos, alloc, 0.0)
        # End-of-bar bookkeeping for open positions: excursions and the trailing stop.
        if in_pos.any():
            hh[:] = np.where(in_pos, np.fmax(hh, h[i]), hh)
            ll[:] = np.where(in_pos, np.fmin(ll, l[i]), ll)
            if use_trail:
                armed = in_pos & trail_on & np.isfinite(risk) & (risk > 0) & ((hh - entry_px) >= act * risk)
                if armed.any():
                    new_stop = hh - dist * risk
                    stop_px[:] = np.where(armed, np.fmax(stop_px, new_stop), stop_px)
            if use_add:
                # One add per trade, only on a winner (the close is add_at_r R above the entry fill), with a stop of its own.
                sd_now = stops[i]
                add_pending[:] = (in_pos & (n_add == 0) & np.isfinite(risk) & (risk > 0) & np.isfinite(sd_now) & (sd_now > 0)
                                  & ((c[i] - entry_px) >= float(var.add_at_r) * risk) & ((c[i] - sd_now) < c[i]))
            if use_so:
                so_pending[:] = in_pos & (n_so == 0) & np.isfinite(risk) & (risk > 0) & ((c[i] - entry_px) >= float(var.scale_out_at_r) * risk)
        if use_ladder:
            lvl, flt, pk = ladder_step(lad_level, lad_flat, lad_peak, equity[i], ladder)
            lad_level = np.where(lmask, lvl, 0)
            lad_flat = np.where(lmask, flt, 0)
            lad_peak = np.where(lmask, pk, lad_peak)
            lad_mult = LADDER_MULTIPLIERS[lad_level]
        if brake_state is not None:
            brake_state.on_bar_close(i, equity[i])

    if not overlay:
        allocation = position.astype(float) * frac_scalar

    # Terminal bookkeeping: value any open position at the last close (not a trade signal).
    if in_pos.any():
        _exit(in_pos.copy(), np.full(C, c[-1]), n - 1, "end_of_data")
        equity[-1] = cash

    if trade_chunks:
        trades = pd.DataFrame({k: np.concatenate([ch[k] for ch in trade_chunks]) for k in ALL_TRADE_COLUMNS})
        trades = trades.sort_values(["combo", "entry_i"], kind="mergesort").reset_index(drop=True)
    else:
        trades = _empty_trades()
    if not np.all(np.isfinite(equity)):
        raise ValueError("non-finite equity produced")
    return SweepResult(
        equity=equity,
        position=position,
        trades=trades,
        init_cash=float(init_cash),
        n_bars=n,
        n_combos=C,
        exposure=position.mean(axis=0) if n else np.zeros(C),
        allocation=allocation,
        brakes=None if brake_state is None else brake_state.summary(),
    )


def buy_and_hold(open_: np.ndarray, close: np.ndarray, *, costs: Costs = Costs(), init_cash: float = 10_000.0) -> np.ndarray:
    """Equity of buying at the first open and holding (benchmark)."""
    o, c = np.asarray(open_, float), np.asarray(close, float)
    fill = o[0] * (1.0 + costs.slippage_rate)
    q = init_cash / (fill * (1.0 + costs.fee_rate))
    cash = init_cash - fill * q * (1.0 + costs.fee_rate)
    return cash + q * c
