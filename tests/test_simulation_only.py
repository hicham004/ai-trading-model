"""Adverse tests for simulation-only enforcement (offline).

Covers Codex finding 4: the backtest must fail closed if given a broker that is
not explicitly a simulation, or a broker that returns a non-simulated fill.
No real/live broker is implemented here; these are test doubles only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.broker.base import Broker, Fill, Order, OrderSide
from app.backtest.simulator import run_signal_backtest
from app.risk.manager import RiskLimits, RiskManager
from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candles(n=3) -> List[MarketCandle]:
    return [
        MarketCandle(
            instrument="BTC-USDT",
            timestamp=START + timedelta(hours=i),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1.0,
        )
        for i in range(n)
    ]


class AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, candles):
        return [
            Signal(
                timestamp=c.timestamp,
                instrument=c.instrument,
                action=SignalAction.LONG,
                confidence=1.0,
                reason="always",
                stop_loss=c.close * 0.5,
            )
            for c in candles
        ]


def _permissive_risk():
    return RiskManager(RiskLimits(max_risk_per_trade=0.5, max_position_size=1.0))


class NonSimBroker(Broker):
    """A broker NOT marked as a simulation (inherits is_simulation = False)."""

    def __init__(self):
        self.submit_calls = 0

    def submit(self, order: Order) -> Fill:
        self.submit_calls += 1
        return Fill(
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=order.reference_price,
            fee=0.0,
            slippage_cost=0.0,
            timestamp=order.timestamp,
            is_simulated=False,
        )


class LyingBroker(Broker):
    """Claims to be a simulation but returns a non-simulated fill."""

    is_simulation = True

    def __init__(self):
        self.submit_calls = 0

    def submit(self, order: Order) -> Fill:
        self.submit_calls += 1
        return Fill(
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=order.reference_price,
            fee=0.0,
            slippage_cost=0.0,
            timestamp=order.timestamp,
            is_simulated=False,  # the lie
        )


def test_backtest_rejects_non_simulation_broker_before_any_submit():
    broker = NonSimBroker()
    with pytest.raises(ValueError):
        run_signal_backtest(
            make_candles(), AlwaysLong(), risk_manager=_permissive_risk(), broker=broker
        )
    # Rejected up front: the broker is never even asked to fill an order.
    assert broker.submit_calls == 0


def test_backtest_rejects_broker_that_returns_non_simulated_fill():
    broker = LyingBroker()
    with pytest.raises(ValueError):
        run_signal_backtest(
            make_candles(), AlwaysLong(), risk_manager=_permissive_risk(), broker=broker
        )
    # It passed the capability gate, so the first entry submit happens, but the
    # fill is rejected before any accounting; the run aborts (no further bars).
    assert broker.submit_calls == 1


def test_default_paper_broker_is_accepted():
    # Sanity: the real PaperBroker is explicitly a simulation and runs fine.
    result = run_signal_backtest(
        make_candles(), AlwaysLong(), risk_manager=_permissive_risk()
    )
    assert result.is_simulation is True


class BadFillBroker(Broker):
    """Simulated broker that returns a fill mismatching the submitted order.

    ``mutate`` receives the faithful fill kwargs plus the order and returns the
    (corrupted) kwargs used to build the returned Fill.
    """

    is_simulation = True

    def __init__(self, mutate):
        self.submit_calls = 0
        self.mutate = mutate

    def submit(self, order: Order) -> Fill:
        self.submit_calls += 1
        kwargs = dict(
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=order.reference_price,
            fee=0.0,
            slippage_cost=0.0,
            timestamp=order.timestamp,
            is_simulated=True,
        )
        return Fill(**self.mutate(kwargs, order))


def _double_quantity(kwargs, order):
    kwargs["quantity"] = order.quantity * 2.0
    return kwargs


def _wrong_timestamp(kwargs, order):
    kwargs["timestamp"] = order.timestamp + timedelta(hours=1)
    return kwargs


def _wrong_instrument(kwargs, order):
    kwargs["instrument"] = "ETH-USDT"
    return kwargs


def _wrong_side(kwargs, order):
    kwargs["side"] = OrderSide.SELL if order.side == OrderSide.BUY else OrderSide.BUY
    return kwargs


@pytest.mark.parametrize(
    "mutate",
    [_double_quantity, _wrong_timestamp, _wrong_instrument, _wrong_side],
    ids=["double_quantity", "wrong_timestamp", "wrong_instrument", "wrong_side"],
)
def test_backtest_rejects_fill_not_matching_order(mutate):
    broker = BadFillBroker(mutate)
    with pytest.raises(ValueError):
        run_signal_backtest(
            make_candles(), AlwaysLong(), risk_manager=_permissive_risk(), broker=broker
        )
    # Rejected on the first (entry) fill, before any cash/position/trade
    # accounting, so the run aborts without partial state.
    assert broker.submit_calls == 1
