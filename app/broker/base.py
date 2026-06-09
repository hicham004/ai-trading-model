"""Abstract broker interface plus order / fill / cost-model value objects.

The :class:`Broker` interface is deliberately tiny: submit an :class:`Order`,
get back a :class:`Fill`. Backtests, paper trading, and (much later, behind a
separate human-approved phase) a live broker can all implement the same shape,
so the rest of the system never needs to know which one is in use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class CostModel:
    """PLACEHOLDER trading-cost assumptions. All default to zero.

    These are simple stand-ins so the simulation structure is ready for a more
    realistic cost model later:

    * ``fee_rate`` - taker/maker fee as a fraction of traded notional.
    * ``slippage_rate`` - price impact as a fraction of price, applied against
      you on entry and exit.
    * ``funding_rate`` - PLACEHOLDER periodic financing charged per bar a
      position is held. Only meaningful for future margin/perpetual research;
      for spot it stays 0. It never implies real leverage.
    """

    fee_rate: float = 0.0
    slippage_rate: float = 0.0
    funding_rate: float = 0.0

    def __post_init__(self) -> None:
        for label, value in (
            ("fee_rate", self.fee_rate),
            ("slippage_rate", self.slippage_rate),
            ("funding_rate", self.funding_rate),
        ):
            if not isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{label} must be between 0.0 (inclusive) and 1.0")


@dataclass(frozen=True)
class Order:
    """A request to trade. ``reference_price`` is the price the decision used."""

    instrument: str
    side: OrderSide
    quantity: float
    reference_price: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.quantity <= 0 or not isfinite(self.quantity):
            raise ValueError("order quantity must be a positive finite number")
        if self.reference_price <= 0 or not isfinite(self.reference_price):
            raise ValueError("reference_price must be a positive finite number")


@dataclass(frozen=True)
class Fill:
    """The result of executing an order.

    ``price`` already includes slippage. ``fee`` and ``slippage_cost`` are
    reported separately so they can be summed into performance metrics.
    ``is_simulated`` is always True in Phase 2.
    """

    instrument: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    slippage_cost: float
    timestamp: datetime
    is_simulated: bool = True


class Broker(ABC):
    """Abstract execution interface. Implementations return a :class:`Fill`.

    ``is_simulation`` is an explicit capability marker, NOT a naming
    convention. It defaults to ``False`` so a broker is treated as
    non-simulated unless it deliberately opts in. The backtest simulator
    refuses any broker whose ``is_simulation`` is not ``True`` (and also
    rejects any fill whose ``is_simulated`` flag is false), so an
    execution-capable broker can never silently enter the backtest path.
    """

    #: Subclasses that produce only simulated fills must set this to True.
    is_simulation: bool = False

    @abstractmethod
    def submit(self, order: Order) -> Fill:
        """Execute ``order`` and return the resulting fill."""
        raise NotImplementedError
