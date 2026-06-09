"""Paper broker: SIMULATED fills only.

The paper broker never connects to any exchange. It takes an order and returns
a simulated fill by applying the placeholder cost model:

* BUY fills a little ABOVE the reference price (slippage works against you).
* SELL fills a little BELOW the reference price.
* A fee is charged on the traded notional.

This is the only broker implementation in Phase 2. It is safe to use freely:
it cannot place real orders, touch an account, or move funds.
"""

from __future__ import annotations

from app.broker.base import Broker, CostModel, Fill, Order, OrderSide
from app.logging_config import get_logger

logger = get_logger(__name__)


class PaperBroker(Broker):
    """A broker that fills orders against a cost model, with no real exchange."""

    # Explicit capability marker: this broker only ever produces simulated
    # fills. The backtest simulator requires this to be True.
    is_simulation: bool = True

    def __init__(self, cost_model: CostModel | None = None) -> None:
        self.cost_model = cost_model or CostModel()

    def submit(self, order: Order) -> Fill:
        slippage_rate = self.cost_model.slippage_rate
        fee_rate = self.cost_model.fee_rate

        if order.side == OrderSide.BUY:
            fill_price = order.reference_price * (1.0 + slippage_rate)
        else:
            fill_price = order.reference_price * (1.0 - slippage_rate)

        notional = fill_price * order.quantity
        fee = notional * fee_rate
        # Slippage cost = how far the fill moved from the reference price.
        slippage_cost = order.reference_price * order.quantity * slippage_rate

        fill = Fill(
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            slippage_cost=slippage_cost,
            timestamp=order.timestamp,
            is_simulated=True,
        )
        logger.info(
            "Paper fill (SIMULATED)",
            extra={
                "instrument": order.instrument,
                "side": order.side.value,
                "quantity": round(order.quantity, 8),
                "fill_price": round(fill_price, 8),
                "fee": round(fee, 8),
            },
        )
        return fill
