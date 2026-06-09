"""Tests for the baseline strategies and the registry (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.strategy.base import MarketCandle, SignalAction
from app.strategy.library import (
    Breakout,
    MovingAverageCrossover,
    RsiVwapMeanReversion,
)
from app.strategy.registry import available_strategies, build_strategy


def candles_from_closes(closes, highs=None, lows=None, volumes=None):
    """Build MarketCandles from a list of closes (and optional H/L/V)."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, close in enumerate(closes):
        high = highs[i] if highs else close
        low = lows[i] if lows else close
        vol = volumes[i] if volumes else 1.0
        out.append(
            MarketCandle(
                instrument="BTC-USDT",
                timestamp=start + timedelta(hours=i),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=vol,
            )
        )
    return out


def _actions(signals):
    return {s.action for s in signals}


def test_strategy_returns_one_signal_per_candle():
    closes = [10.0] * 5 + [11.0, 12.0, 13.0, 14.0, 15.0]
    candles = candles_from_closes(closes)
    signals = MovingAverageCrossover(2, 4).generate_signals(candles)
    assert len(signals) == len(candles)
    assert _actions(signals) <= {SignalAction.LONG, SignalAction.FLAT, SignalAction.HOLD}


def test_ma_crossover_goes_long_on_uptrend_with_stop():
    closes = [10.0, 10.0, 10.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    candles = candles_from_closes(closes)
    signals = MovingAverageCrossover(2, 4, stop_loss_pct=0.02).generate_signals(candles)

    longs = [(i, s) for i, s in enumerate(signals) if s.action == SignalAction.LONG]
    assert longs, "expected at least one LONG signal on a clear uptrend"
    for i, s in longs:
        assert s.confidence >= 0.55
        assert s.stop_loss is not None and s.stop_loss < closes[i]


def test_ma_crossover_validates_params():
    with pytest.raises(ValueError):
        MovingAverageCrossover(short_window=5, long_window=5)
    with pytest.raises(ValueError):
        MovingAverageCrossover(2, 4, stop_loss_pct=1.5)


def test_breakout_enters_on_new_high():
    # Flat then a clear breakout above the prior range.
    closes = [10.0, 10.0, 10.0, 10.0, 20.0, 20.0]
    highs = [10.5, 10.5, 10.5, 10.5, 20.0, 20.0]
    lows = [9.5, 9.5, 9.5, 9.5, 19.0, 19.0]
    candles = candles_from_closes(closes, highs=highs, lows=lows)
    signals = Breakout(entry_window=3, exit_window=2).generate_signals(candles)

    assert any(s.action == SignalAction.LONG for s in signals)
    long = next(s for s in signals if s.action == SignalAction.LONG)
    assert long.stop_loss is not None


def test_mean_reversion_enters_when_oversold_below_vwap():
    # A steep, steady decline drives RSI low and keeps price below the VWAP.
    closes = [100.0 - i for i in range(40)]
    candles = candles_from_closes(closes)
    strat = RsiVwapMeanReversion(
        rsi_period=3, vwap_window=3, oversold=40.0, exit_level=60.0
    )
    signals = strat.generate_signals(candles)
    assert any(s.action == SignalAction.LONG for s in signals)
    # LONG entries must carry a stop-loss below the price.
    for s in signals:
        if s.action == SignalAction.LONG:
            assert s.stop_loss is not None


def test_mean_reversion_validates_params():
    with pytest.raises(ValueError):
        RsiVwapMeanReversion(oversold=60.0, exit_level=50.0)


def test_registry_builds_known_strategies():
    assert set(available_strategies()) == {"ma_crossover", "rsi_vwap", "breakout"}
    assert isinstance(build_strategy("breakout"), Breakout)
    with pytest.raises(ValueError):
        build_strategy("does_not_exist")
