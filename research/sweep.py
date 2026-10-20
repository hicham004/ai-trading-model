"""Parameter sweeps over a candidate: cartesian grids, per-combo metrics, heatmaps, robustness."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.engine import Costs, SweepResult, run_vectorized
from research.metrics import summarize_combo
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
    n = len(df)
    C = len(combos)
    desired = np.zeros((n, C), dtype=bool)
    stop = np.full((n, C), np.nan)
    strength = np.full((n, C), np.nan)
    time_stops: List[Optional[int]] = []
    ok = tradeable_mask(df, context.timeframe, context.periods_per_year, no_trade) if no_trade is not None else None
    for j, params in enumerate(combos):
        frame = strategy.build(df, params, context)
        d = apply_no_trade(frame, ok) if ok is not None else frame.desired
        desired[:, j] = d.to_numpy(dtype=bool)
        stop[:, j] = frame.stop_distance.to_numpy(dtype=float)
        strength[:, j] = frame.strength.to_numpy(dtype=float)
        time_stops.append(frame.time_stop_bars)
    return Frames(desired=desired, stop=stop, strength=strength, time_stops=time_stops)


def simulate_slice(
    df: pd.DataFrame,
    frames: Frames,
    sl: slice,
    *,
    costs: Costs,
    size_fraction: float = 1.0,
    init_cash: float = 10_000.0,
    columns: Optional[Sequence[int]] = None,
) -> SweepResult:
    """Simulate (a subset of) combos on ``df[sl]`` starting flat."""
    cols = np.arange(frames.desired.shape[1]) if columns is None else np.asarray(list(columns), dtype=int)
    desired = frames.desired[sl][:, cols]
    stop = frames.stop[sl][:, cols]
    time_stops = {frames.time_stops[c] for c in cols}
    time_stop = time_stops.pop() if len(time_stops) == 1 else None
    sub = df.iloc[sl]
    return run_vectorized(
        sub["open"].to_numpy(), sub["high"].to_numpy(), sub["low"].to_numpy(), sub["close"].to_numpy(),
        desired, stop, costs=costs, time_stop_bars=time_stop, size_fraction=size_fraction, init_cash=init_cash,
    )


def metrics_table(result: SweepResult, combos: Sequence[Mapping[str, Any]], *, periods_per_year: float, columns: Optional[Sequence[int]] = None) -> pd.DataFrame:
    """One row per simulated combo: parameters + metrics."""
    cols = list(range(len(combos))) if columns is None else list(columns)
    rows = []
    for k, c in enumerate(cols):
        m = summarize_combo(result.equity[:, k], result.trades_for(k), float(result.exposure[k]),
                            init_cash=result.init_cash, periods_per_year=periods_per_year)
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
