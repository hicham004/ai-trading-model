"""Tests for the risk manager skeleton (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.risk.manager import RiskContext, RiskLimits, RiskManager
from app.strategy.base import Signal, SignalAction

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _long_signal(confidence=0.9, stop_loss=98.0) -> Signal:
    return Signal(
        timestamp=NOW,
        instrument="BTC-USDT",
        action=SignalAction.LONG,
        confidence=confidence,
        reason="test",
        stop_loss=stop_loss,
    )


def _context(**overrides) -> RiskContext:
    base = dict(
        equity=10_000.0,
        reference_price=100.0,
        day_start_equity=10_000.0,
        day_realized_pnl=0.0,
        now=NOW,
        data_time=NOW,
    )
    base.update(overrides)
    return RiskContext(**base)


def test_allows_a_well_formed_entry():
    decision = RiskManager().evaluate_entry(_long_signal(), _context())
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_rejects_low_confidence():
    rm = RiskManager(RiskLimits(min_confidence=0.6))
    decision = rm.evaluate_entry(_long_signal(confidence=0.5), _context())
    assert not decision.allowed
    assert decision.reason == "confidence_too_low"


def test_rejects_missing_stop_loss():
    decision = RiskManager().evaluate_entry(_long_signal(stop_loss=None), _context())
    assert not decision.allowed
    assert decision.reason == "stop_loss_required"


def test_rejects_stop_not_below_entry():
    decision = RiskManager().evaluate_entry(
        _long_signal(stop_loss=105.0), _context(reference_price=100.0)
    )
    assert not decision.allowed
    assert decision.reason == "stop_loss_not_below_entry"


def test_rejects_stale_data():
    rm = RiskManager(RiskLimits(max_data_staleness=timedelta(minutes=30)))
    ctx = _context(data_time=NOW - timedelta(hours=2))
    decision = rm.evaluate_entry(_long_signal(), ctx)
    assert not decision.allowed
    assert decision.reason == "stale_data"


def test_one_hour_old_signal_rejected_at_one_minute_staleness():
    # Finding 2: a signal one hour old must be rejected when max staleness is
    # one minute.
    rm = RiskManager(RiskLimits(max_data_staleness=timedelta(minutes=1)))
    ctx = _context(now=NOW, data_time=NOW - timedelta(hours=1))
    decision = rm.evaluate_entry(_long_signal(), ctx)
    assert not decision.allowed
    assert decision.reason == "stale_data"


def test_rejects_future_dated_signal():
    # A signal whose data time is after the execution time is invalid.
    ctx = _context(now=NOW, data_time=NOW + timedelta(hours=1))
    decision = RiskManager().evaluate_entry(_long_signal(), ctx)
    assert not decision.allowed
    assert decision.reason == "future_signal"


def test_rejects_naive_timestamps():
    naive_now = datetime(2026, 1, 1, 12, 0)  # no tzinfo
    ctx = _context(now=naive_now, data_time=naive_now)
    decision = RiskManager().evaluate_entry(_long_signal(), ctx)
    assert not decision.allowed
    assert decision.reason == "naive_timestamp"


def test_rejects_when_daily_loss_reached():
    rm = RiskManager(RiskLimits(max_daily_loss=0.05))
    # Already lost 5% of the day's starting equity.
    ctx = _context(day_realized_pnl=-500.0, day_start_equity=10_000.0)
    decision = rm.evaluate_entry(_long_signal(), ctx)
    assert not decision.allowed
    assert decision.reason == "max_daily_loss_reached"


def test_non_entry_signal_is_not_allowed_as_entry():
    flat = Signal(timestamp=NOW, instrument="BTC-USDT", action=SignalAction.FLAT)
    decision = RiskManager().evaluate_entry(flat, _context())
    assert not decision.allowed
    assert decision.reason == "not_an_entry"


def test_position_fraction_is_bounded_by_risk_and_size():
    # Stop is 2% below entry; max risk per trade 1% -> 0.5 by risk, but capped
    # by max_position_size 0.25.
    rm = RiskManager(RiskLimits(max_risk_per_trade=0.01, max_position_size=0.25))
    frac = rm.position_fraction(_long_signal(stop_loss=98.0), _context(reference_price=100.0))
    assert frac == pytest.approx(0.25)


def test_position_fraction_scales_with_stop_distance():
    # Wider stop (10% below) -> smaller size for the same risk budget.
    rm = RiskManager(RiskLimits(max_risk_per_trade=0.01, max_position_size=1.0))
    frac = rm.position_fraction(_long_signal(stop_loss=90.0), _context(reference_price=100.0))
    assert frac == pytest.approx(0.10)


def test_leverage_must_stay_one():
    with pytest.raises(ValueError):
        RiskLimits(max_leverage=3.0)
