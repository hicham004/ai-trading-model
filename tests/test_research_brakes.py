"""Plan row R18: the Trader Policy brakes act on new entries only, with the pre-registered numbers, and count what they do."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from research.brakes import (
    BRAKE_NAMES,
    BRAKES_OFF,
    TRADER_BRAKES,
    TURTLE_LADDER_ONLY,
    BarCalendar,
    BrakeSpec,
    EntryBrakes,
    TurtleLadder,
    heat_groups,
    heat_multipliers,
    merge_summaries,
    summary_for_column,
    trailing_return_correlations,
)
from research.engine import Costs, run_vectorized
from tests.test_research_engine import ohlc

ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)


def _times(n: int, freq: str = "6h", start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq, tz="UTC")


def test_turtle_ladder_steps_escalate_and_restore_only_on_a_new_high():
    lad = TurtleLadder()
    assert lad.steps == ((0.10, 0.80), (0.20, 0.64)) and "turtle" in lad.label
    np.testing.assert_allclose(lad.multiplier(np.array([0.0, 0.05, 0.10, 0.15, 0.20, 0.5])), [1, 1, 0.8, 0.8, 0.64, 0.64])
    cal = BarCalendar.from_times(_times(8))
    eb = EntryBrakes(TURTLE_LADDER_ONLY, 1, 100.0, cal)
    path = [100, 95, 89, 92, 79, 85, 101, 90]  # -11 %, recovers to -8 % (stays 0.8), -21 %, recovers (stays 0.64), new high, -11 % again
    mults = []
    for i, eq in enumerate(path):
        eb.on_bar_close(i, np.array([float(eq)]))
        mults.append(float(eb.lad_mult[0]))
    assert mults == [1.0, 1.0, 0.8, 0.8, 0.64, 0.64, 1.0, 0.8]
    with pytest.raises(ValueError):
        TurtleLadder(steps=((0.2, 0.8), (0.1, 0.64)))
    with pytest.raises(ValueError):
        TurtleLadder(steps=())
    assert TurtleLadder.from_dict(lad.to_dict()) == lad


def test_brake_spec_defaults_labels_round_trip_and_validation():
    spec = TRADER_BRAKES
    assert spec.hard_stop_dd == 0.30 and spec.max_entries_per_market_per_day == 1 and spec.max_entries_per_day == 3
    assert spec.daily_loss_limit == 0.03 and spec.weekly_loss_limit == 0.06 and spec.monthly_loss_limit == 0.10 and spec.heat_cap == 0.06
    assert spec.heat_group_share == 0.5 and spec.corr_threshold == 0.70 and spec.corr_lookback_days == 60 and spec.active
    assert "hard stop -30%" in spec.label and "3%/24h" in spec.label and "heat cap 6%" in spec.label
    assert BrakeSpec.from_dict(spec.to_dict()) == spec
    assert not BRAKES_OFF.active and BRAKES_OFF.label == "no brakes" and BrakeSpec.from_dict(BRAKES_OFF.to_dict()) == BRAKES_OFF
    assert TURTLE_LADDER_ONLY.active and TURTLE_LADDER_ONLY.hard_stop_dd is None and TURTLE_LADDER_ONLY.ladder == TurtleLadder()
    for bad in ({"hard_stop_dd": 1.5}, {"daily_loss_limit": 0.0}, {"max_entries_per_day": 0}, {"heat_group_share": 0.0}, {"corr_lookback_days": 1}):
        with pytest.raises(ValueError):
            dataclasses.replace(spec, **bad)


def test_bar_calendar_days_monday_weeks_months_and_bars_per_day():
    times = pd.DatetimeIndex(["2024-01-07 18:00", "2024-01-08 00:00", "2024-01-08 06:00", "2024-02-01 00:00"], tz="UTC")  # Sunday, Monday, ...
    cal = BarCalendar.from_times(times)
    assert list(cal.day) == [19729, 19730, 19730, 19754]
    assert cal.week[0] != cal.week[1] and cal.week[1] == cal.week[2]  # the week turns at Monday 00:00 UTC
    assert cal.month[0] == cal.month[1] == 2024 * 12 and cal.month[3] == 2024 * 12 + 1
    assert BarCalendar.from_times(_times(50, "6h")).bars_per_day == 4 and BarCalendar.from_times(_times(50, "4h")).bars_per_day == 6
    assert BarCalendar.from_times(_times(50, "1h")).bars_per_day == 24 and BarCalendar.from_times(_times(50, "1D")).bars_per_day == 1
    with pytest.raises(ValueError):
        BarCalendar.from_times([])
    # Stored Parquet candles come back with microsecond timestamps (resampled bars with nanoseconds): the calendar must not depend on the unit.
    ns_idx = _times(60, "4h")
    us_idx = ns_idx.as_unit("us")
    a, b = BarCalendar.from_times(ns_idx.values), BarCalendar.from_times(us_idx.values)
    assert us_idx.values.dtype == "datetime64[us]" and ns_idx.values.dtype == "datetime64[ns]"
    np.testing.assert_array_equal(a.day, b.day)
    np.testing.assert_array_equal(a.week, b.week)
    assert a.bars_per_day == b.bars_per_day == 6 and len(set(b.day.tolist())) == 10
    c = BarCalendar.from_times(us_idx)  # a tz-aware index in microseconds, not just its values
    np.testing.assert_array_equal(a.day, c.day)


def _flat_series(n: int, price: float = 100.0):
    return ohlc([price] * n)


def test_entry_caps_block_a_second_entry_in_a_day_and_the_bar_after_an_exit():
    # Six 4H bars a day; the rule wants to be long every bar, the stop is hit on bar 2, so the base engine re-enters on bar 3.
    n = 12
    o, h, l, c = ohlc([100] * n, lows=[99] * 2 + [90] + [99] * (n - 3))
    desired = np.ones(n, dtype=bool)
    stops = np.full(n, 5.0)
    times = _times(n, "4h")
    base = run_vectorized(o, h, l, c, desired, stops, costs=ZERO)
    assert list(base.trades["entry_i"]) == [1, 3] and base.trades.loc[0, "exit_reason"] == "stop_loss"
    only_after_exit = dataclasses.replace(BRAKES_OFF, no_entry_bar_after_exit=True)
    res = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, brakes=only_after_exit, bar_times=times.values)
    assert list(res.trades["entry_i"]) == [1, 4]  # bar 3 (the bar after the exit) is skipped
    assert res.brakes["counts"]["entry_after_exit"][0] == 1 and res.brakes["counts"]["entry_cap_market_day"][0] == 0
    per_day = dataclasses.replace(BRAKES_OFF, max_entries_per_market_per_day=1)
    res2 = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, brakes=per_day, bar_times=times.values)
    assert list(res2.trades["entry_i"]) == [1, 6]  # the day (bars 0-5) already had its entry; the next day opens at bar 6
    assert res2.brakes["counts"]["entry_cap_market_day"][0] == 3 and res2.brakes["opportunities"][0] == 5
    assert set(res2.brakes["counts"]) == set(BRAKE_NAMES)


def test_turtle_ladder_scales_entries_only_and_never_touches_an_open_position():
    # A losing trade takes the account 12 % down; the next entry is sized at 0.8; the open position is never reduced.
    closes = [100, 100, 100, 88, 88, 88, 88, 88]
    o, h, l, c = ohlc(closes, highs=[x + 0.5 for x in closes], lows=[x - 0.5 for x in closes], closes=closes)
    desired = np.array([True, True, True, False, True, True, True, True])
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=TURTLE_LADDER_ONLY, bar_times=_times(len(closes)).values)
    t = res.trades
    assert list(t["entry_i"]) == [1, 5] and t.loc[0, "exit_reason"] == "signal" and t.loc[0, "reductions"] == 0
    assert t.loc[0, "size_fraction"] == 1.0 and t.loc[1, "size_fraction"] == pytest.approx(0.8)
    assert res.brakes["counts"]["ladder"][0] == 1 and res.brakes["entries_at"]["x0.8"][0] == 1
    # The Reference ladder, by contrast, would have reduced the open position (the known Sprint 2b behaviour).
    assert all(t["reductions"] == 0)


def test_hard_stop_blocks_new_entries_after_a_30_percent_drawdown_until_the_simulation_restarts():
    closes = [100, 100, 100, 65, 65, 65, 65, 65, 65]
    o, h, l, c = ohlc(closes, highs=[x + 0.5 for x in closes], lows=[x - 0.5 for x in closes], closes=closes)
    desired = np.array([True, True, True, False, True, True, True, True, True])
    spec = dataclasses.replace(BRAKES_OFF, hard_stop_dd=0.30)
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=spec, bar_times=_times(len(closes)).values)
    assert len(res.trades) == 1 and res.trades.loc[0, "exit_reason"] == "signal"  # no re-entry: halted after the -35 %
    assert res.brakes["trips"]["hard_stop"][0] == 1 and res.brakes["counts"]["hard_stop"][0] == 4
    # A fresh simulation (the next walk-forward window) starts un-halted.
    again = run_vectorized(o[4:], h[4:], l[4:], c[4:], desired[4:], None, costs=ZERO, brakes=spec, bar_times=_times(5).values)
    assert len(again.trades) == 1


def test_loss_limits_block_entries_for_their_period_and_are_counted():
    # 4H bars (6 a day). A 4 % loss in one day trips the daily limit: entries are blocked for the next 24 hours (6 bars).
    n = 30
    closes = [100] * 6 + [96] + [96] * (n - 7)
    o, h, l, c = ohlc(closes, highs=[x + 0.1 for x in closes], lows=[x - 0.1 for x in closes], closes=closes)
    desired = np.array([True] * 6 + [False] + [True] * (n - 7))
    daily = dataclasses.replace(BRAKES_OFF, daily_loss_limit=0.03)
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=daily, bar_times=_times(n, "4h").values)
    t = res.trades
    assert t.loc[0, "exit_i"] == 7 and t.loc[0, "exit_reason"] == "signal"
    # The loss is seen at the close of bar 6 (equity 96 vs 100 six bars earlier): bars 7..12 are blocked, bar 13 may enter.
    assert t.loc[1, "entry_i"] == 13 and res.brakes["trips"]["daily_loss"][0] >= 1 and res.brakes["counts"]["daily_loss"][0] >= 1
    # Weekly: a 7 % loss on Tuesday blocks entries until next Monday 00:00 UTC.
    times = pd.date_range("2024-01-01", periods=60, freq="6h", tz="UTC")  # Monday 00:00 start
    closes = [100] * 6 + [93] * 54
    o, h, l, c = ohlc(closes, highs=[x + 0.1 for x in closes], lows=[x - 0.1 for x in closes], closes=closes)
    desired = np.array([True] * 6 + [False] + [True] * 53)
    weekly = dataclasses.replace(BRAKES_OFF, weekly_loss_limit=0.06)
    res_w = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=weekly, bar_times=times.values)
    assert res_w.trades.loc[1, "entry_i"] == 28  # the bar that opens Monday 2024-01-08 00:00 UTC may enter again
    assert res_w.brakes["trips"]["weekly_loss"][0] == 1
    monthly = dataclasses.replace(BRAKES_OFF, monthly_loss_limit=0.10)
    closes = [100] * 6 + [89] * 54
    o, h, l, c = ohlc(closes, highs=[x + 0.1 for x in closes], lows=[x - 0.1 for x in closes], closes=closes)
    res_m = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=monthly, bar_times=times.values)
    assert len(res_m.trades) == 1 and res_m.brakes["trips"]["monthly_loss"][0] == 1  # January never re-arms within 15 days
    times_feb = pd.date_range("2024-01-29", periods=60, freq="6h", tz="UTC")
    res_m2 = run_vectorized(o, h, l, c, desired, None, costs=ZERO, brakes=monthly, bar_times=times_feb.values)
    assert res_m2.trades.loc[1, "entry_i"] == 12  # the bar that opens 2024-02-01 00:00 UTC: the new month re-arms


def test_heat_cap_on_one_sleeve_scales_an_oversized_entry_and_the_book_functions_share_the_cut():
    o, h, l, c = ohlc([100] * 6)
    desired = np.ones(6, dtype=bool)
    stops = np.full(6, 20.0)  # a 20 % stop at full size = 20 % of equity at risk
    spec = dataclasses.replace(BRAKES_OFF, heat_cap=0.06)
    res = run_vectorized(o, h, l, c, desired, stops, costs=ZERO, brakes=spec, bar_times=_times(6).values)
    assert res.trades.loc[0, "size_fraction"] == pytest.approx(0.30) and res.trades.loc[0, "risk_pct"] == pytest.approx(0.06)
    assert res.brakes["counts"]["heat_cap"][0] == 1
    # Book level: every position in a correlated group is cut by the same factor, then the whole book if still above the cap.
    groups = heat_groups({"S1/BTC": "BTC", "S1/ETH": "ETH", "S1/SOL": "SOL"}, {("BTC", "ETH"): 0.8, ("BTC", "SOL"): 0.5, ("ETH", "SOL"): 0.4}, 0.7)
    assert groups == [["S1/BTC", "S1/ETH"], ["S1/SOL"]]
    m = heat_multipliers({"S1/BTC": 0.02, "S1/ETH": 0.02, "S1/SOL": 0.02}, groups, cap=0.06, group_share=0.5)
    assert m["S1/BTC"] == pytest.approx(0.75) and m["S1/ETH"] == pytest.approx(0.75) and m["S1/SOL"] == pytest.approx(1.0)
    m2 = heat_multipliers({"a": 0.05, "b": 0.05}, [["a"], ["b"]], cap=0.06, group_share=0.5)
    assert m2["a"] == pytest.approx(0.6) and m2["b"] == pytest.approx(0.6)  # 3 % each: the groups' halves, total exactly the cap
    assert heat_multipliers({"a": 0.01}, [["a"]], cap=0.06) == {"a": 1.0}
    with pytest.raises(ValueError):
        heat_multipliers({"a": 0.01}, [["a"]], cap=1.5)
    closes = pd.DataFrame({"BTC": np.linspace(100, 120, 80), "ETH": np.linspace(50, 61, 80)}, index=pd.date_range("2024-01-01", periods=80, freq="D", tz="UTC"))
    corr = trailing_return_correlations(closes, 60, 20)
    assert ("BTC", "ETH") in corr and np.isnan(corr[("BTC", "ETH")].iloc[20]) and corr[("BTC", "ETH")].iloc[-1] == pytest.approx(1.0, abs=1e-4)


def test_brakes_need_bar_times_and_summaries_merge_per_column():
    o, h, l, c = ohlc([100] * 5)
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, np.ones(5, dtype=bool), None, costs=ZERO, brakes=TRADER_BRAKES)
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, np.ones(5, dtype=bool), None, costs=ZERO, brakes=TRADER_BRAKES, bar_times=_times(4).values)
    res = run_vectorized(o, h, l, c, np.ones((5, 2), dtype=bool), None, costs=ZERO, brakes=TRADER_BRAKES, bar_times=_times(5).values)
    one = summary_for_column(res.brakes, 1)
    assert one["opportunities"] == 1 and one["counts"]["ladder"] == 0 and one["bars"] == 5
    merged = merge_summaries([one, one, {}])
    assert merged["opportunities"] == 2 and merged["bars"] == 10 and merged["counts"]["ladder"] == 0 and merged["spec"] == TRADER_BRAKES.to_dict()
    assert merge_summaries([]) == {}
    # No brakes at all: the result carries none.
    assert run_vectorized(o, h, l, c, np.ones(5, dtype=bool), None, costs=ZERO, brakes=BRAKES_OFF, bar_times=_times(5).values).brakes is None
