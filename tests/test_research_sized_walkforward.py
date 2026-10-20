"""Two-stage sized walk-forward: rule then sizing selection on train only, stitching, replays, sizing sweep."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.engine import Costs
from research.sized_walkforward import (
    SizingSelection,
    replay_columns,
    replay_sizing_sweep,
    run_sized_walk_forward,
    select_sizing,
    stitched_metrics,
)
from research.sizing import LadderConfig, fraction_matrix, sizing_grid
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import build_frames, param_grid, simulate_slice
from research.walkforward import WalkForwardConfig, make_windows
from tests.test_research_strategies import synthetic

PPY = 8766.0
COSTS = Costs(0.001, 0.0005)


@pytest.fixture(scope="module")
def setup():
    df = synthetic(4000, seed=11)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("baseline")
    combos = param_grid({"short_window": [5, 10], "long_window": [30, 50], "bracket": ["none", "trail1"]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    specs = sizing_grid(targets=(0.15,), lookbacks=(20,), fixed=(0.5,), crash=((0.1, 5.0),), crash_modes=("half",), ladders=(False, True))
    fractions = fraction_matrix(df, specs, "1H", PPY)
    ladder = LadderConfig(recovery_bars=48)
    return df, frames, combos, specs, fractions, ladder


def test_select_sizing_prefers_calmar_under_the_cap_with_fallback():
    table = pd.DataFrame({
        "combo": [0, 1, 2, 3],
        "n_trades": [20, 20, 20, 3],
        "max_drawdown": [0.10, 0.14, 0.30, 0.05],
        "calmar": [0.8, 1.2, 2.0, 5.0],
        "sharpe": [1.0, 1.1, 1.5, 2.0],
    })
    cfg = SizingSelection(dd_cap=0.15, min_trades=10)
    assert int(select_sizing(table, cfg)["combo"]) == 1  # best Calmar among drawdown <= cap and enough trades
    none_qualify = table.assign(max_drawdown=[0.3, 0.4, 0.5, 0.2])
    assert int(select_sizing(none_qualify, cfg)["combo"]) == 3  # fallback: the lowest drawdown with any trades
    assert select_sizing(table.assign(n_trades=0), cfg) is None
    with pytest.raises(ValueError):
        SizingSelection(dd_cap=1.5)
    assert SizingSelection().to_dict()["rebalance_threshold"] == 0.25


def test_sized_walk_forward_selects_rule_then_sizing_on_train_only(setup):
    df, frames, combos, specs, fractions, ladder = setup
    cfg = WalkForwardConfig(train_bars=1500, test_bars=500, purge_bars=24, min_trades=3)
    res = run_sized_walk_forward(df, frames, combos, cfg, specs, fractions, ladder, costs=COSTS, periods_per_year=PPY,
                                 sizing_cfg=SizingSelection(dd_cap=0.15, min_trades=3))
    assert len(res.windows) == len(make_windows(len(df), cfg)) >= 3
    traded = [w for w in res.windows if w.rule_combo is not None]
    assert traded, "the baseline should qualify in at least one window"
    labels = {s.label for s in specs}
    for w in traded:
        assert w.sizing_label in labels and 0 <= w.sizing_index < len(specs)
        assert "bracket" in w.rule_params and 0.0 <= w.test_metrics["avg_allocation"] <= 1.0
        assert len(w.train_sharpes_rules) == len(combos) and len(w.train_sharpes_sizing) == len(specs)
        if w.sizing_train:
            assert w.sizing_train["n_trades"] >= 1
    assert res.rule_most_often is not None and res.sizing_most_often is not None
    assert sum(res.rule_frequency.values()) == len(traded) == sum(res.sizing_frequency.values())
    assert {"sharpe", "max_drawdown", "calmar", "avg_allocation", "giveback_share_reached", "windows_traded"} <= set(res.oos_metrics)
    assert len(res.oos_equity) == sum(len(w.test_returns) for w in res.windows)
    assert res.last_selected is traded[-1]
    # The sizing stage can only lower exposure relative to full size.
    assert res.oos_metrics["avg_allocation"] <= res.oos_metrics["exposure"] + 1e-12
    with pytest.raises(ValueError):
        run_sized_walk_forward(df, frames, combos, cfg, specs, fractions[:, :2], ladder, costs=COSTS, periods_per_year=PPY)


def test_sized_walk_forward_without_qualified_rule_stays_flat(setup):
    df, frames, combos, specs, fractions, ladder = setup
    cfg = WalkForwardConfig(train_bars=1500, test_bars=500, purge_bars=24, min_trades=10_000)
    res = run_sized_walk_forward(df, frames, combos, cfg, specs, fractions, ladder, costs=COSTS, periods_per_year=PPY)
    assert all(w.rule_combo is None for w in res.windows)
    assert (res.oos_equity == 1.0).all() and res.oos_metrics["windows_traded"] == 0
    assert res.rule_most_often is None and res.sizing_most_often is None and res.last_selected is None


def test_replays_and_sizing_sweep(setup):
    df, frames, combos, specs, fractions, ladder = setup
    cfg = WalkForwardConfig(train_bars=1500, test_bars=500, purge_bars=24, min_trades=3)
    windows = make_windows(len(df), cfg)
    rows = replay_columns(df, frames, [0, 1], windows, costs=COSTS, periods_per_year=PPY, size_fraction=fractions[:, [0]],
                          ladder=ladder, ladder_on=False, rebalance_threshold=0.25)
    assert len(rows) == 2 and {"total_return", "max_drawdown", "calmar", "n_trades", "worst_window_drawdown", "giveback_share_reached"} <= set(rows[0])
    sweep = replay_sizing_sweep(df, frames, 0, windows, specs, fractions, ladder, costs=COSTS, periods_per_year=PPY)
    assert len(sweep) == len(specs) and list(sweep["sizing"]) == [s.label for s in specs]
    fixed = sweep[sweep["sizing"] == "fixed50"].iloc[0]
    assert fixed["avg_allocation"] == pytest.approx(0.5 * fixed["exposure"])
    # Single-window stitching equals that window's own metrics.
    one = simulate_slice(df, frames, windows[0].test, costs=COSTS, columns=[0])
    st = stitched_metrics([one], 0, periods_per_year=PPY)
    assert st["total_return"] == pytest.approx(one.equity[-1, 0] / one.init_cash - 1.0)
    assert st["n_trades"] == len(one.trades)
