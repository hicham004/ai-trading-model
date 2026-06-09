"""Tests for the demo strategy and the backtest skeleton (offline)."""

from __future__ import annotations

import pytest

from app.backtest.engine import BacktestConfig, run_backtest
from app.backtest.strategy import DemoMovingAverageStrategy


def test_demo_strategy_returns_one_position_per_bar():
    strat = DemoMovingAverageStrategy(short_window=2, long_window=4)
    closes = [1, 2, 3, 4, 5, 6]
    positions = strat.generate_positions(closes)
    assert len(positions) == len(closes)
    # Before enough history exists, the strategy stays flat.
    assert positions[0] == 0.0
    assert positions[1] == 0.0
    assert positions[2] == 0.0
    # Each position is either flat or fully long.
    assert set(positions) <= {0.0, 1.0}


def test_demo_strategy_validates_windows():
    with pytest.raises(ValueError):
        DemoMovingAverageStrategy(short_window=5, long_window=5)


def test_backtest_with_too_few_bars_is_flat():
    strat = DemoMovingAverageStrategy()
    result = run_backtest([100.0], strat)
    assert result.num_trades == 0
    assert result.ending_equity == result.starting_cash
    assert result.is_simulation is True


def test_backtest_no_fee_no_slippage_rising_market():
    # A strategy that is always long should track the market return when there
    # are no fees or slippage.
    class AlwaysLong:
        name = "always_long"

        def generate_positions(self, closes):
            return [1.0] * len(closes)

    closes = [100.0, 110.0, 121.0]  # +10% each step
    result = run_backtest(closes, AlwaysLong(), BacktestConfig(starting_cash=1000.0))

    # No look-ahead: the bar-0 signal causes an entry at bar 1 (price 110), so
    # we capture only the 110 -> 121 move (+10%), not the first 100 -> 110 step.
    assert result.num_trades == 1
    assert result.total_fees_paid == 0.0
    assert result.total_slippage_cost == 0.0
    assert result.ending_equity == pytest.approx(1100.0)
    assert result.total_return_pct == pytest.approx(10.0)


def test_backtest_applies_fee_placeholder():
    class AlwaysLong:
        name = "always_long"

        def generate_positions(self, closes):
            return [1.0] * len(closes)

    closes = [100.0, 100.0]  # flat market isolates the cost of trading
    no_fee = run_backtest(closes, AlwaysLong(), BacktestConfig(starting_cash=1000.0))
    with_fee = run_backtest(
        closes, AlwaysLong(), BacktestConfig(starting_cash=1000.0, fee_rate=0.01)
    )

    # The fee placeholder reduces equity relative to the zero-fee run.
    assert no_fee.total_fees_paid == 0.0
    assert with_fee.total_fees_paid > 0.0
    assert with_fee.ending_equity < no_fee.ending_equity


def test_backtest_entry_fee_is_paid_without_negative_cash_financing():
    class AlwaysLong:
        name = "always_long"

        def generate_positions(self, closes):
            return [1.0] * len(closes)

    result = run_backtest(
        [100.0, 100.0],
        AlwaysLong(),
        BacktestConfig(starting_cash=1000.0, fee_rate=0.01),
    )

    assert result.total_fees_paid == pytest.approx(1000.0 / 101.0)
    assert result.ending_equity == pytest.approx(1000.0 / 1.01)


def test_backtest_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        BacktestConfig(starting_cash=0.0)
    with pytest.raises(ValueError):
        BacktestConfig(fee_rate=-0.01)
    with pytest.raises(ValueError):
        BacktestConfig(slippage_rate=1.0)


def test_backtest_rejects_invalid_prices_and_positions():
    strat = DemoMovingAverageStrategy()
    with pytest.raises(ValueError):
        run_backtest([100.0, 0.0], strat)

    class InvalidPosition:
        name = "invalid"

        def generate_positions(self, closes):
            return [0.5] * len(closes)

    with pytest.raises(ValueError):
        run_backtest([100.0, 101.0], InvalidPosition())


def test_backtest_is_always_marked_simulation():
    strat = DemoMovingAverageStrategy()
    result = run_backtest([100.0, 101.0, 102.0, 103.0], strat)
    assert result.is_simulation is True
    assert "SIMULATION" in result.summary()
