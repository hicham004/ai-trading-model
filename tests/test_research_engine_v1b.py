"""Engine overlays (Sprint 2b): size matrices, reduce-only de-risking, ladder, trailing stop, brackets, MFE/MAE."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.bracket import BRACKETS, apply_bracket, get_bracket
from research.engine import Costs, run_vectorized
from research.metrics import giveback_metrics
from research.sizing import LadderConfig
from research.strategies import get_candidate
from research.strategies.base import FeatureContext, SignalFrame
from research.sweep import build_frames, param_grid, simulate_sizing, simulate_slice
from tests.test_research_engine import ohlc
from tests.test_research_strategies import synthetic

ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)


def test_size_matrix_sizes_the_entry_from_the_decision_bar():
    o, h, l, c = ohlc([100] * 6)
    desired = np.ones(6, dtype=bool)
    frac = np.array([[0.5], [0.25], [0.25], [0.25], [0.25], [0.25]])
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac)
    t = res.trades
    assert len(t) == 1 and t.loc[0, "entry_i"] == 1 and t.loc[0, "quantity"] == pytest.approx(50.0)
    assert t.loc[0, "size_fraction"] == 0.5 and t.loc[0, "reductions"] == 0
    assert res.allocation[1, 0] == 0.5 and res.allocation[5, 0] == 0.5 and res.allocation[0, 0] == 0.0
    assert res.avg_allocation[0] == pytest.approx(0.5 * 5 / 6)
    # Reduce-only rebalancing: the fraction fell to 0.25 (> 25 % below 0.5) -> sold down at the next open.
    res2 = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac, rebalance_threshold=0.25)
    t2 = res2.trades
    assert t2.loc[0, "reductions"] == 1 and t2.loc[0, "quantity"] == pytest.approx(50.0)
    assert res2.allocation[1, 0] == 0.5 and res2.allocation[2, 0] == 0.25
    assert res2.equity[-1, 0] == pytest.approx(10_000)
    # NaN (vol warm-up) or zero fraction means no entry.
    frac_nan = np.array([[np.nan], [0.3], [0.3], [0.3], [0.3], [0.3]])
    res3 = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac_nan)
    assert res3.trades.loc[0, "entry_i"] == 2 and res3.trades.loc[0, "size_fraction"] == pytest.approx(0.3)
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=np.full((6, 1), 1.5))


def test_reduce_only_never_adds_and_zero_fraction_derisks():
    o, h, l, c = ohlc([100] * 7)
    desired = np.ones(7, dtype=bool)
    frac = np.array([0.8, 0.8, 0.2, 0.2, 0.9, 0.9, 0.9])[:, None]
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac, rebalance_threshold=0.25)
    t = res.trades
    assert len(t) == 1 and t.loc[0, "reductions"] == 1
    assert list(res.allocation[:, 0]) == [0.0, 0.8, 0.8, 0.2, 0.2, 0.2, 0.2]  # 0.9 later never adds back
    assert t.loc[0, "pnl"] == pytest.approx(0.0)
    frac0 = np.array([0.5, 0.5, 0.0, 0.0, 0.5, 0.5, 0.5])[:, None]
    res2 = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac0, rebalance_threshold=0.25)
    t2 = res2.trades
    assert t2.loc[0, "exit_reason"] == "derisk" and t2.loc[0, "exit_i"] == 3
    assert t2.loc[1, "entry_i"] == 5  # re-enters once the fraction is positive again (decision bar 4)
    # Without rebalancing the position is kept (entry-sized only).
    res3 = run_vectorized(o, h, l, c, desired, None, costs=ZERO, size_fraction=frac0)
    assert len(res3.trades) == 1 and res3.trades.loc[0, "exit_reason"] == "end_of_data"


def test_ladder_halves_then_flattens_then_rearms():
    closes = [100, 100, 100, 94, 94, 80, 80, 80, 80, 80, 80]
    o, h, l, c = ohlc(closes, highs=[x + 0.5 for x in closes], lows=[x - 0.5 for x in closes], closes=closes)
    desired = np.ones(len(closes), dtype=bool)
    cfg = LadderConfig(half_dd=0.05, flat_dd=0.10, recovery_bars=3)
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, ladder=cfg)
    t = res.trades
    assert t.loc[0, "entry_i"] == 1 and t.loc[0, "exit_i"] == 6 and t.loc[0, "exit_reason"] == "derisk"
    assert t.loc[0, "reductions"] == 1  # halved at bar 4 after the -6 % drawdown
    assert res.allocation[4, 0] == 0.5 and res.allocation[6, 0] == 0.0 and res.allocation[7, 0] == 0.0
    assert t.loc[1, "entry_i"] == 8 and t.loc[1, "exit_reason"] == "end_of_data"  # re-armed after 3 bars flat
    np.testing.assert_allclose(res.equity[:, 0], [10000, 10000, 10000, 9400, 9400, 8700, 8700, 8700, 8700, 8700, 8700])
    # ladder_mask: the second column runs without the ladder.
    res2 = run_vectorized(o, h, l, c, np.ones((len(closes), 2), dtype=bool), None, costs=ZERO, ladder=cfg,
                          ladder_mask=np.array([True, False]))
    assert len(res2.trades_for(0)) == 2 and len(res2.trades_for(1)) == 1
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, None, costs=ZERO, ladder=cfg, ladder_mask=np.array([True, False]))


def test_trailing_stop_arms_after_1r_follows_highs_and_only_moves_up():
    o = np.array([100, 100, 100, 106, 112, 100], dtype=float)
    h = np.array([101, 101, 110, 115, 113, 101], dtype=float)
    l = np.array([99, 99, 99, 106, 108, 97], dtype=float)
    c = np.array([100, 100, 100, 110, 110, 100], dtype=float)
    desired = np.ones(6, dtype=bool)
    res = run_vectorized(o, h, l, c, desired, np.full(6, 5.0), costs=ZERO, trail_activate_r=1.0, trail_r=1.0)
    t = res.trades
    assert len(t) == 1
    assert t.loc[0, "exit_i"] == 4 and t.loc[0, "exit_reason"] == "stop_loss" and t.loc[0, "exit_price"] == pytest.approx(110.0)
    assert t.loc[0, "mfe_pct"] == pytest.approx(0.15) and t.loc[0, "mae_pct"] == pytest.approx(-0.01)
    # Without the trail the fixed stop at 95 never triggers and the position runs to the end.
    plain = run_vectorized(o, h, l, c, desired, np.full(6, 5.0), costs=ZERO)
    assert plain.trades.loc[0, "exit_reason"] == "end_of_data"
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, np.full(6, 5.0), costs=ZERO, trail_activate_r=1.0)
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, np.full(6, 5.0), costs=ZERO, trail_activate_r=1.0, trail_r=0.0)


def test_bracket_take_profit_time_stop_and_frames():
    idx = pd.RangeIndex(5)
    frame = SignalFrame(desired=pd.Series(True, index=idx), stop_distance=pd.Series(5.0, index=idx), strength=pd.Series(np.nan, index=idx))
    tp = apply_bracket(frame, get_bracket("tp2"), "1H")
    assert list(tp.target_distance) == [10.0] * 5 and tp.trail_r is None and tp.time_stop_bars is None
    o, h, l, c = ohlc([100] * 5, highs=[101, 101, 112, 101, 101])
    res = run_vectorized(o, h, l, c, np.ones(5, dtype=bool), np.full(5, 5.0), costs=ZERO, target_distance=tp.target_distance.to_numpy())
    assert res.trades.loc[0, "exit_reason"] == "target" and res.trades.loc[0, "exit_price"] == pytest.approx(110.0)
    both = apply_bracket(frame, get_bracket("trail1_tp3"), "4H")
    assert both.trail_activate_r == 1.0 and both.trail_r == 1.0 and list(both.target_distance) == [15.0] * 5
    timed = apply_bracket(SignalFrame(frame.desired, frame.stop_distance, frame.strength, time_stop_bars=10), get_bracket("time30"), "4H")
    assert timed.time_stop_bars == 10  # the tighter of the strategy's own and the bracket's time stop
    assert apply_bracket(frame, get_bracket("none"), "1H") is frame
    with pytest.raises(ValueError):
        get_bracket("tp99")
    assert set(BRACKETS) == {"none", "tp2", "tp3", "trail1", "trail2", "trail1_tp3", "time30"}


def test_per_column_time_stops():
    o, h, l, c = ohlc([100] * 6)
    desired = np.ones((6, 2), dtype=bool)
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, time_stop_bars=[2, None])
    t0, t1 = res.trades_for(0), res.trades_for(1)
    assert list(t0["exit_reason"]) == ["time_stop", "end_of_data"] and int(t0.iloc[0]["exit_i"]) == 3
    assert list(t1["exit_reason"]) == ["end_of_data"]
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, None, costs=ZERO, time_stop_bars=[0, None])


def test_overlays_off_matches_scalar_sizing_exactly():
    df = synthetic(1200)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rng = np.random.default_rng(2)
    desired = rng.random((1200, 3)) > 0.5
    stops = np.repeat((c * 0.02)[:, None], 3, axis=1)
    costs = Costs(0.001, 0.0005)
    base = run_vectorized(o, h, l, c, desired, stops, costs=costs, time_stop_bars=12)
    matrix = run_vectorized(o, h, l, c, desired, stops, costs=costs, time_stop_bars=12, size_fraction=np.ones((1200, 3)))
    np.testing.assert_array_equal(base.equity, matrix.equity)
    pd.testing.assert_frame_equal(base.trades, matrix.trades)
    assert {"mfe_pct", "mae_pct", "size_fraction", "reductions"} <= set(base.trades.columns)
    assert (base.trades["mfe_pct"] >= base.trades["mae_pct"]).all()
    assert (base.trades["size_fraction"] == 1.0).all()


def test_giveback_metrics():
    trades = pd.DataFrame({"mfe_pct": [0.05, 0.01, 0.04], "mae_pct": [-0.01, -0.02, -0.03], "return_pct": [-0.01, 0.02, 0.03]})
    g = giveback_metrics(trades, mfe_threshold=0.03)
    assert g["n_reached"] == 2 and g["share_reached"] == pytest.approx(2 / 3)
    assert g["share_reached_closed_negative"] == pytest.approx(0.5)
    assert g["avg_giveback_pct"] == pytest.approx((0.06 + 0.01) / 2)
    assert giveback_metrics(pd.DataFrame())["n_trades"] == 0


def test_sweep_frames_with_brackets_and_sizing_simulation():
    df = synthetic(1500)
    ctx = FeatureContext("1H", 8766.0)
    cand = get_candidate("baseline")
    combos = param_grid({"short_window": [10], "bracket": ["none", "tp3", "trail1", "time30"]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    assert frames.n_combos == 4 and frames.target is not None
    assert np.isnan(frames.target[:, 0]).all() and np.isfinite(frames.target[:, 1]).any()
    np.testing.assert_allclose(frames.target[:, 1], frames.stop[:, 1] * 3.0)
    assert np.isnan(frames.trail_dist[0]) and frames.trail_dist[2] == 1.0 and frames.trail_activate[2] == 1.0
    assert frames.time_stops == [None, None, None, 720]
    res = simulate_slice(df, frames, slice(0, 1500), costs=Costs())
    assert res.n_combos == 4 and len(res.trades_for(0)) > 3
    assert "target" in set(res.trades_for(1)["exit_reason"]) or len(res.trades_for(1)) > 0
    fractions = np.column_stack([np.full(1500, 0.25), np.full(1500, 0.5), np.full(1500, 1.0)])
    sized = simulate_sizing(df, frames, 0, slice(200, 1500), fractions, costs=Costs(), ladder=LadderConfig(), ladder_mask=np.array([False, False, True]))
    assert sized.n_combos == 3 and sized.n_bars == 1300 and len(sized.trades_for(0)) > 3
    assert 0 < sized.avg_allocation[0] < sized.avg_allocation[1] <= 0.5
    assert (sized.trades_for(0)["size_fraction"] == 0.25).all()
    laddered = sized.trades_for(2)
    assert (laddered["reductions"] > 0).any() or (laddered["exit_reason"] == "derisk").any()  # the ladder acted on a losing path
    with pytest.raises(ValueError):
        simulate_slice(df, frames, slice(0, 1500), costs=Costs(), size_fraction=np.ones((10, 1)))
