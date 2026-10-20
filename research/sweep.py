"""Parameter sweeps over a candidate: cartesian grids, per-combo metrics, heatmaps, robustness."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from research.bracket import apply_bracket, get_bracket
from research.engine import Costs, SweepResult, run_vectorized
from research.metrics import summarize_combo
from research.sizing import LadderConfig
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, gate_entries
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask


def param_grid(grid: Mapping[str, Sequence[Any]], base: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Cartesian product of the grid merged over ``base`` defaults."""
    keys = list(grid)
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        params = dict(base or {})
        params.update(dict(zip(keys, values)))
        combos.append(params)
    return combos


@dataclass
class Frames:
    desired: np.ndarray  # (n, C)
    stop: np.ndarray  # (n, C)
    strength: np.ndarray  # (n, C)
    time_stops: List[Optional[int]]
    target: Optional[np.ndarray] = None  # (n, C) take-profit distances (NaN = none)
    trail_activate: Optional[np.ndarray] = None  # (C,) activation in R (NaN = no trailing stop)
    trail_dist: Optional[np.ndarray] = None  # (C,) trail distance in R

    @property
    def n_combos(self) -> int:
        return int(self.desired.shape[1])


def apply_no_trade(frame: SignalFrame, ok: pd.Series) -> pd.Series:
    """Entries only: a bar desired while untradeable stays flat; open positions are kept."""
    return gate_entries(frame.desired, ok)


def build_frames(
    strategy: ResearchStrategy,
    df: pd.DataFrame,
    combos: Sequence[Mapping[str, Any]],
    context: FeatureContext,
    *,
    no_trade: Optional[NoTradeConfig] = NoTradeConfig(),
) -> Frames:
    """Signal frames for every combo; a ``bracket`` key in the params layers an exit bracket on."""
    n = len(df)
    C = len(combos)
    desired = np.zeros((n, C), dtype=bool)
    stop = np.full((n, C), np.nan)
    strength = np.full((n, C), np.nan)
    target = np.full((n, C), np.nan)
    trail_act = np.full(C, np.nan)
    trail_dist = np.full(C, np.nan)
    has_target = False
    time_stops: List[Optional[int]] = []
    ok = tradeable_mask(df, context.timeframe, context.periods_per_year, no_trade) if no_trade is not None else None
    for j, params in enumerate(combos):
        frame = strategy.build(df, params, context)
        bracket_key = params.get("bracket")
        if bracket_key:
            frame = apply_bracket(frame, get_bracket(str(bracket_key)), context.timeframe)
        d = apply_no_trade(frame, ok) if ok is not None else frame.desired
        desired[:, j] = d.to_numpy(dtype=bool)
        stop[:, j] = frame.stop_distance.to_numpy(dtype=float)
        strength[:, j] = frame.strength.to_numpy(dtype=float)
        if frame.target_distance is not None:
            target[:, j] = frame.target_distance.to_numpy(dtype=float)
            has_target = True
        if frame.trail_r is not None:
            trail_act[j] = float(frame.trail_activate_r if frame.trail_activate_r is not None else 0.0)
            trail_dist[j] = float(frame.trail_r)
        time_stops.append(frame.time_stop_bars)
    return Frames(
        desired=desired, stop=stop, strength=strength, time_stops=time_stops,
        target=target if has_target else None,
        trail_activate=trail_act if np.isfinite(trail_dist).any() else None,
        trail_dist=trail_dist if np.isfinite(trail_dist).any() else None,
    )


def _slice_fraction(size_fraction: Union[float, np.ndarray], sl: slice, n_total: int, n_cols: int) -> Union[float, np.ndarray]:
    if np.isscalar(size_fraction):
        return size_fraction
    sf = np.asarray(size_fraction, dtype=float)
    if sf.ndim == 1:
        sf = sf[:, None]
    if sf.shape[0] != n_total:
        raise ValueError("size_fraction matrix must have one row per bar of the full frame")
    sf = sf[sl]
    if sf.shape[1] == 1 and n_cols > 1:
        sf = np.repeat(sf, n_cols, axis=1)
    elif sf.shape[1] != n_cols:
        raise ValueError(f"size_fraction matrix must have 1 or {n_cols} columns, got {sf.shape[1]}")
    return sf


def simulate_slice(
    df: pd.DataFrame,
    frames: Frames,
    sl: slice,
    *,
    costs: Costs,
    size_fraction: Union[float, np.ndarray] = 1.0,
    init_cash: float = 10_000.0,
    columns: Optional[Sequence[int]] = None,
    ladder: Optional[LadderConfig] = None,
    ladder_mask: Optional[np.ndarray] = None,
    rebalance_threshold: Optional[float] = None,
) -> SweepResult:
    """Simulate (a subset of) combos on ``df[sl]`` starting flat.

    ``size_fraction`` is a scalar or a full-length (n, 1 | k) matrix of entry
    fractions that is sliced like ``df``; ``ladder_mask`` refers to the selected
    columns (length k) when given.
    """
    cols = np.arange(frames.n_combos) if columns is None else np.asarray(list(columns), dtype=int)
    desired = frames.desired[sl][:, cols]
    stop = frames.stop[sl][:, cols]
    time_stops = [frames.time_stops[c] for c in cols]
    target = None if frames.target is None else frames.target[sl][:, cols]
    act = None if frames.trail_activate is None else frames.trail_activate[cols]
    dist = None if frames.trail_dist is None else frames.trail_dist[cols]
    sub = df.iloc[sl]
    return run_vectorized(
        sub["open"].to_numpy(), sub["high"].to_numpy(), sub["low"].to_numpy(), sub["close"].to_numpy(),
        desired, stop, costs=costs, time_stop_bars=time_stops, target_distance=target,
        size_fraction=_slice_fraction(size_fraction, sl, len(df), len(cols)), init_cash=init_cash,
        trail_activate_r=act, trail_r=dist, ladder=ladder, ladder_mask=ladder_mask,
        rebalance_threshold=rebalance_threshold,
    )


def simulate_sizing(
    df: pd.DataFrame,
    frames: Frames,
    column: int,
    sl: slice,
    fractions: np.ndarray,
    *,
    costs: Costs,
    ladder: Optional[LadderConfig] = None,
    ladder_mask: Optional[np.ndarray] = None,
    rebalance_threshold: Optional[float] = None,
    init_cash: float = 10_000.0,
) -> SweepResult:
    """One rule (``column``) under every sizing column of ``fractions`` (full-length (n, S))."""
    S = int(np.asarray(fractions).shape[1])
    desired = np.repeat(frames.desired[sl][:, [column]], S, axis=1)
    stop = np.repeat(frames.stop[sl][:, [column]], S, axis=1)
    target = None if frames.target is None else np.repeat(frames.target[sl][:, [column]], S, axis=1)
    act = None if frames.trail_activate is None else np.full(S, frames.trail_activate[column])
    dist = None if frames.trail_dist is None else np.full(S, frames.trail_dist[column])
    sub = df.iloc[sl]
    return run_vectorized(
        sub["open"].to_numpy(), sub["high"].to_numpy(), sub["low"].to_numpy(), sub["close"].to_numpy(),
        desired, stop, costs=costs, time_stop_bars=[frames.time_stops[column]] * S, target_distance=target,
        size_fraction=np.asarray(fractions, dtype=float)[sl], init_cash=init_cash,
        trail_activate_r=act, trail_r=dist, ladder=ladder, ladder_mask=ladder_mask,
        rebalance_threshold=rebalance_threshold,
    )


def metrics_table(result: SweepResult, combos: Sequence[Mapping[str, Any]], *, periods_per_year: float, columns: Optional[Sequence[int]] = None) -> pd.DataFrame:
    """One row per simulated combo: parameters + metrics."""
    cols = list(range(len(combos))) if columns is None else list(columns)
    rows = []
    alloc = result.avg_allocation
    for k, c in enumerate(cols):
        m = summarize_combo(result.equity[:, k], result.trades_for(k), float(result.exposure[k]),
                            init_cash=result.init_cash, periods_per_year=periods_per_year,
                            allocation=float(alloc[k]) if alloc.size else None)
        row = {"combo": int(c)}
        row.update({f"p_{key}": _param_value(v) for key, v in combos[c].items()})
        row.update(m)
        rows.append(row)
    return pd.DataFrame(rows)


def _param_value(v: Any) -> Any:
    return str(v) if isinstance(v, (tuple, list)) else v


def _scale(value: Any, factor: float) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        scaled = int(round(value * factor))
        if scaled == value:
            scaled = value + 1 if factor > 1 else max(1, value - 1)
        return scaled
    if isinstance(value, float):
        return value * factor
    if isinstance(value, (tuple, list)):
        return tuple(_scale(v, factor) for v in value)
    return value


def perturbed_params(params: Mapping[str, Any], keys: Sequence[str], tolerance: float = 0.30) -> List[Dict[str, Any]]:
    """±tolerance perturbations of the numeric/tuple parameters in ``keys``.

    One-at-a-time up and down for each key, plus all-up and all-down; duplicates
    and the original set are dropped. Integers move by at least one step.
    """
    numeric = [
        k for k in keys
        if k in params and isinstance(params[k], (int, float, tuple, list)) and not isinstance(params[k], bool)
    ]
    out: List[Dict[str, Any]] = []
    seen = {str(sorted(params.items()))}
    variants = []
    for k in numeric:
        for factor in (1 - tolerance, 1 + tolerance):
            variants.append({k: _scale(params[k], factor)})
    for factor in (1 - tolerance, 1 + tolerance):
        variants.append({k: _scale(params[k], factor) for k in numeric})
    for change in variants:
        candidate = dict(params)
        candidate.update(change)
        key = str(sorted(candidate.items()))
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def heatmap(table: pd.DataFrame, x_param: str, y_param: str, metric: str, agg: str = "median") -> pd.DataFrame:
    return table.pivot_table(index=f"p_{y_param}", columns=f"p_{x_param}", values=metric, aggfunc=agg)


def robustness(table: pd.DataFrame, best: Mapping[str, Any], metric: str, *, tolerance: float = 0.30, threshold: float = 0.0) -> Dict[str, Any]:
    """Metric distribution over grid points within ±tolerance of the best numeric params.

    Non-numeric parameters (tuples) must match exactly. Robust means most
    neighbours stay above ``threshold`` and the median is not far below the best.
    """
    mask = pd.Series(True, index=table.index)
    for key, value in best.items():
        col = f"p_{key}"
        if col not in table:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lo, hi = value * (1 - tolerance), value * (1 + tolerance)
            if value < 0:
                lo, hi = hi, lo
            mask &= table[col].astype(float).between(min(lo, hi), max(lo, hi))
        else:
            mask &= table[col].astype(str) == str(value)
    neighbours = table[mask]
    best_rows = neighbours
    for key, value in best.items():
        col = f"p_{key}"
        if col in table:
            best_rows = best_rows[best_rows[col].astype(str) == str(_param_value(value))]
    best_metric = float(best_rows[metric].iloc[0]) if len(best_rows) else float("nan")
    values = neighbours[metric].replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "n_neighbours": int(len(neighbours)),
        "best": best_metric,
        "median": float(values.median()) if len(values) else float("nan"),
        "min": float(values.min()) if len(values) else float("nan"),
        "share_above_threshold": float((values > threshold).mean()) if len(values) else float("nan"),
    }
