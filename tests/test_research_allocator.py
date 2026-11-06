"""Allocator v2: v1 with its brakes off, each brake on its own, no look-ahead, only-lowers-exposure bounds, JSON state."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.allocator import (
    DEFAULT_ALLOCATOR_V2,
    AllocatorState,
    AllocatorV2Config,
    DayInputs,
    allocate_v2,
    asset_groups,
    base_sizing,
    brake_stats,
    daily_closes_to_returns,
    previous_close_positions,
    sleeve_groups,
    step_day,
    trailing_correlations,
)
from research.portfolio import combine_sized, rolling_inverse_vol_weights, vol_target_scale
from research.sizing import LadderConfig, apply_ladder_to_returns

LADDER = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30)
ASSETS = {"S1/BTC/6H": "BTC-USDT", "S2/BTC/4H": "BTC-USDT", "S1/ETH/6H": "ETH-USDT", "S2/ETH/4H": "ETH-USDT"}
OFF = AllocatorV2Config(group_cap=None, loss_limit=None)


def _market(n: int = 420, seed: int = 3, start: str = "2025-01-01"):
    """Daily sleeve returns (zero on flat days), the long/flat state at each close, and two correlated coins."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC", name="day")
    common = rng.normal(0.0005, 0.03, n)
    coins = pd.DataFrame({"BTC-USDT": common + rng.normal(0, 0.012, n), "ETH-USDT": 1.2 * common + rng.normal(0, 0.02, n)}, index=idx)
    held = pd.DataFrame({name: (rng.random(n) > 0.35) for name in ASSETS}, index=idx)
    # A sleeve's return on day t comes from being long during day t: long at the previous close (plus noise of its own exits/entries).
    prev = held.shift(1, fill_value=False)
    daily = pd.DataFrame({name: np.where(prev[name], coins[ASSETS[name]] + rng.normal(0, 0.004, n), 0.0) for name in ASSETS}, index=idx)
    return daily, held, coins


def test_with_every_brake_off_v2_is_v1_to_the_last_bit():
    daily, held, coins = _market()
    run = allocate_v2(daily, held, coins, ASSETS, cfg=OFF, ladder=LADDER)
    ref = combine_sized(daily, name="v1", target_vol=0.15, vol_lookback_days=30, weight_lookback_days=60, ladder=LADDER)
    np.testing.assert_allclose(run.returns.to_numpy(), ref.daily_returns.to_numpy(), rtol=0, atol=1e-15)
    np.testing.assert_allclose(run.equity.to_numpy(), ref.equity.to_numpy(), rtol=1e-13)
    assert run.metrics["cagr"] == pytest.approx(ref.metrics["cagr"], rel=1e-12)
    assert run.metrics["max_drawdown"] == pytest.approx(ref.metrics["max_drawdown"], rel=1e-12)


def test_the_paired_reference_is_always_v1_even_with_the_brakes_on():
    daily, held, coins = _market(seed=5)
    run = allocate_v2(daily, held, coins, ASSETS, ladder=LADDER)
    ref = combine_sized(daily, name="v1", target_vol=0.15, vol_lookback_days=30, weight_lookback_days=60, ladder=LADDER)
    np.testing.assert_allclose(run.reference_equity.to_numpy(), ref.equity.to_numpy(), rtol=1e-13)
    assert not np.allclose(run.equity.to_numpy(), ref.equity.to_numpy())  # the brakes did something on this market


def test_a_warm_up_seeds_the_estimates_and_the_books_start_at_the_start_day():
    daily, held, coins = _market(seed=8)
    start = daily.index[150]
    run = allocate_v2(daily, held, coins, ASSETS, cfg=OFF, ladder=LADDER, start=start)
    weights = rolling_inverse_vol_weights(daily, 60)
    raw = (daily * weights).sum(axis=1)
    scale = vol_target_scale(raw, 0.15, 30)
    expected, _ = apply_ladder_to_returns((raw * scale).loc[start:], LADDER)
    np.testing.assert_allclose(run.returns.to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-15)
    assert run.days[0] == start and run.records[0]["reference_v1"]["ladder_multiplier"] == 1.0


def _inputs(weights, returns, held, rho, scale=1.0):
    return DayInputs(returns=returns, weights=weights, vol_scale=scale, positions=held, correlations={("BTC-USDT", "ETH-USDT"): rho})


EQUAL = {n: 0.25 for n in ASSETS}
ALL_LONG = {n: True for n in ASSETS}


def test_correlated_coins_are_one_bet_capped_at_half_of_equity():
    state = AllocatorState()
    rec = step_day(state, _inputs(EQUAL, {n: 0.02 for n in ASSETS}, ALL_LONG, 0.85), ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
    assert rec["groups"] == [sorted(ASSETS)]
    assert rec["invested_before_cap"] == {"+".join(sorted(ASSETS)): pytest.approx(1.0)}
    assert rec["final_weights"] == {n: pytest.approx(0.125) for n in ASSETS}
    assert rec["invested_share"] == pytest.approx(0.5) and rec["portfolio_return"] == pytest.approx(0.01)
    assert rec["reference_v1"]["return"] == pytest.approx(0.02) and rec["brakes"] == ["correlation cap"]


def test_decorrelated_coins_are_capped_one_by_one_and_flat_sleeves_do_not_count():
    state = AllocatorState()
    weights = {"S1/BTC/6H": 0.35, "S2/BTC/4H": 0.30, "S1/ETH/6H": 0.20, "S2/ETH/4H": 0.15}
    held = {"S1/BTC/6H": True, "S2/BTC/4H": True, "S1/ETH/6H": True, "S2/ETH/4H": False}
    rec = step_day(state, _inputs(weights, {n: 0.01 for n in ASSETS}, held, 0.40), ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
    assert rec["groups"] == [["S1/BTC/6H", "S2/BTC/4H"], ["S1/ETH/6H", "S2/ETH/4H"]]
    btc, eth = "S1/BTC/6H+S2/BTC/4H", "S1/ETH/6H+S2/ETH/4H"
    assert rec["invested_before_cap"][btc] == pytest.approx(0.65) and rec["group_multipliers"][btc] == pytest.approx(0.5 / 0.65)
    assert rec["invested_before_cap"][eth] == pytest.approx(0.20) and rec["group_multipliers"][eth] == 1.0
    assert rec["final_weights"]["S2/ETH/4H"] == pytest.approx(0.15)  # a flat sleeve keeps its share; it is not invested
    assert rec["invested_share"] == pytest.approx(0.5 + 0.20)


def test_the_vol_target_already_below_the_cap_leaves_the_book_alone():
    rec = step_day(AllocatorState(), _inputs(EQUAL, {n: 0.01 for n in ASSETS}, ALL_LONG, 0.9, scale=0.3), ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
    assert rec["brakes"] == [] and rec["portfolio_return"] == pytest.approx(rec["reference_v1"]["return"])


def test_an_unknown_correlation_counts_as_correlated():
    assert asset_groups(["BTC-USDT", "ETH-USDT"], {("BTC-USDT", "ETH-USDT"): None}, 0.7) == [["BTC-USDT", "ETH-USDT"]]
    assert asset_groups(["BTC-USDT", "ETH-USDT"], {("BTC-USDT", "ETH-USDT"): float("nan")}, 0.7) == [["BTC-USDT", "ETH-USDT"]]
    assert asset_groups(["BTC-USDT", "ETH-USDT"], {("ETH-USDT", "BTC-USDT"): 0.69}, 0.7) == [["BTC-USDT"], ["ETH-USDT"]]
    assert asset_groups(["BTC-USDT", "ETH-USDT"], {("BTC-USDT", "ETH-USDT"): 0.70}, 0.7) == [["BTC-USDT", "ETH-USDT"]]
    three = asset_groups(["A", "B", "C"], {("A", "B"): 0.9, ("A", "C"): 0.1, ("B", "C"): 0.8}, 0.7)
    assert three == [["A", "B", "C"]]  # linked through B
    assert sleeve_groups({"x": "A", "y": "A", "z": "C"}, {("A", "C"): 0.0}, 0.7) == [["x", "y"], ["z"]]


def _days(state, cfg, returns_per_day, held=ALL_LONG, rho=0.9, scale=1.0):
    return [step_day(state, _inputs(EQUAL, {n: r for n in ASSETS}, held, rho, scale=scale), ASSETS, cfg, LADDER) for r in returns_per_day]


def test_a_bad_week_sends_the_book_to_cash_for_the_cooldown_then_it_re_arms():
    cfg = AllocatorV2Config(group_cap=None)  # the loss limit alone
    state = AllocatorState()
    recs = _days(state, cfg, [0.01, -0.03, -0.025])  # 1.01 * 0.97 * 0.975 - 1 = -4.48 %: not yet
    assert not any(r["loss_limit_tripped"] for r in recs)
    recs += _days(state, cfg, [-0.01])  # -5.4 % over the window: trips at this close
    assert recs[-1]["loss_limit_tripped"] and recs[-1]["cooldown_days_left"] == 7 and recs[-1]["loss_window_return"] <= -0.05
    eq = state.equity
    cool = _days(state, cfg, [0.05] * 7)  # seven days in cash: the sleeves' gains do not reach the book
    assert all(r["loss_multiplier"] == 0.0 and r["portfolio_return"] == 0.0 and "cooldown" in r["brakes"] for r in cool)
    assert [r["cooldown_days_left"] for r in cool] == [6, 5, 4, 3, 2, 1, 0] and state.equity == eq
    assert state.loss_window == [eq]  # re-armed with a fresh window: the old loss cannot trip it again
    back = _days(state, cfg, [-0.02])
    assert back[0]["loss_multiplier"] == 1.0 and back[0]["portfolio_return"] == pytest.approx(-0.02) and not back[0]["loss_limit_tripped"]
    assert state.trips == 1 and back[0]["reference_v1"]["equity_index"] > state.equity


def test_the_loss_window_is_seven_days_and_an_exact_limit_trips():
    cfg = AllocatorV2Config(group_cap=None)
    state = AllocatorState()
    _days(state, cfg, [-0.01] * 4 + [0.0] * 3)  # 7 days: -3.94 %
    assert len(state.loss_window) == 8 and state.cooldown_left == 0
    _days(state, cfg, [0.0] * 4)  # the four losing days leave the window
    assert state.loss_window[0] == pytest.approx(state.equity)
    exact = AllocatorState()
    rec = _days(exact, cfg, [-0.05])
    assert rec[0]["loss_limit_tripped"]


def test_the_ladder_acts_on_v2s_own_equity():
    cfg = AllocatorV2Config(group_cap=None, loss_limit=None)
    state = AllocatorState()
    recs = _days(state, cfg, [-0.04, -0.04])  # 7.84 % below the peak: half size from the next day
    assert recs[-1]["ladder_level_after"] == 1 and recs[-1]["ladder_changed"]
    nxt = _days(state, cfg, [0.01])
    assert nxt[0]["ladder_multiplier"] == 0.5 and nxt[0]["portfolio_return"] == pytest.approx(0.005) and "ladder half" in nxt[0]["brakes"]


def test_sizing_never_reads_the_day_it_sizes_and_later_days_change_nothing_before_them():
    daily, held, coins = _market(seed=11)
    run = allocate_v2(daily, held, coins, ASSETS, ladder=LADDER)
    cut = daily.index[300]
    short = allocate_v2(daily.loc[:cut], held.loc[:cut], coins.loc[:cut], ASSETS, ladder=LADDER)
    np.testing.assert_allclose(short.returns.to_numpy(), run.returns.loc[:cut].to_numpy(), rtol=0, atol=1e-15)
    # Rewrite day `cut` (returns, its close position, coin moves): the weights used ON that day do not move.
    d2, h2, c2 = daily.copy(), held.copy(), coins.copy()
    d2.loc[cut] = d2.loc[cut] * -5.0
    h2.loc[cut] = ~h2.loc[cut]
    c2.loc[cut] = c2.loc[cut] * -3.0
    other = allocate_v2(d2, h2, c2, ASSETS, ladder=LADDER)
    k = list(run.days).index(cut)
    assert other.records[k]["final_weights"] == run.records[k]["final_weights"]
    assert other.records[k]["groups"] == run.records[k]["groups"]


def test_brakes_only_lower_exposure():
    daily, held, coins = _market(seed=13, n=600)
    run = allocate_v2(daily, held, coins, ASSETS, ladder=LADDER)
    weights, scale = base_sizing(daily, target_vol=0.15, vol_lookback_days=30, weight_lookback_days=60)
    for d, rec in zip(run.days, run.records):
        for n, e in rec["final_weights"].items():
            assert 0.0 <= e <= weights.loc[d, n] * scale.loc[d] + 1e-15
        assert sum(rec["final_weights"].values()) <= 1.0 + 1e-12
        for g, mult in rec["group_multipliers"].items():
            assert 0.0 < mult <= 1.0
            invested = sum(rec["final_weights"][n] for n in g.split("+") if rec["positions_previous_close"][n])
            assert invested <= DEFAULT_ALLOCATOR_V2.group_cap + 1e-12
    stats = brake_stats(run)
    assert 0.0 < stats["correlation_cap_days_share"] < 1.0 and stats["invested_share_max"] <= 0.5 + 1e-12
    assert stats["invested_share_max_reference"] > 0.5 and stats["reference_above_cap_days_share"] > 0.0
    assert stats["reweighting_cost_per_year"] == pytest.approx(stats["reweighting_turnover_per_year"] * 0.0015)
    # A bet at a day's CLOSE (after the day's own entries) can stand above the cap: the cap is checked on the previous close.
    close_bets = [max(sum(r["final_weights"][n] for n in g if nxt["positions_previous_close"][n]) for g in r["groups"])
                  for r, nxt in zip(run.records[:-1], run.records[1:])]
    assert stats["bet_above_cap_at_close_days"] == sum(1 for b in close_bets if b > 0.5 + 1e-12) > 0
    assert stats["bet_at_close_max"] == pytest.approx(max(close_bets))
    # v2 is not always smaller than v1: its ladder follows its own equity.
    assert stats["ladder_v2_above_v1_days"] == sum(1 for r in run.records if r["ladder_multiplier"] > r["reference_v1"]["ladder_multiplier"])
    assert stats["reference_bet_max"] <= stats["invested_share_max_reference"] + 1e-12


def test_state_round_trips_through_json_and_continues_identically():
    daily, held, coins = _market(seed=17, n=200)
    weights, scale = base_sizing(daily, target_vol=0.15, vol_lookback_days=30, weight_lookback_days=60)
    corr = trailing_correlations(coins, 60, 20)
    prev = previous_close_positions(held, daily.index)
    a, b = AllocatorState(), AllocatorState()
    for k, d in enumerate(daily.index):
        inputs = DayInputs(returns=daily.loc[d].to_dict(), weights=weights.loc[d].to_dict(), vol_scale=float(scale.loc[d]),
                           positions=prev.loc[d].to_dict(), correlations={p: (None if pd.isna(s.loc[d]) else float(s.loc[d])) for p, s in corr.items()})
        ra = step_day(a, inputs, ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
        b = AllocatorState.from_dict(json.loads(json.dumps(b.to_dict())))
        rb = step_day(b, inputs, ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
        assert ra == rb, k
    assert a == b


def test_inputs_helpers():
    idx = pd.date_range("2026-01-01", periods=6, freq="D", tz="UTC")
    closes = pd.DataFrame({"BTC-USDT": [100, 101, np.nan, 103, 104, 105.0]}, index=idx)
    rets = daily_closes_to_returns(closes)
    assert np.isnan(rets.iloc[2, 0]) and np.isnan(rets.iloc[3, 0]) and rets.iloc[1, 0] == pytest.approx(0.01)  # no return across a gap
    pos = pd.DataFrame({"a": [True, False, True]}, index=idx[[0, 1, 3]])
    prev = previous_close_positions(pos, idx)
    assert prev["a"].tolist() == [False, True, False, False, True, True]  # day 2 has no record: day 1's close carries
    two = pd.DataFrame({"A": np.arange(30.0) % 7, "B": (np.arange(30.0) % 7) * 2}, index=pd.date_range("2026-01-01", periods=30, freq="D", tz="UTC"))
    rho = trailing_correlations(two, 10, 5)[("A", "B")]
    assert np.isnan(rho.iloc[4]) and rho.iloc[5] == pytest.approx(1.0)  # five days known before day 5, used from day 5 on


def test_config_validation_and_label():
    assert DEFAULT_ALLOCATOR_V2.group_cap == 0.50 and DEFAULT_ALLOCATOR_V2.loss_limit == 0.05 and DEFAULT_ALLOCATOR_V2.cooldown_days == 7
    assert DEFAULT_ALLOCATOR_V2.corr_threshold == 0.70 and DEFAULT_ALLOCATOR_V2.corr_lookback_days == 60
    assert "correlation cap 50%" in DEFAULT_ALLOCATOR_V2.label and "weekly loss limit 5%" in DEFAULT_ALLOCATOR_V2.label
    assert OFF.label == "no brakes (allocator v1)"
    assert AllocatorV2Config.from_dict(DEFAULT_ALLOCATOR_V2.to_dict()) == DEFAULT_ALLOCATOR_V2
    for bad in ({"group_cap": 0.0}, {"group_cap": 1.5}, {"loss_limit": 1.0}, {"cooldown_days": 0}, {"corr_threshold": 0.0},
                {"corr_min_days": 70}, {"loss_window_days": 0}):
        with pytest.raises(ValueError):
            AllocatorV2Config(**bad)
    with pytest.raises(ValueError, match="different sleeves"):
        step_day(AllocatorState(), _inputs({"x": 1.0}, {}, {}, 0.9), ASSETS, DEFAULT_ALLOCATOR_V2, LADDER)
