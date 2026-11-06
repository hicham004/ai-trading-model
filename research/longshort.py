"""Long/short backtester for the Phase 9 design study (plan row R9, SIMULATION ONLY).

A transcription of :func:`research.engine.run_vectorized` with a second,
short side. With no short decisions and no funding it is the long-only engine
operation for operation (parity-tested to the last bit), so a long-only
configuration run through it reproduces Sprint 2c's stored numbers.

The short side mirrors every long rule:

- A decision on bar ``i-1`` executes at bar ``i``'s open: a short SELLS at
  ``open x (1 - slippage)`` and BUYS back at ``price x (1 + slippage)``; fees
  are charged on traded notional per side, as for longs.
- The stop is a PRICE fixed at decision time ``close[i-1] + stop_distance``
  (above the entry). It is checked on the bar's HIGH first: a gap above the
  stop fills at the (worse) open, otherwise at the stop. A short needs a
  finite stop (``require_short_stop``) and is skipped when its stop is not
  above the execution open — the mirror of the long rule.
- Targets sit ``target_distance`` below the decision close and fill on the
  bar's low (a gap below fills at the better open); time stops are the same;
  the trailing stop follows the running LOW at ``trail_r x R`` above it and
  only ever moves down.
- Reduce-only de-risking buys part of the short back; positions are never
  increased mid-trade (no averaging, no pyramiding).
- One position per column at any time: long, short or flat. When both sides
  are desired on the same decision bar the long wins, so the long side is the
  long-only rule unchanged and a short can only use bars the long rule spends
  flat. A flip is an exit and an entry at the same open, and every conflict
  falls on the short side: a short that the long side needs closes at the open
  (``exit_reason = "flip"``) before the bar's stops are checked, so the long
  enters at that open as the long-only rule does; a long that gives way to a
  short keeps the long-only stop-first rule, and if its stop fires in the bar
  the short starts one bar later. Without ladder the long side's trades
  (timing, prices, exit reasons, returns) are therefore exactly the long-only
  engine's (tested); only their size differs, because the equity behind them
  includes the shorts' P&L.
- Sizing: an entry uses ``fraction x equity`` (fee included) for either side,
  ``fraction <= 1``: the short's notional at entry never exceeds the equity
  that collateralizes it (no leverage at entry). The ladder runs on the
  column's combined equity. ``short_size_fraction`` (optional, a diagnostic)
  sizes short entries and short rebalancing from a different matrix.

Perpetual-swap mechanics:

- **Funding.** ``funding_long`` / ``funding_short`` are per-bar sums of the
  funding rates settled during the bar (:func:`research.longshort_data.funding_per_bar`);
  a leg without an array pays none (the spot leg of the hybrid design). At the
  bar's close an open position on a funded leg receives ``-qty x close x rate``
  (longs pay a positive rate, shorts receive it). Funding is part of the
  trade's P&L and of the equity curve.
- **Liquidation tripwire.** A short is modelled as an ISOLATED 1x position
  whose margin equals its notional at entry; its liquidation price is
  ``entry x 2 / (1 + mmr)`` (``mmr`` = maintenance margin rate; OKX tier 1:
  0.4 %), about +99 %. A bar whose high reaches it before the stop's fill
  closes the short there (``exit_reason = "liquidation"``); a gap above it
  fills at the open, which books more than the isolated margin (conservative:
  on the exchange an isolated position cannot lose more than its margin). With
  the ATR stops of this study it never fires; it is there so a missing or
  absurd stop can never silently pass unnoticed.
- **Leverage trace.** ``max_leverage`` is the largest ``|qty| x price /
  equity`` at any bar close: it rises above the entry fraction only for a
  short whose price moves against it.
- **Execution prices per side.** ``long_ohlc`` / ``short_ohlc`` let a leg
  trade another instrument's prices than the signal path (the short leg on the
  perpetual swap's own candles); stops and targets are anchored to that
  instrument's decision close. By default both legs trade the given OHLC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from research.engine import TRADE_COLUMNS, Costs, SweepResult, _as_matrix, _per_column
from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step

LS_TRADE_COLUMNS = TRADE_COLUMNS + ("side", "funding", "max_leverage")
_OBJECT_COLUMNS = ("exit_reason",)
_INT_COLUMNS = ("combo", "entry_i", "exit_i", "bars_held", "reductions", "side")
DEFAULT_MMR = 0.004  # OKX BTC-/ETH-USDT-SWAP isolated tier-1 maintenance margin rate (public position-tiers, 2026-10-22)
OHLC = Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


@dataclass
class LongShortResult(SweepResult):
    side: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.int8))  # (n, C) +1 / -1 / 0 at the bar's close
    funding_total: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (C,) net funding received (> 0) or paid (< 0)
    max_leverage: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (C,) max |qty| x price / equity at a bar close
    liquidations: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))  # (C,)

    def short_share(self) -> np.ndarray:
        """Fraction of bars each column ends short."""
        if self.side.size == 0:
            return np.zeros(self.n_combos)
        return (self.side == -1).mean(axis=0)


def _empty_trades() -> pd.DataFrame:
    cols = {}
    for k in LS_TRADE_COLUMNS:
        if k in _OBJECT_COLUMNS:
            cols[k] = pd.Series(dtype=object)
        elif k in _INT_COLUMNS:
            cols[k] = pd.Series(dtype=np.int64)
        else:
            cols[k] = pd.Series(dtype=float)
    return pd.DataFrame(cols)


def _prices(values: Optional[OHLC], default: OHLC, n: int, name: str) -> OHLC:
    if values is None:
        return default
    if len(values) != 4:
        raise ValueError(f"{name} must be (open, high, low, close)")
    arrs = tuple(np.asarray(x, dtype=float) for x in values)
    if any(a.shape != (n,) for a in arrs):
        raise ValueError(f"{name} arrays must have one value per bar")
    if np.any(~np.isfinite(np.stack(arrs))) or np.any(arrs[2] <= 0):
        raise ValueError(f"{name} must be finite and positive")
    return arrs  # type: ignore[return-value]


def _funding(values: Optional[np.ndarray], n: int, name: str) -> Optional[np.ndarray]:
    if values is None:
        return None
    arr = np.asarray(values, dtype=float)
    if arr.shape != (n,):
        raise ValueError(f"{name} must have one value per bar")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite")
    return arr


def run_long_short(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    desired_long: np.ndarray,
    desired_short: Optional[np.ndarray] = None,
    stop_distance: Optional[np.ndarray] = None,
    *,
    costs_long: Costs = Costs(),
    costs_short: Optional[Costs] = None,
    funding_long: Optional[np.ndarray] = None,
    funding_short: Optional[np.ndarray] = None,
    long_ohlc: Optional[OHLC] = None,
    short_ohlc: Optional[OHLC] = None,
    time_stop_bars: Union[None, int, Sequence[Optional[int]]] = None,
    target_distance: Optional[np.ndarray] = None,
    size_fraction: Union[float, np.ndarray] = 1.0,
    short_size_fraction: Optional[np.ndarray] = None,
    init_cash: float = 10_000.0,
    trail_activate_r: Union[None, float, Sequence[Optional[float]]] = None,
    trail_r: Union[None, float, Sequence[Optional[float]]] = None,
    ladder: Optional[LadderConfig] = None,
    ladder_mask: Optional[np.ndarray] = None,
    rebalance_threshold: Optional[float] = None,
    maintenance_margin_rate: float = DEFAULT_MMR,
    require_short_stop: bool = True,
) -> LongShortResult:
    """Simulate every column of ``desired_long`` / ``desired_short`` (bool, shape (n, C)) on the same bars."""
    o, h, l, c = (np.asarray(x, dtype=float) for x in (open_, high, low, close))
    n = len(c)
    if not (len(o) == len(h) == len(l) == n):
        raise ValueError("OHLC arrays must have the same length")
    dl = np.asarray(desired_long, dtype=bool)
    if dl.ndim == 1:
        dl = dl[:, None]
    if dl.shape[0] != n:
        raise ValueError("desired_long must have one row per bar")
    C = dl.shape[1]
    if desired_short is None:
        ds = np.zeros((n, C), dtype=bool)
    else:
        ds = np.asarray(desired_short, dtype=bool)
        if ds.ndim == 1:
            ds = ds[:, None]
        if ds.shape != (n, C):
            raise ValueError(f"desired_short must have shape ({n}, {C})")
    if init_cash <= 0:
        raise ValueError("init_cash must be positive")
    if not (0.0 <= maintenance_margin_rate < 0.5):
        raise ValueError("maintenance_margin_rate must be in [0, 0.5)")
    stops = None if stop_distance is None else _as_matrix(stop_distance, n, C, "stop_distance", float)
    targets = None if target_distance is None else _as_matrix(target_distance, n, C, "target_distance", float)
    if np.any(~np.isfinite(np.stack([o, h, l, c]))) or np.any(l <= 0):
        raise ValueError("OHLC must be finite and positive")
    lo, lh, ll_, lc = _prices(long_ohlc, (o, h, l, c), n, "long_ohlc")
    so, sh, sl_, sc = _prices(short_ohlc, (o, h, l, c), n, "short_ohlc")
    f_long = _funding(funding_long, n, "funding_long")
    f_short = _funding(funding_short, n, "funding_short")
    use_funding = f_long is not None or f_short is not None
    costs_s = costs_long if costs_short is None else costs_short

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

    # -- sizing: scalar or per-bar matrix (same fraction rules for both sides) -------
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
            raise ValueError("size_fraction values must be in [0, 1] (no leverage: collateral >= position)")
        frac_scalar = 1.0
    # Optional separate fractions for SHORT entries and short rebalancing (a diagnostic; default: the same as longs).
    frac_s: Optional[np.ndarray] = None
    if short_size_fraction is not None:
        if frac is None:
            raise ValueError("short_size_fraction needs a size_fraction matrix")
        frac_s = _as_matrix(short_size_fraction, n, C, "short_size_fraction", float)
        finite_s = frac_s[np.isfinite(frac_s)]
        if finite_s.size and (finite_s.min() < 0.0 or finite_s.max() > 1.0 + 1e-12):
            raise ValueError("short_size_fraction values must be in [0, 1] (no leverage: collateral >= position)")

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

    fee_l, slip_l = costs_long.fee_rate, costs_long.slippage_rate
    fee_s, slip_s = costs_s.fee_rate, costs_s.slippage_rate
    liq_mult = 2.0 / (1.0 + float(maintenance_margin_rate))
    cash = np.full(C, float(init_cash))
    qty = np.zeros(C)  # signed: > 0 long, < 0 short
    qty0 = np.zeros(C)  # absolute size at entry
    in_pos = np.zeros(C, dtype=bool)
    side = np.zeros(C, dtype=np.int8)
    entry_px = np.zeros(C)
    entry_fee = np.zeros(C)
    entry_i = np.full(C, -1, dtype=np.int64)
    stop_px = np.full(C, np.nan)
    target_px = np.full(C, np.nan)
    liq_px = np.full(C, np.nan)
    risk = np.full(C, np.nan)  # R = |decision close - stop price|
    hh = np.full(C, np.nan)  # running high since entry (bar highs)
    ll = np.full(C, np.nan)  # running low since entry (bar lows)
    alloc = np.zeros(C)
    alloc0 = np.zeros(C)
    realized = np.zeros(C)
    fees_acc = np.zeros(C)
    fund_acc = np.zeros(C)
    lev_trade = np.zeros(C)
    n_red = np.zeros(C, dtype=np.int64)
    lad_level = np.zeros(C, dtype=np.int64)
    lad_flat = np.zeros(C, dtype=np.int64)
    lad_peak = np.full(C, float(init_cash))
    lad_mult = np.ones(C)
    equity = np.empty((n, C))
    position = np.zeros((n, C), dtype=bool)
    side_m = np.zeros((n, C), dtype=np.int8)
    allocation = np.zeros((n, C))
    funding_total = np.zeros(C)
    max_lev = np.zeros(C)
    n_liq = np.zeros(C, dtype=np.int64)
    combos = np.arange(C)

    trade_chunks: List[dict] = []

    def _record(mask: np.ndarray, i: int, reason: str, fill: np.ndarray, pnl: np.ndarray, fees: np.ndarray, mfe: np.ndarray,
                mae: np.ndarray, sign: int) -> None:
        ep = entry_px[mask]
        q0 = qty0[mask]
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
                "mfe_pct": mfe,
                "mae_pct": mae,
                "size_fraction": alloc0[mask].copy(),
                "reductions": n_red[mask].copy(),
                "side": np.full(count, sign, dtype=np.int64),
                "funding": fund_acc[mask].copy(),
                "max_leverage": lev_trade[mask].copy(),
            }
        )

    def _exit(mask: np.ndarray, price: np.ndarray, i: int, reason: str) -> None:
        """Close positions for ``mask`` at ``price`` (pre-slippage reference, per column)."""
        if not mask.any():
            return
        m_l = mask & (side == 1)
        if m_l.any():
            fill = price[m_l] * (1.0 - slip_l)
            q = qty[m_l]
            q0 = qty0[m_l]
            proceeds = fill * q
            exit_fee = proceeds * fee_l
            cash[m_l] += proceeds - exit_fee
            share = q / q0
            ep = entry_px[m_l]
            pnl = realized[m_l] + proceeds - exit_fee - ep * q - entry_fee[m_l] * share + fund_acc[m_l]
            fees = fees_acc[m_l] + exit_fee
            mfe = np.where(np.isfinite(hh[m_l]), hh[m_l] / ep - 1.0, 0.0)
            mae = np.where(np.isfinite(ll[m_l]), ll[m_l] / ep - 1.0, 0.0)
            _record(m_l, i, reason, fill, pnl, fees, mfe, mae, 1)
        m_s = mask & (side == -1)
        if m_s.any():
            fill = price[m_s] * (1.0 + slip_s)
            q = -qty[m_s]
            q0 = qty0[m_s]
            cost = fill * q
            exit_fee = cost * fee_s
            cash[m_s] -= cost + exit_fee
            share = q / q0
            ep = entry_px[m_s]
            pnl = realized[m_s] + ep * q - cost - exit_fee - entry_fee[m_s] * share + fund_acc[m_s]
            fees = fees_acc[m_s] + exit_fee
            mfe = np.where(np.isfinite(ll[m_s]), 1.0 - ll[m_s] / ep, 0.0)
            mae = np.where(np.isfinite(hh[m_s]), 1.0 - hh[m_s] / ep, 0.0)
            _record(m_s, i, reason, fill, pnl, fees, mfe, mae, -1)
        in_pos[mask] = False
        side[mask] = 0
        qty[mask] = 0.0
        qty0[mask] = 0.0
        stop_px[mask] = np.nan
        target_px[mask] = np.nan
        liq_px[mask] = np.nan
        risk[mask] = np.nan
        hh[mask] = np.nan
        ll[mask] = np.nan
        alloc[mask] = 0.0
        alloc0[mask] = 0.0
        realized[mask] = 0.0
        fees_acc[mask] = 0.0
        fund_acc[mask] = 0.0
        lev_trade[mask] = 0.0
        n_red[mask] = 0

    def _reduce(mask: np.ndarray, price: np.ndarray, target_alloc: np.ndarray) -> None:
        """Bring the open positions in ``mask`` down to ``target_alloc`` (reduce-only, either side)."""
        if not mask.any():
            return
        m_l = mask & (side == 1)
        if m_l.any():
            fill = price[m_l] * (1.0 - slip_l)
            ratio = target_alloc[m_l] / alloc[m_l]
            dq = qty[m_l] * (1.0 - ratio)
            proceeds = fill * dq
            f = proceeds * fee_l
            cash[m_l] += proceeds - f
            realized[m_l] += proceeds - f - entry_px[m_l] * dq - entry_fee[m_l] * (dq / qty0[m_l])
            fees_acc[m_l] += f
            qty[m_l] -= dq
            alloc[m_l] = target_alloc[m_l]
            n_red[m_l] += 1
        m_s = mask & (side == -1)
        if m_s.any():
            fill = price[m_s] * (1.0 + slip_s)
            ratio = target_alloc[m_s] / alloc[m_s]
            dq = -qty[m_s] * (1.0 - ratio)
            cost = fill * dq
            f = cost * fee_s
            cash[m_s] -= cost + f
            realized[m_s] += entry_px[m_s] * dq - cost - f - entry_fee[m_s] * (dq / qty0[m_s])
            fees_acc[m_s] += f
            qty[m_s] += dq
            alloc[m_s] = target_alloc[m_s]
            n_red[m_s] += 1

    def _short_stops(cand: np.ndarray, i: int) -> np.ndarray:
        """Stop / liquidation for the short positions in ``cand`` on bar ``i``; returns the exits."""
        if not cand.any():
            return np.zeros(C, dtype=bool)
        trig_stop = cand & np.isfinite(stop_px) & (sh[i] >= stop_px)
        trig_liq = cand & np.isfinite(liq_px) & (sh[i] >= liq_px)
        stop_ref = np.where(so[i] > stop_px, so[i], stop_px)
        liq_ref = np.where(so[i] > liq_px, so[i], liq_px)
        # Liquidated when its price is reached before the stop would fill (no stop, a stop beyond it, or a gap through both).
        liq = trig_liq & (~trig_stop | (stop_ref >= liq_px))
        hit = trig_stop & ~liq
        if hit.any():
            _exit(hit, stop_ref, i, "stop_loss")
        if liq.any():
            n_liq[liq] += 1
            _exit(liq, liq_ref, i, "liquidation")
        return hit | liq

    def _check_stops(i: int) -> np.ndarray:
        """Apply stop / target / time stop for bar ``i``; return mask of exits."""
        exited = np.zeros(C, dtype=bool)
        if not in_pos.any():
            return exited
        is_l = in_pos & (side == 1)
        is_s = in_pos & (side == -1)
        # Stop first (worst case if both stop and target are touched).
        hit = is_l & np.isfinite(stop_px) & (ll_[i] <= stop_px)
        if hit.any():
            ref = np.where(lo[i] < stop_px, lo[i], stop_px)
            _exit(hit, ref, i, "stop_loss")
            exited |= hit
        exited |= _short_stops(is_s, i)
        if targets is not None:
            hit_t = is_l & ~exited & np.isfinite(target_px) & (lh[i] >= target_px)
            if hit_t.any():
                ref = np.where(lo[i] > target_px, lo[i], target_px)
                _exit(hit_t, ref, i, "target")
                exited |= hit_t
            hit_ts = is_s & ~exited & np.isfinite(target_px) & (sl_[i] <= target_px)
            if hit_ts.any():
                ref = np.where(so[i] < target_px, so[i], target_px)
                _exit(hit_ts, ref, i, "target")
                exited |= hit_ts
        if use_time_stop:
            aged = in_pos & ~exited & np.isfinite(ts_arr) & ((i - entry_i) >= ts_arr)
            if aged.any():
                _exit(aged, np.where(side == -1, so[i], lo[i]), i, "time_stop")
                exited |= aged
        return exited

    for i in range(n):
        if i > 0:
            want_l = dl[i - 1]
            want_s = ds[i - 1] & ~want_l  # the long side wins a tie: it is the long-only rule unchanged
            # A short that the long side needs is closed at the open BEFORE the bar's stops are checked, so the long
            # enters at that open exactly as the long-only rule does (never delayed by the short's stop). A long that
            # gives way to a short keeps the long-only engine's stop-first rule; if its stop fires in the bar, the
            # short waits for the next one. Every conflict falls on the short side. Never true without shorts.
            flip = in_pos & (side == -1) & want_l
            if flip.any():
                _exit(flip, np.where(side == -1, so[i], lo[i]), i, "flip")
            exited = _check_stops(i)
            # Exit at the open when the decision for the held side turned off.
            to_exit = in_pos & ~exited & (((side == 1) & ~want_l) | ((side == -1) & ~want_s))
            if to_exit.any():
                _exit(to_exit, np.where(side == -1, so[i], lo[i]), i, "signal")
            # Reduce-only de-risking of positions still open (ladder / fraction overlays), either side.
            if overlay and in_pos.any():
                still = in_pos & ~exited
                if rebalance_threshold is None:
                    basis = alloc0
                else:
                    f_dec = frac[i - 1] if frac is not None else np.full(C, frac_scalar)
                    if frac_s is not None:
                        f_dec = np.where(side == -1, frac_s[i - 1], f_dec)
                    basis = np.where(np.isfinite(f_dec), f_dec, alloc0)
                target = np.minimum(alloc, basis * lad_mult)
                kill = still & (target <= 1e-12)
                if kill.any():
                    _exit(kill, np.where(side == -1, so[i], lo[i]), i, "derisk")
                thr = 0.0 if rebalance_threshold is None else float(rebalance_threshold)
                red = still & ~kill & (target < alloc * (1.0 - thr) - 1e-12)
                if red.any():
                    _reduce(red, np.where(side == -1, so[i], lo[i]), target)
            # Enter at the open when flat and desired (a long's stop below its open, a short's above).
            to_enter = (want_l | want_s) & ~in_pos & ~exited
            if to_enter.any():
                f_entry = (frac[i - 1] if frac is not None else np.full(C, frac_scalar)) * lad_mult
                if frac_s is not None:
                    f_entry = np.where(want_s & ~want_l, frac_s[i - 1] * lad_mult, f_entry)
                f_entry = np.where(np.isfinite(f_entry), f_entry, 0.0)
                to_enter &= f_entry > 0.0
                go_l = to_enter & want_l
                go_s = to_enter & want_s
                if stops is not None:
                    sd_prev = stops[i - 1]
                    has_stop = np.isfinite(sd_prev) & (sd_prev > 0)
                    if go_l.any():
                        go_l &= ~has_stop | ((lc[i - 1] - sd_prev) < lo[i])
                    if go_s.any():
                        go_s &= (has_stop | (not require_short_stop)) & (~has_stop | ((sc[i - 1] + sd_prev) > so[i]))
                elif require_short_stop:
                    go_s[:] = False
                if go_l.any():
                    fill = lo[i] * (1.0 + slip_l)
                    notional = cash[go_l] * f_entry[go_l]
                    q = notional / (fill * (1.0 + fee_l))
                    f = fill * q * fee_l
                    cash[go_l] -= fill * q + f
                    qty[go_l] = q
                    qty0[go_l] = q
                    side[go_l] = 1
                    entry_px[go_l] = fill
                    entry_fee[go_l] = f
                    entry_i[go_l] = i
                    in_pos[go_l] = True
                    alloc[go_l] = f_entry[go_l]
                    alloc0[go_l] = f_entry[go_l]
                    realized[go_l] = 0.0
                    fees_acc[go_l] = f
                    fund_acc[go_l] = 0.0
                    lev_trade[go_l] = 0.0
                    n_red[go_l] = 0
                    hh[go_l] = np.nan
                    ll[go_l] = np.nan
                    if stops is not None:
                        sd = stops[i - 1][go_l]
                        has = np.isfinite(sd) & (sd > 0)
                        stop_px[go_l] = np.where(has, lc[i - 1] - sd, np.nan)
                        risk[go_l] = np.where(has, sd, np.nan)
                    if targets is not None:
                        td = targets[i - 1][go_l]
                        target_px[go_l] = np.where(np.isfinite(td) & (td > 0), lc[i - 1] + td, np.nan)
                    # Same-bar stop for a position just opened at the open.
                    hit = go_l & np.isfinite(stop_px) & (ll_[i] <= stop_px)
                    if hit.any():
                        ref = np.where(lo[i] < stop_px, lo[i], stop_px)
                        _exit(hit, ref, i, "stop_loss")
                if go_s.any():
                    fill = so[i] * (1.0 - slip_s)
                    notional = cash[go_s] * f_entry[go_s]
                    q = notional / (fill * (1.0 + fee_s))
                    f = fill * q * fee_s
                    cash[go_s] += fill * q - f
                    qty[go_s] = -q
                    qty0[go_s] = q
                    side[go_s] = -1
                    entry_px[go_s] = fill
                    entry_fee[go_s] = f
                    entry_i[go_s] = i
                    in_pos[go_s] = True
                    alloc[go_s] = f_entry[go_s]
                    alloc0[go_s] = f_entry[go_s]
                    realized[go_s] = 0.0
                    fees_acc[go_s] = f
                    fund_acc[go_s] = 0.0
                    lev_trade[go_s] = 0.0
                    n_red[go_s] = 0
                    hh[go_s] = np.nan
                    ll[go_s] = np.nan
                    liq_px[go_s] = fill * liq_mult
                    if stops is not None:
                        sd = stops[i - 1][go_s]
                        has = np.isfinite(sd) & (sd > 0)
                        stop_px[go_s] = np.where(has, sc[i - 1] + sd, np.nan)
                        risk[go_s] = np.where(has, sd, np.nan)
                    if targets is not None:
                        td = targets[i - 1][go_s]
                        target_px[go_s] = np.where(np.isfinite(td) & (td > 0), sc[i - 1] - td, np.nan)
                    _short_stops(go_s.copy(), i)
        # Funding settled during this bar, on the position open at its close.
        if use_funding and in_pos.any():
            flow = np.zeros(C)
            if f_long is not None and f_long[i] != 0.0:
                m = in_pos & (side == 1)
                flow[m] = -qty[m] * lc[i] * f_long[i]
            if f_short is not None and f_short[i] != 0.0:
                m = in_pos & (side == -1)
                flow[m] = -qty[m] * sc[i] * f_short[i]
            cash += flow
            fund_acc += flow
            funding_total += flow
        mark = np.where(side == -1, sc[i], lc[i])
        equity[i] = cash + qty * mark
        position[i] = in_pos
        side_m[i] = side
        if overlay:
            allocation[i] = np.where(in_pos, alloc, 0.0)
        # End-of-bar bookkeeping for open positions: leverage, excursions and the trailing stop.
        if in_pos.any():
            with np.errstate(divide="ignore", invalid="ignore"):
                lev = np.where(in_pos & (equity[i] > 0), np.abs(qty) * mark / equity[i], np.where(in_pos, np.inf, 0.0))
            lev_trade[:] = np.where(in_pos, np.fmax(lev_trade, lev), lev_trade)
            max_lev[:] = np.fmax(max_lev, lev)
            hh[:] = np.where(in_pos, np.fmax(hh, np.where(side == -1, sh[i], lh[i])), hh)
            ll[:] = np.where(in_pos, np.fmin(ll, np.where(side == -1, sl_[i], ll_[i])), ll)
            if use_trail:
                armed = in_pos & (side == 1) & trail_on & np.isfinite(risk) & (risk > 0) & ((hh - entry_px) >= act * risk)
                if armed.any():
                    new_stop = hh - dist * risk
                    stop_px[:] = np.where(armed, np.fmax(stop_px, new_stop), stop_px)
                armed_s = in_pos & (side == -1) & trail_on & np.isfinite(risk) & (risk > 0) & ((entry_px - ll) >= act * risk)
                if armed_s.any():
                    new_stop = ll + dist * risk
                    stop_px[:] = np.where(armed_s, np.fmin(stop_px, new_stop), stop_px)
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
        _exit(in_pos.copy(), np.where(side == -1, sc[-1], lc[-1]), n - 1, "end_of_data")
        equity[-1] = cash

    if trade_chunks:
        trades = pd.DataFrame({k: np.concatenate([ch[k] for ch in trade_chunks]) for k in LS_TRADE_COLUMNS})
        trades = trades.sort_values(["combo", "entry_i"], kind="mergesort").reset_index(drop=True)
    else:
        trades = _empty_trades()
    if not np.all(np.isfinite(equity)):
        raise ValueError("non-finite equity produced")
    return LongShortResult(
        equity=equity,
        position=position,
        trades=trades,
        init_cash=float(init_cash),
        n_bars=n,
        n_combos=C,
        exposure=position.mean(axis=0) if n else np.zeros(C),
        allocation=allocation,
        side=side_m,
        funding_total=funding_total,
        max_leverage=max_lev,
        liquidations=n_liq,
    )


NO_LOSS_PROFIT_FACTOR = 999.0  # profit factor of trades without a single loss (Sprint 2c's convention for an infinite value)


def side_metrics(trades: pd.DataFrame, *, init_cash: float) -> dict:
    """P&L attribution by side for one column's trades (pnl includes fees and funding)."""
    out = {}
    for name, sign in (("long", 1), ("short", -1)):
        t = trades[trades["side"] == sign] if len(trades) and "side" in trades else trades.iloc[0:0]
        pnl = t["pnl"].to_numpy(dtype=float) if len(t) else np.zeros(0)
        wins, losses = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
        out[name] = {
            "n_trades": int(len(t)),
            "pnl": float(pnl.sum()),
            "pnl_pct_of_start": float(pnl.sum() / init_cash) if init_cash else 0.0,
            "profit_factor": float(wins / losses) if losses > 0 else (NO_LOSS_PROFIT_FACTOR if wins > 0 else 0.0),
            "win_rate": float((pnl > 0).mean()) if pnl.size else 0.0,
            "funding": float(t["funding"].sum()) if len(t) else 0.0,
            "fees": float(t["fees"].sum()) if len(t) else 0.0,
            "avg_bars_held": float(t["bars_held"].mean()) if len(t) else 0.0,
            "worst_return_pct": float(t["return_pct"].min()) if len(t) else 0.0,
            "worst_mae_pct": float(t["mae_pct"].min()) if len(t) else 0.0,
            "max_leverage": float(t["max_leverage"].max()) if len(t) else 0.0,
            "liquidations": int((t["exit_reason"] == "liquidation").sum()) if len(t) else 0,
        }
    return out
