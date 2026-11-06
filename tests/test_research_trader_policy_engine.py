"""Plan row R18: stop-aware sizing tiers, the add and scale-out variants behind flags, the extra trade columns, the walk-forward plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.brakes import TRADER_BRAKES, TURTLE_LADDER_ONLY
from research.engine import ALL_TRADE_COLUMNS, EXTRA_TRADE_COLUMNS, TRADE_COLUMNS, Costs, EngineVariants, run_vectorized
from research.gated_walkforward import cost_scenarios_gated, make_windows, regimes_for_windows, replay_gated, run_gated_walk_forward
from research.montecarlo import trade_order_bootstrap
from research.regime_v2 import RegimeV2Config
from research.sizing import SIZING_TIERS, LadderConfig, SizingSpec, fraction_components, fraction_matrix, fraction_series, rule_fraction_matrix
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import Frames, build_frames, param_grid, simulate_sizing
from research.walkforward import WalkForwardConfig
from tests.test_research_engine import ohlc
from tests.test_research_strategies import synthetic

ROOT = Path(__file__).resolve().parents[1]
ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)
PPY = 8766.0


def _times(n: int, freq: str = "6h") -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")


# -- sizing ---------------------------------------------------------------------------------------------

def test_sizing_tiers_are_the_fixed_ones_and_the_reference_serialises_as_sprint_2c_stored_it():
    ref, trader, aggressive, risk = (SIZING_TIERS[k] for k in ("reference", "trader", "aggressive", "risk1.5"))
    assert ref.label == "vt10/30 crash15/90dh ladder" and trader.label == "vt20/30 crash15/90dh cap2" and aggressive.label == "vt25/30 crash15/90dh cap2.5"
    assert risk.label == "risk1.5 crash15/90dh" and risk.kind == "risk" and risk.risk_fraction == 0.015 and risk.needs_stop
    assert trader.risk_cap == 0.02 and aggressive.risk_cap == 0.025 and not trader.ladder and not aggressive.ladder and ref.ladder
    stored = json.loads((ROOT / "docs" / "research" / "ensemble_v1c_results.json").read_text(encoding="utf-8"))["meta"]["policy_sizing"]
    assert ref.to_dict() == stored  # no new key leaks into a spec without the R18 fields
    assert set(trader.to_dict()) == set(stored) | {"risk_cap"} and "risk_fraction" not in trader.to_dict()
    for bad in ({"kind": "risk"}, {"kind": "vol_target", "risk_fraction": 0.01}, {"risk_cap": 0.0}, {"kind": "risk", "risk_fraction": 1.5}):
        with pytest.raises(ValueError):
            SizingSpec(**bad)


def test_fraction_series_applies_the_per_trade_cap_from_the_stop_and_keeps_the_warm_up():
    df = synthetic(600)
    close = df["close"]
    stop = (close * 0.10).to_numpy()  # a 10 % stop: the 2 % cap allows at most 20 % of equity
    plain = SizingSpec(kind="vol_target", target_vol=5.0, vol_lookback=20)  # a huge target: the vol fraction is 1.0 once warm
    capped = SizingSpec(kind="vol_target", target_vol=5.0, vol_lookback=20, risk_cap=0.02)
    base = fraction_series(df, plain, "1H", PPY)
    frac = fraction_series(df, capped, "1H", PPY, stop_distance=stop)
    assert base.iloc[:20].isna().all() and (base.iloc[20:] == 1.0).all()
    assert frac.iloc[:20].isna().all() and np.allclose(frac.iloc[20:], 0.20)
    with pytest.raises(ValueError):
        fraction_series(df, capped, "1H", PPY)  # the cap needs the stop
    # Without a usable stop the cap cannot act: the base fraction stands (and a NaN stop never creates an entry on its own).
    no_stop = np.full(len(df), np.nan)
    pd.testing.assert_series_equal(fraction_series(df, capped, "1H", PPY, stop_distance=no_stop), base, check_names=False)
    # Kovner's rule: 1.5 % / stop %, capped at 100 %.
    risk = SizingSpec(kind="risk", risk_fraction=0.015)
    assert np.allclose(fraction_series(df, risk, "1H", PPY, stop_distance=stop), 0.15)
    assert np.allclose(fraction_series(df, risk, "1H", PPY, stop_distance=(close * 0.01).to_numpy()), 1.0)
    assert fraction_series(df, risk, "1H", PPY, stop_distance=no_stop).isna().all()
    # The conviction multiplier scales the base before the cap and never above it.
    mult = pd.Series(np.where(np.arange(len(df)) % 2 == 0, 1.25, 0.75), index=df.index)
    vt = SizingSpec(kind="vol_target", target_vol=0.5, vol_lookback=20, risk_cap=0.02)
    with_m = fraction_series(df, vt, "1H", PPY, stop_distance=stop, multiplier=mult)
    without = fraction_series(df, vt, "1H", PPY, stop_distance=stop)
    assert (with_m.dropna() <= 0.20 + 1e-12).all()
    low = without.dropna() < 0.16
    assert np.allclose(with_m.dropna()[low & (mult.reindex(with_m.dropna().index) == 1.25)], (without.dropna() * 1.25)[low & (mult.reindex(with_m.dropna().index) == 1.25)])
    comp = fraction_components(df, capped, "1H", PPY, stop_distance=stop)
    assert set(comp.columns) == {"base", "cap_allocation", "fraction", "cap_binds"} and comp["cap_binds"].iloc[20:].all() and not comp["cap_binds"].iloc[:20].any()
    assert np.allclose(comp["cap_allocation"].iloc[20:], 0.2) and np.allclose(comp["fraction"].iloc[20:], 0.2)
    assert not fraction_components(df, plain, "1H", PPY, stop_distance=stop)["cap_binds"].any()


def test_rule_fraction_matrix_gives_one_policy_column_per_rule_column():
    df = synthetic(900)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("S1")
    combos = param_grid({"lookbacks_days": [(7, 14, 30)], "vote": [1, 2], "atr_mult": [2.0, 4.0]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    trader = SIZING_TIERS["trader"]
    pf = rule_fraction_matrix(df, trader, frames.stop, "1H", PPY)
    assert pf.shape == (len(df), len(combos))
    for k in range(len(combos)):
        np.testing.assert_allclose(pf[:, k], fraction_series(df, trader, "1H", PPY, stop_distance=frames.stop[:, k]).to_numpy(), equal_nan=True)
    # Columns 0 and 2 share the 2 x ATR stop (votes 1 and 2), columns 1 and 3 the 4 x ATR stop: under a cap that binds, the wider
    # stop allows less.
    assert [c["atr_mult"] for c in combos] == [2.0, 4.0, 2.0, 4.0]
    tight = SizingSpec(kind="vol_target", target_vol=0.2, vol_lookback=30, risk_cap=0.003)
    pt = rule_fraction_matrix(df, tight, frames.stop, "1H", PPY)
    np.testing.assert_array_equal(pt[:, 0], pt[:, 2])
    np.testing.assert_array_equal(pt[:, 1], pt[:, 3])
    ok = np.isfinite(pt[:, 0]) & np.isfinite(pt[:, 1])
    assert (pt[ok, 1] <= pt[ok, 0] + 1e-12).all() and (pt[ok, 1] < pt[ok, 0]).any()
    # A policy that does not read the stop replicates Sprint 2c's single column.
    ref = rule_fraction_matrix(df, SIZING_TIERS["reference"], frames.stop, "1H", PPY)
    np.testing.assert_array_equal(ref, np.repeat(fraction_matrix(df, [SIZING_TIERS["reference"]], "1H", PPY), len(combos), axis=1))
    with pytest.raises(ValueError):
        rule_fraction_matrix(df, trader, frames.stop[:-1], "1H", PPY)


# -- engine: flags off are today's engine; the extra columns; the variants ----------------------------------

def test_flags_off_are_bit_for_bit_and_the_extra_columns_carry_the_initial_stop_and_risk():
    df = synthetic(1500, seed=5)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rng = np.random.default_rng(3)
    desired = rng.random((1500, 2)) > 0.6
    stops = np.repeat((c * 0.03)[:, None], 2, axis=1)
    costs = Costs(0.001, 0.0005)
    frac = np.clip(rng.uniform(0.1, 0.9, (1500, 2)), 0, 1)
    base = run_vectorized(o, h, l, c, desired, stops, costs=costs, size_fraction=frac, rebalance_threshold=0.25, ladder=LadderConfig(recovery_bars=50))
    same = run_vectorized(o, h, l, c, desired, stops, costs=costs, size_fraction=frac, rebalance_threshold=0.25, ladder=LadderConfig(recovery_bars=50),
                          variants=EngineVariants(), brakes=None)
    np.testing.assert_array_equal(base.equity, same.equity)
    pd.testing.assert_frame_equal(base.trades, same.trades)
    assert list(base.trades.columns) == list(ALL_TRADE_COLUMNS) and ALL_TRADE_COLUMNS[: len(TRADE_COLUMNS)] == TRADE_COLUMNS
    assert set(EXTRA_TRADE_COLUMNS) == {"stop_price", "risk", "risk_pct", "adds", "add_worst_case_r", "scale_outs"}
    t = base.trades
    assert (t["adds"] == 0).all() and (t["scale_outs"] == 0).all() and t["add_worst_case_r"].isna().all()
    # The initial stop is the decision close minus the stop distance; risk = quantity x (fill - stop); risk_pct against the cash at entry.
    dec = t["entry_i"].to_numpy() - 1
    np.testing.assert_allclose(t["stop_price"], c[dec] - stops[dec, 0])
    np.testing.assert_allclose(t["risk"], t["quantity"] * (t["entry_price"] - t["stop_price"]))
    assert (t["risk_pct"] > 0).all() and (t["risk_pct"] < 1).all()
    # Without a stop the risk columns are NaN.
    none = run_vectorized(o, h, l, c, desired[:, :1], None, costs=costs)
    assert none.trades["stop_price"].isna().all() and none.trades["risk"].isna().all() and none.trades["risk_pct"].isna().all()
    with pytest.raises(ValueError):
        EngineVariants(add_at_r=0.0)
    with pytest.raises(ValueError):
        EngineVariants(scale_out_share=1.0)
    assert not EngineVariants().active and EngineVariants(add_at_r=1.0).label == "add 0.5x at +1R"


def test_the_add_variant_adds_once_on_a_winner_with_its_own_stop_and_reports_the_worst_case():
    # Entry at 100 with a 10-point stop (R = 10 per unit); the close reaches 110 (+1 R) on bar 3 -> the add fills at bar 4's open.
    closes = [100, 100, 100, 110, 110, 110, 110, 110]
    opens = [100, 100, 100, 100, 110, 110, 110, 110]
    highs = [x + 0.5 for x in closes]
    lows = [x - 0.5 for x in closes]
    o, h, l, c = ohlc(opens, highs=highs, lows=lows, closes=closes)
    desired = np.ones(8, dtype=bool)
    stops = np.full(8, 10.0)
    var = EngineVariants(add_at_r=1.0, add_size=0.5)
    res = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, size_fraction=0.5, variants=var)
    t = res.trades
    assert len(t) == 1 and t.loc[0, "adds"] == 1 and t.loc[0, "quantity"] == pytest.approx(50.0)  # 5,000 / 100 = 50 units at first
    # Equity after the add: 50 + 25 units at 110 plus the cash left; the add is 25 units bought at 110 with its stop at 100 (110 - 10).
    np.testing.assert_allclose(res.equity[4:, 0], 10_000 + 50 * 10)  # 50 units gained 10 each; the add is flat at its own price
    # Worst case at the stops: the first unit loses 50 x 10 = 500 (1 R), the add 25 x 10 = 250 -> 1.5 R.
    assert t.loc[0, "add_worst_case_r"] == pytest.approx(1.5)
    assert t.loc[0, "pnl"] == pytest.approx(500.0) and t.loc[0, "exit_reason"] == "end_of_data"
    # Only the add unit is stopped when the low reaches its stop (100) but not the first unit's stop (90).
    lows2 = list(lows)
    lows2[6] = 99.0
    o2, h2, l2, c2 = ohlc(opens, highs=highs, lows=lows2, closes=closes)
    res2 = run_vectorized(o2, h2, l2, c2, desired, stops, costs=ZERO, size_fraction=0.5, variants=var)
    t2 = res2.trades
    assert len(t2) == 1 and t2.loc[0, "adds"] == 1 and t2.loc[0, "exit_reason"] == "end_of_data"
    assert t2.loc[0, "pnl"] == pytest.approx(500.0 - 25 * 10)  # the add lost 10 points on 25 units; the first unit kept its 500
    assert res2.equity[6, 0] == pytest.approx(10_000 + 500 - 250) and res2.equity[7, 0] == pytest.approx(10_250)
    # The add's stop also holds on the add's own entry bar (Codex review of PR #13): the add fills at bar 4's open (110,
    # stop 100) and the same bar's low (99) crosses that stop but not the first unit's (90) -> only the add is stopped.
    lows5 = list(lows)
    lows5[4] = 99.0
    o5, h5, l5, c5 = ohlc(opens, highs=highs, lows=lows5, closes=closes)
    res5 = run_vectorized(o5, h5, l5, c5, desired, stops, costs=ZERO, size_fraction=0.5, variants=var)
    t5 = res5.trades
    assert len(t5) == 1 and t5.loc[0, "adds"] == 1 and t5.loc[0, "exit_reason"] == "end_of_data"
    assert t5.loc[0, "pnl"] == pytest.approx(500.0 - 25 * 10)  # the add lost its 10 points on its entry bar
    np.testing.assert_allclose(res5.equity[4:, 0], 10_000 + 500 - 250)
    # Never twice: a second +1 R later does not add again; never after a loss (a close below the entry never adds).
    closes3 = [100, 100, 100, 110, 110, 125, 125, 125]
    o3, h3, l3, c3 = ohlc([100, 100, 100, 100, 110, 110, 125, 125], highs=[x + 0.5 for x in closes3], lows=[x - 0.5 for x in closes3], closes=closes3)
    assert run_vectorized(o3, h3, l3, c3, desired, stops, costs=ZERO, size_fraction=0.5, variants=var).trades.loc[0, "adds"] == 1
    losing = [100, 100, 100, 95, 95, 95, 95, 95]
    o4, h4, l4, c4 = ohlc(losing, highs=[x + 0.5 for x in losing], lows=[x - 0.5 for x in losing], closes=losing)
    assert run_vectorized(o4, h4, l4, c4, desired, stops, costs=ZERO, size_fraction=0.5, variants=var).trades.loc[0, "adds"] == 0
    # The add never borrows: with 100 % allocated there is no cash, so the add has zero size (counted as an add of nothing is avoided).
    full = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, size_fraction=1.0, variants=var)
    assert full.trades.loc[0, "adds"] == 1 and full.trades.loc[0, "add_worst_case_r"] == pytest.approx(1.0, abs=1e-9)
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, desired, None, costs=ZERO, variants=var)  # the add needs the candidate's stop


def test_the_scale_out_variant_sells_half_at_plus_two_r_through_the_reduce_only_path():
    closes = [100, 100, 100, 120, 120, 120, 120]
    opens = [100, 100, 100, 100, 120, 120, 120]
    o, h, l, c = ohlc(opens, highs=[x + 0.5 for x in closes], lows=[x - 0.5 for x in closes], closes=closes)
    desired = np.ones(7, dtype=bool)
    stops = np.full(7, 10.0)
    res = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, variants=EngineVariants(scale_out_at_r=2.0, scale_out_share=0.5))
    t = res.trades
    assert len(t) == 1 and t.loc[0, "scale_outs"] == 1 and t.loc[0, "reductions"] == 1
    # 100 units at 100; at bar 4's open 50 units sold at 120 (+1,000 realized); the rest marked at 120: equity 12,000 throughout.
    np.testing.assert_allclose(res.equity[3:, 0], 12_000.0)
    assert t.loc[0, "pnl"] == pytest.approx(2_000.0) and res.allocation[4, 0] == pytest.approx(0.5)
    plain = run_vectorized(o, h, l, c, desired, stops, costs=ZERO)
    assert plain.trades.loc[0, "scale_outs"] == 0 and plain.trades.loc[0, "reductions"] == 0


# -- walk-forward plumbing -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wf_setup():
    df = synthetic(5000, seed=11)
    ctx = FeatureContext("1H", PPY)
    cand = get_candidate("S1")
    combos = param_grid({"lookbacks_days": [(7, 14, 30)], "vote": [1, 2], "atr_mult": [2.0, 4.0]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, ctx)
    cfg = WalkForwardConfig(train_bars=1500, test_bars=500, purge_bars=24, min_trades=3)
    return df, ctx, cand, combos, frames, cfg


def test_walk_forward_takes_a_per_rule_fraction_matrix_brakes_and_variant_test_frames(wf_setup):
    df, ctx, cand, combos, frames, cfg = wf_setup
    trader = SIZING_TIERS["trader"]
    ref = SIZING_TIERS["reference"]
    ladder = LadderConfig(recovery_bars=48)
    rc = RegimeV2Config(mode="none", vol_window_days=1.0)
    pf_ref = fraction_matrix(df, [ref], "1H", PPY)
    pf_trader = rule_fraction_matrix(df, trader, frames.stop, "1H", PPY)
    base = run_gated_walk_forward(df, frames, combos, cfg, ref, pf_ref, ladder, rc, costs=ZERO, periods_per_year=PPY, timeframe="1H")
    tier = run_gated_walk_forward(df, frames, combos, cfg, trader, pf_trader, ladder, rc, costs=ZERO, periods_per_year=PPY, timeframe="1H",
                                  brakes=TURTLE_LADDER_ONLY)
    assert tier.rule_frequency == base.rule_frequency  # the selection never sees the tier
    assert tier.oos_metrics["n_trades"] > 0 and tier.brake_summary["opportunities"] > 0 and "ladder" in tier.brake_summary["counts"]
    assert base.brake_summary == {}
    # The per-rule matrix sized every trade at most at the cap: risk_pct <= 2 % (plus nothing: zero costs here).
    assert (tier.oos_trades["risk_pct"].dropna() <= 0.02 + 1e-9).all()
    # A matrix with a wrong column count is refused.
    with pytest.raises(ValueError):
        run_gated_walk_forward(df, frames, combos, cfg, trader, pf_trader[:, :2], ladder, rc, costs=ZERO, periods_per_year=PPY, timeframe="1H")
    # Variant frames: a wider stop on the test slice only; the selection is unchanged, the stops are not.
    wider = [dict(p, atr_mult=p["atr_mult"] + 1.0) for p in combos]
    test_frames = build_frames(cand, df, wider, ctx)
    var = run_gated_walk_forward(df, frames, combos, cfg, ref, pf_ref, ladder, rc, costs=ZERO, periods_per_year=PPY, timeframe="1H", test_frames=test_frames)
    assert var.rule_frequency == base.rule_frequency and not np.allclose(var.oos_equity.to_numpy(), base.oos_equity.to_numpy())
    with pytest.raises(ValueError):
        run_gated_walk_forward(df, frames, combos, cfg, ref, pf_ref, ladder, rc, costs=ZERO, periods_per_year=PPY, timeframe="1H",
                               test_frames=Frames(desired=frames.desired[:, :1], stop=frames.stop[:, :1], strength=frames.strength[:, :1], time_stops=[None]))
    # Replays and cost scenarios accept a per-column matrix and the brakes.
    windows = make_windows(len(df), cfg)
    regimes = regimes_for_windows(df, windows, rc, "1H", PPY)
    m, series = replay_gated(df, frames, [0, 2], windows, regimes, costs=ZERO, periods_per_year=PPY, size_fraction=pf_trader[:, [0, 2]],
                             ladder=ladder, ladder_on=False, rebalance_threshold=0.25, want_returns=True, brakes=TRADER_BRAKES)
    assert len(m) == 2 and len(series) == 2 and all("total_return" in x for x in m)
    scen = cost_scenarios_gated(df, frames, 0, windows, regimes, scenarios={"measured": Costs(0.0005, 0.0005), "altcoin": Costs(0.001, 0.0015)},
                                periods_per_year=PPY, size_fraction=pf_trader[:, [0]], ladder=ladder, ladder_on=False, rebalance_threshold=0.25)
    assert set(scen) == {"measured", "altcoin"} and scen["measured"]["round_trip"] == pytest.approx(0.002) and scen["altcoin"]["round_trip"] == pytest.approx(0.005)
    assert scen["altcoin"]["total_return"] <= scen["measured"]["total_return"]
    # One rule under the tier and the add variant through simulate_sizing.
    res = simulate_sizing(df, frames, 0, slice(0, 2000), pf_trader[:, [0]], costs=ZERO, brakes=TRADER_BRAKES, variants=EngineVariants(add_at_r=1.0))
    assert res.brakes is not None and "adds" in res.trades


def test_bootstrap_reports_the_probability_of_touching_the_hard_stop():
    out = trade_order_bootstrap([0.05, -0.02, 0.03, -0.01] * 10, n_paths=200, seed=1)
    assert "prob_max_dd_ge_30" in out and 0.0 <= out["prob_max_dd_ge_30"] <= 1.0
    deep = trade_order_bootstrap([-0.4, -0.35, -0.5], n_paths=50, seed=1, dd_thresholds=(0.30, 0.10))
    assert deep["prob_max_dd_ge_30"] == 1.0 and deep["prob_max_dd_ge_10"] == 1.0
    assert set(trade_order_bootstrap([], n_paths=5)) == {"n_trades", "paths"}
