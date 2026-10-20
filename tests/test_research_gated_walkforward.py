"""Gated walk-forward: per-window train-only regime fits, entries-only gating, policy sizing, replays, mode 'none' parity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.engine import Costs
from research.gated_walkforward import regimes_for_windows, replay_gated, run_gated_walk_forward, slippage_stress_gated
from research.regime_v2 import RegimeV2Config
from research.sized_walkforward import SizingSelection, run_sized_walk_forward
from research.sizing import LadderConfig, SizingSpec, fraction_matrix, sizing_grid
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import build_frames, param_grid
from research.walkforward import WalkForwardConfig, make_windows
from tests.test_research_strategies import synthetic

PPY = 8766.0
COSTS = Costs(0.001, 0.0005)
POLICY = SizingSpec(kind="vol_target", target_vol=0.10, vol_lookback=30, crash_dd=0.15, crash_window_days=5.0, crash_mode="half", ladder=True)


@pytest.fixture(scope="module")
def setup():
    df = synthetic(5000, seed=11)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("S1")
    combos = param_grid({"lookbacks_days": [(7, 14, 30)], "vote": [1, 2], "atr_mult": [3.0], "bracket": ["none", "tp2"]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    cfg = WalkForwardConfig(train_bars=1500, test_bars=500, purge_bars=24, min_trades=3)
    pf = fraction_matrix(df, [POLICY], "1H", PPY)
    ladder = LadderConfig(recovery_bars=48)
    stage_a, siblings = [0, 2], {0: [0, 1], 1: [0, 1], 2: [2, 3], 3: [2, 3]}
    return df, frames, combos, cfg, pf, ladder, stage_a, siblings


def _run(setup, mode, **kw):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    rc = RegimeV2Config(mode=mode, vol_window_days=1.0)
    return run_gated_walk_forward(df, frames, combos, cfg, POLICY, pf, ladder, rc, costs=COSTS, periods_per_year=PPY, timeframe="1H",
                                  stage_a_columns=stage_a, siblings=siblings, **kw)


def test_mode_none_matches_the_sprint_2b_policy_walk_forward(setup):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    gated = _run(setup, "none")
    sized = run_sized_walk_forward(df, frames, combos, cfg, [POLICY], pf, ladder, costs=COSTS, periods_per_year=PPY,
                                   sizing_cfg=SizingSelection(dd_cap=0.99, min_trades=1, rebalance_threshold=0.25),
                                   stage_a_columns=stage_a, siblings=siblings)
    pd.testing.assert_series_equal(gated.oos_equity, sized.oos_equity)
    assert gated.rule_frequency == sized.rule_frequency
    assert gated.oos_metrics["n_trades"] == sized.oos_metrics["n_trades"]
    assert gated.oos_metrics["gate_blocked_share"] == 0.0
    assert all(r.fitted is None for r in gated.regimes)


def test_gate_mode_fits_per_window_on_train_only_and_only_removes_entries(setup):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    res = _run(setup, "gate")
    windows = make_windows(len(df), cfg)
    assert len(res.regimes) == len(windows) == len(res.windows)
    for w, reg in zip(windows, res.regimes):
        assert reg.fitted is not None and reg.fitted.train_bars <= (w.train.stop - w.train.start)
        assert len(reg.ok) == w.test.stop - w.train.start
    assert 0.0 <= res.oos_metrics["gate_blocked_share"] <= 1.0
    assert len(res.oos_equity) == sum(len(w.test_returns) for w in res.windows)
    for w in res.windows:
        if w.rule_combo is not None:
            assert set(w.regime_train) == {"bars", "bear_share", "mean_bear_prob"}
            assert 0.0 <= w.gate_blocked_share <= 1.0
    # The policy fraction bounds exposure in every mode.
    assert 0.0 <= res.oos_metrics["avg_allocation"] <= 1.0


def test_scale_mode_reduces_allocation_in_bear_bars(setup):
    none = _run(setup, "none")
    scale = _run(setup, "scale")
    assert all(r.mult is not None and set(np.unique(r.mult)) <= {0.25, 1.0} for r in scale.regimes)
    assert scale.oos_metrics["avg_allocation"] <= none.oos_metrics["avg_allocation"] + 1e-12
    assert scale.oos_metrics["gate_blocked_share"] == 0.0  # scale mode never blocks an entry


def test_comparison_sizing_is_reported_separately(setup):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    specs = sizing_grid(targets=(0.15,), lookbacks=(20,), fixed=(0.5,), crash=((0.1, 5.0),), crash_modes=("half",), ladders=(True,))
    res = _run(setup, "none", comparison_specs=specs, comparison_fractions=fraction_matrix(df, specs, "1H", PPY),
               comparison_cfg=SizingSelection(dd_cap=0.15, min_trades=3, rebalance_threshold=0.25))
    assert res.comparison_returns is not None and len(res.comparison_returns) == len(res.oos_returns)
    assert set(res.comparison_frequency) <= {s.label for s in specs} and sum(res.comparison_frequency.values()) == res.oos_metrics["windows_traded"]
    assert {"sharpe", "max_drawdown", "calmar"} <= set(res.comparison_metrics)
    # The proposal (policy) is untouched by the comparison.
    plain = _run(setup, "none")
    pd.testing.assert_series_equal(res.oos_equity, plain.oos_equity)


def test_replays_reuse_window_regimes_and_match_the_selected_rule(setup):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    res = _run(setup, "gate")
    windows = make_windows(len(df), cfg)
    sel = res.rule_most_often
    col = next(i for i, c in enumerate(combos) if c == sel)
    metrics, series = replay_gated(df, frames, [col], windows, res.regimes, costs=COSTS, periods_per_year=PPY, size_fraction=pf,
                                   ladder=ladder, ladder_on=True, rebalance_threshold=0.25, want_returns=True)
    assert len(series) == 1 and len(series[0]) == len(res.oos_returns) and "worst_window_drawdown" in metrics[0]
    full, full_series = replay_gated(df, frames, [col, col], windows, res.regimes, costs=COSTS, periods_per_year=PPY, size_fraction=None, want_returns=True)
    assert full[0]["total_return"] == full[1]["total_return"] and full[0]["avg_allocation"] >= metrics[0]["avg_allocation"]
    stress = slippage_stress_gated(df, frames, col, windows, res.regimes, base_costs=COSTS, periods_per_year=PPY, size_fraction=pf, ladder=ladder,
                                   ladder_on=True, rebalance_threshold=0.25)
    assert list(stress) == ["x1", "x2", "x3"] and stress["x1"] >= stress["x3"]
    # Refitting the regimes gives the same gate (deterministic), so a replay is reproducible.
    again = regimes_for_windows(df, windows, RegimeV2Config(mode="gate", vol_window_days=1.0), "1H", PPY)
    for a, b in zip(res.regimes, again):
        np.testing.assert_array_equal(a.ok, b.ok)


def test_validation_errors(setup):
    df, frames, combos, cfg, pf, ladder, stage_a, siblings = setup
    with pytest.raises(ValueError):
        run_gated_walk_forward(df, frames, combos, cfg, POLICY, pf[:100], ladder, RegimeV2Config(mode="none"), costs=COSTS, periods_per_year=PPY, timeframe="1H")
    with pytest.raises(ValueError):
        run_gated_walk_forward(df, frames, combos, cfg, POLICY, pf, ladder, RegimeV2Config(mode="none"), costs=COSTS, periods_per_year=PPY, timeframe="1H", regimes=[])
    with pytest.raises(ValueError):
        run_gated_walk_forward(df.iloc[:100], frames, combos, cfg, POLICY, pf[:100], ladder, RegimeV2Config(mode="none"), costs=COSTS, periods_per_year=PPY, timeframe="1H")
