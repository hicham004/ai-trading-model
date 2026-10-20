"""Sweep helpers, regime labels, calibration, Monte Carlo, report rendering, data helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from research.calibration import StrengthCalibrator, entry_outcomes
from research.data import bars_per_year, split_holdout
from research.engine import Costs
from research.montecarlo import slippage_stress, trade_order_bootstrap
from research.regime import metrics_by_regime, regime_labels
from research.report import acceptance_check, render_report
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import apply_no_trade, build_frames, heatmap, metrics_table, param_grid, robustness, simulate_slice
from tests.test_research_strategies import synthetic

PPY = 8766.0


def test_param_grid_and_frames_and_table():
    grid = {"a": [1, 2], "b": [(1, 2), (3, 4)]}
    combos = param_grid(grid, base={"c": 9})
    assert len(combos) == 4 and combos[0] == {"c": 9, "a": 1, "b": (1, 2)}
    df = synthetic(1500)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("baseline")
    combos = param_grid(cand.grid, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    assert frames.desired.shape == (1500, len(combos)) and frames.stop.shape == frames.desired.shape
    res = simulate_slice(df, frames, slice(0, 1500), costs=Costs())
    table = metrics_table(res, combos, periods_per_year=PPY)
    assert len(table) == len(combos) and {"p_short_window", "p_long_window", "sharpe", "n_trades"} <= set(table.columns)
    sub = simulate_slice(df, frames, slice(100, 900), costs=Costs(), columns=[0, 3])
    assert sub.n_combos == 2 and sub.n_bars == 800
    hm = heatmap(table, "short_window", "long_window", "total_return")
    assert hm.shape == (3, 3)
    best = {"short_window": 10, "long_window": 50, "stop_loss_pct": 0.02}
    rb = robustness(table, best, "total_return", tolerance=0.3)
    assert rb["n_neighbours"] >= 1 and "share_above_threshold" in rb and np.isfinite(rb["best"])


def test_apply_no_trade_blocks_entries_but_keeps_positions():
    idx = pd.RangeIndex(6)
    frame_desired = pd.Series([True, True, True, False, True, True], index=idx)
    ok = pd.Series([True, False, False, False, False, True], index=idx)

    class F:  # minimal SignalFrame stand-in
        desired = frame_desired

    out = apply_no_trade(F, ok)
    assert list(out) == [True, True, True, False, False, True]


def test_regime_labels_and_breakdown():
    df = synthetic(6000)
    labels = regime_labels(df, "1H", PPY, vol_lookback_days=60)
    assert len(labels) == len(df)
    known = labels[~labels.str.contains("unknown")]
    assert len(known) > 1000
    assert set(known.str.split("_").str[0]) <= {"lowvol", "midvol", "highvol"}
    assert set(known.str.split("_").str[1]) <= {"up", "down", "range"}
    rets = pd.Series(np.random.default_rng(0).normal(0, 0.01, len(df)), index=df.index)
    table = metrics_by_regime(rets, labels, PPY)
    assert table["share"].sum() == pytest.approx(1.0) and table["bars"].sum() == len(df)


def test_calibrator_fit_confidence_roundtrip_and_entry_outcomes():
    rng = np.random.default_rng(0)
    strengths = rng.uniform(0, 1, 500)
    wins = rng.uniform(0, 1, 500) < strengths  # stronger signals win more often
    cal = StrengthCalibrator(n_bins=5, min_samples=20).fit(strengths, wins)
    assert cal.fitted and len(cal.hit_rates) == 5
    assert cal.confidence(0.95) > cal.confidence(0.05)
    assert cal.confidence(float("nan")) == pytest.approx(cal.pooled_hit_rate)
    again = StrengthCalibrator.from_dict(cal.to_dict())
    assert again.confidence(0.5) == cal.confidence(0.5)
    assert not StrengthCalibrator().fit([], []).fitted
    assert StrengthCalibrator().confidence(0.3) == 0.5
    table = cal.table()
    assert list(table.columns) == ["bucket", "upper_edge", "n", "hit_rate"] and table["n"].sum() == 500
    trades = pd.DataFrame({"combo": [0, 0, 1], "entry_i": [5, 9, 3], "pnl": [1.0, -1.0, 2.0]})
    strength = np.arange(20, dtype=float).reshape(10, 2)
    s, w = entry_outcomes(trades, strength, 0)
    np.testing.assert_allclose(s, [strength[4, 0], strength[8, 0]])
    assert list(w) == [True, False]
    assert entry_outcomes(trades, strength, 5)[0].size == 0


def test_monte_carlo_and_slippage_stress():
    out = trade_order_bootstrap([0.02, -0.01, 0.03, -0.02, 0.01] * 10, n_paths=500, seed=1)
    assert out["n_trades"] == 50 and out["paths"] == 500
    assert out["terminal_p05"] <= out["terminal_p50"] <= out["terminal_p95"]
    assert 0 <= out["max_dd_p50"] <= out["max_dd_p95"] <= out["max_dd_worst"] <= 1
    assert trade_order_bootstrap([]) == {"n_trades": 0, "paths": 0}
    seen = []

    def run(costs):
        seen.append(costs.slippage_rate)
        return {"total_return": 1.0 - costs.slippage_rate * 100}

    stress = slippage_stress(run, Costs(0.001, 0.0005), multipliers=(1, 2, 4))
    assert list(stress) == ["x1", "x2", "x4"] and seen == [0.0005, 0.001, 0.002]
    assert stress["x1"] > stress["x4"]


def test_split_holdout_and_bars_per_year():
    df = synthetic(24 * 400)
    ins, hold = split_holdout(df, holdout_months=3)
    assert len(ins) + len(hold) == len(df) and hold.index[0] > ins.index[-1]
    assert (hold.index[-1] - hold.index[0]).days >= 85
    assert bars_per_year("1H") == pytest.approx(8766) and bars_per_year("1D") == pytest.approx(365.25)
    e, h = split_holdout(df.iloc[:0])
    assert e.empty and h.empty


def test_acceptance_and_report_rendering():
    oos_good = {"profit_factor": 1.5, "max_drawdown": 0.1, "n_trades": 40, "total_return": 0.3, "cagr": 0.1, "sharpe": 1.1,
                "sortino": 1.5, "win_rate": 0.5, "exposure": 0.4, "fees_pct_of_start": 0.05, "windows": 4, "windows_traded": 4,
                "windows_positive": 3}
    yearly = {2022: 0.1, 2023: -0.02, 2024: 0.2, 2025: 0.05}
    good = acceptance_check(oos_good, yearly, {"share_above_threshold": 0.8})
    assert good["passed"] and good["positive_years"] == 3
    bad = acceptance_check(dict(oos_good, profit_factor=1.0), yearly, {"share_above_threshold": 0.8})
    assert not bad["passed"] and not bad["pf_gt_1_2"]
    assert not acceptance_check(oos_good, {}, {"share_above_threshold": 0.8})["positive_in_3_of_4_years"]

    run = {
        "meta": {"generated_at": "2026-10-20 12:00 UTC", "data_span": "BTC-USDT 1H: 2020→2026", "fee_rate": 0.001,
                 "slippage_rate": 0.0005, "size_fraction": 1.0, "train_days": 540, "test_days": 180, "purge_days": 7,
                 "select_by": "sharpe", "min_trades": 20, "holdout_months": 12, "holdout_span": "2025-10→2026-10"},
        "benchmark": [{"instrument": "BTC-USDT", "timeframe": "1H", "total_return": 0.5, "max_drawdown": 0.3}],
        "results": [{
            "candidate": "S1", "label": "TSMOM", "instrument": "BTC-USDT", "timeframe": "1H", "grid_size": 36,
            "selected_params": {"vote": 2}, "oos": oos_good, "yearly": yearly,
            "by_regime": [{"regime": "lowvol_up", "share": 0.5, "total_return": 0.1, "sharpe": 1.0}],
            "robustness": {"best": 1.1, "median": 0.9, "min": 0.2, "share_above_threshold": 0.8, "n_neighbours": 5},
            "dsr": {"n_trials": 36, "expected_max_sr": 0.02, "observed_sr": 0.03, "dsr": 0.7},
            "montecarlo": {"n_trades": 40, "paths": 100, "terminal_p05": 0.9, "terminal_p50": 1.2, "terminal_p95": 1.6,
                           "prob_loss": 0.1, "max_dd_p50": 0.1, "max_dd_p95": 0.2},
            "slippage_stress": {"x1": 0.3, "x2": 0.2, "x3": 0.1},
            "acceptance": good,
            "holdout": {"total_return": 0.05, "sharpe": 0.5, "profit_factor": 1.1, "max_drawdown": 0.08, "n_trades": 9},
            "holdout_event_driven": {"total_return": 0.05, "n_trades": 9, "rejected_entries": 0, "difference": 0.0},
            "notes": ["a note"],
        }],
    }
    text = render_report(run)
    assert "# Ensemble v1" in text and "| S1 | BTC-USDT 1H |" in text and "**PASS**" in text
    assert "Holdout (2025-10→2026-10)" in text and "Event-driven cross-check" in text and "- a note" in text
    assert "Nothing here authorizes" in text


def test_perturbed_params_and_fixed_replay():
    from research.sweep import perturbed_params
    from research.walkforward import WalkForwardConfig, make_windows, replay_fixed_params

    base = {"lookbacks_days": (7, 14, 30), "vote": 2, "atr_mult": 3.0, "label": "x"}
    sets = perturbed_params(base, ["lookbacks_days", "vote", "atr_mult", "label"], tolerance=0.3)
    assert sets and all(s != base for s in sets)
    assert {s["vote"] for s in sets} <= {1, 2, 3}
    assert any(s["lookbacks_days"] == (5, 10, 21) for s in sets) and any(s["lookbacks_days"] == (9, 18, 39) for s in sets)
    assert len({str(sorted(s.items())) for s in sets}) == len(sets)  # no duplicates
    assert all(s["label"] == "x" for s in sets)

    df = synthetic(2000)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("baseline")
    frames = build_frames(cand, df, [cand.default_params], ctx)
    windows = make_windows(len(df), WalkForwardConfig(train_bars=800, test_bars=300, purge_bars=10, min_trades=1))
    out = replay_fixed_params(df, frames, 0, windows, costs=Costs())
    assert set(out) == {"total_return", "worst_window_drawdown", "n_trades"} and 0 <= out["worst_window_drawdown"] <= 1
