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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step


@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.0010  # 0.10 % per side (OKX regular spot taker tier)
    slippage_rate: float = 0.0005  # 0.05 % per side

    def __post_init__(self) -> None:
        for name in ("fee_rate", "slippage_rate"):
            v = getattr(self, name)
            if not (0.0 <= v < 0.1):
                raise ValueError(f"{name} must be in [0, 0.1)")


TRADE_COLUMNS = (
    "combo", "entry_i", "exit_i", "entry_price", "exit_price", "quantity",
    "fees", "pnl", "return_pct", "bars_held", "exit_reason",
    "mfe_pct", "mae_pct", "size_fraction", "reductions",
)
_OBJECT_COLUMNS = ("exit_reason",)
_INT_COLUMNS = ("combo", "entry_i", "exit_i", "bars_held", "reductions")


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
    for k in TRADE_COLUMNS:
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
) -> SweepResult:
    """Simulate every column of ``desired`` (bool, shape (n, C)) on the same OHLC path."""
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
        proceeds = fill * q
        exit_fee = proceeds * fee
        cash[mask] += proceeds - exit_fee
        share = q / q0
        ep = entry_px[mask]
        pnl = realized[mask] + proceeds - exit_fee - ep * q - entry_fee[mask] * share
        fees = fees_acc[mask] + exit_fee
        outlay = ep * q0 + entry_fee[mask]
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

    def _reduce(mask: np.ndarray, price: np.ndarray, target_alloc: np.ndarray) -> None:
        """Sell part of the open positions in ``mask`` down to ``target_alloc`` (reduce-only)."""
        if not mask.any():
            return
        fill = price[mask] * (1.0 - slip)
        ratio = target_alloc[mask] / alloc[mask]
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
        # Stop first (worst case if both stop and target are touched).
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
            exited = _check_stops(i)
            want = desired[i - 1]
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
                target = np.minimum(alloc, basis * lad_mult)
                kill = still & (target <= 1e-12)
                if kill.any():
                    _exit(kill, np.full(C, o[i]), i, "derisk")
                thr = 0.0 if rebalance_threshold is None else float(rebalance_threshold)
                red = still & ~kill & (target < alloc * (1.0 - thr) - 1e-12)
                if red.any():
                    _reduce(red, np.full(C, o[i]), target)
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
                if to_enter.any():
                    fill = o[i] * (1.0 + slip)
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
                    if targets is not None:
                        td = targets[i - 1][to_enter]
                        target_px[to_enter] = np.where(np.isfinite(td) & (td > 0), c[i - 1] + td, np.nan)
                    # Same-bar stop for a position just opened at the open.
                    hit = to_enter & np.isfinite(stop_px) & (l[i] <= stop_px)
                    if hit.any():
                        ref = np.where(o[i] < stop_px, o[i], stop_px)
                        _exit(hit, ref, i, "stop_loss")
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
        if use_ladder:
            lvl, flt, pk = ladder_step(lad_level, lad_flat, lad_peak, equity[i], ladder)
            lad_level = np.where(lmask, lvl, 0)
            lad_flat = np.where(lmask, flt, 0)
            lad_peak = np.where(lmask, pk, lad_peak)
            lad_mult = LADDER_MULTIPLIERS[lad_level]

    if not overlay:
        allocation = position.astype(float) * frac_scalar

    # Terminal bookkeeping: value any open position at the last close (not a trade signal).
    if in_pos.any():
        _exit(in_pos.copy(), np.full(C, c[-1]), n - 1, "end_of_data")
        equity[-1] = cash

    if trade_chunks:
        trades = pd.DataFrame({k: np.concatenate([ch[k] for ch in trade_chunks]) for k in TRADE_COLUMNS})
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
    )


def buy_and_hold(open_: np.ndarray, close: np.ndarray, *, costs: Costs = Costs(), init_cash: float = 10_000.0) -> np.ndarray:
    """Equity of buying at the first open and holding (benchmark)."""
    o, c = np.asarray(open_, float), np.asarray(close, float)
    fill = o[0] * (1.0 + costs.slippage_rate)
    q = init_cash / (fill * (1.0 + costs.fee_rate))
    cash = init_cash - fill * q * (1.0 + costs.fee_rate)
    return cash + q * c
