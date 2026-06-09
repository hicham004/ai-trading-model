"""Phase 4 risk controls (SIMULATION ONLY).

Every paper entry must pass the deterministic risk manager, which holds the
final veto. Phase 4 layers *environmental* gates (live-feed health, order-book
synchronization, quote freshness, portfolio exposure, open-position count, and
a local kill switch) on top of the accepted Phase 2
:class:`~app.risk.manager.RiskManager`, which still enforces the per-entry
rules (confidence floor, required valid stop-loss below entry, naive/future/
stale-signal rejection, and the daily realised-loss lockout) and still performs
risk-based position sizing.

Composition - not duplication - keeps the accepted Phase 2 risk logic untouched
and authoritative: this layer calls into it and only *adds* refusals. A
no-trade decision is always valid and is preferred whenever required state is
uncertain. The kill switch, daily-loss lockout, and feed/quote checks block new
*entries* only; protective exits are handled by the engine and are never
blocked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import isfinite
from typing import Optional

from app.logging_config import get_logger
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.risk.manager import RiskContext, RiskDecision, RiskLimits, RiskManager
from app.strategy.base import Signal, SignalAction

logger = get_logger(__name__)


@dataclass(frozen=True)
class PaperRiskLimits:
    """Phase 4 risk limits: the Phase 2 limits plus environmental caps.

    Attributes:
        base: the accepted Phase 2 :class:`RiskLimits` (confidence floor,
            required stop, max risk-per-trade, max position size, daily-loss
            limit, signal staleness, and the leverage lock at 1.0).
        max_total_exposure: hard cap on the fraction of equity held across all
            open positions combined.
        max_open_positions: hard cap on the number of simultaneously open
            positions.
        max_quote_age: a best bid/ask older than this (relative to the decision
            time) is too stale to price a fill.
        future_quote_tolerance: small allowance for clock skew before a quote
            dated after the decision time is rejected.
    """

    base: RiskLimits = field(default_factory=RiskLimits)
    max_total_exposure: float = 0.50
    max_open_positions: int = 1
    max_quote_age: timedelta = timedelta(seconds=10)
    future_quote_tolerance: timedelta = timedelta(seconds=2)

    def __post_init__(self) -> None:
        if not isfinite(self.max_total_exposure) or not 0.0 < self.max_total_exposure <= 1.0:
            raise ValueError("max_total_exposure must be in (0.0, 1.0]")
        if isinstance(self.max_open_positions, bool) or not isinstance(
            self.max_open_positions, int
        ) or self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be a positive integer")
        if self.max_quote_age <= timedelta(0):
            raise ValueError("max_quote_age must be positive")
        if self.future_quote_tolerance < timedelta(0):
            raise ValueError("future_quote_tolerance must be non-negative")


@dataclass(frozen=True)
class PaperRiskContext:
    """Live facts the Phase 4 risk manager needs to judge an entry.

    ``reference_price`` is the ask (the price a marketable buy would cross), so
    the required-stop-below-entry check is evaluated against the price we would
    actually pay. ``data_time`` is the source candle's CLOSE time (when the bar
    became complete), distinct from ``now`` (the decision time).
    """

    signal: Signal
    equity: float
    cash: float
    reference_price: float
    current_position_value: float
    open_position_count: int
    has_position_in_instrument: bool
    day_start_equity: float
    day_realized_pnl: float
    now: datetime
    data_time: datetime
    quote: Optional[QuoteSnapshot]
    feed_status: FeedStatus
    kill_switch_engaged: bool

    def inner_context(self) -> RiskContext:
        return RiskContext(
            equity=self.equity,
            reference_price=self.reference_price,
            day_start_equity=self.day_start_equity,
            day_realized_pnl=self.day_realized_pnl,
            now=self.now,
            data_time=self.data_time,
        )


class PaperRiskManager:
    """Final veto for paper entries; composes the accepted Phase 2 manager."""

    def __init__(self, limits: Optional[PaperRiskLimits] = None) -> None:
        self.limits = limits or PaperRiskLimits()
        self._inner = RiskManager(self.limits.base)

    @property
    def inner(self) -> RiskManager:
        return self._inner

    def evaluate_entry(self, ctx: PaperRiskContext) -> RiskDecision:
        """Decide whether a LONG entry is allowed. Returns a reasoned verdict."""
        signal = ctx.signal
        limits = self.limits

        if signal.action != SignalAction.LONG:
            return RiskDecision(False, "not_an_entry")

        # --- environmental gates (Phase 4) ---------------------------------
        if ctx.kill_switch_engaged:
            return RiskDecision(False, "kill_switch_engaged")
        quote_decision = self.evaluate_execution_quote(
            instrument=signal.instrument,
            quote=ctx.quote,
            feed_status=ctx.feed_status,
            now=ctx.now,
            data_time=ctx.data_time,
        )
        if not quote_decision.allowed:
            return quote_decision

        # --- portfolio gates (Phase 4) -------------------------------------
        if ctx.has_position_in_instrument:
            # No second entry / no averaging down on an open position.
            return RiskDecision(False, "already_in_position")
        if ctx.open_position_count >= limits.max_open_positions:
            return RiskDecision(False, "max_open_positions_reached")
        if self._exposure_room(ctx) <= 0.0:
            return RiskDecision(False, "max_exposure_reached")

        # --- accepted Phase 2 deterministic gate (FINAL per-entry veto) ----
        inner_decision = self._inner.evaluate_entry(signal, ctx.inner_context())
        if not inner_decision.allowed:
            return inner_decision
        return RiskDecision(True, "ok")

    def evaluate_execution_quote(
        self,
        *,
        instrument: str,
        quote: Optional[QuoteSnapshot],
        feed_status: FeedStatus,
        now: datetime,
        data_time: datetime,
    ) -> RiskDecision:
        """Validate feed and quote timing for any quote-priced virtual fill."""
        limits = self.limits
        if not feed_status.connected:
            return RiskDecision(False, "feed_disconnected")
        if feed_status.stale:
            return RiskDecision(False, "feed_stale")
        if quote is None or not quote.synchronized:
            return RiskDecision(False, "order_book_unsynchronized")
        if quote.instrument != instrument:
            return RiskDecision(False, "quote_instrument_mismatch")
        if not quote.prices_finite_and_coherent():
            return RiskDecision(False, "invalid_quote")
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or data_time.tzinfo is None
            or data_time.utcoffset() is None
            or quote.timestamp.tzinfo is None
            or quote.timestamp.utcoffset() is None
        ):
            return RiskDecision(False, "naive_timestamp")
        if quote.timestamp < data_time:
            return RiskDecision(False, "quote_before_signal")
        if now - quote.timestamp > limits.max_quote_age:
            return RiskDecision(False, "stale_quote")
        if quote.timestamp - now > limits.future_quote_tolerance:
            return RiskDecision(False, "future_quote")
        return RiskDecision(True, "ok")

    def _exposure_room(self, ctx: PaperRiskContext) -> float:
        """Notional headroom before the total-exposure cap is reached."""
        return max(
            0.0,
            self.limits.max_total_exposure * ctx.equity - ctx.current_position_value,
        )

    def max_entry_quantity(
        self,
        ctx: PaperRiskContext,
        *,
        fee_rate: float,
        slippage_rate: float,
    ) -> float:
        """Maximum quantity including modeled entry and stop-exit costs.

        The non-gap stop scenario includes adverse slippage and fees on both
        legs. Gap-through losses can still exceed the configured risk fraction,
        because no bar-based model can guarantee an unavailable stop price.
        """
        signal = ctx.signal
        quote = ctx.quote
        if signal.stop_loss is None or quote is None:
            return 0.0

        entry_fill = quote.ask * (1.0 + slippage_rate)
        stop_fill = signal.stop_loss * (1.0 - slippage_rate)
        loss_per_unit = (
            entry_fill
            - stop_fill
            + entry_fill * fee_rate
            + stop_fill * fee_rate
        )
        if not isfinite(loss_per_unit) or loss_per_unit <= 0:
            return 0.0

        risk_quantity = (
            ctx.equity * self.limits.base.max_risk_per_trade / loss_per_unit
        )
        position_quantity = (
            ctx.equity * self.limits.base.max_position_size / entry_fill
        )
        exposure_quantity = self._exposure_room(ctx) / entry_fill
        return max(
            0.0,
            min(risk_quantity, position_quantity, exposure_quantity),
        )
