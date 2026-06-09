"""Risk manager skeleton: limits, an entry veto, and position sizing.

The risk manager is the single gate every entry must pass. It enforces:

* a minimum confidence (no trade if the strategy is unsure),
* a required, valid stop-loss below the entry price,
* a data-freshness check (no trade on stale data),
* a max daily loss kill-switch (stop opening trades after a bad day),
* position sizing bounded by max risk-per-trade and max position size,
* a max-leverage PLACEHOLDER (kept at 1.0 == no leverage in research).

These rules are intentionally simple but real: the backtest simulator obeys
them, and they are the same checks a future paper/demo/live path must reuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Optional

from app.logging_config import get_logger
from app.strategy.base import Signal, SignalAction

logger = get_logger(__name__)


@dataclass(frozen=True)
class RiskLimits:
    """Risk limits. Defaults are conservative and research-only.

    Attributes:
        max_risk_per_trade: fraction of equity risked between entry and stop.
        max_daily_loss: fraction of the day's starting equity; once realised
            losses reach this, no new entries are allowed for the rest of the
            (UTC) day.
        max_position_size: hard cap on the fraction of equity in one position.
        max_leverage: PLACEHOLDER. Must stay 1.0 in research (no leverage).
            Real-exchange leverage is forbidden by the project rules.
        min_confidence: entries below this confidence are rejected.
        max_data_staleness: reject entries when the latest data is older than
            this relative to "now".
        require_stop_loss: when True, an entry without a valid stop is rejected.
    """

    max_risk_per_trade: float = 0.01
    max_daily_loss: float = 0.05
    max_position_size: float = 0.25
    max_leverage: float = 1.0
    min_confidence: float = 0.50
    max_data_staleness: timedelta = timedelta(hours=2)
    require_stop_loss: bool = True

    def __post_init__(self) -> None:
        fractions = {
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_daily_loss": self.max_daily_loss,
            "max_position_size": self.max_position_size,
            "min_confidence": self.min_confidence,
        }
        for label, value in fractions.items():
            if not isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{label} must be in (0.0, 1.0]")
        # Safety lock: research and all near-term phases are spot, no leverage.
        if self.max_leverage != 1.0:
            raise ValueError(
                "max_leverage must be 1.0 in this phase. Real-exchange leverage "
                "is not allowed (see PROJECT_RULES.md)."
            )
        if self.max_data_staleness <= timedelta(0):
            raise ValueError("max_data_staleness must be positive")


@dataclass(frozen=True)
class RiskContext:
    """Live facts the risk manager needs to judge an entry.

    ``now`` and ``data_time`` are deliberately distinct:

    * ``now`` is the decision/execution time (in a backtest, the timestamp of
      the candle on which the order would execute).
    * ``data_time`` is the signal's source-data time (the timestamp of the
      candle that produced the signal).

    Both must be timezone-aware. A signal whose ``data_time`` is older than the
    allowed staleness, or is in the future relative to ``now``, is rejected.
    """

    equity: float
    reference_price: float
    day_start_equity: float
    day_realized_pnl: float
    now: datetime  # decision/execution time
    data_time: datetime  # signal source-data time


@dataclass(frozen=True)
class RiskDecision:
    """The risk manager's verdict for a single entry."""

    allowed: bool
    reason: str


class RiskManager:
    """Vets entries and sizes positions. Final veto over every entry."""

    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate_entry(self, signal: Signal, context: RiskContext) -> RiskDecision:
        """Decide whether a LONG entry is allowed. Returns a reasoned verdict."""
        limits = self.limits

        if signal.action != SignalAction.LONG:
            return RiskDecision(False, "not_an_entry")

        if signal.confidence < limits.min_confidence:
            return RiskDecision(False, "confidence_too_low")

        if limits.require_stop_loss and signal.stop_loss is None:
            return RiskDecision(False, "stop_loss_required")

        if signal.stop_loss is not None and signal.stop_loss >= context.reference_price:
            return RiskDecision(False, "stop_loss_not_below_entry")

        # Timestamps must be timezone-aware so age comparisons are unambiguous.
        if context.now.tzinfo is None or context.data_time.tzinfo is None:
            return RiskDecision(False, "naive_timestamp")

        # A signal dated after the execution time is invalid (look-ahead/clock
        # error) and must never be acted on.
        if context.data_time > context.now:
            return RiskDecision(False, "future_signal")

        # The signal's source data must not be older than the allowed staleness.
        if context.now - context.data_time > limits.max_data_staleness:
            return RiskDecision(False, "stale_data")

        daily_loss_limit = -limits.max_daily_loss * context.day_start_equity
        if context.day_realized_pnl <= daily_loss_limit:
            return RiskDecision(False, "max_daily_loss_reached")

        return RiskDecision(True, "ok")

    def position_fraction(self, signal: Signal, context: RiskContext) -> float:
        """Fraction of equity to allocate, bounded by the risk limits.

        Sizing ties the position to the stop distance: risking at most
        ``max_risk_per_trade`` of equity if the stop is hit, and never more
        than ``max_position_size`` of equity in the position. There is no
        martingale or averaging-down: size depends only on the stop distance,
        never on prior wins or losses.
        """
        if signal.stop_loss is None:
            return 0.0
        ref = context.reference_price
        risk_per_unit = (ref - signal.stop_loss) / ref
        if risk_per_unit <= 0:
            return 0.0
        fraction_by_risk = self.limits.max_risk_per_trade / risk_per_unit
        return max(0.0, min(fraction_by_risk, self.limits.max_position_size))
