"""Walk-forward validation with a purge gap and an untouched holdout.

For each rolling window: sweep every parameter combo on the TRAIN slice, pick
the best by ``select_by`` among combos with at least ``min_trades`` trades,
skip ``purge_bars`` (so features/positions straddling the boundary cannot leak),
then run only the selected combo on the TEST slice. Test slices are stitched
into one out-of-sample equity curve. Nothing in a test slice ever influences
the selection that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.engine import Costs
from research.metrics import equity_metrics, return_moments, sharpe, trade_metrics, yearly_returns
from research.sweep import Frames, metrics_table, simulate_slice

WINDOW_INIT_CASH = 10_000.0  # every test window restarts from the same capital


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int
    test_bars: int
    purge_bars: int = 0
    min_trades: int = 20
    select_by: str = "sharpe"
    step_bars: Optional[int] = None
    min_test_fraction: float = 0.5

    def __post_init__(self) -> None:
        if self.train_bars <= 0 or self.test_bars <= 0 or self.purge_bars < 0:
            raise ValueError("train/test must be positive and purge non-negative")
        if self.step_bars is not None and self.step_bars <= 0:
            raise ValueError("step_bars must be positive")


@dataclass(frozen=True)
class Window:
    idx: int
    train: slice
    test: slice


def make_windows(n_bars: int, cfg: WalkForwardConfig) -> List[Window]:
    step = cfg.step_bars or cfg.test_bars
    windows: List[Window] = []
    start = 0
    idx = 0
    while True:
        train_end = start + cfg.train_bars
        test_start = train_end + cfg.purge_bars
        test_end = min(test_start + cfg.test_bars, n_bars)
        if test_start >= n_bars or (test_end - test_start) < cfg.min_test_fraction * cfg.test_bars:
            break
        windows.append(Window(idx, slice(start, train_end), slice(test_start, test_end)))
        idx += 1
        start += step
    return windows


@dataclass
class WindowResult:
    idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    selected_combo: Optional[int]
    selected_params: Dict[str, Any]
    train_metric: float
    n_qualified: int
    test_metrics: Dict[str, float]
    test_returns: pd.Series  # bar returns over the test slice (0 when no combo qualified)
    train_sharpes: List[float] = field(default_factory=list)  # per-period SR of every combo (for DSR)


@dataclass
class WalkForwardResult:
    windows: List[WindowResult]
    oos_equity: pd.Series  # stitched, starts at 1.0
    oos_trades: pd.DataFrame
    oos_metrics: Dict[str, float]
    yearly: pd.Series
    params_frequency: Dict[str, int]
    config: WalkForwardConfig

    @property
    def selected_most_often(self) -> Optional[Dict[str, Any]]:
        if not self.params_frequency:
            return None
        key = max(self.params_frequency, key=self.params_frequency.get)
        for w in self.windows:
            if w.selected_combo is not None and _params_key(w.selected_params) == key:
                return dict(w.selected_params)
        return None


def _params_key(params: Mapping[str, Any]) -> str:
    return " ".join(f"{k}={v}" for k, v in sorted(params.items()))


def _select(table: pd.DataFrame, cfg: WalkForwardConfig) -> Optional[pd.Series]:
    qualified = table[table["n_trades"] >= cfg.min_trades].replace([np.inf, -np.inf], np.nan)
    qualified = qualified.dropna(subset=[cfg.select_by])
    if qualified.empty:
        return None
    return qualified.sort_values([cfg.select_by, "n_trades"], ascending=[False, False]).iloc[0]


def replay_fixed_params(
    df: pd.DataFrame,
    frames: Frames,
    column: int,
    windows: Sequence[Window],
    *,
    costs: Costs,
    size_fraction: float = 1.0,
) -> Dict[str, float]:
    """Run ONE parameter set (``column`` of ``frames``) over every test window without re-selection."""
    growth = 1.0
    worst_dd = 0.0
    trades = 0
    for w in windows:
        res = simulate_slice(df, frames, w.test, costs=costs, size_fraction=size_fraction, columns=[column])
        eq = res.equity[:, 0]
        growth *= eq[-1] / res.init_cash
        peaks = np.maximum.accumulate(eq)
        worst_dd = max(worst_dd, float((1.0 - eq / peaks).max()))
        trades += int(len(res.trades))
    return {"total_return": growth - 1.0, "worst_window_drawdown": worst_dd, "n_trades": trades}


def run_walk_forward(
    df: pd.DataFrame,
    frames: Frames,
    combos: Sequence[Mapping[str, Any]],
    cfg: WalkForwardConfig,
    *,
    costs: Costs,
    periods_per_year: float,
    size_fraction: float = 1.0,
) -> WalkForwardResult:
    n = len(df)
    windows = make_windows(n, cfg)
    if not windows:
        raise ValueError(f"not enough bars ({n}) for train={cfg.train_bars} purge={cfg.purge_bars} test={cfg.test_bars}")
    results: List[WindowResult] = []
    oos_returns: List[pd.Series] = []
    oos_trades: List[pd.DataFrame] = []
    freq: Dict[str, int] = {}

    for w in windows:
        train_res = simulate_slice(df, frames, w.train, costs=costs, size_fraction=size_fraction)
        table = metrics_table(train_res, combos, periods_per_year=periods_per_year)
        # Per-period Sharpe of every combo on the train slice (deflated-Sharpe input).
        train_sharpes = [sharpe(np.diff(train_res.equity[:, k]) / train_res.equity[:-1, k], 1.0) for k in range(train_res.n_combos)]
        best = _select(table, cfg)
        test_index = df.index[w.test]
        if best is None:
            test_returns = pd.Series(0.0, index=test_index)
            results.append(WindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                        None, {}, float("nan"), 0, {}, test_returns, train_sharpes))
            oos_returns.append(test_returns)
            continue
        combo = int(best["combo"])
        params = dict(combos[combo])
        freq[_params_key(params)] = freq.get(_params_key(params), 0) + 1
        test_res = simulate_slice(df, frames, w.test, costs=costs, size_fraction=size_fraction, columns=[combo])
        eq = test_res.equity[:, 0]
        test_returns = pd.Series(np.concatenate([[eq[0] / test_res.init_cash - 1.0], eq[1:] / eq[:-1] - 1.0]), index=test_index)
        tm = equity_metrics(eq, periods_per_year)
        tm.update(trade_metrics(test_res.trades, init_cash=test_res.init_cash, n_bars=len(eq), periods_per_year=periods_per_year))
        tm["exposure"] = float(test_res.exposure[0])
        trades = test_res.trades.copy()
        trades["window"] = w.idx
        trades["entry_time"] = test_index[trades["entry_i"].to_numpy(dtype=int)] if len(trades) else pd.Series(dtype="datetime64[ns, UTC]")
        oos_trades.append(trades)
        results.append(WindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                    combo, params, float(best[cfg.select_by]), int((table["n_trades"] >= cfg.min_trades).sum()),
                                    tm, test_returns, train_sharpes))
        oos_returns.append(test_returns)

    stitched = pd.concat(oos_returns).sort_index()
    oos_equity = (1.0 + stitched).cumprod()
    oos_trades_df = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    oos_metrics = equity_metrics(np.concatenate([[1.0], oos_equity.to_numpy()]), periods_per_year)
    oos_metrics.update(trade_metrics(oos_trades_df, init_cash=WINDOW_INIT_CASH, n_bars=len(oos_equity), periods_per_year=periods_per_year))
    traded = [r for r in results if r.selected_combo is not None]
    oos_metrics["exposure"] = (
        sum(r.test_metrics.get("exposure", 0.0) * len(r.test_returns) for r in traded) / len(oos_equity) if len(oos_equity) else 0.0
    )
    oos_metrics["traded_bars_share"] = sum(len(r.test_returns) for r in traded) / len(oos_equity) if len(oos_equity) else 0.0
    oos_metrics.update({f"ret_{k}": v for k, v in return_moments(stitched.to_numpy()).items()})
    oos_metrics["windows"] = len(results)
    oos_metrics["windows_traded"] = sum(1 for r in results if r.selected_combo is not None)
    oos_metrics["windows_positive"] = sum(1 for r in results if r.selected_combo is not None and r.test_metrics.get("total_return", 0) > 0)
    return WalkForwardResult(results, oos_equity, oos_trades_df, oos_metrics, yearly_returns(oos_equity), freq, cfg)
