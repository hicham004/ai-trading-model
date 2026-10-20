"""Lower-turnover variants, hysteresis bands, the S5 re-test grid and the scheduled-event S0 windows."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.events import FOMC_DECISION_DAYS, EventWindow, fomc_windows, in_event_window, load_event_windows, windows_as_tuples
from research.strategies import CANDIDATES, S5_RETEST_VARIANTS, TURNOVER_VARIANTS, get_candidate
from research.strategies.base import FeatureContext
from research.strategies.s0_filters import NoTradeConfig, all_event_windows, blocked_share, tradeable_mask
from research.strategies.turnover import daily_close_bars, weekly_decision_bars
from tests.test_research_strategies import synthetic

PPY = 8766.0


def test_variant_registry_is_consistent():
    for variant, base in {**TURNOVER_VARIANTS, **S5_RETEST_VARIANTS}.items():
        assert variant in CANDIDATES and base in CANDIDATES
        assert get_candidate(variant).key == variant
    assert get_candidate("S1").default_params["entry_band"] == 0.0  # S1 itself is untouched


def test_weekly_and_daily_clocks():
    idx = pd.date_range("2024-01-01", periods=24 * 14, freq="h", tz="UTC")  # starts on a Monday
    weekly = weekly_decision_bars(idx)
    assert weekly.iloc[0] and weekly.sum() == 2 and weekly.iloc[24 * 7]
    daily_4h = daily_close_bars(pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC"), "4H")
    assert daily_4h.tolist() == [False] * 5 + [True] + [False] * 5 + [True]
    assert daily_close_bars(pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"), "1D").all()


def test_weekly_clock_holds_state_between_decision_bars():
    df = synthetic(2000, seed=2)
    ctx = FeatureContext("1H", PPY)
    base = get_candidate("S1").build(df, get_candidate("S1").default_params, ctx)
    weekly = get_candidate("S1w").build(df, get_candidate("S1w").default_params, ctx)
    decide = weekly_decision_bars(df.index)
    # On decision bars the weekly state equals the base state; in between it is constant.
    assert (weekly.desired[decide] == base.desired[decide]).all()
    changes = (weekly.desired != weekly.desired.shift(1)).fillna(False)
    assert changes[~decide].sum() == 0
    assert (weekly.desired != weekly.desired.shift(1)).sum() <= (base.desired != base.desired.shift(1)).sum()


def test_daily_entry_clock_blocks_entries_but_not_exits():
    df = synthetic(2000, seed=4)
    ctx = FeatureContext("4H", 2191.5)
    df4 = df.iloc[::4].copy()
    base = get_candidate("S2").build(df4, get_candidate("S2").default_params, ctx)
    daily = get_candidate("S2d").build(df4, get_candidate("S2d").default_params, ctx)
    ok = daily_close_bars(df4.index, "4H")
    entries = daily.desired & ~daily.desired.shift(1).fillna(False).astype(bool)
    assert ok[entries].all()  # every entry happens on a daily-close bar
    assert (daily.desired & ~base.desired).sum() == 0  # never long when the base is not
    exits_base = (~base.desired) & base.desired.shift(1).fillna(False).astype(bool)
    assert (daily.desired[exits_base]).sum() == 0  # base exits are honoured on any bar


def test_hysteresis_reduces_flips_and_defaults_match_s1():
    df = synthetic(3000, seed=5)
    ctx = FeatureContext("1H", PPY)
    s1 = get_candidate("S1")
    plain = s1.build(df, s1.default_params, ctx)
    zero_band = s1.build(df, dict(s1.default_params, entry_band=0.0, exit_band=0.0), ctx)
    pd.testing.assert_series_equal(plain.desired, zero_band.desired)
    s1h = get_candidate("S1h")
    banded = s1h.build(df, dict(s1h.default_params, entry_band=0.5, exit_band=0.5), ctx)
    flips = lambda s: int((s != s.shift(1)).fillna(False).sum())  # noqa: E731
    assert flips(banded.desired) < flips(plain.desired)
    assert "entry_band" in s1h.grid and s1h.key == "S1h"


def test_s5_retest_variant_has_short_windows():
    cand = get_candidate("S1+S5s")
    assert cand.grid["funding_z_window"] == [21, 42] and cand.grid["oi_change_window_days"] == [1, 3]
    df = synthetic(1500, seed=6)
    ctx = FeatureContext("1H", PPY)
    idx = df.index
    ctx.funding = pd.DataFrame({"funding_rate": np.where(np.arange(len(idx)) % 50 < 5, 0.01, 0.0001)}, index=idx)
    ctx.open_interest = pd.DataFrame({"oi_usd": np.linspace(1e9, 1.2e9, len(idx))}, index=idx)
    frame = cand.build(df, dict(cand.default_params, funding_z_window=21, funding_z_max=2.0, oi_change_window_days=3), ctx)
    base = get_candidate("S1").build(df, get_candidate("S1").default_params, ctx)
    assert (frame.desired & ~base.desired).sum() == 0


def test_fomc_calendar_mechanics():
    assert len(FOMC_DECISION_DAYS) == len(set(FOMC_DECISION_DAYS)) and all(len(d) == 10 for d in FOMC_DECISION_DAYS)
    windows = fomc_windows(before_hours=6, after_hours=6)
    assert len(windows) == len(FOMC_DECISION_DAYS)
    w = next(x for x in windows if x.label == "FOMC 2022-06-15")
    assert w.start == pd.Timestamp("2022-06-15 12:00", tz="UTC") and w.end == pd.Timestamp("2022-06-16 00:00", tz="UTC")
    idx = pd.date_range("2022-06-14", periods=24, freq="4h", tz="UTC")
    mask = in_event_window(idx, windows)
    assert mask.sum() == 4 and mask[pd.Timestamp("2022-06-15 16:00", tz="UTC")] and not mask[pd.Timestamp("2022-06-14 16:00", tz="UTC")]
    with pytest.raises(ValueError):
        fomc_windows(before_hours=-1)


def test_scheduled_events_block_entries_in_s0(tmp_path):
    idx = pd.date_range("2022-06-13", periods=36, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    off = NoTradeConfig(scheduled_events=False, cooldown_bars=0)
    on = NoTradeConfig(scheduled_events=True, cooldown_bars=0)
    assert tradeable_mask(df, "4H", 2191.5, off).all()
    blocked = ~tradeable_mask(df, "4H", 2191.5, on)
    assert blocked.sum() == 4 and blocked[pd.Timestamp("2022-06-15 16:00", tz="UTC")]
    assert "FOMC" in on.label and "FOMC" not in off.label
    assert blocked_share(df, "4H", 2191.5, on) == pytest.approx(4 / 36)
    assert len(all_event_windows(on)) == len(FOMC_DECISION_DAYS) and all_event_windows(off) == ()
    # Operator JSON calendar.
    path = tmp_path / "events.json"
    path.write_text('[{"start": "2022-06-13T04:00:00Z", "end": "2022-06-13T08:00:00Z", "label": "CPI"}]', encoding="utf-8")
    loaded = load_event_windows(path)
    assert loaded == [EventWindow(pd.Timestamp("2022-06-13 04:00", tz="UTC"), pd.Timestamp("2022-06-13 08:00", tz="UTC"), "CPI")]
    custom = NoTradeConfig(event_windows=windows_as_tuples(loaded), cooldown_bars=0)
    assert (~tradeable_mask(df, "4H", 2191.5, custom)).sum() == 2
    path.write_text('[{"start": "2022-06-13T08:00:00Z", "end": "2022-06-13T04:00:00Z"}]', encoding="utf-8")
    with pytest.raises(ValueError):
        load_event_windows(path)
