"""Tests for the backtest runner over stored candles (offline, in-memory DB)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.backtest.runner import (
    load_market_candles,
    run_backtest_on_stored_candles,
)
from app.db.models import Candle as CandleRow
from app.strategy.base import Signal, SignalAction, Strategy
from app.strategy.library import MovingAverageCrossover


class _AlwaysLong(Strategy):
    """Always emit a LONG signal with a stop well below price."""

    name = "always_long"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                action=SignalAction.LONG,
                confidence=1.0,
                stop_loss=c.close * 0.9,
            )
            for c in candles
        ]


def _seed_constant(session, timeframe, interval, n=30, price=100.0):
    """Insert ``n`` flat-price candles spaced ``interval`` apart."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        CandleRow(
            instrument="BTC-USDT",
            timeframe=timeframe,
            open_time=start + interval * i,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=10.0,
        )
        for i in range(n)
    ]
    session.add_all(rows)
    session.commit()


def _seed(session, n=60):
    """Insert ``n`` BTC-USDT 1H candles following a gentle sine wave."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        price = 100.0 + 10.0 * math.sin(i / 5.0)
        rows.append(
            CandleRow(
                instrument="BTC-USDT",
                timeframe="1H",
                open_time=start + timedelta(hours=i),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=10.0,
            )
        )
    session.add_all(rows)
    session.commit()


def test_load_market_candles_returns_utc_oldest_first(db_session):
    _seed(db_session, n=5)
    candles = load_market_candles(db_session, "BTC-USDT", "1H")
    assert len(candles) == 5
    times = [c.timestamp for c in candles]
    assert times == sorted(times)
    assert all(c.timestamp.tzinfo is not None for c in candles)


def test_runner_executes_strategy_over_stored_candles(db_session):
    _seed(db_session, n=60)
    result = run_backtest_on_stored_candles(
        db_session, MovingAverageCrossover(5, 15), "BTC-USDT", "1H"
    )
    assert result.bars == 60
    assert result.instrument == "BTC-USDT"
    assert result.timeframe == "1H"
    assert result.is_simulation is True
    assert result.metrics.num_trades >= 0
    assert len(result.equity_curve) == 60


def test_runner_requires_enough_candles(db_session):
    _seed(db_session, n=1)
    with pytest.raises(ValueError):
        run_backtest_on_stored_candles(
            db_session, MovingAverageCrossover(5, 15), "BTC-USDT", "1H"
        )


def test_runner_is_timeframe_aware_for_4h(db_session):
    # Regression: calling the runner directly (no explicit risk_manager) must be
    # timeframe-aware. A valid previous-bar 4H signal must NOT be rejected as
    # stale (the old fixed two-hour default would have rejected all of them).
    _seed_constant(db_session, "4H", timedelta(hours=4), n=30)
    result = run_backtest_on_stored_candles(
        db_session, _AlwaysLong(), "BTC-USDT", "4H"
    )
    assert result.rejected_entries == 0
    assert result.metrics.num_trades >= 1


def test_runner_is_timeframe_aware_for_1d(db_session):
    _seed_constant(db_session, "1D", timedelta(days=1), n=30)
    result = run_backtest_on_stored_candles(
        db_session, _AlwaysLong(), "BTC-USDT", "1D"
    )
    assert result.rejected_entries == 0
    assert result.metrics.num_trades >= 1
