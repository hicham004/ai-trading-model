"""Candidates S0–S5 + baseline: shapes, no look-ahead, filters, adapter into the Strategy contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.strategy.base import MarketCandle, SignalAction
from research.calibration import StrengthCalibrator
from research.data import frame_from_candles, to_market_candles
from research.strategies import CANDIDATES, get_candidate
from research.strategies.adapters import ResearchStrategyAdapter
from research.strategies.base import FeatureContext, days_to_bars, state_from_events
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask
from research.strategies.s5_positioning import PositioningFiltered, positioning_coverage, positioning_mask
from research.sweep import param_grid

PPY = 8766.0


def synthetic(n: int = 3000, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    volume = rng.lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


@pytest.fixture(scope="module")
def df():
    return synthetic()


@pytest.fixture(scope="module")
def ctx():
    return FeatureContext(timeframe="1H", periods_per_year=PPY)


@pytest.mark.parametrize("key", sorted(CANDIDATES))
def test_every_candidate_builds_a_valid_frame(df, ctx, key):
    cand = get_candidate(key)
    frame = cand.build(df, cand.default_params, ctx)
    assert len(frame.desired) == len(df) and frame.desired.dtype == bool
    assert len(frame.stop_distance) == len(df) and len(frame.strength) == len(df)
    assert frame.desired.sum() > 0, f"{key} never wants to be long on the synthetic series"
    assert (frame.stop_distance.dropna() > 0).all()
    # strength is only defined where there is a signal
    assert frame.strength.notna().sum() <= len(df)
    assert len(param_grid(cand.grid, base=cand.default_params)) >= 4


@pytest.mark.parametrize("key", sorted(CANDIDATES))
def test_no_look_ahead(df, ctx, key):
    cand = get_candidate(key)
    cut = 2000
    base = cand.build(df.iloc[:cut], cand.default_params, ctx)
    perturbed = df.copy()
    perturbed.iloc[cut:, :4] *= 1.5  # change the future only
    perturbed.iloc[cut:, 4] *= 3.0
    full = cand.build(perturbed, cand.default_params, ctx)
    pd.testing.assert_series_equal(base.desired, full.desired.iloc[:cut], check_names=False)
    pd.testing.assert_series_equal(base.stop_distance, full.stop_distance.iloc[:cut], check_names=False)
    pd.testing.assert_series_equal(base.strength, full.strength.iloc[:cut], check_names=False)


def test_state_from_events_and_days_to_bars():
    idx = pd.RangeIndex(5)
    entries = pd.Series([True, False, False, True, False], index=idx)
    exits = pd.Series([False, False, True, True, False], index=idx)
    assert list(state_from_events(entries, exits)) == [True, True, False, False, False]  # tie -> exit wins
    assert days_to_bars(1, "1H") == 24 and days_to_bars(1, "4H") == 6 and days_to_bars(1, "1D") == 1
    assert days_to_bars(0.01, "1D") == 1


def test_no_trade_filter_blocks_gaps_spikes_and_event_windows(df):
    broken = df.drop(df.index[1000:1010])  # a 10-bar hole
    ok = tradeable_mask(broken, "1H", PPY, NoTradeConfig(cooldown_bars=3))
    after_gap = broken.index.get_loc(df.index[1010])
    assert not ok.iloc[after_gap] and not ok.iloc[after_gap + 2] and ok.iloc[after_gap + 3]
    window = (df.index[500], df.index[520])
    ok2 = tradeable_mask(df, "1H", PPY, NoTradeConfig(event_windows=(window,)))
    assert not ok2.iloc[500:521].any() and ok2.iloc[521]
    spiky = df.copy()
    spiky.iloc[1500, spiky.columns.get_loc("high")] *= 1.3  # enormous bar range
    ok3 = tradeable_mask(spiky, "1H", PPY)
    assert not ok3.iloc[1500]


def test_positioning_filter_uses_only_past_values_and_keeps_open_positions(df):
    idx = df.index
    funding = pd.Series(0.0001, index=idx[::8])
    funding.iloc[200:205] = 0.01  # crowded longs for 5 settlements
    ctx = FeatureContext("1H", PPY, funding=funding.to_frame("funding_rate"))
    mask = positioning_mask(df, {"funding_z_max": 2.0, "funding_z_window": 90}, ctx)
    blocked = ~mask
    assert blocked.sum() > 0
    first_blocked = blocked[blocked].index[0]
    assert first_blocked >= funding.index[200]
    assert 0.9 < positioning_coverage(df, ctx) <= 1.0
    assert positioning_coverage(df, FeatureContext("1H", PPY)) == 0.0

    cand = PositioningFiltered(get_candidate("S1"))
    plain = get_candidate("S1").build(df, cand.default_params, ctx)
    filtered = cand.build(df, cand.default_params, ctx)
    assert filtered.desired.sum() <= plain.desired.sum()
    assert not (filtered.desired & ~plain.desired).any()  # filter never adds longs
    assert cand.key == "S1+S5" and "funding_z_max" in cand.grid


def test_adapter_produces_contract_signals(df, ctx):
    candles = to_market_candles(df.iloc[:800], "BTC-USDT", "1H")
    adapter = ResearchStrategyAdapter(get_candidate("S1"), {}, ctx, fallback_confidence=0.6)
    signals = adapter.generate_signals(candles)
    assert len(signals) == len(candles)
    longs = [s for s in signals if s.action == SignalAction.LONG]
    assert longs and all(s.stop_loss is not None and s.stop_loss < c.close for s, c in zip(signals, candles) if s.action == SignalAction.LONG)
    assert all(s.confidence == 0.6 for s in longs)
    assert all(s.timeframe == "1H" for s in signals)
    assert adapter.name == "research_S1"
    assert adapter.generate_signals([]) == []
    calibrator = StrengthCalibrator(min_samples=1).fit([0.1, 0.5, 0.9, 1.3], [False, True, True, True])
    calibrated = ResearchStrategyAdapter(get_candidate("S1"), {}, ctx, calibrator=calibrator).generate_signals(candles)
    assert all(0.0 <= s.confidence <= 1.0 for s in calibrated)
    frame = frame_from_candles(candles)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"] and len(frame) == 800


def test_unknown_candidate_rejected():
    with pytest.raises(ValueError):
        get_candidate("S9")
