"""Sprint 2b sizing overlays: vol targeting, crash-state de-risking, drawdown ladder; no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research import features
from research.sizing import (
    LadderConfig,
    SizingSpec,
    apply_ladder_to_returns,
    crash_multiplier,
    find_spec,
    fraction_matrix,
    fraction_series,
    ladder_mask,
    ladder_multiplier_path,
    ladder_step,
    sizing_grid,
    vol_target_fraction,
)
from tests.test_research_strategies import synthetic

PPY = 8766.0


def test_vol_target_fraction_math_warmup_and_clamp():
    df = synthetic(600)
    close = df["close"]
    frac = vol_target_fraction(close, 0.15, 20, PPY)
    vol = features.realized_vol(close, 20, PPY)
    assert frac.iloc[:20].isna().all() and np.isfinite(frac.iloc[20])
    expected = (0.15 / vol).clip(upper=1.0)
    pd.testing.assert_series_equal(frac.dropna(), expected.dropna(), check_names=False)
    assert (vol_target_fraction(close, 50.0, 20, PPY).dropna() == 1.0).all()  # clamp at 100 % (no leverage)
    assert (vol_target_fraction(close, 1e-6, 20, PPY).dropna() < 0.01).all()
    for bad in ({"target_vol": 0.0}, {"lookback": 1}, {"cap": 1.5}):
        kwargs = {"target_vol": 0.15, "lookback": 20, "cap": 1.0}
        kwargs.update(bad)
        with pytest.raises(ValueError):
            vol_target_fraction(close, kwargs["target_vol"], kwargs["lookback"], PPY, cap=kwargs["cap"])


def test_crash_multiplier_modes_and_recovery():
    idx = pd.date_range("2024-01-01", periods=120, freq="h", tz="UTC")
    close = pd.Series(np.concatenate([np.linspace(90, 100, 40), np.full(40, 80.0), np.full(40, 80.0)]), index=idx)
    half = crash_multiplier(close, 0.15, 50, mode="half")
    zero = crash_multiplier(close, 0.15, 50, mode="zero")
    assert (half.iloc[:40] == 1.0).all()
    assert (half.iloc[40:80] == 0.5).all() and (zero.iloc[40:80] == 0.0).all()  # 20 % below the 50-bar peak
    assert (half.iloc[90:] == 1.0).all()  # the peak rolled out of the window: no longer a crash state
    with pytest.raises(ValueError):
        crash_multiplier(close, 1.5, 50)
    with pytest.raises(ValueError):
        crash_multiplier(close, 0.1, 50, mode="double")


def test_sizing_series_use_only_past_bars():
    df = synthetic(800)
    cut = 500
    spec = SizingSpec(kind="vol_target", target_vol=0.2, vol_lookback=30, crash_dd=0.1, crash_window_days=5.0, crash_mode="zero")
    base = fraction_series(df.iloc[:cut], spec, "1H", PPY)
    perturbed = df.copy()
    perturbed.iloc[cut:, :4] *= 0.5  # crash the future only
    full = fraction_series(perturbed, spec, "1H", PPY)
    pd.testing.assert_series_equal(base, full.iloc[:cut], check_names=False)
    pd.testing.assert_series_equal(
        crash_multiplier(df["close"].iloc[:cut], 0.1, 120), crash_multiplier(perturbed["close"], 0.1, 120).iloc[:cut], check_names=False
    )


def test_ladder_state_machine_half_flat_release_and_reset():
    cfg = LadderConfig(half_dd=0.05, flat_dd=0.10, recovery_bars=3)
    equity = [100, 100, 95, 97, 98, 100, 89, 89, 89, 95]
    mult = ladder_multiplier_path(equity, cfg)
    assert list(mult) == [1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    # Flat is also released by a new equity high.
    assert list(ladder_multiplier_path([100, 89, 101], cfg)) == [1.0, 0.0, 1.0]
    # Vectorized step over columns.
    level, flat, peak = ladder_step(np.zeros(2, dtype=int), np.zeros(2, dtype=int), np.array([100.0, 100.0]), np.array([94.0, 85.0]), cfg)
    assert list(level) == [1, 2] and list(flat) == [0, 1] and list(peak) == [100.0, 100.0]
    assert cfg.release == pytest.approx(0.025) and cfg.to_dict()["recovery_bars"] == 3
    with pytest.raises(ValueError):
        LadderConfig(half_dd=0.2, flat_dd=0.1)
    with pytest.raises(ValueError):
        LadderConfig(recovery_bars=0)


def test_apply_ladder_to_returns_scales_next_bar():
    cfg = LadderConfig(half_dd=0.05, flat_dd=0.10, recovery_bars=2)
    r = pd.Series([0.0, -0.06, 0.02, -0.12, 0.05, 0.05, 0.05])
    scaled, used = apply_ladder_to_returns(r, cfg)
    # bar 1 loses 6 % -> half size from bar 2; bar 3's -12 % (half-sized -> -6 %) deepens the drawdown past 10 % -> flat.
    assert list(used) == [1.0, 1.0, 0.5, 0.5, 0.0, 1.0, 1.0]
    assert scaled.iloc[1] == pytest.approx(-0.06) and scaled.iloc[2] == pytest.approx(0.01)
    assert scaled.iloc[3] == pytest.approx(-0.06)
    assert scaled.iloc[4] == 0.0  # flat during the cooling-off
    assert scaled.iloc[5] == pytest.approx(0.05)  # re-armed after the 2-bar cooling-off


def test_sizing_grid_specs_labels_and_matrix():
    specs = sizing_grid()
    assert len(specs) == 364
    labels = [s.label for s in specs]
    assert len(set(labels)) == len(labels)
    assert "vt15/30" in labels and "fixed25 ladder" in labels and "vt20/60 crash15/90dz" in labels
    assert find_spec(specs, "vt15/30") is not None and find_spec(specs, "nope") is None
    assert ladder_mask(specs).sum() == 182
    df = synthetic(400)
    sub = [SizingSpec(kind="fixed", fraction=0.25), SizingSpec(kind="vol_target", target_vol=0.15, vol_lookback=20, ladder=True)]
    m = fraction_matrix(df, sub, "1H", PPY)
    assert m.shape == (400, 2) and (m[:, 0] == 0.25).all() and np.isnan(m[:20, 1]).all()
    assert sub[1].to_dict()["label"] == "vt15/20 ladder"
    for bad in ({"kind": "fixed", "fraction": 1.5}, {"crash_dd": 0.1}, {"crash_mode": "x"}, {"kind": "lever"}):
        with pytest.raises(ValueError):
            SizingSpec(**bad)
