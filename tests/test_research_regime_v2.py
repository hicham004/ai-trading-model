"""Regime v2 (HMM entry gate): train-only fitting, forward filtering, gate/scale semantics, no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.gated_walkforward import gate_desired_matrix, regime_for_window, window_frames
from research.regime_v2 import (
    RegimeV2Config,
    bear_probability,
    entry_gate_mask,
    filtered_probabilities,
    fit_regime,
    regime_features,
    regime_summary,
    size_multiplier,
)
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import Frames, build_frames, param_grid
from research.walkforward import Window
from tests.test_research_strategies import synthetic

PPY = 8766.0


def _regime_df(n: int = 4000, seed: int = 7) -> pd.DataFrame:
    """Synthetic hourly series with a planted bear stretch (negative drift, high vol)."""
    rng = np.random.default_rng(seed)
    drift = np.full(n, 0.0004)
    vol = np.full(n, 0.006)
    drift[1500:2200] = -0.003
    vol[1500:2200] = 0.02
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol)))
    idx = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.lognormal(3, 0.5, n)}, index=idx)


def test_config_validation_and_labels():
    assert RegimeV2Config().label == "hmm3 bear>=0.5 gate"
    assert RegimeV2Config(mode="scale", bear_scale=0.25).label.endswith("scale0.25")
    assert RegimeV2Config(mode="none").label == "no regime gate" and not RegimeV2Config(mode="none").active
    for bad in (dict(mode="smooth"), dict(n_states=1), dict(bear_prob_max=0.0), dict(bear_scale=1.5), dict(vol_window_days=0)):
        with pytest.raises(ValueError):
            RegimeV2Config(**bad)


def test_features_are_backward_looking():
    df = _regime_df(600)
    cfg = RegimeV2Config(vol_window_days=1.0)
    full = regime_features(df, "1H", PPY, cfg)
    prefix = regime_features(df.iloc[:400], "1H", PPY, cfg)
    pd.testing.assert_frame_equal(full.iloc[:400], prefix)
    assert full.iloc[:24].isna().any().any() and full.iloc[30:].notna().all().all()


def test_fit_on_train_identifies_the_bear_state_and_filter_is_causal():
    df = _regime_df()
    cfg = RegimeV2Config(mode="gate", vol_window_days=1.0)
    fitted = fit_regime(df.iloc[:3000], "1H", PPY, cfg)  # train contains the planted bear stretch
    assert fitted.bear_state != fitted.bull_state and 0 <= fitted.bear_state < cfg.n_states
    bear = bear_probability(fitted, df, "1H", PPY, cfg)
    assert bear.iloc[:24].isna().all() and bear.dropna().between(0.0, 1.0).all()
    # The planted bear stretch carries a much higher bear probability than the calm stretches.
    assert bear.iloc[1600:2200].mean() > bear.iloc[300:1400].mean() + 0.3
    assert bear.iloc[1600:2200].mean() > bear.iloc[2400:3900].mean() + 0.3
    # No look-ahead: filtering a prefix gives the prefix of the full result; future bars never change the past.
    prefix = bear_probability(fitted, df.iloc[:2500], "1H", PPY, cfg)
    pd.testing.assert_series_equal(prefix.dropna(), bear.iloc[:2500].dropna())
    shocked = df.copy()
    shocked.loc[shocked.index[3500:], "close"] *= np.linspace(1.0, 0.2, len(shocked) - 3500)
    pd.testing.assert_series_equal(bear_probability(fitted, shocked, "1H", PPY, cfg).iloc[:3400].dropna(), bear.iloc[:3400].dropna())
    probs = filtered_probabilities(fitted, df, "1H", PPY, cfg)
    assert np.allclose(probs.dropna().sum(axis=1), 1.0)
    summary = regime_summary(bear, cfg)
    assert 0.0 < summary["bear_share"] < 1.0 and summary["bars"] > 3000
    d = fitted.to_dict()
    assert d["model"]["fitted"] and d["train_bars"] > 2900


def test_fit_fails_closed_on_too_few_bars():
    df = _regime_df(400)
    with pytest.raises(ValueError):
        fit_regime(df.iloc[:150], "1H", PPY, RegimeV2Config(vol_window_days=1.0, min_train_bars=200))


def test_gate_and_scale_act_on_entries_only():
    idx = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    bear = pd.Series([np.nan, 0.1, 0.9, 0.9, 0.2, 0.1, 0.8, 0.1], index=idx)
    gate = RegimeV2Config(mode="gate", bear_prob_max=0.5)
    ok = entry_gate_mask(bear, gate)
    assert ok.tolist() == [False, True, False, False, True, True, False, True]  # warm-up blocks too
    scale = RegimeV2Config(mode="scale", bear_prob_max=0.5, bear_scale=0.25)
    mult = size_multiplier(bear, scale)
    assert mult.tolist() == [1.0, 1.0, 0.25, 0.25, 1.0, 1.0, 0.25, 1.0]
    assert entry_gate_mask(bear, scale).all() and (size_multiplier(bear, gate) == 1.0).all()
    # Entries-only gating on a desired matrix: a position opened while allowed survives a later blocked bar.
    desired = np.array([[1, 1, 1, 1, 0, 1, 1, 1], [0, 0, 1, 1, 1, 0, 0, 0]], dtype=bool).T
    gated = gate_desired_matrix(desired, ok.to_numpy())
    assert gated[:, 0].tolist() == [False, True, True, True, False, True, True, True]  # entered at bar 1, kept through bear bars
    assert gated[:, 1].tolist() == [False, False, False, False, True, False, False, False]  # could only enter once allowed
    with pytest.raises(ValueError):
        gate_desired_matrix(desired, ok.to_numpy()[:4])


def test_window_regime_fits_on_train_only_and_window_frames_gate():
    df = _regime_df(3500)
    cfg = RegimeV2Config(mode="gate", vol_window_days=1.0)
    w = Window(0, slice(0, 2500), slice(2524, 3500))
    reg = regime_for_window(df, w, cfg, "1H", PPY)
    assert reg.fitted is not None and reg.ok is not None and reg.mult is None and len(reg.ok) == 3500
    # The window's fitted parameters equal a direct fit on the train slice (nothing from the test slice leaked in).
    direct = fit_regime(df.iloc[w.train], "1H", PPY, cfg)
    np.testing.assert_allclose(reg.fitted.model.means_, direct.model.means_)
    assert set(reg.train_summary) == {"bars", "bear_share", "mean_bear_prob"} and reg.test_summary["bars"] > 900
    none = regime_for_window(df, w, RegimeV2Config(mode="none"), "1H", PPY)
    assert none.fitted is None and none.ok is None and none.mult is None
    cand = get_candidate("S1")
    combos = param_grid({"vote": [1, 2]}, base=cand.default_params)
    frames = build_frames(cand, df, combos, FeatureContext("1H", PPY))
    fw = window_frames(frames, 0, 3500, reg.ok)
    assert fw.desired.shape == frames.desired.shape and fw.desired.sum() <= frames.desired.sum()
    assert (fw.desired & ~frames.desired).sum() == 0  # the gate can only remove desired bars
    scale_reg = regime_for_window(df, w, RegimeV2Config(mode="scale", vol_window_days=1.0, bear_scale=0.5), "1H", PPY)
    assert scale_reg.ok is None and scale_reg.mult is not None and set(np.unique(scale_reg.mult)) <= {0.5, 1.0}
