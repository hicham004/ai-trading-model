"""Tests for the pure indicator helpers (offline)."""

from __future__ import annotations

import pytest

from app.strategy.indicators import (
    rolling_max,
    rolling_min,
    rolling_vwap,
    rsi,
    simple_moving_average,
)


def test_sma_warmup_and_values():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    sma = simple_moving_average(values, 3)
    assert sma[0] is None and sma[1] is None
    assert sma[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert sma[3] == pytest.approx(3.0)
    assert sma[4] == pytest.approx(4.0)


def test_sma_rejects_bad_window():
    with pytest.raises(ValueError):
        simple_moving_average([1.0], 0)


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 20)]  # strictly increasing
    values = rsi(closes, period=14)
    assert values[:14] == [None] * 14
    assert values[14] == pytest.approx(100.0)


def test_rsi_all_losses_is_0():
    closes = [float(i) for i in range(20, 1, -1)]  # strictly decreasing
    values = rsi(closes, period=14)
    assert values[14] == pytest.approx(0.0)


def test_rsi_handles_short_input():
    assert rsi([1.0, 2.0], period=14) == [None, None]


def test_rolling_vwap_basic():
    highs = [10, 10, 10, 10]
    lows = [10, 10, 10, 10]
    closes = [10, 10, 10, 10]
    volumes = [1, 1, 1, 1]
    vwap = rolling_vwap(highs, lows, closes, volumes, window=2)
    assert vwap[0] is None
    assert vwap[1] == pytest.approx(10.0)


def test_rolling_vwap_zero_volume_is_none():
    vwap = rolling_vwap([1, 2], [1, 2], [1, 2], [0, 0], window=1)
    assert vwap == [None, None]


def test_rolling_max_and_min():
    values = [3.0, 1.0, 4.0, 1.0, 5.0]
    assert rolling_max(values, 2) == [None, 3.0, 4.0, 4.0, 5.0]
    assert rolling_min(values, 2) == [None, 1.0, 1.0, 1.0, 1.0]
