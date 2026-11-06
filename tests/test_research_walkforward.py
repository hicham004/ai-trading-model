"""Walk-forward windows, purge gap, selection, stitching, and the no-qualified-combo path."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.engine import Costs
from research.sweep import Frames
from research.walkforward import WalkForwardConfig, make_windows, run_walk_forward


def test_windows_geometry_with_purge_gap():
    cfg = WalkForwardConfig(train_bars=300, test_bars=100, purge_bars=10)
    windows = make_windows(1000, cfg)
    assert windows[0].train == slice(0, 300) and windows[0].test == slice(310, 410)
    assert windows[1].train == slice(100, 400) and windows[1].test == slice(410, 510)
    for w in windows:
        assert w.test.start - w.train.stop == 10  # purge gap
        assert w.test.stop <= 1000
    # The last window with a test shorter than half the test size is dropped.
    assert windows[-1].test.stop - windows[-1].test.start >= 50
    assert make_windows(200, cfg) == []
    with pytest.raises(ValueError):
        WalkForwardConfig(train_bars=0, test_bars=10)


def _uptrend(n: int) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    close = 100 * np.exp(np.linspace(0, 1.0, n) + 0.01 * np.sin(np.arange(n) / 7.0))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001, "low": np.minimum(open_, close) * 0.999,
                         "close": close, "volume": 1.0}, index=idx)


def _frames(n: int) -> Frames:
    desired = np.zeros((n, 2), dtype=bool)
    desired[:, 0] = True  # always long
    # Combo 1: long on alternating 50-bar blocks (many trades, weaker edge)
    desired[:, 1] = (np.arange(n) // 50) % 2 == 0
    return Frames(desired=desired, stop=np.full((n, 2), np.nan), strength=np.full((n, 2), np.nan), time_stops=[None, None])


def test_walk_forward_selects_and_stitches():
    n = 3000
    df = _uptrend(n)
    frames = _frames(n)
    combos = [{"mode": "always"}, {"mode": "blocks"}]
    cfg = WalkForwardConfig(train_bars=1000, test_bars=500, purge_bars=24, min_trades=1, select_by="total_return")
    res = run_walk_forward(df, frames, combos, cfg, costs=Costs(0.001, 0.0005), periods_per_year=8766)
    assert len(res.windows) == len(make_windows(n, cfg)) >= 3
    assert all(w.selected_combo == 0 for w in res.windows)  # always-long wins an uptrend
    assert res.params_frequency == {"mode=always": len(res.windows)}
    assert res.selected_most_often == {"mode": "always"}
    total_test_bars = sum(w.test.stop - w.test.start for w in make_windows(n, cfg))
    assert len(res.oos_equity) == total_test_bars
    assert res.oos_equity.iloc[-1] > 1.0 and res.oos_metrics["total_return"] > 0
    assert res.oos_metrics["windows_traded"] == len(res.windows)
    assert res.oos_metrics["windows_positive"] == len(res.windows)
    assert not res.yearly.empty
    assert res.oos_trades["window"].nunique() == len(res.windows)
    assert set(res.oos_metrics) >= {"sharpe", "max_drawdown", "profit_factor", "n_trades", "ret_skew"}


def test_walk_forward_without_qualified_combo_stays_flat():
    n = 3000
    df = _uptrend(n)
    frames = _frames(n)
    combos = [{"mode": "always"}, {"mode": "blocks"}]
    cfg = WalkForwardConfig(train_bars=1000, test_bars=500, purge_bars=24, min_trades=500)
    res = run_walk_forward(df, frames, combos, cfg, costs=Costs(), periods_per_year=8766)
    assert all(w.selected_combo is None for w in res.windows)
    assert res.oos_metrics["windows_traded"] == 0 and res.oos_metrics["n_trades"] == 0
    assert (res.oos_equity == 1.0).all()
    assert res.selected_most_often is None


def test_walk_forward_requires_enough_bars():
    df = _uptrend(100)
    with pytest.raises(ValueError):
        run_walk_forward(df, _frames(100), [{}, {}], WalkForwardConfig(train_bars=80, test_bars=50), costs=Costs(), periods_per_year=8766)
