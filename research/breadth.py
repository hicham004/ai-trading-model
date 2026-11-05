"""Breadth (plan row R20, ``docs/TRADER_PLAN_2026-11-05.md`` section 6.1), SIMULATION ONLY.

Two simulators, both arithmetic on public candles; nothing here can reach an order:

- :func:`run_book` — ONE account across several markets. Every sleeve (a rule on a
  market) brings the bar-by-bar signals the research engine would trade on its own
  (desired long, the stop distance, the exit bracket) and the Trader tier's entry
  fraction; the book funds the entries out of one equity and applies the section 4.3
  brakes at BOOK level — the Turtle ladder, the hard stop, the entry caps (one new
  entry per MARKET per UTC day across the market's sleeves, three per day across the
  book, none in a market on the bar after an exit there), the rolling 24-hour / weekly
  / monthly loss limits on the book's equity, and the heat cap (total current risk,
  price to current stop, at most 6 % of equity; positions whose markets' trailing
  60-day return correlation is 0.70 or more count as one bet with half of the cap;
  when more signals fire than the cap allows, every open and new position of the bet
  is sized down equally, never first come, first served). Allocator v2 (plan row R5b)
  lends its correlation cap (the sleeves of one bet may hold at most 50 % of equity,
  checked at the previous day's close) and its daily record; its portfolio volatility
  target and weekly cash-out are switched OFF so the tier is not sized twice. Spot,
  long only: new entries take at most the cash left and an open position is never
  sold to make room for a new one. On one sleeve with no brakes the book is
  bit-for-bit :func:`research.engine.run_vectorized` (tested).
- :func:`run_weekly_basket` — a daily-booked, weekly-rebalanced long-only basket
  (the rotation test of section 6.1 and its benchmarks): the selection is taken at
  Sunday's close, filled at Monday 00:00 UTC, sized by a volatility target, with an
  optional daily filter that sends the basket to cash.

Every quantity a bar's decision depends on is known at the previous bar's close.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.brakes import BarCalendar, BrakeSpec, EntryBrakes, heat_groups, heat_multipliers, trailing_return_correlations
from research.engine import ALL_TRADE_COLUMNS, Costs, _empty_trades
from research.metrics import equity_metrics, max_drawdown, trade_metrics, yearly_returns

BOOK_TRADE_COLUMNS = ALL_TRADE_COLUMNS + ("sleeve", "instrument", "candidate", "funded_multiplier", "cash_bound", "entry_time", "exit_time")
DAYS_PER_YEAR = 365.25


# -- inputs -------------------------------------------------------------------------------------------------------------

@dataclass
class SleeveInput:
    """One rule on one market, as bar-by-bar arrays over the BOOK's clock (NaN / False where the market has no bar or no rule)."""

    name: str
    instrument: str
    candidate: str
    desired: np.ndarray  # (n,) bool: long wanted at the bar's close (executes at the next open)
    stop: np.ndarray  # (n,) stop distance at the decision bar (NaN = no stop)
    fraction: np.ndarray  # (n,) the tier's entry fraction of equity at the decision bar (NaN = no entry)
    strength: Optional[np.ndarray] = None  # (n,) the rule's strength (same-bar tie-break for the entry caps; NaN = none)
    target: Optional[np.ndarray] = None  # (n,) take-profit distance (NaN = none)
    time_stop: Optional[np.ndarray] = None  # (n,) time stop in bars for a trade entered on the decision bar (NaN = none)
    trail_activate: Optional[np.ndarray] = None  # (n,) trailing activation in R (NaN = no trailing stop)
    trail_r: Optional[np.ndarray] = None  # (n,) trailing distance in R

    def __post_init__(self) -> None:
        n = len(self.desired)
        for key in ("stop", "fraction", "strength", "target", "time_stop", "trail_activate", "trail_r"):
            arr = getattr(self, key)
            if arr is not None and len(arr) != n:
                raise ValueError(f"{self.name}: {key} must have one value per bar")
        if (self.trail_activate is None) != (self.trail_r is None):
            raise ValueError(f"{self.name}: trail_activate and trail_r go together")


@dataclass(frozen=True)
class BookConfig:
    """What the book layers over its sleeves. ``brakes=None`` and ``corr_cap=None`` leave only the cash constraint."""

    brakes: Optional[BrakeSpec] = None
    corr_cap: Optional[float] = 0.50  # allocator v2's correlation cap: one bet may hold at most this share of equity (None = off)
    corr_lookback_days: int = 60
    corr_min_days: int = 20
    corr_threshold: float = 0.70
    rebalance_threshold: Optional[float] = 0.25  # Sprint 2c's reduce-only mid-trade adjustment
    init_cash: float = 10_000.0

    def __post_init__(self) -> None:
        if self.corr_cap is not None and not (0.0 < float(self.corr_cap) <= 1.0):
            raise ValueError("corr_cap must be in (0, 1] or None")
        if int(self.corr_lookback_days) < 2 or not (2 <= int(self.corr_min_days) <= int(self.corr_lookback_days)):
            raise ValueError("corr_lookback_days must be >= 2 and corr_min_days in [2, corr_lookback_days]")
        if not (0.0 < float(self.corr_threshold) <= 1.0):
            raise ValueError("corr_threshold must be in (0, 1]")
        if self.rebalance_threshold is not None and not (0.0 <= float(self.rebalance_threshold) < 1.0):
            raise ValueError("rebalance_threshold must be in [0, 1) or None")
        if float(self.init_cash) <= 0:
            raise ValueError("init_cash must be positive")

    @property
    def label(self) -> str:
        parts = [self.brakes.label if self.brakes is not None and self.brakes.active else "no book brakes"]
        parts.append(f"correlation cap {self.corr_cap * 100:.0f}% per bet (corr >= {self.corr_threshold:.2f} over {int(self.corr_lookback_days)}d)"
                     if self.corr_cap is not None else "no correlation cap")
        parts.append("no portfolio volatility target, no weekly cash-out (the tier sizes each entry)")
        return "; ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"brakes": None if self.brakes is None else self.brakes.to_dict(), "corr_cap": self.corr_cap, "corr_lookback_days": int(self.corr_lookback_days),
                "corr_min_days": int(self.corr_min_days), "corr_threshold": float(self.corr_threshold), "rebalance_threshold": self.rebalance_threshold,
                "init_cash": float(self.init_cash), "label": self.label}


@dataclass
class BookResult:
    clock: pd.DatetimeIndex
    equity: pd.Series  # marked at every bar close
    position: pd.DataFrame  # (n, S) bool
    value_share: pd.DataFrame  # (n, S) position value / equity at the bar close
    trades: pd.DataFrame
    daily: List[Dict[str, Any]]  # allocator v2's record structure, one per UTC day
    brakes: Dict[str, Any]  # counts of what the book-level rules did
    config: Dict[str, Any]
    sleeves: List[Dict[str, Any]]
    init_cash: float

    def metrics(self, periods_per_year: float) -> Dict[str, Any]:
        """The engine's metrics of the book: the equity curve, the pooled trades, exposure and allocation."""
        eq = np.concatenate([[self.init_cash], self.equity.to_numpy(dtype=float)])
        out: Dict[str, Any] = equity_metrics(eq, periods_per_year)
        out.update(trade_metrics(self.trades, init_cash=self.init_cash, n_bars=len(self.equity), periods_per_year=periods_per_year))
        out["exposure"] = float(self.position.any(axis=1).mean()) if len(self.position) else 0.0
        out["avg_allocation"] = float(self.value_share.sum(axis=1).mean()) if len(self.value_share) else 0.0
        out["max_allocation"] = float(self.value_share.sum(axis=1).max()) if len(self.value_share) else 0.0
        out["positions_mean"] = float(self.position.sum(axis=1).mean()) if len(self.position) else 0.0
        out["positions_max"] = int(self.position.sum(axis=1).max()) if len(self.position) else 0
        return out


# -- helpers ------------------------------------------------------------------------------------------------------------------

def daily_closes(clock: pd.DatetimeIndex, closes: Mapping[str, np.ndarray]) -> pd.DataFrame:
    """One close per UTC day per market: the last bar that opened that day (NaN when the market had no bar)."""
    idx = pd.DatetimeIndex(clock)
    days = idx.tz_convert("UTC").floor("D") if idx.tz is not None else idx.floor("D")
    frame = pd.DataFrame({m: np.asarray(v, dtype=float) for m, v in closes.items()}, index=days)
    out = frame.groupby(level=0).last()
    out.index.name = "day"
    return out


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# -- the book ------------------------------------------------------------------------------------------------------------------

def run_book(clock: pd.DatetimeIndex, markets: Mapping[str, pd.DataFrame], sleeves: Sequence[SleeveInput], *, costs: Mapping[str, Costs],
             cfg: BookConfig = BookConfig(), market_order: Optional[Sequence[str]] = None, start: int = 0) -> BookResult:
    """Simulate the book over ``clock`` from bar ``start`` on (the bars before it only warm up the daily correlations).

    ``markets``: per instrument an OHLC frame REINDEXED to ``clock`` (NaN rows where the market has no bar); ``costs``: per
    instrument the fee and slippage per side; ``market_order``: the fixed order that breaks same-bar ties among entries (after
    the rules' strength), default the order of ``markets``. The result's series cover ``clock[start:]``; the trades' bar
    indexes are those of the full clock.
    """
    n = len(clock)
    S = len(sleeves)
    if n == 0 or S == 0:
        raise ValueError("the book needs bars and at least one sleeve")
    start = int(start)
    if not (0 <= start < n):
        raise ValueError("start must index a bar of the clock")
    order = list(market_order or markets)
    for s in sleeves:
        if s.instrument not in markets:
            raise ValueError(f"sleeve {s.name}: no candles for {s.instrument}")
        if s.instrument not in costs:
            raise ValueError(f"sleeve {s.name}: no costs for {s.instrument}")
        if len(s.desired) != n:
            raise ValueError(f"sleeve {s.name}: arrays must cover the book clock ({n} bars)")
    insts = sorted(set(s.instrument for s in sleeves), key=lambda m: order.index(m) if m in order else len(order))
    M = len(insts)
    m_of = np.array([insts.index(s.instrument) for s in sleeves], dtype=int)
    rank_of_market = {m: k for k, m in enumerate(insts)}

    def arr(frame: pd.DataFrame, col: str) -> np.ndarray:
        if len(frame) != n:
            raise ValueError("every market frame must be reindexed to the book clock")
        return frame[col].to_numpy(dtype=float)

    O = np.column_stack([arr(markets[m], "open") for m in insts])
    H = np.column_stack([arr(markets[m], "high") for m in insts])
    L = np.column_stack([arr(markets[m], "low") for m in insts])
    C = np.column_stack([arr(markets[m], "close") for m in insts])
    has_bar = np.isfinite(C) & np.isfinite(O) & np.isfinite(H) & np.isfinite(L)
    if np.any(L[has_bar] <= 0):
        raise ValueError("OHLC must be positive")
    fee = np.array([costs[m].fee_rate for m in insts])
    slip = np.array([costs[m].slippage_rate for m in insts])

    def stack(key: str, default: float = np.nan) -> np.ndarray:
        cols = []
        for s in sleeves:
            v = getattr(s, key)
            cols.append(np.full(n, default) if v is None else np.asarray(v, dtype=float))
        return np.column_stack(cols)

    desired = np.column_stack([np.asarray(s.desired, dtype=bool) for s in sleeves])
    stop = stack("stop")
    frac = stack("fraction")
    strength = stack("strength")
    target = stack("target")
    tstop = stack("time_stop")
    tact = stack("trail_activate")
    tdist = stack("trail_r")
    finite_frac = frac[np.isfinite(frac)]
    if finite_frac.size and (finite_frac.min() < 0.0 or finite_frac.max() > 1.0 + 1e-12):
        raise ValueError("entry fractions must be in [0, 1] (long-only spot, no leverage)")

    cal = BarCalendar.from_times(clock)
    spec = cfg.brakes if (cfg.brakes is not None and cfg.brakes.active) else None
    book_brakes = EntryBrakes(spec, 1, float(cfg.init_cash), cal) if spec is not None else None  # the book's equity brakes (ladder, hard stop, loss limits)
    corr_threshold = float(spec.corr_threshold) if spec is not None else float(cfg.corr_threshold)
    corr_lookback = int(spec.corr_lookback_days) if spec is not None else int(cfg.corr_lookback_days)
    need_groups = (spec is not None and spec.heat_cap is not None) or cfg.corr_cap is not None
    dclose = daily_closes(clock, {m: C[:, k] for k, m in enumerate(insts)})
    corr_series = trailing_return_correlations(dclose, corr_lookback, min_days=int(cfg.corr_min_days)) if (need_groups and M > 1) else {}
    corr_days = dclose.index
    asset_of = {s.name: s.instrument for s in sleeves}
    names = [s.name for s in sleeves]
    name_idx = {s.name: k for k, s in enumerate(sleeves)}

    def correlations_at(day_ts: pd.Timestamp) -> Dict[Tuple[str, str], Optional[float]]:
        out: Dict[Tuple[str, str], Optional[float]] = {}
        for pair, series in corr_series.items():
            v = series.get(day_ts) if day_ts in series.index else None
            out[pair] = _finite(v)
        return out

    def groups_at(day_ts: pd.Timestamp) -> Tuple[List[List[str]], Dict[Tuple[str, str], Optional[float]]]:
        corr = correlations_at(day_ts)
        return heat_groups(asset_of, corr, corr_threshold), corr

    # -- state --------------------------------------------------------------------------------------------------------
    cash = float(cfg.init_cash)
    qty = np.zeros(S)
    qty0 = np.zeros(S)
    in_pos = np.zeros(S, dtype=bool)
    entry_px = np.zeros(S)
    entry_fee = np.zeros(S)
    entry_i = np.full(S, -1, dtype=np.int64)
    stop_px = np.full(S, np.nan)
    target_px = np.full(S, np.nan)
    risk = np.full(S, np.nan)
    hh = np.full(S, np.nan)
    ll = np.full(S, np.nan)
    alloc = np.zeros(S)
    alloc0 = np.zeros(S)
    realized = np.zeros(S)
    fees_acc = np.zeros(S)
    n_red = np.zeros(S, dtype=np.int64)
    stop0 = np.full(S, np.nan)
    risk_money = np.full(S, np.nan)
    risk_pct = np.full(S, np.nan)
    ts_bars = np.full(S, np.nan)
    tr_act = np.full(S, np.nan)
    tr_dist = np.full(S, np.nan)
    funded = np.ones(S)
    cash_bound = np.zeros(S, dtype=bool)
    last_close = np.full(M, np.nan)
    equity = np.empty(n)
    position = np.zeros((n, S), dtype=bool)
    value_share = np.zeros((n, S))
    entries_today = np.zeros(M, dtype=np.int64)
    book_entries_today = 0
    last_exit_bar = np.full(M, -10, dtype=np.int64)
    cur_day: Optional[int] = None
    group_mult_today: Dict[str, float] = {}
    groups_today: List[List[str]] = [[nm] for nm in names]
    corr_today: Dict[Tuple[str, str], Optional[float]] = {}
    counts: Dict[str, int] = {k: 0 for k in ("hard_stop", "entry_cap_market_day", "entry_cap_book_day", "entry_after_exit", "daily_loss", "weekly_loss",
                                             "monthly_loss", "ladder", "heat_cap_entries", "heat_cap_reductions", "corr_cap_entries", "corr_cap_reductions",
                                             "cash_bound_entries", "cash_blocked_entries", "opportunities", "entries", "bars_blocked")}
    corr_cap_days = 0
    corr_cap_cuts: List[float] = []
    heat_total_max = 0.0
    heat_totals: List[float] = []
    trade_chunks: List[Dict[str, Any]] = []
    daily: List[Dict[str, Any]] = []
    day_brakes: List[str] = []
    day_invested_before: Dict[str, float] = {}
    day_group_mult: Dict[str, float] = {}
    day_heat_before = 0.0
    day_heat_after = 0.0

    def mark_equity(prices: np.ndarray) -> float:
        # A market that has no bar yet has no price; nothing is held in it, so it adds nothing (never 0 x NaN).
        held = qty > 0
        return float(cash + np.sum(np.where(held, qty * prices[m_of], 0.0)))

    def _exit_one(s: int, price: float, i: int, reason: str) -> None:
        nonlocal cash
        k = m_of[s]
        fill = price * (1.0 - slip[k])
        q, q0 = qty[s], qty0[s]
        proceeds = fill * q
        exit_fee = proceeds * fee[k]
        cash += proceeds - exit_fee
        share = q / q0 if q0 > 0 else 0.0
        pnl = realized[s] + proceeds - exit_fee - entry_px[s] * q - entry_fee[s] * share
        fees = fees_acc[s] + exit_fee
        outlay = entry_px[s] * q0 + entry_fee[s]
        trade_chunks.append({
            "combo": s, "entry_i": int(entry_i[s]), "exit_i": int(i), "entry_price": float(entry_px[s]), "exit_price": float(fill), "quantity": float(q0),
            "fees": float(fees), "pnl": float(pnl), "return_pct": float(pnl / outlay) if outlay > 0 else 0.0, "bars_held": int(i - entry_i[s]), "exit_reason": reason,
            "mfe_pct": float(hh[s] / entry_px[s] - 1.0) if np.isfinite(hh[s]) else 0.0, "mae_pct": float(ll[s] / entry_px[s] - 1.0) if np.isfinite(ll[s]) else 0.0,
            "size_fraction": float(alloc0[s]), "reductions": int(n_red[s]), "stop_price": float(stop0[s]), "risk": float(risk_money[s]), "risk_pct": float(risk_pct[s]),
            "adds": 0, "add_worst_case_r": np.nan, "scale_outs": 0, "sleeve": names[s], "instrument": insts[k], "candidate": sleeves[s].candidate,
            "funded_multiplier": float(funded[s]), "cash_bound": bool(cash_bound[s]), "entry_time": clock[int(entry_i[s])], "exit_time": clock[int(i)],
        })
        in_pos[s] = False
        qty[s] = qty0[s] = 0.0
        stop_px[s] = target_px[s] = risk[s] = hh[s] = ll[s] = np.nan
        alloc[s] = alloc0[s] = realized[s] = fees_acc[s] = 0.0
        n_red[s] = 0
        stop0[s] = risk_money[s] = risk_pct[s] = ts_bars[s] = tr_act[s] = tr_dist[s] = np.nan
        funded[s] = 1.0
        cash_bound[s] = False
        last_exit_bar[k] = i

    def _reduce_one(s: int, price: float, target_alloc: float) -> None:
        nonlocal cash
        k = m_of[s]
        fill = price * (1.0 - slip[k])
        ratio = target_alloc / alloc[s] if alloc[s] > 0 else 1.0
        dq = qty[s] * (1.0 - ratio)
        proceeds = fill * dq
        f = proceeds * fee[k]
        cash += proceeds - f
        realized[s] += proceeds - f - entry_px[s] * dq - entry_fee[s] * (dq / qty0[s])
        fees_acc[s] += f
        qty[s] -= dq
        alloc[s] = target_alloc
        n_red[s] += 1

    def _check_stops(i: int) -> np.ndarray:
        exited = np.zeros(S, dtype=bool)
        for s in np.where(in_pos)[0]:
            k = m_of[s]
            if not has_bar[i, k]:
                continue
            if np.isfinite(stop_px[s]) and L[i, k] <= stop_px[s]:
                _exit_one(s, min(O[i, k], stop_px[s]), i, "stop_loss")
                exited[s] = True
                continue
            if np.isfinite(target_px[s]) and H[i, k] >= target_px[s]:
                _exit_one(s, max(O[i, k], target_px[s]), i, "target")
                exited[s] = True
                continue
            if np.isfinite(ts_bars[s]) and (i - entry_i[s]) >= ts_bars[s]:
                _exit_one(s, O[i, k], i, "time_stop")
                exited[s] = True
        return exited

    def _value_shares(prices: np.ndarray, eq: float) -> np.ndarray:
        if eq <= 0:
            return np.zeros(S)
        out = np.where(in_pos, qty * prices[m_of] / eq, 0.0)
        return np.where(np.isfinite(out), out, 0.0)

    def _close_day(i: int, day_ts: pd.Timestamp) -> None:
        nonlocal day_brakes, day_invested_before, day_group_mult, day_heat_before, day_heat_after
        eq = float(equity[i])
        shares = _value_shares(np.where(np.isfinite(C[i]), C[i], last_close), eq)
        held = {nm: bool(in_pos[k]) for k, nm in enumerate(names)}
        inv_group = {"+".join(g): float(sum(shares[name_idx[nm]] for nm in g)) for g in groups_today}
        daily.append({"day": day_ts.strftime("%Y-%m-%d"), "equity_index": eq / float(cfg.init_cash), "positions_close": held,
                      "value_share_close": {nm: float(shares[k]) for k, nm in enumerate(names) if in_pos[k]}, "invested_share_close": float(shares.sum()),
                      "groups": [list(g) for g in groups_today], "correlations": {f"{a}/{b}": v for (a, b), v in sorted(corr_today.items())},
                      "invested_before_cap": dict(day_invested_before), "group_multipliers": dict(day_group_mult), "heat_before_cap": day_heat_before,
                      "heat_after_cap": day_heat_after, "ladder_multiplier": float(book_brakes.lad_mult[0]) if book_brakes is not None else 1.0,
                      "halted": bool(book_brakes.halted[0]) if book_brakes is not None else False, "brakes": sorted(set(day_brakes))})
        day_brakes, day_invested_before, day_group_mult = [], {}, {}
        day_heat_before = day_heat_after = 0.0

    equity[:start] = float(cfg.init_cash)
    for i in range(start, n):
        day = int(cal.day[i])
        new_day = day != cur_day
        if new_day:
            cur_day = day
            entries_today[:] = 0
            book_entries_today = 0
            group_mult_today = {}
            if need_groups and M > 1:
                day_ts = pd.Timestamp(clock[i]).tz_convert("UTC").floor("D") if pd.Timestamp(clock[i]).tzinfo is not None else pd.Timestamp(clock[i]).floor("D")
                groups_today, corr_today = groups_at(day_ts if day_ts in corr_days else corr_days[corr_days <= day_ts][-1] if (corr_days <= day_ts).any() else day_ts)
            else:
                groups_today = [[nm] for nm in names]
                corr_today = {}
        if i > start:
            prev_prices = np.where(np.isfinite(C[i - 1]), C[i - 1], last_close)
            exited = _check_stops(i)
            # Exit at the open when the decision turned off.
            for s in np.where(in_pos & ~desired[i - 1] & ~exited)[0]:
                k = m_of[s]
                if has_bar[i, k]:
                    _exit_one(s, O[i, k], i, "signal")
            # Reduce-only de-risking (the Sprint 2c fraction overlay): the decision-bar fraction against the entry allocation.
            if cfg.rebalance_threshold is not None:
                thr = float(cfg.rebalance_threshold)
                for s in np.where(in_pos)[0]:
                    k = m_of[s]
                    if not has_bar[i, k]:
                        continue
                    f_dec = frac[i - 1, s]
                    basis = f_dec if np.isfinite(f_dec) else alloc0[s]
                    tgt = min(alloc[s], basis)
                    if tgt <= 1e-12:
                        _exit_one(s, O[i, k], i, "derisk")
                    elif tgt < alloc[s] * (1.0 - thr) - 1e-12:
                        _reduce_one(s, O[i, k], tgt)
            # Allocator v2's correlation cap, once a day at the previous close: a bet above the cap is scaled down equally.
            if cfg.corr_cap is not None and new_day and in_pos.any():
                eq_prev = mark_equity(prev_prices)
                shares_prev = _value_shares(prev_prices, eq_prev)
                acted = False
                for g in groups_today:
                    key = "+".join(g)
                    members = [name_idx[nm] for nm in g]
                    invested = float(sum(shares_prev[s] for s in members))
                    day_invested_before[key] = invested
                    if invested > float(cfg.corr_cap) + 1e-12:
                        m_g = float(cfg.corr_cap) / invested
                        group_mult_today[key] = m_g
                        day_group_mult[key] = m_g
                        acted = True
                        corr_cap_cuts.append(1.0 - m_g)
                        for s in members:
                            if in_pos[s] and has_bar[i, m_of[s]]:
                                _reduce_one(s, O[i, m_of[s]], alloc[s] * m_g)
                                counts["corr_cap_reductions"] += 1
                if acted:
                    corr_cap_days += 1
                    day_brakes.append("correlation cap")
            # Entries at the open: the candidates, the book's brakes, the heat cap, then the fills.
            want = desired[i - 1] & ~in_pos & ~exited & has_bar[i, m_of] & has_bar[i - 1, m_of]
            f_entry = np.where(np.isfinite(frac[i - 1]), frac[i - 1], 0.0)
            want &= f_entry > 0.0
            if want.any():
                sd_prev = stop[i - 1]
                has_stop = np.isfinite(sd_prev) & (sd_prev > 0)
                c_prev = C[i - 1][m_of]
                o_now = O[i][m_of]
                want &= ~has_stop | ((c_prev - sd_prev) < o_now)
            if want.any():
                counts["opportunities"] += int(want.sum())
                blocked_any = False
                stren = strength[i - 1]
                cands = sorted(np.where(want)[0].tolist(), key=lambda s: (-(stren[s] if np.isfinite(stren[s]) else -np.inf), rank_of_market[insts[m_of[s]]], s))
                survivors: List[int] = []
                for s in cands:
                    k = m_of[s]
                    blocked = False
                    if book_brakes is not None:
                        if spec.hard_stop_dd is not None and book_brakes.halted[0]:
                            counts["hard_stop"] += 1
                            blocked = True
                        if spec.daily_loss_limit is not None and i < book_brakes.daily_block_until[0]:
                            counts["daily_loss"] += 1
                            blocked = True
                        if spec.weekly_loss_limit is not None and book_brakes.week_blocked_id[0] == cal.week[i]:
                            counts["weekly_loss"] += 1
                            blocked = True
                        if spec.monthly_loss_limit is not None and book_brakes.month_blocked_id[0] == cal.month[i]:
                            counts["monthly_loss"] += 1
                            blocked = True
                        if spec.no_entry_bar_after_exit and (i - last_exit_bar[k]) == 1:
                            counts["entry_after_exit"] += 1
                            blocked = True
                        if spec.max_entries_per_market_per_day is not None and entries_today[k] >= int(spec.max_entries_per_market_per_day):
                            counts["entry_cap_market_day"] += 1
                            blocked = True
                        if spec.max_entries_per_day is not None and (book_entries_today + len(survivors)) >= int(spec.max_entries_per_day):
                            counts["entry_cap_book_day"] += 1
                            blocked = True
                    if blocked:
                        blocked_any = True
                        continue
                    if book_brakes is not None and spec.ladder is not None and book_brakes.lad_mult[0] < 1.0:
                        f_entry[s] *= float(book_brakes.lad_mult[0])
                        counts["ladder"] += 1
                        day_brakes.append("ladder")
                    g_key = next(("+".join(g) for g in groups_today if names[s] in g), names[s])
                    if g_key in group_mult_today:
                        f_entry[s] *= group_mult_today[g_key]
                        counts["corr_cap_entries"] += 1
                    survivors.append(s)
                    if spec is not None and spec.max_entries_per_market_per_day is not None:
                        entries_today[k] += 1  # provisional: the candidate holds the market's slot for this bar (released below if it cannot fill)
                if blocked_any:
                    counts["bars_blocked"] += 1
                if survivors:
                    # The heat cap: the current risk of the open positions plus the wanted entries, per bet and in total.
                    prev_prices = np.where(np.isfinite(C[i - 1]), C[i - 1], last_close)
                    eq_mark = mark_equity(prev_prices)
                    heat_mult = {nm: 1.0 for nm in names}
                    if spec is not None and spec.heat_cap is not None and eq_mark > 0:
                        risks: Dict[str, float] = {}
                        for s in np.where(in_pos)[0]:
                            r_open = qty[s] * (prev_prices[m_of[s]] - stop_px[s]) / eq_mark if np.isfinite(stop_px[s]) else 0.0
                            if r_open > 1e-12:
                                risks[names[s]] = float(r_open)
                        for s in survivors:
                            sp = stop[i - 1, s] / C[i - 1, m_of[s]] if np.isfinite(stop[i - 1, s]) and stop[i - 1, s] > 0 else np.nan
                            if np.isfinite(sp):
                                risks[names[s]] = float(f_entry[s] * sp)
                        total_before = float(sum(risks.values()))
                        heat_totals.append(total_before)
                        heat_total_max = max(heat_total_max, total_before)
                        day_heat_before = max(day_heat_before, total_before)
                        wanted_names = {names[s] for s in survivors}
                        heat_mult.update(_heat_scaling(risks, groups_today, float(spec.heat_cap), float(spec.heat_group_share), wanted_names))
                        acted = False
                        for s in np.where(in_pos)[0]:
                            m_s = heat_mult.get(names[s], 1.0)
                            if m_s < 1.0 - 1e-12 and has_bar[i, m_of[s]]:
                                _reduce_one(s, O[i, m_of[s]], alloc[s] * m_s)
                                counts["heat_cap_reductions"] += 1
                                acted = True
                        for s in survivors:
                            m_s = heat_mult.get(names[s], 1.0)
                            if m_s < 1.0 - 1e-12:
                                f_entry[s] *= m_s
                                counts["heat_cap_entries"] += 1
                                acted = True
                        if acted:
                            day_brakes.append("heat cap")
                        day_heat_after = max(day_heat_after, float(sum(r * heat_mult.get(nm, 1.0) for nm, r in risks.items())))
                        eq_mark = mark_equity(prev_prices)
                    for s in survivors:
                        k = m_of[s]
                        if f_entry[s] <= 0.0:
                            entries_today[k] -= 1 if (spec is not None and spec.max_entries_per_market_per_day is not None) else 0
                            continue
                        wanted_notional = f_entry[s] * eq_mark
                        notional = min(wanted_notional, cash)
                        if notional <= 1e-9:
                            counts["cash_blocked_entries"] += 1
                            day_brakes.append("cash")
                            if spec is not None and spec.max_entries_per_market_per_day is not None:
                                entries_today[k] -= 1
                            continue
                        bound = notional < wanted_notional - 1e-9
                        if bound:
                            counts["cash_bound_entries"] += 1
                            day_brakes.append("cash")
                        fill = O[i, k] * (1.0 + slip[k])
                        q = notional / (fill * (1.0 + fee[k]))
                        f = fill * q * fee[k]
                        equity_before = eq_mark
                        cash -= fill * q + f
                        qty[s] = qty0[s] = q
                        entry_px[s] = fill
                        entry_fee[s] = f
                        entry_i[s] = i
                        in_pos[s] = True
                        alloc[s] = alloc0[s] = notional / equity_before if equity_before > 0 else f_entry[s]
                        realized[s] = 0.0
                        fees_acc[s] = f
                        n_red[s] = 0
                        hh[s] = ll[s] = np.nan
                        funded[s] = float(f_entry[s] / frac[i - 1, s]) if frac[i - 1, s] > 0 else 1.0
                        cash_bound[s] = bool(bound)
                        sd = stop[i - 1, s]
                        if np.isfinite(sd) and sd > 0:
                            stop_px[s] = C[i - 1, k] - sd
                            risk[s] = sd
                            stop0[s] = stop_px[s]
                            risk_money[s] = q * (fill - stop_px[s])
                            risk_pct[s] = risk_money[s] / equity_before if equity_before > 0 else np.nan
                        td = target[i - 1, s]
                        target_px[s] = C[i - 1, k] + td if (np.isfinite(td) and td > 0) else np.nan
                        ts_bars[s] = tstop[i - 1, s] if (np.isfinite(tstop[i - 1, s]) and tstop[i - 1, s] > 0) else np.nan
                        if np.isfinite(tact[i - 1, s]) and np.isfinite(tdist[i - 1, s]):
                            tr_act[s], tr_dist[s] = float(tact[i - 1, s]), float(tdist[i - 1, s])
                        counts["entries"] += 1
                        book_entries_today += 1
                        if book_brakes is not None:
                            book_brakes.on_entry(i, np.array([True]))
                        # Same-bar stop for a position just opened at the open.
                        if np.isfinite(stop_px[s]) and L[i, k] <= stop_px[s]:
                            _exit_one(s, min(O[i, k], stop_px[s]), i, "stop_loss")
        if i == start and start > 0:
            for k in range(M):
                earlier = C[:start, k][np.isfinite(C[:start, k])]
                if earlier.size:
                    last_close[k] = earlier[-1]
        prices_now = np.where(np.isfinite(C[i]), C[i], last_close)
        last_close = np.where(np.isfinite(C[i]), C[i], last_close)
        equity[i] = mark_equity(prices_now)
        position[i] = in_pos
        value_share[i] = _value_shares(prices_now, float(equity[i]))
        # End-of-bar bookkeeping of the open positions: excursions and the trailing stops.
        for s in np.where(in_pos)[0]:
            k = m_of[s]
            if not has_bar[i, k]:
                continue
            hh[s] = H[i, k] if not np.isfinite(hh[s]) else max(hh[s], H[i, k])
            ll[s] = L[i, k] if not np.isfinite(ll[s]) else min(ll[s], L[i, k])
            if np.isfinite(tr_act[s]) and np.isfinite(risk[s]) and risk[s] > 0 and (hh[s] - entry_px[s]) >= tr_act[s] * risk[s]:
                new_stop = hh[s] - tr_dist[s] * risk[s]
                stop_px[s] = new_stop if not np.isfinite(stop_px[s]) else max(stop_px[s], new_stop)
        if book_brakes is not None:
            book_brakes.on_bar_close(i, np.array([equity[i]]))
        last_bar_of_day = i == n - 1 or int(cal.day[i + 1]) != day
        if last_bar_of_day:
            ts = pd.Timestamp(clock[i])
            _close_day(i, ts.tz_convert("UTC").floor("D") if ts.tzinfo is not None else ts.floor("D"))

    # Terminal bookkeeping: value any open position at the last close (not a trade signal).
    if in_pos.any():
        for s in np.where(in_pos)[0]:
            _exit_one(s, float(last_close[m_of[s]]), n - 1, "end_of_data")
        equity[-1] = cash
    if trade_chunks:
        trades = pd.DataFrame(trade_chunks, columns=list(BOOK_TRADE_COLUMNS)).sort_values(["combo", "entry_i"], kind="mergesort").reset_index(drop=True)
    else:
        trades = _empty_trades()
        for col in BOOK_TRADE_COLUMNS[len(ALL_TRADE_COLUMNS):]:
            trades[col] = pd.Series(dtype=object)
    if not np.all(np.isfinite(equity)):
        raise ValueError("non-finite equity produced")
    summary: Dict[str, Any] = {
        "counts": counts, "spec": None if spec is None else spec.to_dict(), "corr_cap": cfg.corr_cap, "corr_cap_days": corr_cap_days,
        "corr_cap_average_cut": float(np.mean(corr_cap_cuts)) if corr_cap_cuts else None,
        "heat_total_max": heat_total_max, "heat_total_mean_at_entries": float(np.mean(heat_totals)) if heat_totals else None,
        "trips": {k: int(v[0]) for k, v in book_brakes.trips.items()} if book_brakes is not None else {},
        "ladder_bars": {k: int(v[0]) for k, v in book_brakes.ladder_bars.items()} if book_brakes is not None else {},
        "bars": int(n - start), "days": len(daily), "start_bar": str(clock[start]),
        "halted_from": next((d["day"] for d in daily if d.get("halted")), None),
        "halted_days_share": (sum(1 for d in daily if d.get("halted")) / len(daily)) if daily else 0.0,
    }
    sub = slice(start, n)
    out_clock = pd.DatetimeIndex(clock[sub])
    return BookResult(clock=out_clock, equity=pd.Series(equity[sub], index=out_clock), position=pd.DataFrame(position[sub], index=out_clock, columns=names),
                      value_share=pd.DataFrame(value_share[sub], index=out_clock, columns=names), trades=trades, daily=daily, brakes=summary,
                      config=dict(cfg.to_dict(), costs={m: {"fee_rate": costs[m].fee_rate, "slippage_rate": costs[m].slippage_rate} for m in insts}),
                      sleeves=[{"name": s.name, "instrument": s.instrument, "candidate": s.candidate} for s in sleeves], init_cash=float(cfg.init_cash))


def _heat_scaling(risks: Mapping[str, float], groups: Sequence[Sequence[str]], cap: float, group_share: float, wanted: set) -> Dict[str, float]:
    """The heat cap's multipliers, entries only: a bet is scaled down (open and new positions equally) only when a NEW entry is wanted in it; a
    bet whose open positions drifted above their share on their own is left alone until a new entry asks for room; the total cap then scales
    every position equally (:func:`research.brakes.heat_multipliers` with the bets without a wanted entry taken out of the group step)."""
    active = [g for g in groups if any(n in wanted for n in g)]
    passive = {n for g in groups if not any(n in wanted for n in g) for n in g}
    mult = heat_multipliers({n: r for n, r in risks.items() if n not in passive}, active, cap, group_share)
    # The total cap over everything: the passive positions count toward it and share the cut when the wanted entries push the book over it.
    total = sum(max(0.0, float(risks[n])) * mult.get(n, 1.0) for n in risks)
    if total > cap + 1e-12:
        f = cap / total
        return {n: mult.get(n, 1.0) * f for n in risks}
    return {n: mult.get(n, 1.0) for n in risks}


def sleeve_contributions(result: BookResult) -> pd.DataFrame:
    """Each sleeve's closed-trade P&L booked on its exit day as a fraction of the book's equity at that close (daily, for correlations)."""
    if result.trades.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="day"))
    eq = result.equity
    days = eq.index.tz_convert("UTC").floor("D") if eq.index.tz is not None else eq.index.floor("D")
    eq_day = eq.groupby(days).last()
    out = pd.DataFrame(0.0, index=eq_day.index, columns=sorted({s["name"] for s in result.sleeves}))
    for _, t in result.trades.iterrows():
        d = pd.Timestamp(t["exit_time"])
        d = d.tz_convert("UTC").floor("D") if d.tzinfo is not None else d.floor("D")
        if d in out.index and float(eq_day.loc[d]) > 0:
            out.loc[d, t["sleeve"]] += float(t["pnl"]) / float(eq_day.loc[d])
    out.index.name = "day"
    return out


# -- the daily basket (the rotation test and its benchmarks) --------------------------------------------------------------------

@dataclass(frozen=True)
class BasketConfig:
    vol_target: Optional[float] = 0.20  # annualized; None = fully invested
    vol_lookback_days: int = 30
    costs_per_side: Mapping[str, float] = field(default_factory=dict)  # per market: fee + slippage per side, charged on traded notional
    default_cost_per_side: float = 0.0015
    rebalance_weekday: int = 0  # Monday (the decision is taken at the previous day's close)
    init_cash: float = 10_000.0

    def __post_init__(self) -> None:
        if self.vol_target is not None and float(self.vol_target) <= 0:
            raise ValueError("vol_target must be positive or None")
        if int(self.vol_lookback_days) < 2:
            raise ValueError("vol_lookback_days must be at least 2")
        if not (0 <= int(self.rebalance_weekday) <= 6):
            raise ValueError("rebalance_weekday must be 0..6")
        if float(self.init_cash) <= 0:
            raise ValueError("init_cash must be positive")

    def cost(self, market: str) -> float:
        return float(self.costs_per_side.get(market, self.default_cost_per_side))

    def to_dict(self) -> Dict[str, Any]:
        return {"vol_target": self.vol_target, "vol_lookback_days": int(self.vol_lookback_days), "costs_per_side": dict(self.costs_per_side),
                "default_cost_per_side": self.default_cost_per_side, "rebalance_weekday": int(self.rebalance_weekday), "init_cash": float(self.init_cash)}


@dataclass
class BasketResult:
    equity: pd.Series  # marked at each day's close
    weights: pd.DataFrame  # target weights set at each day's open (after the vol scale), by day
    records: List[Dict[str, Any]]
    config: Dict[str, Any]
    init_cash: float

    def metrics(self) -> Dict[str, Any]:
        eq = np.concatenate([[self.init_cash], self.equity.to_numpy(dtype=float)])
        out: Dict[str, Any] = equity_metrics(eq, DAYS_PER_YEAR)
        years = len(self.equity) / DAYS_PER_YEAR
        turnover = sum(float(r["turnover"]) for r in self.records)
        fees = sum(float(r["cost"]) for r in self.records)
        invested = [float(r["invested_share"]) for r in self.records]
        out.update({"days": int(len(self.equity)), "years": years, "turnover_per_year": turnover / years if years else 0.0,
                    "fees_pct_of_start": fees / self.init_cash, "fees_pct_per_year": fees / self.init_cash / years if years else 0.0,
                    "rebalances": int(sum(1 for r in self.records if r["rebalanced"])), "filter_exits": int(sum(1 for r in self.records if r["filter_exit"])),
                    "invested_share_mean": float(np.mean(invested)) if invested else 0.0, "days_invested_share": float(np.mean([v > 0 for v in invested])) if invested else 0.0,
                    "days_filtered_out_share": float(np.mean([bool(r["filtered"]) for r in self.records])) if self.records else 0.0})
        return out


Selector = Callable[[pd.Timestamp, pd.DataFrame], Dict[str, float]]


def run_weekly_basket(closes: pd.DataFrame, opens: pd.DataFrame, select: Selector, *, cfg: BasketConfig, start: pd.Timestamp, end: pd.Timestamp,
                      allowed: Optional[pd.Series] = None) -> BasketResult:
    """A daily-booked basket: decided at a day's close, filled at the NEXT day's first open.

    ``closes`` / ``opens``: one row per UTC day (the day's last close, the day's first open), the same columns. ``select(day, closes_up_to_day)``
    returns the target weights (before the volatility scale) at a rebalance decision; the scale is ``min(1, vol_target / realized vol)`` of the
    equal-weight basket of the selected markets over the trailing ``vol_lookback_days`` daily returns. ``allowed`` (bool by day): False at a
    day's close sends the basket to cash at the next open and keeps it there until a rebalance day on which it is True. Costs are charged on the
    traded notional at every fill; marks are at the day's close.
    """
    if list(closes.columns) != list(opens.columns):
        raise ValueError("closes and opens must have the same markets")
    days = closes.index[(closes.index >= start) & (closes.index <= end)]
    if len(days) == 0:
        raise ValueError("no days in the basket's span")
    markets = list(closes.columns)
    holdings = {m: 0.0 for m in markets}
    cash = float(cfg.init_cash)
    pending: Optional[Dict[str, float]] = None
    pending_kind = ""
    equity_vals: List[float] = []
    weight_rows: List[Dict[str, float]] = []
    records: List[Dict[str, Any]] = []
    rets = closes.pct_change()
    in_cash_until_rebalance = False
    for d in days:
        o = opens.loc[d]
        c = closes.loc[d]
        turnover = 0.0
        cost = 0.0
        rebalanced = False
        filter_exit = False
        if pending is not None:
            eq_open = cash + sum(holdings[m] * float(o[m]) for m in markets if holdings[m] > 0 and np.isfinite(o[m]))
            # The costs come out of the money invested, never out of a negative cash balance (spot, no leverage): the targets are set on the
            # equity net of the costs of reaching them (two passes; the second-order residual is clipped from the largest buy).
            tradable = [m for m in markets if np.isfinite(float(o[m]))]

            def deltas(equity_after_costs: float):
                out = {}
                for m in tradable:
                    out[m] = equity_after_costs * float(pending.get(m, 0.0)) - holdings[m] * float(o[m])
                return out

            d1 = deltas(eq_open)
            cost1 = sum(abs(v) * cfg.cost(m) for m, v in d1.items())
            d2 = deltas(eq_open - cost1)
            for m in tradable:
                price = float(o[m])
                delta = d2[m]
                if abs(delta) <= 1e-9 * max(1.0, eq_open):
                    continue
                c_side = cfg.cost(m)
                cash -= delta + abs(delta) * c_side
                holdings[m] = (holdings[m] * price + delta) / price
                turnover += abs(delta) / eq_open if eq_open > 0 else 0.0
                cost += abs(delta) * c_side
            if cash < 0.0:
                # The second-order residual of the two-pass cost estimate: sell that hair of the largest holding so the account never borrows.
                m_big = max(tradable, key=lambda m: holdings[m] * float(o[m]))
                holdings[m_big] = max(0.0, holdings[m_big] + cash / float(o[m_big]))
                cash = 0.0
            rebalanced = pending_kind == "rebalance"
            filter_exit = pending_kind == "filter"
            pending = None
            pending_kind = ""
        eq_close = cash + sum(holdings[m] * float(c[m]) for m in markets if holdings[m] > 0 and np.isfinite(c[m]))
        equity_vals.append(eq_close)
        invested = sum(holdings[m] * float(c[m]) for m in markets if holdings[m] > 0 and np.isfinite(c[m])) / eq_close if eq_close > 0 else 0.0
        ok = True if allowed is None else bool(allowed.get(d, False))
        weights_now = {m: (holdings[m] * float(c[m]) / eq_close if (eq_close > 0 and np.isfinite(c[m])) else 0.0) for m in markets}
        weight_rows.append(weights_now)
        next_is_rebalance = (d + pd.Timedelta(days=1)).weekday() == int(cfg.rebalance_weekday) or len(records) == 0
        scale = None
        selected: Dict[str, float] = {}
        if not ok and any(holdings[m] > 0 for m in markets):
            pending, pending_kind = {m: 0.0 for m in markets}, "filter"
            in_cash_until_rebalance = True
        elif next_is_rebalance and ok:
            hist = closes.loc[:d]
            selected = {m: float(w) for m, w in select(d, hist).items() if w > 0}
            scale = 1.0
            if selected and cfg.vol_target is not None:
                basket = rets.loc[:d, list(selected)].tail(int(cfg.vol_lookback_days))
                basket = basket.dropna(how="any")
                if len(basket) < int(cfg.vol_lookback_days):
                    scale = 0.0
                else:
                    w = np.array([selected[m] for m in basket.columns])
                    w = w / w.sum()
                    sigma = float((basket.to_numpy() @ w).std(ddof=1) * math.sqrt(DAYS_PER_YEAR))
                    scale = min(1.0, float(cfg.vol_target) / sigma) if sigma > 0 else 1.0
            total = sum(selected.values())
            pending = {m: (selected.get(m, 0.0) / total * scale if total > 0 else 0.0) for m in markets}
            pending_kind = "rebalance"
            in_cash_until_rebalance = False
        records.append({"day": d.strftime("%Y-%m-%d"), "equity": eq_close, "turnover": turnover, "cost": cost, "rebalanced": rebalanced,
                        "filter_exit": filter_exit, "filtered": (not ok) or in_cash_until_rebalance, "invested_share": float(invested),
                        "selected": selected, "scale": scale, "weights_close": {m: w for m, w in weights_now.items() if w > 0}})
    equity = pd.Series(equity_vals, index=days, dtype=float)
    weights = pd.DataFrame(weight_rows, index=days)
    return BasketResult(equity=equity, weights=weights, records=records, config=cfg.to_dict(), init_cash=float(cfg.init_cash))


def top_n_selector(lookback_days: int, n: int, order: Sequence[str]) -> Selector:
    """The rotation's selection: the ``n`` markets with the highest trailing ``lookback_days`` return, equal weight (ties by ``order``)."""
    rank = {m: k for k, m in enumerate(order)}

    def select(day: pd.Timestamp, hist: pd.DataFrame) -> Dict[str, float]:
        if len(hist) <= lookback_days:
            return {}
        last = hist.iloc[-1]
        past = hist.iloc[-1 - lookback_days]
        ret = (last / past - 1.0)
        eligible = [m for m in hist.columns if np.isfinite(ret[m]) and hist[m].tail(lookback_days + 1).notna().all()]
        if not eligible:
            return {}
        chosen = sorted(eligible, key=lambda m: (-float(ret[m]), rank.get(m, len(rank))))[:n]
        return {m: 1.0 / len(chosen) for m in chosen}

    return select


def fixed_selector(weights: Mapping[str, float]) -> Selector:
    """A fixed basket (the benchmarks): the given weights among the markets that have a close that day."""

    def select(day: pd.Timestamp, hist: pd.DataFrame) -> Dict[str, float]:
        last = hist.iloc[-1]
        out = {m: float(w) for m, w in weights.items() if m in hist.columns and np.isfinite(last[m])}
        total = sum(out.values())
        return {m: w / total for m, w in out.items()} if total > 0 else {}

    return select


def sma_filter(closes: pd.Series, window: int) -> pd.Series:
    """True on the days the close is above its simple moving average (False while the average is warming up)."""
    sma = closes.rolling(int(window), min_periods=int(window)).mean()
    return (closes > sma).fillna(False).astype(bool)


def basket_metrics(result: BasketResult) -> Dict[str, Any]:
    """Metrics, the yearly gate (calendar years and rolling 12-month windows) of a daily basket."""
    from research.report_v1c import yearly_gate_v2

    out = result.metrics()
    out["yearly_gate"] = yearly_gate_v2(result.equity / result.init_cash)
    out["yearly"] = {int(k): float(v) for k, v in yearly_returns(result.equity).items()}
    out["max_drawdown_check"] = max_drawdown(np.concatenate([[result.init_cash], result.equity.to_numpy(dtype=float)]))
    return out
