"""Two-stage walk-forward for sizing-aware candidates (Sprint 2b, SIMULATION ONLY).

Per rolling window, using the TRAIN slice only:

1. **Rule stage** — every (entry/exit rule x exit bracket) combo is simulated
   at full size and the best by ``cfg.select_by`` (Sharpe) among combos with
   at least ``cfg.min_trades`` trades is selected, exactly like Sprint 2.
2. **Sizing stage** — the selected rule is simulated under every sizing spec
   (vol target / fixed x crash filter x ladder); the spec with the best
   ``sizing_cfg.select_by`` (Calmar) among those whose train max drawdown is
   at most ``sizing_cfg.dd_cap`` is selected (fallback: the lowest drawdown).

Only then is the TEST slice simulated, once, with the selected rule and
sizing. Test slices are stitched into one out-of-sample curve; each window
restarts from the same capital and flat (the ladder state restarts too).
Nothing in a test slice influences the selection that produced it.

Replays (robustness, sizing sweep, slippage stress) run FIXED choices over the
same test windows without any re-selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.engine import Costs, SweepResult
from research.metrics import bar_returns, equity_metrics, giveback_metrics, return_moments, sharpe, trade_metrics, yearly_returns
from research.sizing import LadderConfig, SizingSpec, ladder_mask
from research.sweep import Frames, metrics_table, simulate_sizing, simulate_slice
from research.walkforward import WINDOW_INIT_CASH, WalkForwardConfig, Window, _params_key, _select, make_windows


@dataclass(frozen=True)
class SizingSelection:
    dd_cap: float = 0.15  # train max drawdown a sizing variant may show to qualify (margin under the 20 % gate)
    select_by: str = "calmar"
    min_trades: int = 10
    rebalance_threshold: Optional[float] = 0.25  # reduce-only mid-trade adjustments; None = entry-sized only

    def __post_init__(self) -> None:
        if not (0.0 < self.dd_cap < 1.0):
            raise ValueError("dd_cap must be in (0, 1)")
        if self.rebalance_threshold is not None and not (0.0 <= self.rebalance_threshold < 1.0):
            raise ValueError("rebalance_threshold must be in [0, 1) when given")

    def to_dict(self) -> Dict[str, Any]:
        return {"dd_cap": self.dd_cap, "select_by": self.select_by, "min_trades": self.min_trades,
                "rebalance_threshold": self.rebalance_threshold}


def select_sizing(table: pd.DataFrame, cfg: SizingSelection) -> Optional[pd.Series]:
    """Best sizing row under the drawdown cap; fallback = lowest drawdown among traded variants."""
    t = table.replace([np.inf, -np.inf], np.nan)
    qualified = t[(t["n_trades"] >= cfg.min_trades) & (t["max_drawdown"] <= cfg.dd_cap)].dropna(subset=[cfg.select_by])
    if not qualified.empty:
        return qualified.sort_values([cfg.select_by, "sharpe", "n_trades"], ascending=[False, False, False]).iloc[0]
    fallback = t[t["n_trades"] >= 1].dropna(subset=["max_drawdown"])
    if fallback.empty:
        return None
    return fallback.sort_values(["max_drawdown", "sharpe"], ascending=[True, False]).iloc[0]


@dataclass
class SizedWindowResult:
    idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    rule_combo: Optional[int]
    rule_params: Dict[str, Any]
    rule_train_metric: float
    n_qualified: int
    sizing_index: Optional[int]
    sizing_label: str
    sizing_train: Dict[str, float]
    test_metrics: Dict[str, float]
    test_returns: pd.Series
    train_sharpes_rules: List[float] = field(default_factory=list)
    train_sharpes_sizing: List[float] = field(default_factory=list)


@dataclass
class SizedWalkForwardResult:
    windows: List[SizedWindowResult]
    oos_equity: pd.Series
    oos_trades: pd.DataFrame
    oos_metrics: Dict[str, float]
    yearly: pd.Series
    rule_frequency: Dict[str, int]
    sizing_frequency: Dict[str, int]
    config: WalkForwardConfig
    sizing_cfg: SizingSelection

    def _most_often(self, freq: Dict[str, int]) -> Optional[str]:
        return max(freq, key=freq.get) if freq else None

    @property
    def rule_most_often(self) -> Optional[Dict[str, Any]]:
        key = self._most_often(self.rule_frequency)
        if key is None:
            return None
        for w in self.windows:
            if w.rule_combo is not None and _params_key(w.rule_params) == key:
                return dict(w.rule_params)
        return None

    @property
    def sizing_most_often(self) -> Optional[int]:
        key = self._most_often(self.sizing_frequency)
        if key is None:
            return None
        for w in self.windows:
            if w.sizing_index is not None and w.sizing_label == key:
                return w.sizing_index
        return None

    @property
    def last_selected(self) -> Optional[SizedWindowResult]:
        return next((w for w in reversed(self.windows) if w.rule_combo is not None), None)


def _window_returns(res: SweepResult, column: int, index: pd.Index) -> pd.Series:
    eq = res.equity[:, column]
    return pd.Series(np.concatenate([[eq[0] / res.init_cash - 1.0], eq[1:] / eq[:-1] - 1.0]), index=index)


def stitched_metrics(
    results: Sequence[SweepResult], column: int, *, periods_per_year: float, index: Optional[Sequence[pd.Index]] = None
) -> Dict[str, float]:
    """Metrics of one column stitched across window results (each window restarts from the same capital)."""
    rets: List[np.ndarray] = []
    trades: List[pd.DataFrame] = []
    bars = 0
    alloc_sum = 0.0
    exposure_sum = 0.0
    for res in results:
        eq = res.equity[:, column]
        rets.append(np.concatenate([[eq[0] / res.init_cash - 1.0], eq[1:] / eq[:-1] - 1.0]))
        trades.append(res.trades_for(column))
        bars += res.n_bars
        alloc_sum += float(res.avg_allocation[column]) * res.n_bars
        exposure_sum += float(res.exposure[column]) * res.n_bars
    stitched = np.concatenate(rets) if rets else np.zeros(0)
    equity = np.concatenate([[1.0], np.cumprod(1.0 + stitched)])
    out = equity_metrics(equity, periods_per_year)
    all_trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    out.update(trade_metrics(all_trades, init_cash=WINDOW_INIT_CASH, n_bars=max(1, bars), periods_per_year=periods_per_year))
    out["exposure"] = exposure_sum / bars if bars else 0.0
    out["avg_allocation"] = alloc_sum / bars if bars else 0.0
    out["worst_window_drawdown"] = max((equity_metrics(r.equity[:, column], periods_per_year)["max_drawdown"] for r in results), default=0.0)
    out.update({f"giveback_{k}": v for k, v in giveback_metrics(all_trades).items() if k != "n_trades"})
    return out


def run_sized_walk_forward(
    df: pd.DataFrame,
    frames: Frames,
    combos: Sequence[Mapping[str, Any]],
    cfg: WalkForwardConfig,
    specs: Sequence[SizingSpec],
    fractions: np.ndarray,
    ladder: LadderConfig,
    *,
    costs: Costs,
    periods_per_year: float,
    sizing_cfg: SizingSelection = SizingSelection(),
) -> SizedWalkForwardResult:
    n = len(df)
    windows = make_windows(n, cfg)
    if not windows:
        raise ValueError(f"not enough bars ({n}) for train={cfg.train_bars} purge={cfg.purge_bars} test={cfg.test_bars}")
    if np.asarray(fractions).shape != (n, len(specs)):
        raise ValueError("fractions must be an (n_bars, n_specs) matrix")
    lmask = ladder_mask(specs)
    spec_dicts = [s.to_dict() for s in specs]
    results: List[SizedWindowResult] = []
    oos_returns: List[pd.Series] = []
    oos_trades: List[pd.DataFrame] = []
    rule_freq: Dict[str, int] = {}
    sizing_freq: Dict[str, int] = {}

    for w in windows:
        test_index = df.index[w.test]
        # Stage 1: rule selection at full size.
        train_res = simulate_slice(df, frames, w.train, costs=costs)
        table = metrics_table(train_res, combos, periods_per_year=periods_per_year)
        rule_sharpes = [sharpe(bar_returns(train_res.equity[:, k]), 1.0) for k in range(train_res.n_combos)]
        best = _select(table, cfg)
        if best is None:
            flat = pd.Series(0.0, index=test_index)
            results.append(SizedWindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                             None, {}, float("nan"), 0, None, "", {}, {}, flat, rule_sharpes, []))
            oos_returns.append(flat)
            continue
        rule = int(best["combo"])
        params = dict(combos[rule])
        rule_freq[_params_key(params)] = rule_freq.get(_params_key(params), 0) + 1
        # Stage 2: sizing selection for the selected rule, train slice only.
        size_res = simulate_sizing(df, frames, rule, w.train, fractions, costs=costs, ladder=ladder, ladder_mask=lmask,
                                   rebalance_threshold=sizing_cfg.rebalance_threshold)
        size_table = metrics_table(size_res, spec_dicts, periods_per_year=periods_per_year)
        sizing_sharpes = [sharpe(bar_returns(size_res.equity[:, k]), 1.0) for k in range(size_res.n_combos)]
        chosen = select_sizing(size_table, sizing_cfg)
        s_idx = int(chosen["combo"]) if chosen is not None else 0
        sizing_train = {k: float(chosen[k]) for k in ("total_return", "sharpe", "max_drawdown", "calmar", "n_trades", "avg_allocation")} if chosen is not None else {}
        label = specs[s_idx].label
        sizing_freq[label] = sizing_freq.get(label, 0) + 1
        # Test: the selected rule under the selected sizing, once.
        test_res = simulate_sizing(df, frames, rule, w.test, fractions[:, [s_idx]], costs=costs, ladder=ladder,
                                   ladder_mask=lmask[[s_idx]], rebalance_threshold=sizing_cfg.rebalance_threshold)
        test_returns = _window_returns(test_res, 0, test_index)
        tm = equity_metrics(test_res.equity[:, 0], periods_per_year)
        tm.update(trade_metrics(test_res.trades, init_cash=test_res.init_cash, n_bars=test_res.n_bars, periods_per_year=periods_per_year))
        tm["exposure"] = float(test_res.exposure[0])
        tm["avg_allocation"] = float(test_res.avg_allocation[0])
        trades = test_res.trades.copy()
        trades["window"] = w.idx
        trades["entry_time"] = test_index[trades["entry_i"].to_numpy(dtype=int)] if len(trades) else pd.Series(dtype="datetime64[ns, UTC]")
        oos_trades.append(trades)
        results.append(SizedWindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                         rule, params, float(best[cfg.select_by]), int((table["n_trades"] >= cfg.min_trades).sum()),
                                         s_idx, label, sizing_train, tm, test_returns, rule_sharpes, sizing_sharpes))
        oos_returns.append(test_returns)

    stitched = pd.concat(oos_returns).sort_index()
    oos_equity = (1.0 + stitched).cumprod()
    oos_trades_df = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    oos_metrics = equity_metrics(np.concatenate([[1.0], oos_equity.to_numpy()]), periods_per_year)
    oos_metrics.update(trade_metrics(oos_trades_df, init_cash=WINDOW_INIT_CASH, n_bars=len(oos_equity), periods_per_year=periods_per_year))
    traded = [r for r in results if r.rule_combo is not None]
    total = len(oos_equity)
    oos_metrics["exposure"] = sum(r.test_metrics.get("exposure", 0.0) * len(r.test_returns) for r in traded) / total if total else 0.0
    oos_metrics["avg_allocation"] = sum(r.test_metrics.get("avg_allocation", 0.0) * len(r.test_returns) for r in traded) / total if total else 0.0
    oos_metrics["traded_bars_share"] = sum(len(r.test_returns) for r in traded) / total if total else 0.0
    oos_metrics.update({f"ret_{k}": v for k, v in return_moments(stitched.to_numpy()).items()})
    oos_metrics.update({f"giveback_{k}": v for k, v in giveback_metrics(oos_trades_df).items() if k != "n_trades"})
    oos_metrics["windows"] = len(results)
    oos_metrics["windows_traded"] = len(traded)
    oos_metrics["windows_positive"] = sum(1 for r in traded if r.test_metrics.get("total_return", 0) > 0)
    return SizedWalkForwardResult(results, oos_equity, oos_trades_df, oos_metrics, yearly_returns(oos_equity),
                                  rule_freq, sizing_freq, cfg, sizing_cfg)


def replay_columns(
    df: pd.DataFrame,
    frames: Frames,
    columns: Sequence[int],
    windows: Sequence[Window],
    *,
    costs: Costs,
    periods_per_year: float,
    size_fraction=1.0,
    ladder: Optional[LadderConfig] = None,
    ladder_on: bool = False,
    rebalance_threshold: Optional[float] = None,
) -> List[Dict[str, float]]:
    """Replay FIXED rule columns under one fixed sizing over every test window; stitched metrics per column."""
    cols = list(columns)
    mask = np.full(len(cols), bool(ladder_on)) if ladder is not None else None
    results = [
        simulate_slice(df, frames, w.test, costs=costs, size_fraction=size_fraction, columns=cols, ladder=ladder,
                       ladder_mask=mask, rebalance_threshold=rebalance_threshold)
        for w in windows
    ]
    return [stitched_metrics(results, k, periods_per_year=periods_per_year) for k in range(len(cols))]


def replay_sizing_sweep(
    df: pd.DataFrame,
    frames: Frames,
    rule_column: int,
    windows: Sequence[Window],
    specs: Sequence[SizingSpec],
    fractions: np.ndarray,
    ladder: LadderConfig,
    *,
    costs: Costs,
    periods_per_year: float,
    rebalance_threshold: Optional[float] = 0.25,
) -> pd.DataFrame:
    """One FIXED rule under every sizing spec over the test windows (informational sweep, no selection)."""
    lmask = ladder_mask(specs)
    results = [
        simulate_sizing(df, frames, rule_column, w.test, fractions, costs=costs, ladder=ladder, ladder_mask=lmask,
                        rebalance_threshold=rebalance_threshold)
        for w in windows
    ]
    rows = []
    for j, spec in enumerate(specs):
        m = stitched_metrics(results, j, periods_per_year=periods_per_year)
        row = {"sizing": spec.label, **{k: v for k, v in spec.to_dict().items() if k != "label"}}
        row.update(m)
        rows.append(row)
    return pd.DataFrame(rows)
