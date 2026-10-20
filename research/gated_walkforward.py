"""Walk-forward with a per-window regime-v2 entry gate and fixed policy sizing (Sprint 2c, SIMULATION ONLY).

Per rolling window:

1. the regime model is fitted on the TRAIN slice only (:func:`research.regime_v2.fit_regime`);
2. its forward-filtered bear probability is computed over the window's
   train+test bars with those fixed parameters (no look-ahead);
3. the candidate's desired-long matrix is gated on ENTRIES only
   (``mode="gate"``) or the entry fraction is scaled (``mode="scale"``);
4. the trading rule is selected on the gated TRAIN slice at full size
   exactly like Sprint 2b (entries among bracket-free rules, then the exit
   bracket among siblings);
5. the TEST slice is simulated once under the fixed a-priori policy sizing
   (planner decision 2) — optionally also under a small train-selected sizing
   comparison grid, reported as a comparison only.

Test slices are stitched into one out-of-sample curve; each window restarts
from the same capital and flat. ``mode="none"`` gives the Sprint 2b path with
policy sizing. Replays (robustness, slippage stress, full-size sleeves)
reuse the per-window fitted regimes, so nothing is refitted on test data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.engine import Costs, SweepResult
from research.metrics import bar_returns, equity_metrics, giveback_metrics, return_moments, sharpe, trade_metrics, yearly_returns
from research.regime_v2 import FittedRegime, RegimeV2Config, bear_probability, entry_gate_mask, fit_regime, regime_summary, size_multiplier
from research.sized_walkforward import SizingSelection, select_sizing
from research.sizing import LadderConfig, SizingSpec, ladder_mask
from research.sweep import Frames, metrics_table, simulate_sizing, simulate_slice
from research.walkforward import WINDOW_INIT_CASH, WalkForwardConfig, Window, _params_key, _select, make_windows


# -- gating helpers -----------------------------------------------------------

def gate_desired_matrix(desired: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Entries-only gate for a (n, C) desired matrix: ``out[i] = desired[i] & (ok[i] | out[i-1])``."""
    desired = np.asarray(desired, dtype=bool)
    ok = np.asarray(ok, dtype=bool)
    if desired.ndim == 1:
        desired = desired[:, None]
    if ok.shape[0] != desired.shape[0]:
        raise ValueError("ok must have one value per bar")
    out = np.zeros_like(desired)
    prev = np.zeros(desired.shape[1], dtype=bool)
    for i in range(desired.shape[0]):
        prev = desired[i] & (ok[i] | prev)
        out[i] = prev
    return out


def window_frames(frames: Frames, lo: int, hi: int, ok: Optional[np.ndarray]) -> Frames:
    """Rows ``lo:hi`` of ``frames`` with the entry gate ``ok`` (length hi-lo) applied."""
    desired = frames.desired[lo:hi]
    if ok is not None:
        desired = gate_desired_matrix(desired, ok)
    return Frames(
        desired=desired, stop=frames.stop[lo:hi], strength=frames.strength[lo:hi], time_stops=list(frames.time_stops),
        target=None if frames.target is None else frames.target[lo:hi],
        trail_activate=frames.trail_activate, trail_dist=frames.trail_dist,
    )


@dataclass
class WindowRegime:
    """What the regime layer did in one window (fitted on train only)."""

    idx: int
    fitted: Optional[FittedRegime]
    bear_prob: Optional[pd.Series]  # over the window's train+test bars
    ok: Optional[np.ndarray]  # entry gate over train+test (None = no gate)
    mult: Optional[np.ndarray]  # entry-fraction multiplier over train+test (None = 1)
    train_summary: Dict[str, float]
    test_summary: Dict[str, float]
    error: Optional[str] = None


def regime_for_window(df: pd.DataFrame, w: Window, cfg: RegimeV2Config, timeframe: str, periods_per_year: float) -> WindowRegime:
    lo, hi = w.train.start, w.test.stop
    if not cfg.active:
        return WindowRegime(w.idx, None, None, None, None, {}, {})
    try:
        fitted = fit_regime(df.iloc[w.train], timeframe, periods_per_year, cfg)
    except ValueError as exc:  # too few finite bars: fail closed (no entries while unknown)
        n = hi - lo
        ok = np.zeros(n, dtype=bool) if cfg.mode == "gate" else None
        mult = np.full(n, cfg.bear_scale) if cfg.mode == "scale" else None
        return WindowRegime(w.idx, None, None, ok, mult, {}, {}, error=str(exc))
    sub = df.iloc[lo:hi]
    bear = bear_probability(fitted, sub, timeframe, periods_per_year, cfg)
    ok = entry_gate_mask(bear, cfg).to_numpy(dtype=bool) if cfg.mode == "gate" else None
    mult = size_multiplier(bear, cfg).to_numpy(dtype=float) if cfg.mode == "scale" else None
    train_len = w.train.stop - w.train.start
    test_rel = slice(w.test.start - lo, hi - lo)
    return WindowRegime(
        w.idx, fitted, bear, ok, mult,
        regime_summary(bear.iloc[:train_len], cfg), regime_summary(bear.iloc[test_rel], cfg),
    )


def regimes_for_windows(df: pd.DataFrame, windows: Sequence[Window], cfg: RegimeV2Config, timeframe: str, periods_per_year: float) -> List[WindowRegime]:
    return [regime_for_window(df, w, cfg, timeframe, periods_per_year) for w in windows]


# -- results ------------------------------------------------------------------

@dataclass
class GatedWindowResult:
    idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    rule_combo: Optional[int]
    rule_params: Dict[str, Any]
    rule_train_metric: float
    n_qualified: int
    test_metrics: Dict[str, float]
    test_returns: pd.Series
    train_sharpes_rules: List[float] = field(default_factory=list)
    regime_train: Dict[str, float] = field(default_factory=dict)
    regime_test: Dict[str, float] = field(default_factory=dict)
    gate_blocked_share: float = 0.0  # share of desired test bars removed by the gate (selected rule)
    comparison_label: str = ""
    comparison_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class GatedWalkForwardResult:
    windows: List[GatedWindowResult]
    regimes: List[WindowRegime]
    oos_equity: pd.Series
    oos_returns: pd.Series
    oos_trades: pd.DataFrame
    oos_metrics: Dict[str, float]
    yearly: pd.Series
    rule_frequency: Dict[str, int]
    config: WalkForwardConfig
    regime_cfg: RegimeV2Config
    policy: SizingSpec
    comparison_returns: Optional[pd.Series] = None
    comparison_metrics: Dict[str, float] = field(default_factory=dict)
    comparison_frequency: Dict[str, int] = field(default_factory=dict)

    @property
    def rule_most_often(self) -> Optional[Dict[str, Any]]:
        if not self.rule_frequency:
            return None
        key = max(self.rule_frequency, key=self.rule_frequency.get)
        for w in self.windows:
            if w.rule_combo is not None and _params_key(w.rule_params) == key:
                return dict(w.rule_params)
        return None

    @property
    def last_selected(self) -> Optional[GatedWindowResult]:
        return next((w for w in reversed(self.windows) if w.rule_combo is not None), None)


def _window_returns(res: SweepResult, column: int, index: pd.Index) -> pd.Series:
    eq = res.equity[:, column]
    return pd.Series(np.concatenate([[eq[0] / res.init_cash - 1.0], eq[1:] / eq[:-1] - 1.0]), index=index)


def _stitch(returns: Sequence[pd.Series], trades: Sequence[pd.DataFrame], traded: Sequence[Dict[str, float]], periods_per_year: float) -> Tuple[pd.Series, pd.Series, pd.DataFrame, Dict[str, float]]:
    stitched = pd.concat(returns).sort_index()
    equity = (1.0 + stitched).cumprod()
    trades_df = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    metrics = equity_metrics(np.concatenate([[1.0], equity.to_numpy()]), periods_per_year)
    metrics.update(trade_metrics(trades_df, init_cash=WINDOW_INIT_CASH, n_bars=len(equity), periods_per_year=periods_per_year))
    total = len(equity)
    metrics["exposure"] = sum(t["exposure"] * t["bars"] for t in traded) / total if total else 0.0
    metrics["avg_allocation"] = sum(t["avg_allocation"] * t["bars"] for t in traded) / total if total else 0.0
    metrics["traded_bars_share"] = sum(t["bars"] for t in traded) / total if total else 0.0
    metrics.update({f"ret_{k}": v for k, v in return_moments(stitched.to_numpy()).items()})
    metrics.update({f"giveback_{k}": v for k, v in giveback_metrics(trades_df).items() if k != "n_trades"})
    return stitched, equity, trades_df, metrics


def run_gated_walk_forward(
    df: pd.DataFrame,
    frames: Frames,
    combos: Sequence[Mapping[str, Any]],
    cfg: WalkForwardConfig,
    policy: SizingSpec,
    policy_fractions: np.ndarray,
    ladder: LadderConfig,
    regime_cfg: RegimeV2Config,
    *,
    costs: Costs,
    periods_per_year: float,
    timeframe: str,
    rebalance_threshold: Optional[float] = 0.25,
    stage_a_columns: Optional[Sequence[int]] = None,
    siblings: Optional[Mapping[int, Sequence[int]]] = None,
    regimes: Optional[Sequence[WindowRegime]] = None,
    comparison_specs: Optional[Sequence[SizingSpec]] = None,
    comparison_fractions: Optional[np.ndarray] = None,
    comparison_cfg: SizingSelection = SizingSelection(),
) -> GatedWalkForwardResult:
    n = len(df)
    windows = make_windows(n, cfg)
    if not windows:
        raise ValueError(f"not enough bars ({n}) for train={cfg.train_bars} purge={cfg.purge_bars} test={cfg.test_bars}")
    pf = np.asarray(policy_fractions, dtype=float)
    if pf.ndim == 1:
        pf = pf[:, None]
    if pf.shape != (n, 1):
        raise ValueError("policy_fractions must be an (n_bars, 1) matrix")
    if regimes is None:
        regimes = regimes_for_windows(df, windows, regime_cfg, timeframe, periods_per_year)
    if len(regimes) != len(windows):
        raise ValueError("one regime record per window is required")
    comp_mask = ladder_mask(comparison_specs) if comparison_specs else None
    comp_dicts = [s.to_dict() for s in comparison_specs] if comparison_specs else []

    results: List[GatedWindowResult] = []
    oos_returns: List[pd.Series] = []
    oos_trades: List[pd.DataFrame] = []
    traded: List[Dict[str, float]] = []
    comp_returns: List[pd.Series] = []
    comp_traded: List[Dict[str, float]] = []
    comp_trades: List[pd.DataFrame] = []
    rule_freq: Dict[str, int] = {}
    comp_freq: Dict[str, int] = {}

    for w, reg in zip(windows, regimes):
        lo, hi = w.train.start, w.test.stop
        sub = df.iloc[lo:hi]
        train_rel = slice(0, w.train.stop - lo)
        test_rel = slice(w.test.start - lo, hi - lo)
        test_index = df.index[w.test]
        fw = window_frames(frames, lo, hi, reg.ok)
        fractions_w = pf[lo:hi].copy()
        if reg.mult is not None:
            fractions_w = fractions_w * reg.mult[:, None]

        train_res = simulate_slice(sub, fw, train_rel, costs=costs)
        table = metrics_table(train_res, combos, periods_per_year=periods_per_year)
        rule_sharpes = [sharpe(bar_returns(train_res.equity[:, k]), 1.0) for k in range(train_res.n_combos)]
        stage_table = table if stage_a_columns is None else table[table["combo"].isin(list(stage_a_columns))]
        best = _select(stage_table, cfg)
        if best is not None and siblings is not None and int(best["combo"]) in siblings:
            sib = table[table["combo"].isin(list(siblings[int(best["combo"])]))]
            best_sibling = _select(sib, cfg)
            if best_sibling is not None:
                best = best_sibling
        if best is None:
            flat = pd.Series(0.0, index=test_index)
            results.append(GatedWindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                             None, {}, float("nan"), 0, {}, flat, rule_sharpes, reg.train_summary, reg.test_summary))
            oos_returns.append(flat)
            comp_returns.append(flat)
            continue
        rule = int(best["combo"])
        params = dict(combos[rule])
        rule_freq[_params_key(params)] = rule_freq.get(_params_key(params), 0) + 1

        test_res = simulate_sizing(sub, fw, rule, test_rel, fractions_w, costs=costs, ladder=ladder,
                                   ladder_mask=np.array([policy.ladder]), rebalance_threshold=rebalance_threshold)
        test_returns = _window_returns(test_res, 0, test_index)
        tm = equity_metrics(test_res.equity[:, 0], periods_per_year)
        tm.update(trade_metrics(test_res.trades, init_cash=test_res.init_cash, n_bars=test_res.n_bars, periods_per_year=periods_per_year))
        tm["exposure"] = float(test_res.exposure[0])
        tm["avg_allocation"] = float(test_res.avg_allocation[0])
        trades = test_res.trades.copy()
        trades["window"] = w.idx
        trades["entry_time"] = test_index[trades["entry_i"].to_numpy(dtype=int)] if len(trades) else pd.Series(dtype="datetime64[ns, UTC]")
        oos_trades.append(trades)
        traded.append({"exposure": tm["exposure"], "avg_allocation": tm["avg_allocation"], "bars": len(test_returns)})
        raw_desired = frames.desired[w.test][:, rule]
        gated_desired = fw.desired[test_rel][:, rule]
        blocked = float((raw_desired & ~gated_desired).sum() / max(1, raw_desired.sum())) if raw_desired.any() else 0.0

        comp_label, comp_metrics = "", {}
        if comparison_specs:
            cf = np.asarray(comparison_fractions, dtype=float)[lo:hi].copy()
            if reg.mult is not None:
                cf = cf * reg.mult[:, None]
            size_res = simulate_sizing(sub, fw, rule, train_rel, cf, costs=costs, ladder=ladder, ladder_mask=comp_mask,
                                       rebalance_threshold=rebalance_threshold)
            size_table = metrics_table(size_res, comp_dicts, periods_per_year=periods_per_year)
            chosen = select_sizing(size_table, comparison_cfg)
            s_idx = int(chosen["combo"]) if chosen is not None else 0
            comp_label = comparison_specs[s_idx].label
            comp_freq[comp_label] = comp_freq.get(comp_label, 0) + 1
            comp_res = simulate_sizing(sub, fw, rule, test_rel, cf[:, [s_idx]], costs=costs, ladder=ladder,
                                       ladder_mask=comp_mask[[s_idx]], rebalance_threshold=rebalance_threshold)
            comp_rets = _window_returns(comp_res, 0, test_index)
            comp_metrics = equity_metrics(comp_res.equity[:, 0], periods_per_year)
            comp_metrics.update(trade_metrics(comp_res.trades, init_cash=comp_res.init_cash, n_bars=comp_res.n_bars, periods_per_year=periods_per_year))
            comp_returns.append(comp_rets)
            comp_traded.append({"exposure": float(comp_res.exposure[0]), "avg_allocation": float(comp_res.avg_allocation[0]), "bars": len(comp_rets)})
            ct = comp_res.trades.copy()
            ct["window"] = w.idx
            comp_trades.append(ct)

        results.append(GatedWindowResult(w.idx, df.index[w.train.start], df.index[w.train.stop - 1], test_index[0], test_index[-1],
                                         rule, params, float(best[cfg.select_by]), int((stage_table["n_trades"] >= cfg.min_trades).sum()),
                                         tm, test_returns, rule_sharpes, reg.train_summary, reg.test_summary, blocked, comp_label, comp_metrics))
        oos_returns.append(test_returns)

    stitched, oos_equity, trades_df, oos_metrics = _stitch(oos_returns, oos_trades, traded, periods_per_year)
    oos_metrics["windows"] = len(results)
    oos_metrics["windows_traded"] = sum(1 for r in results if r.rule_combo is not None)
    oos_metrics["windows_positive"] = sum(1 for r in results if r.rule_combo is not None and r.test_metrics.get("total_return", 0) > 0)
    oos_metrics["gate_blocked_share"] = float(np.mean([r.gate_blocked_share for r in results if r.rule_combo is not None])) if oos_metrics["windows_traded"] else 0.0
    out = GatedWalkForwardResult(results, list(regimes), oos_equity, stitched, trades_df, oos_metrics, yearly_returns(oos_equity),
                                 rule_freq, cfg, regime_cfg, policy)
    if comparison_specs and comp_returns:
        c_stitched, _, _, c_metrics = _stitch(comp_returns, comp_trades, comp_traded, periods_per_year)
        out.comparison_returns = c_stitched
        out.comparison_metrics = c_metrics
        out.comparison_frequency = comp_freq
    return out


# -- replays (fixed choices, same windows, same per-window regimes) -----------

def replay_gated(
    df: pd.DataFrame,
    frames: Frames,
    columns: Sequence[int],
    windows: Sequence[Window],
    regimes: Sequence[WindowRegime],
    *,
    costs: Costs,
    periods_per_year: float,
    size_fraction: Optional[np.ndarray] = None,
    ladder: Optional[LadderConfig] = None,
    ladder_on: bool = False,
    rebalance_threshold: Optional[float] = None,
    want_returns: bool = False,
) -> Tuple[List[Dict[str, float]], List[pd.Series]]:
    """Replay FIXED rule columns over every test window with the per-window gate; stitched metrics per column.

    ``size_fraction`` is a full-length (n, 1) policy matrix or None (full size).
    Returns ``(metrics per column, stitched bar-return series per column)``
    (the series list is empty unless ``want_returns``).
    """
    cols = list(columns)
    n_cols = len(cols)
    per_col_returns: List[List[pd.Series]] = [[] for _ in cols]
    per_col_trades: List[List[pd.DataFrame]] = [[] for _ in cols]
    per_col_traded: List[List[Dict[str, float]]] = [[] for _ in cols]
    worst_dd = np.zeros(n_cols)
    for w, reg in zip(windows, regimes):
        lo, hi = w.train.start, w.test.stop
        sub = df.iloc[lo:hi]
        test_rel = slice(w.test.start - lo, hi - lo)
        fw = window_frames(frames, lo, hi, reg.ok)
        if size_fraction is None:
            sf: Any = 1.0
            mask = np.full(n_cols, bool(ladder_on)) if ladder is not None else None
            res = simulate_slice(sub, fw, test_rel, costs=costs, size_fraction=sf, columns=cols, ladder=ladder, ladder_mask=mask,
                                 rebalance_threshold=rebalance_threshold)
        else:
            sf_w = np.asarray(size_fraction, dtype=float)[lo:hi].copy()
            if reg.mult is not None:
                sf_w = sf_w * reg.mult[:, None]
            # one policy column replicated for every rule column
            mask = np.full(n_cols, bool(ladder_on)) if ladder is not None else None
            res = simulate_slice(sub, fw, test_rel, costs=costs, size_fraction=np.repeat(sf_w, n_cols, axis=1) if sf_w.shape[1] == 1 else sf_w,
                                 columns=cols, ladder=ladder, ladder_mask=mask, rebalance_threshold=rebalance_threshold)
        test_index = df.index[w.test]
        for k in range(n_cols):
            per_col_returns[k].append(_window_returns(res, k, test_index))
            per_col_trades[k].append(res.trades_for(k))
            per_col_traded[k].append({"exposure": float(res.exposure[k]), "avg_allocation": float(res.avg_allocation[k]), "bars": res.n_bars})
            worst_dd[k] = max(worst_dd[k], equity_metrics(res.equity[:, k], periods_per_year)["max_drawdown"])
    metrics: List[Dict[str, float]] = []
    series: List[pd.Series] = []
    for k in range(n_cols):
        stitched, _, _, m = _stitch(per_col_returns[k], per_col_trades[k], per_col_traded[k], periods_per_year)
        m["worst_window_drawdown"] = float(worst_dd[k])
        metrics.append(m)
        if want_returns:
            series.append(stitched)
    return metrics, series


def slippage_stress_gated(
    df: pd.DataFrame, frames: Frames, column: int, windows: Sequence[Window], regimes: Sequence[WindowRegime], *,
    base_costs: Costs, periods_per_year: float, size_fraction: np.ndarray, ladder: LadderConfig, ladder_on: bool,
    rebalance_threshold: Optional[float], multipliers: Sequence[float] = (1.0, 2.0, 3.0),
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for mult in multipliers:
        sc = Costs(fee_rate=base_costs.fee_rate, slippage_rate=min(0.0999, base_costs.slippage_rate * mult))
        m, _ = replay_gated(df, frames, [column], windows, regimes, costs=sc, periods_per_year=periods_per_year,
                            size_fraction=size_fraction, ladder=ladder, ladder_on=ladder_on, rebalance_threshold=rebalance_threshold)
        out[f"x{mult:g}"] = float(m[0]["total_return"])
    return out
