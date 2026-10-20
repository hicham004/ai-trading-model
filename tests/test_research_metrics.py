"""Research metrics: drawdown, Sharpe/Sortino, normal helpers, deflated Sharpe, yearly returns."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research import metrics as m


def test_max_drawdown_and_returns():
    assert m.max_drawdown([100, 120, 90, 130]) == pytest.approx(0.25)
    assert m.max_drawdown([100, 101, 102]) == 0.0
    assert m.max_drawdown([]) == 0.0
    np.testing.assert_allclose(m.bar_returns([100, 110, 99]), [0.1, -0.1])


def test_sharpe_sortino_cagr():
    r = np.array([0.01, -0.005, 0.02, 0.0, 0.01])
    expected = r.mean() / r.std(ddof=1) * math.sqrt(252)
    assert m.sharpe(r, 252) == pytest.approx(expected)
    assert m.sortino(r, 252) > m.sharpe(r, 252)
    assert m.sharpe(np.zeros(5), 252) == 0.0
    eq = np.array([1.0] + [1.0 * 1.1 ** (i / 252) for i in range(1, 253)])
    assert m.cagr(eq, 252) == pytest.approx(0.1, rel=1e-6)
    em = m.equity_metrics(eq, 252)
    assert em["total_return"] == pytest.approx(0.1, rel=1e-6) and em["max_drawdown"] == 0.0 and em["bars"] == 253


def test_normal_helpers_roundtrip():
    for p in (0.001, 0.05, 0.5, 0.9, 0.999):
        assert m.norm_cdf(m.norm_ppf(p)) == pytest.approx(p, abs=1e-7)
    with pytest.raises(ValueError):
        m.norm_ppf(1.0)


def test_expected_max_sharpe_grows_with_trials_and_dsr_is_a_probability():
    e10 = m.expected_max_sharpe(10, 0.01)
    e1000 = m.expected_max_sharpe(1000, 0.01)
    assert 0 < e10 < e1000
    assert m.expected_max_sharpe(1, 0.01) == 0.0
    trials = list(np.random.default_rng(0).normal(0, 0.1, 50))
    out = m.deflated_sharpe_ratio(0.3, trials, n_obs=2000)
    assert out["n_trials"] == 50 and 0.0 <= out["dsr"] <= 1.0 and out["expected_max_sr"] > 0
    weak = m.deflated_sharpe_ratio(0.0, trials, n_obs=2000)
    assert weak["dsr"] < out["dsr"]
    assert m.probabilistic_sharpe_ratio(0.0, 0.0, 100) == pytest.approx(0.5)
    assert m.probabilistic_sharpe_ratio(0.1, 0.0, 1) == 0.0


def test_trade_metrics_and_moments():
    trades = pd.DataFrame({
        "pnl": [10.0, -5.0, 20.0, -5.0],
        "entry_price": [100.0] * 4, "exit_price": [101.0] * 4, "quantity": [1.0] * 4,
        "fees": [0.2] * 4, "bars_held": [3, 1, 5, 2],
    })
    tm = m.trade_metrics(trades, init_cash=1000.0, n_bars=2520, periods_per_year=252)
    assert tm["n_trades"] == 4 and tm["win_rate"] == 0.5 and tm["profit_factor"] == pytest.approx(3.0)
    assert tm["trades_per_year"] == pytest.approx(0.4) and tm["fees_total"] == pytest.approx(0.8)
    assert m.trade_metrics(pd.DataFrame(), init_cash=1.0, n_bars=10, periods_per_year=252)["n_trades"] == 0
    mo = m.return_moments(np.array([0.01, -0.02, 0.03, -0.01, 0.0]))
    assert set(mo) == {"skew", "kurt"}
    assert m.return_moments(np.zeros(5)) == {"skew": 0.0, "kurt": 3.0}


def test_yearly_returns():
    idx = pd.date_range("2023-06-01", periods=600, freq="D", tz="UTC")
    eq = pd.Series(np.linspace(1.0, 2.0, 600), index=idx)
    yearly = m.yearly_returns(eq)
    assert list(yearly.index) == [2023, 2024, 2025]
    assert yearly.loc[2023] == pytest.approx(eq[eq.index.year == 2023].iloc[-1] / eq.iloc[0] - 1)
    assert m.yearly_returns(pd.Series(dtype=float)).empty
