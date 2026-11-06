"""Portfolio-level sizing (Sprint 2c item 3): trailing weights, vol-target scale, joint ladder, no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.portfolio import DAYS_PER_YEAR, align_sleeves, combine_sized, rolling_inverse_vol_weights, vol_target_scale
from research.sizing import LadderConfig


def _daily(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    calm = rng.normal(0.0005, 0.01, n)
    wild = rng.normal(0.0005, 0.04, n)
    return pd.DataFrame({"calm": calm, "wild": wild}, index=idx)


def test_rolling_weights_use_only_past_days_and_favour_the_calm_sleeve():
    daily = _daily()
    w = rolling_inverse_vol_weights(daily, 60)
    np.testing.assert_allclose(w.sum(axis=1), 1.0)
    assert (w.iloc[:20] == 0.5).all().all()  # warm-up: equal weights
    assert (w["calm"].iloc[100:] > 0.6).all() and w["calm"].iloc[100:].mean() > 0.75
    # Future data cannot change today's weights (shifted trailing window).
    shocked = daily.copy()
    shocked.loc[shocked.index[300:], "calm"] = 0.5
    pd.testing.assert_frame_equal(rolling_inverse_vol_weights(shocked, 60).iloc[:300], w.iloc[:300])
    with pytest.raises(ValueError):
        rolling_inverse_vol_weights(daily, 1)


def test_vol_target_scale_is_shifted_and_capped():
    daily = _daily()
    r = daily["wild"]
    scale = vol_target_scale(r, 0.10, 30)
    assert (scale.iloc[:10] == 1.0).all() and scale.max() <= 1.0 and (scale > 0).all()
    realized = r.rolling(30).std(ddof=1) * np.sqrt(DAYS_PER_YEAR)
    expected = (0.10 / realized).clip(upper=1.0).shift(1).dropna()
    pd.testing.assert_series_equal(scale.loc[expected.index], expected)
    assert (vol_target_scale(daily["calm"] * 0.01, 0.10, 30).iloc[40:] == 1.0).all()  # tiny vol: capped at 100 % (no leverage)
    with pytest.raises(ValueError):
        vol_target_scale(r, 0.0, 30)
    with pytest.raises(ValueError):
        vol_target_scale(r, 0.1, 30, cap=2.0)


def test_combine_sized_respects_budget_and_reports_sizing():
    daily = _daily()
    ladder = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30)
    res = combine_sized(daily, name="joint", target_vol=0.10, ladder=ladder)
    assert res.sizing["target_vol"] == 0.10 and res.sizing["ladder"]["flat_dd"] == 0.15
    assert res.scale_used is not None and res.scale_used.max() <= 1.0
    assert res.metrics["ann_vol"] < daily["wild"].std() * np.sqrt(DAYS_PER_YEAR)
    d = res.to_dict()
    assert d["avg_scale"] is not None and 0 < d["avg_scale"] <= 1.0 and d["rebalance"].startswith("daily")
    assert abs(sum(d["weights"].values()) - 1.0) < 1e-9
    unsized = combine_sized(daily, name="nol", target_vol=5.0, ladder=None)
    assert unsized.ladder_used is None and (unsized.scale_used == 1.0).all()


def test_combine_sized_has_no_look_ahead():
    daily = _daily()
    res = combine_sized(daily, name="a", target_vol=0.10)
    shocked = daily.copy()
    shocked.loc[shocked.index[400:], :] = -0.2
    res2 = combine_sized(shocked, name="b", target_vol=0.10)
    pd.testing.assert_series_equal(res.daily_returns.iloc[:400], res2.daily_returns.iloc[:400])


def test_align_sleeves_from_bar_returns_on_different_clocks():
    idx4 = pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC")
    idx6 = pd.date_range("2024-01-01", periods=8, freq="6h", tz="UTC")
    daily = align_sleeves({"a": pd.Series(0.01, index=idx4), "b": pd.Series(0.0, index=idx6)})
    assert list(daily.index.date) == [pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-02").date()]
    assert daily["a"].iloc[0] == pytest.approx(1.01 ** 6 - 1.0) and (daily["b"] == 0.0).all()
    with pytest.raises(ValueError):
        combine_sized(pd.DataFrame(), name="empty")
