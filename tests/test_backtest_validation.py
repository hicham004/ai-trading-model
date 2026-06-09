"""Adverse tests for backtest input validation (offline).

Covers Codex finding 5 (signal identity/alignment) and the related market-data
integrity invariants.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.backtest.simulator import run_signal_backtest
from app.backtest.validation import validate_candles, validate_signals
from app.risk.manager import RiskLimits, RiskManager
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(i, *, instrument="BTC-USDT", o=100.0, h=101.0, lo=99.0, c=100.0,
           vol=1.0, timeframe=None, ts=None):
    return MarketCandle(
        instrument=instrument,
        timestamp=ts if ts is not None else START + timedelta(hours=i),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=vol,
        timeframe=timeframe,
    )


def good_candles(n=3, timeframe=None):
    return [candle(i, timeframe=timeframe) for i in range(n)]


# --- validate_candles ------------------------------------------------------

def test_validate_candles_accepts_clean_series():
    validate_candles(good_candles(3), expected_instrument="BTC-USDT")


def test_validate_candles_rejects_multiple_instruments():
    candles = [candle(0), candle(1, instrument="ETH-USDT")]
    with pytest.raises(ValueError):
        validate_candles(candles, expected_instrument="BTC-USDT")


def test_validate_candles_rejects_duplicate_timestamp():
    c0 = candle(0)
    dup = candle(0, ts=c0.timestamp)  # same timestamp
    with pytest.raises(ValueError):
        validate_candles([c0, dup])


def test_validate_candles_rejects_out_of_order():
    candles = [candle(0), candle(1)]
    with pytest.raises(ValueError):
        validate_candles(list(reversed(candles)))


def test_validate_candles_rejects_naive_timestamp():
    naive = MarketCandle("BTC-USDT", datetime(2026, 1, 1), 100, 101, 99, 100, 1.0)
    with pytest.raises(ValueError):
        validate_candles([naive])


def test_validate_candles_rejects_incoherent_ohlc():
    bad = candle(0, o=100, h=95, lo=99, c=100)  # high below open/low
    with pytest.raises(ValueError):
        validate_candles([bad])


def test_validate_candles_rejects_non_positive_price():
    with pytest.raises(ValueError):
        validate_candles([candle(0, o=0.0)])


def test_validate_candles_rejects_timeframe_mismatch():
    with pytest.raises(ValueError):
        validate_candles(
            [candle(0, timeframe="15m")], expected_timeframe="1H"
        )


# --- validate_signals ------------------------------------------------------

def sig(c, action=SignalAction.FLAT, timeframe=None):
    return Signal(
        timestamp=c.timestamp,
        instrument=c.instrument,
        action=action,
        timeframe=timeframe,
    )


def test_validate_signals_accepts_aligned():
    candles = good_candles(3)
    signals = [sig(c) for c in candles]
    validate_signals(signals, candles, expected_instrument="BTC-USDT")


def test_validate_signals_rejects_count_mismatch():
    candles = good_candles(3)
    with pytest.raises(ValueError):
        validate_signals([sig(candles[0])], candles)


def test_validate_signals_rejects_instrument_mismatch():
    candles = good_candles(2)
    signals = [sig(candles[0]), Signal(candles[1].timestamp, "ETH-USDT", SignalAction.FLAT)]
    with pytest.raises(ValueError):
        validate_signals(signals, candles, expected_instrument="BTC-USDT")


def test_validate_signals_rejects_timestamp_misalignment():
    candles = good_candles(2)
    shifted = Signal(
        candles[1].timestamp + timedelta(minutes=5), "BTC-USDT", SignalAction.FLAT
    )
    with pytest.raises(ValueError):
        validate_signals([sig(candles[0]), shifted], candles)


def test_validate_signals_rejects_timeframe_mismatch():
    candles = good_candles(1, timeframe="1H")
    signals = [sig(candles[0], timeframe="15m")]
    with pytest.raises(ValueError):
        validate_signals(signals, candles, expected_timeframe="1H")


# --- simulator-level integration (fails closed) ----------------------------

def _permissive_risk():
    return RiskManager(RiskLimits(max_risk_per_trade=0.5, max_position_size=1.0))


def test_simulator_rejects_wrong_instrument_signals():
    class WrongInstrument(Strategy):
        name = "wrong_instrument"

        def generate_signals(self, candles):
            return [
                Signal(
                    timestamp=c.timestamp,
                    instrument="ETH-USDT",  # never matches BTC candles
                    action=SignalAction.LONG,
                    confidence=1.0,
                    stop_loss=c.close * 0.5,
                )
                for c in candles
            ]

    with pytest.raises(ValueError):
        run_signal_backtest(
            good_candles(3), WrongInstrument(), risk_manager=_permissive_risk()
        )


def test_simulator_rejects_misaligned_timestamps():
    class ShiftedSignals(Strategy):
        name = "shifted"

        def generate_signals(self, candles):
            return [
                Signal(
                    timestamp=c.timestamp + timedelta(minutes=1),  # misaligned
                    instrument=c.instrument,
                    action=SignalAction.FLAT,
                )
                for c in candles
            ]

    with pytest.raises(ValueError):
        run_signal_backtest(
            good_candles(3), ShiftedSignals(), risk_manager=_permissive_risk()
        )
