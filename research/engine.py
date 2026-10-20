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
  against the trader per side. Sizing is ``size_fraction`` of equity (default
  all-in) so the sweep measures the gross edge; production sizing is smaller.
- The stop is a PRICE fixed at decision time, exactly like the ``Signal.stop_loss``
  of the production contract: ``close[signal bar] - stop_distance[signal bar]``.
  An entry whose stop is not below the execution open is skipped (the risk
  manager rejects such a signal with ``stop_loss_not_below_entry``).

All combos (columns) are simulated together: one Python loop over bars with
numpy operations across combos, which is fast enough for 1H/4H/1D research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


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
)


@dataclass
class SweepResult:
    equity: np.ndarray  # (n, C) equity marked at each bar close
    position: np.ndarray  # (n, C) bool, long during the bar's close
    trades: pd.DataFrame  # one row per closed trade
    init_cash: float
    n_bars: int
    n_combos: int
    exposure: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (C,) fraction of bars long

    def trades_for(self, combo: int) -> pd.DataFrame:
        return self.trades[self.trades["combo"] == combo]


def _as_matrix(values, n: int, C: int, name: str, dtype) -> np.ndarray:
    arr = np.asarray(values, dtype=dtype)
    if arr.ndim == 1:
        arr = np.repeat(arr[:, None], C, axis=1)
    if arr.shape != (n, C):
        raise ValueError(f"{name} must have shape ({n}, {C}) or ({n},), got {arr.shape}")
    return arr


def run_vectorized(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    desired: np.ndarray,
    stop_distance: Optional[np.ndarray] = None,
    *,
    costs: Costs = Costs(),
    time_stop_bars: Optional[int] = None,
    target_distance: Optional[np.ndarray] = None,
    size_fraction: float = 1.0,
    init_cash: float = 10_000.0,
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
    if not (0.0 < size_fraction <= 1.0):
        raise ValueError("size_fraction must be in (0, 1]")
    if init_cash <= 0:
        raise ValueError("init_cash must be positive")
    if time_stop_bars is not None and time_stop_bars <= 0:
        raise ValueError("time_stop_bars must be positive when given")
    stops = None if stop_distance is None else _as_matrix(stop_distance, n, C, "stop_distance", float)
    targets = None if target_distance is None else _as_matrix(target_distance, n, C, "target_distance", float)
    if np.any(~np.isfinite(np.stack([o, h, l, c]))) or np.any(l <= 0):
        raise ValueError("OHLC must be finite and positive")

    fee, slip = costs.fee_rate, costs.slippage_rate
    cash = np.full(C, float(init_cash))
    qty = np.zeros(C)
    in_pos = np.zeros(C, dtype=bool)
    entry_px = np.zeros(C)
    entry_fee = np.zeros(C)
    entry_i = np.full(C, -1, dtype=np.int64)
    stop_px = np.full(C, np.nan)
    target_px = np.full(C, np.nan)
    equity = np.empty((n, C))
    position = np.zeros((n, C), dtype=bool)
    combos = np.arange(C)

    trade_chunks: List[dict] = []

    def _exit(mask: np.ndarray, price: np.ndarray, i: int, reason: str) -> None:
        """Close positions for ``mask`` at ``price`` (pre-slippage reference)."""
        if not mask.any():
            return
        fill = price[mask] * (1.0 - slip)
        proceeds = fill * qty[mask]
        exit_fee = proceeds * fee
        cash[mask] += proceeds - exit_fee
        fees = entry_fee[mask] + exit_fee
        cost_basis = entry_px[mask] * qty[mask]
        pnl = proceeds - exit_fee - cost_basis - entry_fee[mask]
        trade_chunks.append(
            {
                "combo": combos[mask],
                "entry_i": entry_i[mask],
                "exit_i": np.full(int(mask.sum()), i, dtype=np.int64),
                "entry_price": entry_px[mask].copy(),
                "exit_price": fill,
                "quantity": qty[mask].copy(),
                "fees": fees,
                "pnl": pnl,
                "return_pct": pnl / (cost_basis + entry_fee[mask]),
                "bars_held": np.full(int(mask.sum()), i, dtype=np.int64) - entry_i[mask],
                "exit_reason": np.full(int(mask.sum()), reason, dtype=object),
            }
        )
        in_pos[mask] = False
        qty[mask] = 0.0
        stop_px[mask] = np.nan
        target_px[mask] = np.nan

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
        if time_stop_bars is not None:
            aged = in_pos & ~exited & ((i - entry_i) >= time_stop_bars)
            if aged.any():
                _exit(aged, np.full(C, o[i]), i, "time_stop")
                exited |= aged
        return exited

    for i in range(n):
        exited = _check_stops(i) if i > 0 else np.zeros(C, dtype=bool)
        if i > 0:
            want = desired[i - 1]
            # Exit at the open when the decision turned off.
            to_exit = in_pos & ~want & ~exited
            if to_exit.any():
                _exit(to_exit, np.full(C, o[i]), i, "signal")
            # Enter at the open when flat and desired (stop must sit below the open).
            to_enter = want & ~in_pos & ~exited
            if stops is not None and to_enter.any():
                sd_prev = stops[i - 1]
                has_stop = np.isfinite(sd_prev) & (sd_prev > 0)
                to_enter &= ~has_stop | ((c[i - 1] - sd_prev) < o[i])
            if to_enter.any():
                fill = o[i] * (1.0 + slip)
                notional = cash[to_enter] * size_fraction
                q = notional / (fill * (1.0 + fee))
                f = fill * q * fee
                cash[to_enter] -= fill * q + f
                qty[to_enter] = q
                entry_px[to_enter] = fill
                entry_fee[to_enter] = f
                entry_i[to_enter] = i
                in_pos[to_enter] = True
                if stops is not None:
                    sd = stops[i - 1][to_enter]
                    stop_px[to_enter] = np.where(np.isfinite(sd) & (sd > 0), c[i - 1] - sd, np.nan)
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

    # Terminal bookkeeping: value any open position at the last close (not a trade signal).
    if in_pos.any():
        _exit(in_pos.copy(), np.full(C, c[-1]), n - 1, "end_of_data")
        equity[-1] = cash

    if trade_chunks:
        trades = pd.DataFrame({k: np.concatenate([ch[k] for ch in trade_chunks]) for k in TRADE_COLUMNS})
        trades = trades.sort_values(["combo", "entry_i"], kind="mergesort").reset_index(drop=True)
    else:
        trades = pd.DataFrame({k: pd.Series(dtype=float if k not in ("exit_reason",) else object) for k in TRADE_COLUMNS})
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
    )


def buy_and_hold(open_: np.ndarray, close: np.ndarray, *, costs: Costs = Costs(), init_cash: float = 10_000.0) -> np.ndarray:
    """Equity of buying at the first open and holding (benchmark)."""
    o, c = np.asarray(open_, float), np.asarray(close, float)
    fill = o[0] * (1.0 + costs.slippage_rate)
    q = init_cash / (fill * (1.0 + costs.fee_rate))
    cash = init_cash - fill * q * (1.0 + costs.fee_rate)
    return cash + q * c
