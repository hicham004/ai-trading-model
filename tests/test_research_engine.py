"""Vectorized research engine: exact trade math, stops, time stops, targets, parity with the simulator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.backtest.models import SimulationConfig
from app.backtest.simulator import run_signal_backtest
from app.broker.base import CostModel
from app.risk.manager import RiskLimits, RiskManager
from app.strategy import indicators
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy
from research.engine import Costs, buy_and_hold, run_vectorized

ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)


def ohlc(opens, highs=None, lows=None, closes=None):
    o = np.asarray(opens, dtype=float)
    h = o + 1.0 if highs is None else np.asarray(highs, dtype=float)
    l = o - 1.0 if lows is None else np.asarray(lows, dtype=float)
    c = o.copy() if closes is None else np.asarray(closes, dtype=float)
    return o, h, l, c


def test_single_trade_fee_and_slippage_math():
    o, h, l, c = ohlc([100, 100, 110, 120, 120])
    desired = np.array([True, True, False, False, False])
    costs = Costs(fee_rate=0.001, slippage_rate=0.0005)
    res = run_vectorized(o, h, l, c, desired, None, costs=costs, init_cash=10_000)
    fill = 100 * 1.0005
    q = 10_000 / (fill * 1.001)
    cash_after_entry = 10_000 - fill * q * 1.001
    exit_fill = 120 * (1 - 0.0005)
    final_cash = cash_after_entry + exit_fill * q * (1 - 0.001)
    assert res.equity[-1, 0] == pytest.approx(final_cash)
    assert res.equity[1, 0] == pytest.approx(cash_after_entry + q * c[1])
    assert list(res.position[:, 0]) == [False, True, True, False, False]
    t = res.trades
    assert len(t) == 1 and t.loc[0, "exit_reason"] == "signal"
    assert t.loc[0, "entry_i"] == 1 and t.loc[0, "exit_i"] == 3 and t.loc[0, "bars_held"] == 2
    assert t.loc[0, "pnl"] == pytest.approx(final_cash - 10_000)
    assert res.exposure[0] == pytest.approx(2 / 5)


def test_stop_fills_at_stop_or_at_gapped_open():
    # Entry at bar 1 (open 100, decision close 100 -> stop 95); bar 2 trades down through 95.
    o, h, l, c = ohlc([100, 100, 100, 100, 100], lows=[99, 99, 90, 99, 99])
    desired = np.array([True, True, True, True, True])
    res = run_vectorized(o, h, l, c, desired, np.full(5, 5.0), costs=ZERO)
    t = res.trades
    assert t.loc[0, "exit_reason"] == "stop_loss" and t.loc[0, "exit_price"] == 95.0 and t.loc[0, "exit_i"] == 2
    assert t.loc[1, "entry_i"] == 3  # re-entry next bar because the decision is still on
    # Gap: bar 2 opens at 92 (< 95): the first achievable price is the open.
    o2 = o.copy()
    o2[2] = 92.0
    res2 = run_vectorized(o2, h, l, c, desired, np.full(5, 5.0), costs=ZERO)
    assert res2.trades.loc[0, "exit_price"] == 92.0


def test_same_bar_stop_after_entry_and_stop_not_below_open_skips_entry():
    o, h, l, c = ohlc([100, 100, 100, 100], lows=[99, 90, 99, 99])
    desired = np.array([True, True, True, True])
    res = run_vectorized(o, h, l, c, desired, np.full(4, 5.0), costs=ZERO)
    t = res.trades
    assert t.loc[0, "entry_i"] == 1 and t.loc[0, "exit_i"] == 1 and t.loc[0, "bars_held"] == 0
    assert t.loc[0, "exit_price"] == 95.0
    # A stop at/above the execution open is not a valid entry (risk manager parity).
    o3, h3, l3, c3 = ohlc([100, 94, 100, 100], closes=[100, 100, 100, 100])
    res3 = run_vectorized(o3, h3, l3, c3, np.array([True, False, False, False]), np.full(4, 5.0), costs=ZERO)
    assert len(res3.trades) == 0 and not res3.position.any()


def test_time_stop_and_target():
    o, h, l, c = ohlc([100] * 8)
    desired = np.ones(8, dtype=bool)
    res = run_vectorized(o, h, l, c, desired, None, costs=ZERO, time_stop_bars=2)
    t = res.trades
    assert list(t["exit_reason"])[:2] == ["time_stop", "time_stop"]
    assert t.loc[0, "entry_i"] == 1 and t.loc[0, "exit_i"] == 3 and t.loc[1, "entry_i"] == 4

    h2 = h.copy()
    h2[3] = 115.0
    res2 = run_vectorized(o, h2, l, c, desired, None, costs=ZERO, target_distance=np.full(8, 10.0))
    t2 = res2.trades
    assert t2.loc[0, "exit_reason"] == "target" and t2.loc[0, "exit_price"] == 110.0 and t2.loc[0, "exit_i"] == 3


def test_end_of_data_closes_open_position():
    o, h, l, c = ohlc([100, 100, 105, 110], closes=[100, 100, 105, 112])
    res = run_vectorized(o, h, l, c, np.ones(4, dtype=bool), None, costs=ZERO)
    assert res.trades.iloc[-1]["exit_reason"] == "end_of_data"
    assert res.equity[-1, 0] == pytest.approx(10_000 * 112 / 100)


def test_many_combos_equal_independent_runs():
    rng = np.random.default_rng(1)
    n = 300
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, 0.001, n))
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    desired = rng.random((n, 4)) > 0.5
    stops = np.repeat((c * 0.02)[:, None], 4, axis=1)
    joint = run_vectorized(o, h, l, c, desired, stops, time_stop_bars=10)
    for k in range(4):
        single = run_vectorized(o, h, l, c, desired[:, k], stops[:, k], time_stop_bars=10)
        np.testing.assert_allclose(joint.equity[:, k], single.equity[:, 0])
        assert len(joint.trades_for(k)) == len(single.trades)


def test_argument_validation():
    o, h, l, c = ohlc([100, 100, 100])
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, np.ones((2, 1), dtype=bool))
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, np.ones(3, dtype=bool), np.ones((3, 2)))
    with pytest.raises(ValueError):
        run_vectorized(o, h, l, c, np.ones(3, dtype=bool), size_fraction=0.0)
    with pytest.raises(ValueError):
        run_vectorized(o, h, np.array([1.0, -1.0, 1.0]), c, np.ones(3, dtype=bool))
    with pytest.raises(ValueError):
        Costs(fee_rate=0.5)


def test_buy_and_hold_benchmark():
    eq = buy_and_hold([100, 110], [100, 120], costs=ZERO)
    assert eq[-1] == pytest.approx(12_000)


class _MaStrategy(Strategy):
    name = "ma_test"

    def generate_signals(self, candles):
        closes = [c.close for c in candles]
        short = indicators.simple_moving_average(closes, 5)
        long = indicators.simple_moving_average(closes, 20)
        out = []
        for i, c in enumerate(candles):
            if short[i] is not None and long[i] is not None and short[i] > long[i]:
                out.append(Signal(c.timestamp, c.instrument, SignalAction.LONG, 0.9, "up", c.close * 0.97))
            else:
                out.append(Signal(c.timestamp, c.instrument, SignalAction.FLAT, 0.0, "flat"))
        return self._validate_output(candles, out)


def test_parity_with_the_event_driven_simulator():
    rng = np.random.default_rng(7)
    n = 400
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n)))
    o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [MarketCandle("BTC-USDT", t0 + timedelta(hours=i), o[i], h[i], l[i], c[i], 1.0, "1H") for i in range(n)]

    short = indicators.simple_moving_average(list(c), 5)
    long = indicators.simple_moving_average(list(c), 20)
    desired = np.array([s is not None and g is not None and s > g for s, g in zip(short, long)])
    costs = Costs(fee_rate=0.001, slippage_rate=0.0005)
    vec = run_vectorized(o, h, l, c, desired, c * 0.03, costs=costs, init_cash=10_000)

    limits = RiskLimits(max_risk_per_trade=1.0, max_daily_loss=1.0, max_position_size=1.0, min_confidence=0.01,
                        max_data_staleness=timedelta(hours=2))
    sim = run_signal_backtest(
        candles, _MaStrategy(), config=SimulationConfig(starting_cash=10_000, costs=CostModel(0.001, 0.0005)),
        risk_manager=RiskManager(limits), timeframe="1H",
    )
    assert len(sim.trades) == len(vec.trades) > 3
    assert sim.rejected_entries == 0
    np.testing.assert_allclose(np.array(sim.equity_curve), vec.equity[:, 0], rtol=1e-9)
    for st, (_, vt) in zip(sim.trades, vec.trades.iterrows()):
        assert st.exit_reason == vt["exit_reason"]
        assert st.exit_price == pytest.approx(vt["exit_price"])
