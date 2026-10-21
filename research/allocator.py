"""Portfolio allocator v2 (Sprint 5b, plan row R5b): the jointly sized portfolio plus brakes (SIMULATION ONLY).

Allocator v1 is the Sprint 2c construction (:func:`research.portfolio.combine_sized`):
full-size sleeves, trailing inverse-vol weights, one portfolio vol target and
one portfolio drawdown ladder. Allocator v2 keeps all of it and multiplies its
own sizing by brakes between 0 and 1:

- **Correlation cap.** Sleeves on the same coin always count as one bet; the
  coins count as one bet while their daily returns over the trailing
  ``corr_lookback_days`` had a correlation of ``corr_threshold`` or more
  (unknown = correlated). The share of equity invested in one bet — the
  sleeves of the group that were long at the previous day's close — may not
  exceed ``group_cap``; above it the whole group is scaled down to the cap.
  The cap is checked once a day: sleeves that enter during the day count from
  the next day, so after several entries a bet can stand above the cap until
  the next close (measured by :func:`brake_stats`).
- **Weekly loss limit.** When the book lost ``loss_limit`` or more over the last
  ``loss_window_days`` days, it goes to cash.
- **Cooldowns.** After that trip the book stays in cash for ``cooldown_days``
  days, then re-arms with a fresh loss window. The drawdown ladder keeps its own
  cooling-off (flat for ``recovery_bars`` days, then the peak is reset).

Every brake reads only days before the day it sizes, exactly like the v1
weights and vol scale; the vol target is measured on the base (v1) weighted
return, so a brake never feeds back into a larger scale. "Only lowers" is
relative to v2's own sizing: the drawdown ladder follows v2's own equity, so
v2 can stay at full size on a day v1's ladder has halved. One step function,
:func:`step_day`, is shared by the research driver (:func:`allocate_v2`) and the
paper fleet's daily booking (``research.paper_fleet.portfolio``), and it also
carries the v1 rules on the same sleeves as a paired reference. With every
brake switched off (``group_cap=None, loss_limit=None``) v2 is v1 up to
floating-point rounding (tested against ``combine_sized`` to 1e-15).

As in the research, moving money between sleeves at the day boundary is
assumed to cost nothing; :func:`brake_stats` estimates that re-weighting cost
separately. Nothing here can reach an order: it is arithmetic on returns.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.metrics import equity_metrics, yearly_returns
from research.portfolio import DAYS_PER_YEAR, rolling_inverse_vol_weights, vol_target_scale
from research.sizing import LADDER_MULTIPLIERS, LadderConfig, ladder_step

Pair = Tuple[str, str]


@dataclass(frozen=True)
class AllocatorV2Config:
    """The brakes of allocator v2. The defaults were fixed before the first run (plan row R5b) and are not tuned.

    - correlation: the 60-day window of the v1 weights; 0.70 is the conventional "highly
      correlated" line; one bet may hold at most half of the equity.
    - loss limit: 5 % in 7 days is a third of the 15 % annual volatility target, about 2.5 to
      3 weekly standard deviations at that target: a circuit breaker for bad weeks, not a
      routine brake; 7 days in cash after a trip.
    ``group_cap=None`` / ``loss_limit=None`` switch a brake off (for the ablations and the v1 parity test).
    """

    corr_lookback_days: int = 60
    corr_min_days: int = 20
    corr_threshold: float = 0.70
    group_cap: Optional[float] = 0.50
    loss_window_days: int = 7
    loss_limit: Optional[float] = 0.05
    cooldown_days: int = 7

    def __post_init__(self) -> None:
        if int(self.corr_lookback_days) < 2:
            raise ValueError("corr_lookback_days must be at least 2")
        if not (2 <= int(self.corr_min_days) <= int(self.corr_lookback_days)):
            raise ValueError("corr_min_days must be in [2, corr_lookback_days]")
        if not (0.0 < float(self.corr_threshold) <= 1.0):
            raise ValueError("corr_threshold must be in (0, 1]")
        if self.group_cap is not None and not (0.0 < float(self.group_cap) <= 1.0):
            raise ValueError("group_cap must be in (0, 1] (or None: no correlation cap)")
        if int(self.loss_window_days) < 1:
            raise ValueError("loss_window_days must be positive")
        if self.loss_limit is not None and not (0.0 < float(self.loss_limit) < 1.0):
            raise ValueError("loss_limit must be in (0, 1) (or None: no weekly loss limit)")
        if int(self.cooldown_days) < 1:
            raise ValueError("cooldown_days must be positive")

    @property
    def label(self) -> str:
        parts = []
        if self.group_cap is not None:
            parts.append(f"correlation cap {self.group_cap * 100:.0f}% per bet (corr >= {self.corr_threshold:.2f} over {int(self.corr_lookback_days)}d)")
        if self.loss_limit is not None:
            parts.append(f"weekly loss limit {self.loss_limit * 100:.0f}% in {int(self.loss_window_days)}d, {int(self.cooldown_days)}d cooldown")
        return ", ".join(parts) or "no brakes (allocator v1)"

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["label"] = self.label
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AllocatorV2Config":
        keys = ("corr_lookback_days", "corr_min_days", "corr_threshold", "group_cap", "loss_window_days", "loss_limit", "cooldown_days")
        return cls(**{k: data[k] for k in keys if k in data})


DEFAULT_ALLOCATOR_V2 = AllocatorV2Config()  # the pre-registered configuration the paper fleet runs


# -- grouping ----------------------------------------------------------------------


def asset_groups(assets: Sequence[str], correlations: Mapping[Pair, Optional[float]], threshold: float) -> List[List[str]]:
    """Assets linked by a correlation >= ``threshold`` (an unknown correlation links: assume they move together)."""
    parent = {a: a for a in assets}

    def root(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in itertools.combinations(sorted(assets), 2):
        rho = correlations.get((a, b), correlations.get((b, a)))
        if rho is None or not math.isfinite(float(rho)) or float(rho) >= threshold:
            parent[root(a)] = root(b)
    groups: Dict[str, List[str]] = {}
    for a in sorted(assets):
        groups.setdefault(root(a), []).append(a)
    return sorted(groups.values())


def sleeve_groups(sleeve_assets: Mapping[str, str], correlations: Mapping[Pair, Optional[float]], threshold: float) -> List[List[str]]:
    """Sleeves grouped by the bet they hold: the same coin always, correlated coins together."""
    out = []
    for coins in asset_groups(sorted(set(sleeve_assets.values())), correlations, threshold):
        out.append(sorted(n for n, a in sleeve_assets.items() if a in coins))
    return out


# -- state and one day ---------------------------------------------------------------


@dataclass
class AllocatorState:
    """Everything allocator v2 carries from one day to the next (JSON round-trips), with the v1 reference."""

    equity: float = 1.0
    peak: float = 1.0
    lad_level: int = 0
    lad_flat: int = 0
    lad_mult: float = 1.0
    loss_window: List[float] = field(default_factory=lambda: [1.0])  # end-of-day equity since the (re-)arm, newest last
    cooldown_left: int = 0
    trips: int = 0
    days: int = 0
    ref_equity: float = 1.0  # the v1 rules (no brakes) on the same sleeves
    ref_peak: float = 1.0
    ref_level: int = 0
    ref_flat: int = 0
    ref_mult: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AllocatorState":
        out = cls()
        for key, default in asdict(out).items():
            if key not in data:
                continue
            value = data[key]
            if key == "loss_window":
                setattr(out, key, [float(v) for v in value])
            elif isinstance(default, int):
                setattr(out, key, int(value))
            else:
                setattr(out, key, float(value))
        return out


@dataclass(frozen=True)
class DayInputs:
    """What the allocator knows when it sizes one day: the base (v1) sizing and the previous close, never the day itself."""

    returns: Mapping[str, float]  # full-size sleeve returns OF the day (applied, never used for sizing)
    weights: Mapping[str, float]  # trailing inverse-vol weights from earlier days (sum to 1)
    vol_scale: float  # portfolio vol-target scale from earlier days, in [0, 1]
    positions: Mapping[str, bool]  # which sleeves were long at the previous day's close
    correlations: Mapping[Pair, Optional[float]]  # trailing coin correlations from earlier days


def _ladder(level: int, flat: int, peak: float, equity: float, cfg: LadderConfig) -> Tuple[int, int, float, float]:
    lvl, flt, pk = ladder_step(np.array([level]), np.array([flat]), np.array([peak]), np.array([equity]), cfg)
    lvl_i = int(lvl[0])
    return lvl_i, int(flt[0]), float(pk[0]), float(LADDER_MULTIPLIERS[lvl_i])


def step_day(state: AllocatorState, inputs: DayInputs, sleeve_assets: Mapping[str, str], cfg: AllocatorV2Config,
             ladder: LadderConfig) -> Dict[str, Any]:
    """Size one day from ``state`` (the previous close), apply its returns, advance ``state`` in place; returns the day's record."""
    names = list(inputs.weights)
    if set(names) != set(sleeve_assets):
        raise ValueError("weights and sleeve assets name different sleeves")
    w = {n: float(inputs.weights[n]) for n in names}
    r = {n: float(inputs.returns.get(n, 0.0)) for n in names}
    held = {n: bool(inputs.positions.get(n, False)) for n in names}
    scale = min(max(float(inputs.vol_scale), 0.0), 1.0)
    lad = float(state.lad_mult)
    cool = 0.0 if state.cooldown_left > 0 else 1.0
    book = scale * lad * cool
    groups = sleeve_groups(sleeve_assets, inputs.correlations, cfg.corr_threshold)
    invested_before: Dict[str, float] = {}
    group_mult: Dict[str, float] = {}
    final: Dict[str, float] = {}
    for g in groups:
        key = "+".join(g)
        x = book * sum(w[n] for n in g if held[n])
        invested_before[key] = x
        m = 1.0
        if cfg.group_cap is not None and x > float(cfg.group_cap) + 1e-12:
            m = float(cfg.group_cap) / x
        group_mult[key] = m
        for n in g:
            final[n] = w[n] * book * m
    port_r = sum(final[n] * r[n] for n in names)
    raw = sum(w[n] * r[n] for n in names)
    ref_mult = float(state.ref_mult)
    ref_r = ref_mult * raw * scale

    # Close of the day: equity, the drawdown ladder, the loss window and the cooldown.
    state.equity *= 1.0 + port_r
    level_before = state.lad_level
    state.lad_level, state.lad_flat, state.peak, state.lad_mult = _ladder(state.lad_level, state.lad_flat, state.peak, state.equity, ladder)
    tripped = False
    loss = None
    if cfg.loss_limit is not None:
        if state.cooldown_left > 0:
            state.cooldown_left -= 1
            if state.cooldown_left == 0:
                state.loss_window = [state.equity]  # re-armed: a fresh window from this close
        else:
            state.loss_window = (list(state.loss_window) + [state.equity])[-(int(cfg.loss_window_days) + 1):]
            loss = state.equity / state.loss_window[0] - 1.0
            if loss <= -float(cfg.loss_limit) + 1e-12:
                tripped = True
                state.cooldown_left = int(cfg.cooldown_days)
                state.trips += 1
    state.ref_equity *= 1.0 + ref_r
    state.ref_level, state.ref_flat, state.ref_peak, state.ref_mult = _ladder(state.ref_level, state.ref_flat, state.ref_peak, state.ref_equity, ladder)
    state.days += 1

    brakes = []
    if any(m < 1.0 for m in group_mult.values()):
        brakes.append("correlation cap")
    if lad < 1.0:
        brakes.append("ladder flat" if lad == 0.0 else "ladder half")
    if cool == 0.0:
        brakes.append("cooldown")
    return {
        "weights": w, "vol_scale": scale, "ladder_multiplier": lad, "loss_multiplier": cool, "book_multiplier": book,
        "correlations": {f"{a}/{b}": (None if v is None or not math.isfinite(float(v)) else float(v)) for (a, b), v in sorted(inputs.correlations.items())},
        "groups": groups, "positions_previous_close": held, "invested_before_cap": invested_before, "group_multipliers": group_mult,
        "final_weights": final, "invested_share": sum(final[n] for n in names if held[n]),
        "invested_share_reference": ref_mult * scale * sum(w[n] for n in names if held[n]),
        "raw_return": raw, "portfolio_return": port_r, "equity_index": state.equity,
        "ladder_level_after": state.lad_level, "ladder_changed": state.lad_level != level_before,
        "loss_window_return": loss, "loss_limit_tripped": tripped, "cooldown_days_left": state.cooldown_left, "trips": state.trips,
        "brakes": brakes,
        "reference_v1": {"return": ref_r, "equity_index": state.ref_equity, "ladder_multiplier": ref_mult},
    }


# -- inputs from a daily history ----------------------------------------------------------


def base_sizing(daily: pd.DataFrame, *, target_vol: float, vol_lookback_days: int, weight_lookback_days: int,
                cap: float = 1.0) -> Tuple[pd.DataFrame, pd.Series]:
    """The v1 weights and vol scale for every day (each from earlier days only), as ``combine_sized`` computes them."""
    weights = rolling_inverse_vol_weights(daily, weight_lookback_days)
    raw = (daily * weights).sum(axis=1)
    scale = vol_target_scale(raw, target_vol, vol_lookback_days, cap=cap)
    return weights, scale


def daily_closes_to_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Coin returns from one close per UTC day; a missing close leaves NaN around it (no fill across a gap)."""
    c = closes.astype(float).sort_index()
    return c / c.shift(1) - 1.0


def trailing_correlations(asset_returns: pd.DataFrame, lookback_days: int, min_days: int) -> Dict[Pair, pd.Series]:
    """Per coin pair, the correlation of the daily returns over the trailing window, usable on the NEXT day (shifted)."""
    out: Dict[Pair, pd.Series] = {}
    cols = sorted(asset_returns.columns)
    for a, b in itertools.combinations(cols, 2):
        rho = asset_returns[a].rolling(int(lookback_days), min_periods=int(min_days)).corr(asset_returns[b])
        out[(a, b)] = rho.shift(1)
    return out


def previous_close_positions(positions: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """For each day of ``index``: was the sleeve long at the latest earlier close (last known value carried forward)?"""
    pos = positions.astype(float)
    full = pos.reindex(pos.index.union(index)).ffill().shift(1)
    return full.reindex(index).fillna(0.0) > 0.5


# -- research driver ---------------------------------------------------------------------


@dataclass
class AllocatorRun:
    name: str
    returns: pd.Series
    equity: pd.Series
    reference_returns: pd.Series
    reference_equity: pd.Series
    records: List[Dict[str, Any]]
    days: pd.DatetimeIndex
    metrics: Dict[str, float]
    reference_metrics: Dict[str, float]
    yearly: pd.Series
    config: Dict[str, Any]

    def diagnostics(self) -> pd.DataFrame:
        rows = [{"vol_scale": r["vol_scale"], "ladder_multiplier": r["ladder_multiplier"], "loss_multiplier": r["loss_multiplier"],
                 "cap_bound": "correlation cap" in r["brakes"], "invested_share": r["invested_share"],
                 "invested_share_reference": r["invested_share_reference"], "n_groups": len(r["groups"]),
                 "tripped": r["loss_limit_tripped"]} for r in self.records]
        return pd.DataFrame(rows, index=self.days)


def allocate_v2(
    daily: pd.DataFrame,
    positions: pd.DataFrame,
    asset_returns: pd.DataFrame,
    sleeve_assets: Mapping[str, str],
    *,
    cfg: AllocatorV2Config = DEFAULT_ALLOCATOR_V2,
    target_vol: float = 0.15,
    vol_lookback_days: int = 30,
    weight_lookback_days: int = 60,
    ladder: LadderConfig = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30),
    cap: float = 1.0,
    start: Optional[pd.Timestamp] = None,
    name: str = "allocator v2",
) -> AllocatorRun:
    """Allocator v2 over a daily sleeve history (FULL-size returns, days x sleeves).

    ``positions`` holds each sleeve's long/flat state at every day's close,
    ``asset_returns`` the coins' daily returns, from as early as they are known
    (``sleeve_assets`` maps a sleeve to its coin). Days before ``start`` only seed the trailing estimates; the
    equity, the ladder and the loss window start at ``start`` (default: the
    first day), as the paper fleet's book starts after its warm-up.
    """
    if daily.empty or len(daily.columns) == 0:
        raise ValueError("no sleeves to allocate")
    weights, scale = base_sizing(daily, target_vol=target_vol, vol_lookback_days=vol_lookback_days,
                                 weight_lookback_days=weight_lookback_days, cap=cap)
    # Coin correlations from all the coin history given (one row per calendar day), so the first sleeve days already know them.
    first = min(asset_returns.index.min(), daily.index.min()) if len(asset_returns) else daily.index.min()
    calendar = pd.date_range(first, daily.index.max(), freq="D", name="day")
    corr = {p: c.reindex(daily.index) for p, c in
            trailing_correlations(asset_returns.reindex(calendar), cfg.corr_lookback_days, cfg.corr_min_days).items()}
    held = previous_close_positions(positions.reindex(columns=daily.columns), daily.index)
    days = daily.index if start is None else daily.index[daily.index >= pd.Timestamp(start)]
    state = AllocatorState()
    records: List[Dict[str, Any]] = []
    for d in days:
        inputs = DayInputs(returns=daily.loc[d].to_dict(), weights=weights.loc[d].to_dict(), vol_scale=float(scale.loc[d]),
                           positions=held.loc[d].to_dict(), correlations={p: _finite(s.loc[d]) for p, s in corr.items()})
        records.append(step_day(state, inputs, sleeve_assets, cfg, ladder))
    port = pd.Series([r["portfolio_return"] for r in records], index=days, dtype=float)
    ref = pd.Series([r["reference_v1"]["return"] for r in records], index=days, dtype=float)
    equity = (1.0 + port).cumprod()
    ref_equity = (1.0 + ref).cumprod()
    return AllocatorRun(
        name=name, returns=port, equity=equity, reference_returns=ref, reference_equity=ref_equity, records=records, days=days,
        metrics=curve_metrics(equity), reference_metrics=curve_metrics(ref_equity), yearly=yearly_returns(equity),
        config={"allocator": cfg.to_dict(), "target_vol": float(target_vol), "vol_lookback_days": int(vol_lookback_days),
                "weight_lookback_days": int(weight_lookback_days), "cap": float(cap), "ladder": ladder.to_dict()},
    )


def _finite(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def curve_metrics(equity: pd.Series) -> Dict[str, float]:
    """``combine_sized``'s metrics of a daily equity curve (with a leading 1.0)."""
    out = equity_metrics(np.concatenate([[1.0], equity.to_numpy(dtype=float)]), DAYS_PER_YEAR)
    r = equity / equity.shift(1).fillna(1.0) - 1.0
    out["positive_days_share"] = float((r > 0).mean()) if len(r) else 0.0
    return out


def reference_stats(stats: Mapping[str, Any]) -> Dict[str, Any]:
    """The paired v1 reference's side of :func:`brake_stats` under the same keys (only its ladder acts)."""
    keys = ("invested_share_mean", "invested_share_max", "ladder_half_days_share", "ladder_flat_days_share", "reweighting_turnover_per_year",
            "reweighting_cost_per_year")
    out: Dict[str, Any] = {"days": stats.get("days"), "years": stats.get("years")}
    out.update({k: stats.get(f"{k}_reference") for k in keys})
    out.update({"correlation_cap_days_share": 0.0, "cooldown_days_share": 0.0, "loss_limit_trips": 0, "loss_limit_trips_per_year": 0.0})
    return out


def brake_stats(run: AllocatorRun, *, cost_per_side: float = 0.0015) -> Dict[str, Any]:
    """How often each brake acted, how invested the book was, and an estimate of the re-weighting cost both allocators ignore.

    Re-weighting turnover of a day = the change of the capital assigned to the sleeves that
    were held over the day boundary (sum of |weight today - weight yesterday|); its cost is
    that turnover times ``cost_per_side`` (fee + slippage). It is NOT deducted from the
    returns (the research convention); it is reported so the frictionless assumption is visible.
    """
    recs = run.records
    n = len(recs)
    years = n / DAYS_PER_YEAR if n else 0.0
    if not n:
        return {"days": 0}
    cap_days = [r for r in recs if "correlation cap" in r["brakes"]]
    cut = [1.0 - r["invested_share"] / sum(r["invested_before_cap"].values()) for r in cap_days if sum(r["invested_before_cap"].values()) > 0]
    single = sum(1 for r in recs if len(r["groups"]) == 1)
    group_cap = (run.config.get("allocator") or {}).get("group_cap")
    turn = turn_ref = 0.0
    prev = prev_ref = None
    for r in recs:
        held = r["positions_previous_close"]
        cur = r["final_weights"]
        cur_ref = {k: r["weights"][k] * r["vol_scale"] * r["reference_v1"]["ladder_multiplier"] for k in r["weights"]}
        if prev is not None:
            turn += sum(abs(cur[k] - prev[k]) for k in cur if held[k])
            turn_ref += sum(abs(cur_ref[k] - prev_ref[k]) for k in cur_ref if held[k])
        prev, prev_ref = cur, cur_ref
    inv = np.array([r["invested_share"] for r in recs])
    inv_ref = np.array([r["invested_share_reference"] for r in recs])
    long_now = np.array([sum(bool(v) for v in r["positions_previous_close"].values()) for r in recs], dtype=float)
    scale = np.array([r["vol_scale"] for r in recs])
    on = np.array(["correlation cap" in r["brakes"] for r in recs])
    long_before = np.array([long_now[i - 10] for i in np.where(on)[0] if i >= 10])
    # v1's largest bet at the previous close (its weights x scale x its own ladder, per group of the day).
    ref_bet = np.array([max((r["reference_v1"]["ladder_multiplier"] * r["vol_scale"] * sum(r["weights"][n] for n in g if r["positions_previous_close"][n])
                             for g in r["groups"]), default=0.0) for r in recs])
    # The largest bet at the day's CLOSE, after the day's own entries and exits (the next day's previous-close positions).
    close_bet = np.array([max((sum(r["final_weights"][n] for n in g if nxt["positions_previous_close"][n]) for g in r["groups"]), default=0.0)
                          for r, nxt in zip(recs[:-1], recs[1:])])
    above_close = close_bet > float(group_cap) + 1e-12 if group_cap is not None else np.zeros(len(close_bet), dtype=bool)
    v2_ladder_above = sum(1 for r in recs if r["ladder_multiplier"] > r["reference_v1"]["ladder_multiplier"])
    v1_ladder_above = sum(1 for r in recs if r["ladder_multiplier"] < r["reference_v1"]["ladder_multiplier"])
    return {
        "days": n, "years": years,
        "correlation_cap_days_share": len(cap_days) / n,
        "correlation_cap_days_by_year": {str(y): int(sum(1 for d, r in zip(run.days, recs) if d.year == y and "correlation cap" in r["brakes"]))
                                         for y in sorted({d.year for d in run.days})},
        "correlation_cap_average_cut": float(np.mean(cut)) if cut else None,
        "coins_one_bet_days_share": single / n,
        # When the cap acts: how many sleeves were long, how many were long ten days earlier, and the vol scale, on its days vs the others.
        "cap_days_sleeves_long_mean": float(long_now[on].mean()) if on.any() else None,
        "cap_days_sleeves_long_10d_before_mean": float(long_before.mean()) if long_before.size else None,
        "other_days_sleeves_long_mean": float(long_now[~on].mean()) if (~on).any() else None,
        "cap_days_vol_scale_mean": float(scale[on].mean()) if on.any() else None,
        "other_days_vol_scale_mean": float(scale[~on].mean()) if (~on).any() else None,
        "ladder_half_days_share": sum(1 for r in recs if r["ladder_multiplier"] == 0.5) / n,
        "ladder_flat_days_share": sum(1 for r in recs if r["ladder_multiplier"] == 0.0) / n,
        "ladder_half_days_share_reference": sum(1 for r in recs if r["reference_v1"]["ladder_multiplier"] == 0.5) / n,
        "ladder_flat_days_share_reference": sum(1 for r in recs if r["reference_v1"]["ladder_multiplier"] == 0.0) / n,
        "cooldown_days_share": sum(1 for r in recs if r["loss_multiplier"] == 0.0) / n,
        "loss_limit_trips": int(recs[-1]["trips"]),
        "loss_limit_trips_per_year": (recs[-1]["trips"] / years) if years else None,
        "trip_days": [str(d.date()) for d, r in zip(run.days, recs) if r["loss_limit_tripped"]],
        "invested_share_mean": float(inv.mean()), "invested_share_max": float(inv.max()),
        "invested_share_mean_reference": float(inv_ref.mean()), "invested_share_max_reference": float(inv_ref.max()),
        "reference_above_cap_days_share": None if group_cap is None else float((ref_bet > float(group_cap) + 1e-12).mean()),
        "reference_bet_max": float(ref_bet.max()),
        # The cap is checked on the previous close: entries during a day count from the next day.
        "bet_above_cap_at_close_days": int(above_close.sum()),
        "bet_at_close_max": float(close_bet.max()) if close_bet.size else None,
        "bet_above_cap_at_close_dates": [str(d.date()) for d, a in zip(run.days[:-1], above_close) if a][:50],
        # v2 is not always smaller than v1: its ladder follows its own equity.
        "ladder_v2_above_v1_days": v2_ladder_above,
        "ladder_v1_above_v2_days": v1_ladder_above,
        "invested_above_reference_days": int((inv > inv_ref + 1e-12).sum()),
        "reweighting_turnover_per_year": turn / years if years else None,
        "reweighting_turnover_per_year_reference": turn_ref / years if years else None,
        "reweighting_cost_per_year": turn * cost_per_side / years if years else None,
        "reweighting_cost_per_year_reference": turn_ref * cost_per_side / years if years else None,
    }
