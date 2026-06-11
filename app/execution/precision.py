"""Decimal tick-size / lot-size / minimum-size / balance validation (SPOT).

All exchange order math is done with :class:`Decimal` to avoid float drift in
price/size quantization. The functions here are pure and deterministic.

Long-only SPOT cash rules enforced:

* a BUY (entry) must not exceed available quote-currency balance or the
  per-order notional cap;
* a SELL (exit) must not exceed the available base-currency balance (no
  shorting, no overselling);
* price is rounded to the instrument tick size; size is floored to the lot
  size; the result must still meet the minimum size; and
* nothing non-finite or non-positive is ever allowed through.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from app.exchange.instruments import InstrumentMeta


class PrecisionError(ValueError):
    """Raised when an order cannot be expressed within instrument rules."""


def to_decimal(value: object, label: str = "value") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PrecisionError(f"{label} is not a valid decimal: {value!r}") from exc
    if not result.is_finite():
        raise PrecisionError(f"{label} must be finite: {value!r}")
    return result


def quantize_price(price: Decimal, tick: Decimal) -> Decimal:
    """Round ``price`` to the nearest tick (half-up), staying positive."""
    if price <= 0 or tick <= 0:
        raise PrecisionError("price and tick must be positive")
    steps = (price / tick).to_integral_value(rounding=ROUND_HALF_UP)
    result = steps * tick
    if result <= 0:
        raise PrecisionError("quantized price collapsed to zero")
    return result.normalize()


def floor_size(size: Decimal, lot: Decimal) -> Decimal:
    """Floor ``size`` down to a whole multiple of the lot size."""
    if size < 0 or lot <= 0:
        raise PrecisionError("size must be non-negative and lot positive")
    steps = (size / lot).to_integral_value(rounding=ROUND_DOWN)
    return (steps * lot).normalize()


@dataclass(frozen=True)
class ValidatedOrder:
    """An order rounded to instrument rules and checked against balances."""

    instrument: str
    side: str  # "buy" or "sell"
    price: Decimal
    size: Decimal
    notional: Decimal


def validate_buy(
    *,
    meta: InstrumentMeta,
    price: Decimal,
    desired_size: Decimal,
    available_quote: Decimal,
    max_notional: Decimal,
) -> ValidatedOrder:
    """Validate/round a long entry (BUY) against rules, balance, and the cap."""
    if not meta.is_tradable():
        raise PrecisionError(f"instrument {meta.instrument} is not a tradable SPOT pair")
    price_q = quantize_price(price, meta.tick_size)
    size_q = floor_size(desired_size, meta.lot_size)
    if size_q < meta.min_size:
        raise PrecisionError(
            f"size {size_q} below minimum {meta.min_size} for {meta.instrument}"
        )
    notional = (price_q * size_q).normalize()
    if notional > max_notional:
        raise PrecisionError(
            f"order notional {notional} exceeds the per-order cap {max_notional}"
        )
    if notional > available_quote:
        raise PrecisionError(
            f"insufficient {meta.quote_ccy} balance: need {notional}, have {available_quote}"
        )
    return ValidatedOrder(
        instrument=meta.instrument,
        side="buy",
        price=price_q,
        size=size_q,
        notional=notional,
    )


def validate_sell(
    *,
    meta: InstrumentMeta,
    price: Decimal,
    base_balance: Decimal,
) -> ValidatedOrder:
    """Validate/round a full long exit (SELL). Never sells more than is held."""
    if not meta.is_tradable():
        raise PrecisionError(f"instrument {meta.instrument} is not a tradable SPOT pair")
    price_q = quantize_price(price, meta.tick_size)
    size_q = floor_size(base_balance, meta.lot_size)
    if size_q <= 0 or size_q < meta.min_size:
        raise PrecisionError(
            f"sellable size {size_q} below minimum {meta.min_size} for {meta.instrument}"
        )
    if size_q > base_balance:  # defensive: floor can only reduce, never exceed
        raise PrecisionError("refusing to sell more than the held base balance")
    return ValidatedOrder(
        instrument=meta.instrument,
        side="sell",
        price=price_q,
        size=size_q,
        notional=(price_q * size_q).normalize(),
    )


def is_flat(position: Decimal, lot_size: Decimal) -> bool:
    """True when no sellable position remains at the instrument's lot size.

    OKX charges SPOT buy fees in the base currency at finer precision than the
    lot size, so a fully exited position can carry an unsellable sub-lot
    residue (observed live: 1.2E-10 BTC after a 0.00015988 BTC round trip).
    Operationally "flat" therefore means floor(position, lot_size) == 0, never
    position == 0, which is unreachable whenever the entry fee is not a lot
    multiple.

    Currently used by reporting/operator-tooling paths only. The safety core
    still treats position > 0 as open (DemoStore.position_summary consumers:
    the driver's per-candle stop check and exit gating); adopting this
    definition there is a future, separately reviewed change.
    """
    if position <= 0:
        return True
    return floor_size(position, lot_size) == 0


def decimal_to_str(value: Decimal) -> str:
    """Render a Decimal as a plain (non-exponent) string for OKX params."""
    return format(value.normalize(), "f")
