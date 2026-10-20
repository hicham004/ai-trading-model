"""Portfolio combination: daily compounding, bucket vs daily rebalancing, equal-risk weights, correlation, ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.portfolio import align_sleeves, combine, equal_risk_weights, equal_weights, to_daily_returns
from research.sizing import LadderConfig


def test_daily_compounding_of_bar_returns():
    idx = pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC")
    r = pd.Series([0.01] * 6 + [-0.01] * 6, index=idx)
    daily = to_daily_returns(r)
    assert len(daily) == 2
    assert daily.iloc[0] == pytest.approx(1.01 ** 6 - 1) and daily.iloc[1] == pytest.approx(0.99 ** 6 - 1)
    assert to_daily_returns(pd.Series(dtype=float)).empty


def test_align_combine_buckets_and_daily():
    idx4 = pd.date_range("2024-01-01", periods=24, freq="4h", tz="UTC")
    idx6 = pd.date_range("2024-01-02", periods=12, freq="6h", tz="UTC")  # starts a day later
    a = pd.Series(0.01, index=idx4)
    b = pd.Series(-0.005, index=idx6)
    daily = align_sleeves({"a": a, "b": b})
    assert list(daily.columns) == ["a", "b"] and len(daily) == 4 and daily.loc[daily.index[0], "b"] == 0.0
    w = equal_weights(daily.columns)
    res = combine(daily, w, name="test")
    # buckets: each sleeve compounds its half; the portfolio equity is the sum.
    expected = 0.5 * (1 + daily["a"]).cumprod() + 0.5 * (1 + daily["b"]).cumprod()
    np.testing.assert_allclose(res.equity.to_numpy(), expected.to_numpy())
    assert res.metrics["total_return"] == pytest.approx(expected.iloc[-1] - 1)
    assert set(res.sleeve_metrics) == {"a", "b"} and res.correlation.shape == (2, 2)
    daily_reb = combine(daily, w, name="test", rebalance="daily")
    np.testing.assert_allclose(daily_reb.daily_returns.to_numpy(), (daily * 0.5).sum(axis=1).to_numpy())
    with pytest.raises(ValueError):
        combine(daily, {"a": 0.7, "b": 0.7}, name="bad")
    with pytest.raises(ValueError):
        combine(daily, w, name="bad", rebalance="weekly")
    d = res.to_dict()
    assert d["weights"] == {"a": 0.5, "b": 0.5} and d["days"] == 4 and "correlation" in d


def test_equal_risk_weights_and_diversification_ratio():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC")
    calm = pd.Series(rng.normal(0.0005, 0.005, 400), index=idx)
    wild = pd.Series(rng.normal(0.0005, 0.02, 400), index=idx)
    daily = align_sleeves({"calm": calm, "wild": wild})
    w = equal_risk_weights(daily)
    assert w["calm"] > w["wild"] and w.sum() == pytest.approx(1.0)
    res = combine(daily, w, name="er")
    assert res.diversification_ratio > 1.0  # uncorrelated sleeves diversify


def test_portfolio_level_ladder_reduces_drawdown():
    idx = pd.date_range("2023-01-01", periods=60, freq="D", tz="UTC")
    path = np.concatenate([np.full(10, 0.01), np.full(20, -0.02), np.full(30, 0.01)])
    a = pd.Series(path, index=idx)
    daily = align_sleeves({"a": a})
    plain = combine(daily, {"a": 1.0}, name="plain")
    laddered = combine(daily, {"a": 1.0}, name="ladder", ladder=LadderConfig(half_dd=0.05, flat_dd=0.10, recovery_bars=10))
    assert laddered.metrics["max_drawdown"] < plain.metrics["max_drawdown"]
    assert laddered.ladder is not None and laddered.to_dict()["ladder_share_reduced"] > 0
