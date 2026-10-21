"""Paper-fleet decisions through the Strategy contract equal the research frames (S0, S5, brackets, regime gate, sizing)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.data import bars_per_year
from research.engine import Costs
from research.gated_walkforward import gate_desired_matrix
from research.regime_v2 import RegimeV2Config, bear_probability, entry_gate_mask, fit_regime
from research.sizing import LadderConfig, SizingSpec, fraction_series
from research.strategies import get_candidate
from research.strategies.adapters import ResearchStrategyAdapter
from research.strategies.base import FeatureContext, days_to_bars
from research.sweep import Frames, build_frames, simulate_sizing
from research.paper_fleet.config import NO_TRADE, PURGE_DAYS, TRAIN_DAYS, SleeveSpec
from research.paper_fleet.engine import SleeveEngine
from research.paper_fleet.regime import fit_series, gate_desired
from research.paper_fleet.signals import decide_buy_and_hold, decide_sleeve, engine_config, frame_decisions
from research.data import to_market_candles

TF = "4H"
PPY = bars_per_year(TF)
POLICY = SizingSpec(kind="vol_target", target_vol=0.10, vol_lookback=30, crash_dd=0.15, crash_window_days=90.0, crash_mode="half", ladder=True)
COSTS = Costs(0.001, 0.0005)


def synthetic_4h(n: int = 1300, seed: int = 5) -> pd.DataFrame:
    """4H bars across the 2024 FOMC dates, with trends, calm spells and volume bursts."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC", name="open_time")
    drift = np.repeat(rng.normal(0.0, 0.004, n // 120 + 1), 120)[:n]
    vol = np.repeat(rng.uniform(0.008, 0.03, n // 90 + 1), 90)[:n]
    close = 50_000 * np.exp(np.cumsum(rng.normal(drift, vol)))
    open_ = np.concatenate([[50_000.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2)))
    volume = rng.lognormal(6, 0.7, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def positioning(df: pd.DataFrame, seed: int = 9) -> FeatureContext:
    rng = np.random.default_rng(seed)
    f_idx = pd.date_range(df.index[0], df.index[-1], freq="8h", tz="UTC", name="ts")
    o_idx = pd.date_range(df.index[0], df.index[-1], freq="1h", tz="UTC", name="ts")
    funding = pd.DataFrame({"funding_rate": 1e-4 + 2e-4 * rng.standard_normal(len(f_idx)).cumsum() / 30}, index=f_idx)
    oi = pd.DataFrame({"oi_usd": 1e9 * np.exp(np.cumsum(rng.normal(0, 0.02, len(o_idx))))}, index=o_idx)
    return FeatureContext(timeframe=TF, periods_per_year=PPY, funding=funding, open_interest=oi)


CASES = [
    ("S1+S5", {"lookbacks_days": (14, 30, 60), "vote": 2, "atr_window": 14, "atr_mult": 3.0, "vol_window_days": 30, "entry_band": 0.0,
               "exit_band": 0.0, "funding_z_max": 1.5, "funding_z_window": 90, "oi_change_max": 0.15, "oi_change_window_days": 1, "bracket": "none"}, "none"),
    ("S2", {"entry_days": 10, "exit_days": 5, "vol_mult": 1.0, "volume_window": 20, "atr_window": 14, "atr_mult": 2.0, "atr_pct_max": 0.9,
            "atr_pct_days": 90, "bracket": "none"}, "gate"),
    ("S2+S5s", {"entry_days": 10, "exit_days": 5, "vol_mult": 1.0, "volume_window": 20, "atr_window": 14, "atr_mult": 2.0, "atr_pct_max": 0.9,
                "atr_pct_days": 90, "funding_z_max": 2.0, "funding_z_window": 21, "oi_change_max": 0.1, "oi_change_window_days": 1, "bracket": "none"}, "gate"),
    ("S4", {"bb_window": 30, "bb_k": 2.0, "squeeze_pct": 0.2, "pct_days": 100, "squeeze_lookback": 10, "atr_window": 14, "atr_mult": 2.0,
            "bracket": "trail1"}, "none"),
    ("S4", {"bb_window": 20, "bb_k": 2.0, "squeeze_pct": 0.3, "pct_days": 100, "squeeze_lookback": 10, "atr_window": 14, "atr_mult": 3.0,
            "bracket": "tp2"}, "none"),
    ("S1h", {"lookbacks_days": (7, 14, 30), "vote": 2, "atr_window": 14, "atr_mult": 2.0, "vol_window_days": 30, "entry_band": 0.1,
             "exit_band": 0.25, "bracket": "none"}, "none"),
    ("S2d", {"entry_days": 10, "exit_days": 20, "vol_mult": 1.0, "volume_window": 20, "atr_window": 14, "atr_mult": 2.0, "atr_pct_max": 0.9,
             "atr_pct_days": 90, "bracket": "time30"}, "gate"),
    ("hold", {"bracket": "none"}, "none"),
]


@pytest.fixture(scope="module")
def market():
    df = synthetic_4h()
    return df, positioning(df)


def _research_expected(df, ctx, spec: SleeveSpec, active_from: pd.Timestamp):
    """What the research code (build_frames + the gated walk-forward's gate + fraction_series) says, bar by bar."""
    frames = build_frames(get_candidate(spec.candidate), df, [dict(spec.params)], ctx, no_trade=NO_TRADE)
    desired = frames.desired[:, 0].copy()
    lo = None
    if spec.regime.active:
        train_end = active_from - pd.Timedelta(days=PURGE_DAYS)
        train_start = train_end - pd.Timedelta(days=TRAIN_DAYS)
        train = df[(df.index >= train_start) & (df.index < train_end)]
        fitted = fit_regime(train, TF, PPY, spec.regime)
        lo = int(np.searchsorted(df.index.values, train_start.to_datetime64()))
        bear = bear_probability(fitted, df.iloc[lo:], TF, PPY, spec.regime)
        ok = entry_gate_mask(bear, spec.regime).to_numpy(dtype=bool)
        desired[lo:] = gate_desired_matrix(frames.desired[lo:, :1], ok)[:, 0]
        desired[:lo] = False
    fractions = fraction_series(df, spec.sizing, TF, PPY).to_numpy() if spec.sizing is not None else np.ones(len(df))
    target = frames.target[:, 0] if frames.target is not None else np.full(len(df), np.nan)
    return frames, desired, frames.stop[:, 0], target, fractions


@pytest.mark.parametrize("candidate,params,mode", CASES, ids=[f"{c}-{p['bracket']}-{m}" for c, p, m in CASES])
def test_contract_decisions_equal_the_research_frames(market, candidate, params, mode):
    df, ctx = market
    regime = RegimeV2Config(mode=mode, vol_window_days=7.0)
    spec = SleeveSpec(candidate, "BTC-USDT", TF, params, regime, POLICY, 0.25)
    k0 = 1000
    active_from = df.index[k0]
    fit = fit_series(df, "BTC-USDT", TF, active_from, regime) if regime.active else None
    if fit is not None:
        assert fit.fitted is not None, fit.error
    _, desired, stop, target, fractions = _research_expected(df, ctx, spec, active_from)
    checked = longs = 0
    for t in range(k0, len(df), 5):
        info = decide_sleeve(spec, df.iloc[: t + 1], ctx, regime_fit=fit, window_days=10_000)
        d = info.decision
        assert d.desired == bool(desired[t]), (t, info.diagnostics)
        assert d.bar_time == df.index[t].strftime("%Y-%m-%dT%H:%M:%SZ") and d.close == df["close"].iloc[t]
        np.testing.assert_allclose(d.fraction, fractions[t], rtol=1e-12, equal_nan=True)
        if info.signal["action"] == "long":
            longs += 1
            if np.isfinite(stop[t]) and stop[t] > 0:
                assert d.stop_distance == pytest.approx(stop[t], rel=1e-9)
                assert d.close - d.stop_distance == d.close - stop[t] or math.isclose(d.close - d.stop_distance, d.close - stop[t], rel_tol=1e-15)
                if np.isfinite(target[t]):
                    assert d.target_distance == pytest.approx(target[t], rel=1e-9)
            else:
                assert math.isnan(d.stop_distance)
        checked += 1
    assert checked >= 60 and longs > 5  # the case really exercises long decisions


def test_frame_decisions_equal_contract_decisions_for_ungated_sleeves(market):
    df, ctx = market
    for candidate, params, mode in CASES:
        if mode != "none":
            continue
        spec = SleeveSpec(candidate, "BTC-USDT", TF, params, RegimeV2Config(mode="none"), POLICY, 0.25)
        start = df.index[1000]
        fast = frame_decisions(spec, df, ctx, start=start)
        for t in range(1000, len(df), 30):
            slow = decide_sleeve(spec, df.iloc[: t + 1], ctx, window_days=10_000).decision
            f = fast[t - 1000]
            assert (f.bar_time, f.desired) == (slow.bar_time, slow.desired)
            np.testing.assert_allclose([f.fraction, f.stop_distance, f.target_distance], [slow.fraction, slow.stop_distance, slow.target_distance],
                                       rtol=1e-9, equal_nan=True)


def test_a_gated_policy_sized_sleeve_runs_exactly_like_the_research_engine():
    """Contract decisions + regime gate + policy sizing + ladder + rebalancing + time-stop bracket, bar by bar,
    against the research engine on the same gated frames (a slice with a stop-loss exit, a signal exit and reductions)."""
    df = synthetic_4h(seed=7)
    ctx = positioning(df)
    candidate, params, _ = CASES[6]  # S2d: daily entry clock, regime gate, time30 bracket
    regime = RegimeV2Config(mode="gate", vol_window_days=7.0)
    spec = SleeveSpec(candidate, "BTC-USDT", TF, params, regime, POLICY, 0.25)
    a, b = 1000, 1150
    fit = fit_series(df, "BTC-USDT", TF, df.index[a], regime)
    frames, desired, stop, target, fractions = _research_expected(df, ctx, spec, df.index[a])
    gated = Frames(desired=desired[:, None], stop=frames.stop, strength=frames.strength, time_stops=frames.time_stops, target=frames.target,
                   trail_activate=frames.trail_activate, trail_dist=frames.trail_dist)
    ladder = LadderConfig(recovery_bars=days_to_bars(30.0, TF))
    res = simulate_sizing(df, gated, 0, slice(a, b), fractions[:, None], costs=COSTS, ladder=ladder, ladder_mask=np.array([True]),
                          rebalance_threshold=0.25)
    assert sorted(res.trades["exit_reason"]) == ["signal", "stop_loss"]
    engine = SleeveEngine(engine_config(spec, costs=COSTS, init_cash=10_000.0))
    equity, exits = [], []
    for t in range(a, b):
        info = decide_sleeve(spec, df.iloc[: t + 1], ctx, regime_fit=fit, window_days=10_000)
        row = df.iloc[t]
        out = engine.step(info.decision.bar_time, row["open"], row["high"], row["low"], row["close"], info.decision)
        equity.append(out.equity)
        exits += [e for e in out.events if e["kind"] == "exit"]
    np.testing.assert_allclose(np.array(equity)[:-1], res.equity[:-1, 0], rtol=0, atol=1e-6)
    assert [e["reason"] for e in exits] == list(res.trades["exit_reason"])
    for ev, pnl in zip(exits, res.trades["pnl"]):
        assert ev["pnl"] == pytest.approx(pnl, abs=1e-6)


def test_window_limits_do_not_change_the_decision(market):
    """The live 400-day window (gated: from the fit's train start minus a warm-up) gives the full-history decision."""
    df, ctx = market
    for candidate, params, mode in CASES:
        regime = RegimeV2Config(mode=mode, vol_window_days=7.0)
        spec = SleeveSpec(candidate, "BTC-USDT", TF, params, regime, POLICY, 0.25)
        fit = fit_series(df, "BTC-USDT", TF, df.index[1000], regime) if regime.active else None
        for t in (1150, len(df) - 1):
            full = decide_sleeve(spec, df.iloc[: t + 1], ctx, regime_fit=fit, window_days=10_000).decision
            live = decide_sleeve(spec, df.iloc[: t + 1], ctx, regime_fit=fit, window_days=150).decision
            assert (full.desired, full.bar_time) == (live.desired, live.bar_time), (candidate, mode, t)
            np.testing.assert_allclose([full.fraction, full.stop_distance], [live.fraction, live.stop_distance], rtol=1e-9, equal_nan=True)


def test_regime_gate_blocks_new_entries_only_and_a_failed_fit_blocks_all_entries(market):
    df, ctx = market
    candidate, params, _ = CASES[1]
    regime = RegimeV2Config(mode="gate", vol_window_days=7.0)
    spec = SleeveSpec(candidate, "BTC-USDT", TF, params, regime, POLICY, 0.25)
    fit = fit_series(df.iloc[:100], "BTC-USDT", TF, df.index[1000], regime)  # far too little training data
    assert fit.fitted is None and fit.error
    for t in range(1000, len(df), 60):
        info = decide_sleeve(spec, df.iloc[: t + 1], ctx, regime_fit=fit, window_days=10_000)
        assert info.decision.desired is False and info.diagnostics["regime"]["entry_allowed"] is False
    # gate_desired keeps an entered run alive while the gate closes, and never opens a run on a blocked bar.
    idx = pd.date_range("2024-01-01", periods=8, freq="4h", tz="UTC")
    desired = pd.Series([True, True, True, False, True, True, True, True], index=idx)
    ok = pd.Series([False, True, False, False, False, False, True, False], index=idx)
    assert gate_desired(desired, ok).tolist() == [False, True, True, False, False, False, True, True]


def test_buy_and_hold_and_the_adapter_no_stop_option(market):
    df, ctx = market
    info = decide_buy_and_hold(df.iloc[:50])
    assert info.decision.desired and info.decision.fraction == 1.0 and math.isnan(info.decision.stop_distance)
    hold = get_candidate("hold")
    candles = to_market_candles(df.iloc[:300], "BTC-USDT", TF)
    with_fallback = ResearchStrategyAdapter(hold, {}, ctx, no_trade=None).generate_signals(candles)
    without = ResearchStrategyAdapter(hold, {}, ctx, no_trade=None, fallback_stop_pct=None).generate_signals(candles)
    assert all(s.stop_loss == pytest.approx(c.close * 0.97) for s, c in zip(with_fallback, candles))  # unchanged default
    assert all(s.action.value == "long" and s.stop_loss is None for s in without)
