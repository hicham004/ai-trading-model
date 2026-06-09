"""Virtual execution for Phase 4 paper trading (SIMULATION ONLY).

This module turns an intent to trade into a validated, simulated :class:`Fill`.
It is a thin, deterministic layer over the accepted Phase 2 ``PaperBroker``,
which performs only local arithmetic and has no network code whatsoever, so the
execution path is *technically incapable* of contacting an exchange.

Two execution entry points exist:

* :func:`execute_at_quote` - fills against a fresh, synchronized best bid/ask
  (BUY against the ask, SELL against the bid), then applies the configured
  adverse slippage and fee. This is the normal entry/exit path. The spread is
  modelled implicitly: a round trip pays ask on the way in and bid on the way
  out.
* :func:`execute_at_price` - fills at a caller-supplied reference price (used
  only for protective stop exits, where the realistic fill is the stop price,
  or the worse open on an adverse gap, rather than a live quote).

Both validate the returned fill with the shared
:func:`~app.broker.validation.validate_simulated_fill` guard before returning,
so a malformed or non-simulated fill never escapes this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Optional

from app.broker.base import Broker, Fill, Order, OrderSide
from app.broker.validation import validate_simulated_fill


class ExecutionError(ValueError):
    """Raised when a virtual fill cannot be produced safely (fail closed)."""


@dataclass(frozen=True)
class QuoteSnapshot:
    """A point-in-time best bid/ask used to price a virtual fill.

    ``timestamp`` is the market/observation time of the quote (UTC).
    ``synchronized`` reflects whether the underlying public order book passed
    sequence-continuity validation; an unsynchronized quote must never price a
    fill. ``source`` is a short label (e.g. ``"order_book"``) for the audit
    trail. A quote is only *usable* when both sides are positive, finite, and
    coherent (bid <= ask) and the book is synchronized.
    """

    instrument: str
    bid: float
    ask: float
    timestamp: datetime
    synchronized: bool
    source: str = "order_book"

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0

    def prices_finite_and_coherent(self) -> bool:
        return (
            isfinite(self.bid)
            and isfinite(self.ask)
            and self.bid > 0
            and self.ask > 0
            and self.bid <= self.ask
        )

    def is_usable(self) -> bool:
        """A quote may price a fill only when synchronized AND coherent."""
        return self.synchronized and self.prices_finite_and_coherent()

    def touch_price(self, side: OrderSide) -> float:
        """The price a marketable order of ``side`` crosses (ask buy / bid sell)."""
        return self.ask if side == OrderSide.BUY else self.bid


@dataclass(frozen=True)
class FeedStatus:
    """Aggregate live-feed health used to gate virtual execution.

    ``connected`` and ``stale`` mirror the read-only live health snapshot.
    Entries are blocked unless the feed is connected and not stale; protective
    exits have their own, narrower rules in the engine.
    """

    connected: bool
    stale: bool

    @property
    def usable(self) -> bool:
        return self.connected and not self.stale


def _submit_validated(broker: Broker, order: Order) -> Fill:
    """Fail closed unless the broker is a simulation and returns a valid fill."""
    if not getattr(broker, "is_simulation", False):
        raise ExecutionError(
            "Paper execution requires a simulation broker "
            "(broker.is_simulation must be True). Refusing to fill."
        )
    fill = broker.submit(order)
    validate_simulated_fill(fill, order)
    return fill


def execute_at_quote(
    broker: Broker,
    *,
    instrument: str,
    side: OrderSide,
    quantity: float,
    quote: Optional[QuoteSnapshot],
    when: datetime,
) -> Fill:
    """Fill ``quantity`` of ``instrument`` against a usable ``quote``.

    BUY crosses the ask and SELL crosses the bid; the broker then applies the
    configured adverse slippage and fee. Raises :class:`ExecutionError` (before
    any fill) if the quote is missing/unsynchronized/incoherent, the quote
    instrument disagrees, or the quantity is not a positive finite number.
    """
    if quote is None or not quote.is_usable():
        raise ExecutionError("no usable synchronized quote available for fill")
    if quote.instrument != instrument:
        raise ExecutionError("quote instrument does not match the order instrument")
    if not (isfinite(quantity) and quantity > 0):
        raise ExecutionError("fill quantity must be a positive finite number")
    reference_price = quote.touch_price(side)
    order = Order(
        instrument=instrument,
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        timestamp=when,
    )
    return _submit_validated(broker, order)


def execute_at_price(
    broker: Broker,
    *,
    instrument: str,
    side: OrderSide,
    quantity: float,
    reference_price: float,
    when: datetime,
) -> Fill:
    """Fill at an explicit ``reference_price`` (protective stop exits only).

    Used when the realistic fill is a candle-derived price (the stop, or the
    worse open on an adverse gap) rather than a live quote. The broker still
    applies adverse slippage and the fee on top.
    """
    if not (isfinite(quantity) and quantity > 0):
        raise ExecutionError("fill quantity must be a positive finite number")
    if not (isfinite(reference_price) and reference_price > 0):
        raise ExecutionError("reference price must be a positive finite number")
    order = Order(
        instrument=instrument,
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        timestamp=when,
    )
    return _submit_validated(broker, order)
