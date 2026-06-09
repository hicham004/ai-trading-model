"""Tests for performance-metric computation (offline)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtest.metrics import compute_metrics, max_drawdown_pct
from app.backtest.models import Trade

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(entry, exit_, qty=1.0, fees=0.0, slippage=0.0, funding=0.0) -> Trade:
    return Trade(
        instrument="BTC-USDT",
        entry_time=T0,
        exit_time=T0,
        entry_price=entry,
        exit_price=exit_,
        quantity=qty,
        fees=fees,
        slippage_cost=slippage,
        funding_cost=funding,
        exit_reason="signal",
    )


def test_trade_pnl_and_win_flag():
    win = _trade(100.0, 110.0, qty=2.0, fees=1.0)
    assert win.pnl == pytest.approx(19.0)  # (110-100)*2 - 1
    assert win.is_win is True

    loss = _trade(100.0, 90.0, qty=1.0)
    assert loss.pnl == pytest.approx(-10.0)
    assert loss.is_win is False


def test_max_drawdown():
    curve = [100, 120, 90, 110, 80]
    # Peak 120 -> trough 80 = 33.33% drop.
    assert max_drawdown_pct(curve) == pytest.approx(100 * (120 - 80) / 120)


def test_compute_metrics_mixed_trades():
    trades = [
        _trade(100.0, 110.0, fees=1.0),  # +9
        _trade(100.0, 95.0, fees=1.0),   # -6
        _trade(100.0, 120.0, fees=2.0),  # +18
    ]
    curve = [10_000.0, 10_009.0, 10_003.0, 10_021.0]
    m = compute_metrics(trades, curve, starting_cash=10_000.0)

    assert m.num_trades == 3
    assert m.win_rate_pct == pytest.approx(2 / 3 * 100)
    assert m.total_fees_paid == pytest.approx(4.0)
    gross_profit = 9.0 + 18.0
    gross_loss = 6.0
    assert m.profit_factor == pytest.approx(gross_profit / gross_loss)
    assert m.average_win == pytest.approx(gross_profit / 2)
    assert m.average_loss == pytest.approx(-6.0)
    assert m.total_return_pct == pytest.approx((10_021.0 - 10_000.0) / 10_000.0 * 100)


def test_profit_factor_infinite_when_no_losses():
    trades = [_trade(100.0, 110.0)]
    m = compute_metrics(trades, [10_000.0, 10_010.0], 10_000.0)
    assert m.profit_factor == float("inf")


def test_no_trades_is_safe():
    m = compute_metrics([], [10_000.0, 10_000.0], 10_000.0)
    assert m.num_trades == 0
    assert m.win_rate_pct == 0.0
    assert m.profit_factor == 0.0
    assert m.average_win == 0.0
    assert m.average_loss == 0.0
