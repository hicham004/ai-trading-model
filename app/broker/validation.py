"""Fail-closed validation for SIMULATED broker fills.

This is the single, shared guard that both the historical backtest simulator
(:mod:`app.backtest.simulator`) and the Phase 4 forward paper-trading engine
(:mod:`app.paper.execution`) use before they account for a fill. Centralising
it means there is exactly one definition of "a fill we are allowed to trust",
so the two execution paths can never drift apart on safety.

A fill is accepted only when it:

* is explicitly marked simulated (``is_simulated`` is True);
* matches the submitted order's instrument, side, and timestamp;
* has a positive, finite price and quantity;
* matches the order's quantity (tolerating only float rounding); and
* carries non-negative, finite fee and slippage figures.

Any violation raises :class:`ValueError` BEFORE the caller mutates cash or a
position, so a bad fill can never produce partial monetary state.
"""

from __future__ import annotations

from math import isclose, isfinite

from app.broker.base import Fill, Order

# Relative/absolute tolerances for matching a fill's quantity to the order's.
# Tight enough to catch real mismatches (e.g. a doubled quantity) while
# tolerating only floating-point rounding.
QTY_REL_TOL = 1e-9
QTY_ABS_TOL = 1e-12


def validate_simulated_fill(fill: Fill, order: Order) -> None:
    """Validate ``fill`` against ``order``. Raise ``ValueError`` if untrusted.

    Callers MUST run this before accounting for the fill so a malformed or
    non-simulated fill can never mutate balances or positions.
    """
    if not getattr(fill, "is_simulated", False):
        raise ValueError(
            "Refused a non-simulated fill (fill.is_simulated is False)."
        )
    if fill.instrument != order.instrument:
        raise ValueError("Broker fill instrument does not match the submitted order.")
    if fill.side != order.side:
        raise ValueError("Broker fill side does not match the submitted order.")
    if not (isfinite(fill.price) and fill.price > 0):
        raise ValueError("Broker fill price must be positive and finite.")
    if not (isfinite(fill.quantity) and fill.quantity > 0):
        raise ValueError("Broker fill quantity must be positive and finite.")
    # Strict quantity match (tolerating only float rounding).
    if not isclose(
        fill.quantity, order.quantity, rel_tol=QTY_REL_TOL, abs_tol=QTY_ABS_TOL
    ):
        raise ValueError("Broker fill quantity does not match the submitted order.")
    if fill.timestamp != order.timestamp:
        raise ValueError("Broker fill timestamp does not match the submitted order.")
    if not (isfinite(fill.fee) and fill.fee >= 0):
        raise ValueError("Broker fill fee must be a non-negative finite number.")
    if not (isfinite(fill.slippage_cost) and fill.slippage_cost >= 0):
        raise ValueError("Broker fill slippage must be a non-negative finite number.")
