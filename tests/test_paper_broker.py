"""Tests for the paper broker and cost model (offline, simulated only)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.broker.base import CostModel, Order, OrderSide
from app.broker.paper import PaperBroker


def _order(side: OrderSide, qty=2.0, price=100.0) -> Order:
    return Order(
        instrument="BTC-USDT",
        side=side,
        quantity=qty,
        reference_price=price,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_buy_fill_includes_slippage_and_fee():
    broker = PaperBroker(CostModel(fee_rate=0.001, slippage_rate=0.01))
    fill = broker.submit(_order(OrderSide.BUY, qty=2.0, price=100.0))

    assert fill.is_simulated is True
    assert fill.price == pytest.approx(101.0)  # +1% slippage
    assert fill.slippage_cost == pytest.approx(2.0)  # 2 units * 100 * 1%
    assert fill.fee == pytest.approx(101.0 * 2.0 * 0.001)


def test_sell_fill_is_below_reference():
    broker = PaperBroker(CostModel(slippage_rate=0.01))
    fill = broker.submit(_order(OrderSide.SELL, qty=1.0, price=100.0))
    assert fill.price == pytest.approx(99.0)  # -1% slippage


def test_zero_cost_model_is_frictionless():
    broker = PaperBroker()
    fill = broker.submit(_order(OrderSide.BUY, qty=3.0, price=50.0))
    assert fill.price == pytest.approx(50.0)
    assert fill.fee == 0.0
    assert fill.slippage_cost == 0.0


def test_cost_model_rejects_out_of_range():
    with pytest.raises(ValueError):
        CostModel(fee_rate=1.0)
    with pytest.raises(ValueError):
        CostModel(slippage_rate=-0.1)


def test_order_rejects_invalid_values():
    with pytest.raises(ValueError):
        _order(OrderSide.BUY, qty=0.0)
    with pytest.raises(ValueError):
        _order(OrderSide.BUY, price=0.0)
