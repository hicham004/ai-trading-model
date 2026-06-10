"""Demo execution runtime: gating, sizing, and lifecycle orchestration.

This ties the accepted Phase 4 deterministic risk veto to the demo order
lifecycle. It is disarmed by default and performs no network mutation until it
is explicitly armed (with an expiry) AND reconciliation is consistent.

Gating rules:

* No order is submitted unless the runtime is ARMED (expiring) and holds the
  runtime lock.
* New ENTRIES additionally require: reconciliation consistent, kill switch
  disengaged, a connected/fresh feed, a synchronized/fresh quote, the
  deterministic risk veto passing, and Decimal precision/balance validation.
* Protective EXITS are allowed while armed even if the kill switch is engaged
  (the kill switch blocks new entries and cancels owned pending entries; it
  must not trap a position).

The decision methods are synchronous and deterministic; network access happens
only through the injected REST client / lifecycle, which tests fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Optional

from app.config import Settings, get_settings
from app.exchange.instruments import InstrumentMeta
from app.execution.lifecycle import INTENT_ENTRY, INTENT_EXIT, OrderLifecycle, SubmitResult
from app.execution.precision import (
    PrecisionError,
    decimal_to_str,
    to_decimal,
    validate_buy,
    validate_sell,
)
from app.execution.reconcile import DemoReconciler
from app.execution.store import (
    STATUS_LIVE,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    DemoStore,
)
from app.logging_config import get_logger
from app.paper.execution import FeedStatus, QuoteSnapshot
from app.risk.manager import RiskContext, RiskDecision, RiskLimits, RiskManager
from app.strategy.base import Signal, SignalAction

logger = get_logger(__name__)


def risk_limits_from_settings(settings: Settings) -> RiskLimits:
    """Build the accepted Phase 4 RiskLimits from demo settings (leverage 1.0)."""
    return RiskLimits(
        max_risk_per_trade=settings.demo_max_risk_per_trade,
        max_daily_loss=settings.demo_max_daily_loss,
        max_position_size=settings.demo_max_position_size,
        min_confidence=settings.demo_min_confidence,
        max_data_staleness=timedelta(seconds=settings.demo_max_candle_age_seconds),
    )


@dataclass(frozen=True)
class EntryContext:
    """Inputs for one entry decision (all balances are exchange-authoritative)."""

    signal: Signal
    instrument: str
    meta: InstrumentMeta
    quote: Optional[QuoteSnapshot]
    feed_status: FeedStatus
    available_quote: Decimal  # USDT available on the demo account
    equity: Decimal
    day_start_equity: Decimal
    day_realized_pnl: Decimal
    now: datetime
    data_time: datetime
    existing_exposure: Decimal = Decimal(0)
    open_positions: int = 0
    instrument_position_size: Decimal = Decimal(0)


class DemoExecutionRuntime:
    """Arming, kill switch, reconcile gating, sizing, and order submission."""

    def __init__(
        self,
        *,
        store: DemoStore,
        lifecycle: OrderLifecycle,
        reconciler: DemoReconciler,
        account_id: int,
        token: str,
        settings: Optional[Settings] = None,
        risk_manager: Optional[RiskManager] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        self._store = store
        self._lifecycle = lifecycle
        self._reconciler = reconciler
        self._account_id = account_id
        self._token = token
        self._settings = settings or get_settings()
        self._risk = risk_manager or RiskManager(risk_limits_from_settings(self._settings))
        self._clock = clock
        self._reconcile_consistent = False

    # -- operator actions ---------------------------------------------------

    def reconcile_now(self):
        result = self._reconciler.reconcile()
        self._reconcile_consistent = result.consistent
        return result

    def set_reconcile_consistent(self, value: bool, *, now: Optional[datetime] = None) -> None:
        """Force the consistency gate (used to fail closed on ambiguous orders).

        Persists ``reconciliation_consistent`` only while holding the lock and
        only to tighten it to False; it never relaxes a persisted False to True
        outside a real reconciliation.
        """
        self._reconcile_consistent = bool(value)
        if not value and self._store.owns_lock(self._account_id, self._token):
            self._store.update_status(
                self._account_id,
                self._token,
                now=now or self._clock(),
                reconciliation_consistent=False,
                heartbeat=False,
            )

    @property
    def reconcile_consistent(self) -> bool:
        return self._reconcile_consistent

    @property
    def token(self) -> str:
        return self._token

    @property
    def account_id(self) -> int:
        return self._account_id

    def arm(self, *, ttl_seconds: Optional[float] = None) -> Optional[datetime]:
        """Arm only if reconciliation is consistent (fail closed otherwise)."""
        if not self._reconcile_consistent or not self._store.owns_lock(
            self._account_id, self._token
        ):
            self._store.record_event(
                self._account_id,
                "arm_refused",
                "warning",
                "refused to arm: reconciliation is inconsistent or runtime lock is lost",
                now=self._clock(),
            )
            return None
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.demo_arm_ttl_seconds
        return self._store.arm(self._account_id, ttl_seconds=ttl, now=self._clock())

    def disarm(self) -> None:
        self._store.disarm(self._account_id, now=self._clock())

    def engage_kill_switch(self) -> list[SubmitResult]:
        """Engage the kill switch (persist first) and cancel owned pending entries.

        Persisting first guarantees new entries are blocked immediately; only
        then are owned pending ENTRY orders cancelled. Protective exits are never
        cancelled. Returns the cancel results.
        """
        self._store.set_kill_switch(self._account_id, True, now=self._clock())
        return self.cancel_pending_entries()

    def cancel_pending_entries(self) -> list[SubmitResult]:
        """Cancel every owned pending ENTRY order; never touch exits or foreign.

        Idempotent: already-terminal orders are skipped. Used by the kill switch
        and by the running driver when it observes an engaged kill switch. The
        true post-cancel state is resolved by querying the exchange, so an
        ambiguous cancel stays UNKNOWN (fail closed) rather than assumed done.
        """
        results: list[SubmitResult] = []
        for intent in self._store.list_open_intents(self._account_id):
            if intent.intent == INTENT_ENTRY and intent.status in (
                STATUS_PENDING,
                STATUS_LIVE,
                STATUS_PARTIAL,
                STATUS_UNKNOWN,
            ):
                results.append(self._lifecycle.cancel(intent.client_order_id, intent.instrument))
        return results

    def kill_switch_engaged(self) -> bool:
        return bool(self._runtime_snapshot().get("kill_switch_engaged"))

    def release_kill_switch(self) -> bool:
        """Release only after reconciliation and all entry orders are resolved."""
        now = self._clock()
        unresolved_entries = [
            intent
            for intent in self._store.list_open_intents(self._account_id)
            if intent.intent == INTENT_ENTRY
        ]
        if (
            not self._store.owns_lock(self._account_id, self._token)
            or not self._reconcile_consistent
            or unresolved_entries
        ):
            self._store.record_event(
                self._account_id,
                "kill_switch_release_refused",
                "warning",
                "kill-switch release refused: reconcile or entry cancellation unresolved",
                payload={"unresolved_entries": len(unresolved_entries)},
                now=now,
            )
            return False
        self._store.set_kill_switch(self._account_id, False, now=now)
        return True

    # -- gates --------------------------------------------------------------

    def entry_block_reason(self, now: datetime) -> Optional[str]:
        """Return why entries are blocked, or None if entries are allowed."""
        if not self._store.owns_lock(self._account_id, self._token):
            return "runtime_lock_lost"
        if not self._reconcile_consistent:
            return "reconciliation_inconsistent"
        if not self._store.is_armed(self._account_id, now=now):
            return "disarmed"
        if self._runtime_snapshot().get("kill_switch_engaged"):
            return "kill_switch_engaged"
        return None

    def exit_block_reason(self, now: datetime) -> Optional[str]:
        """Exits require arming but are NOT blocked by the kill switch."""
        if not self._store.owns_lock(self._account_id, self._token):
            return "runtime_lock_lost"
        if not self._store.is_armed(self._account_id, now=now):
            return "disarmed"
        return None

    def _runtime_snapshot(self) -> dict:
        from sqlalchemy import select

        from app.db.models import DemoRuntimeStatus

        session = self._store._session_factory()  # read-only snapshot
        try:
            row = session.scalar(
                select(DemoRuntimeStatus).where(
                    DemoRuntimeStatus.account_id == self._account_id
                )
            )
            if row is None:
                return {}
            return {
                "kill_switch_engaged": row.kill_switch_engaged,
                "reconciliation_consistent": row.reconciliation_consistent,
                "armed_until": row.armed_until,
            }
        finally:
            session.close()

    # -- decisions ----------------------------------------------------------

    def consider_entry(self, ctx: EntryContext) -> Optional[SubmitResult]:
        """Evaluate one entry: gates -> risk veto -> precision -> submit."""
        now = ctx.now
        signal = ctx.signal
        if signal.action != SignalAction.LONG:
            return None

        block = self.entry_block_reason(now)
        if block is not None:
            self._record_decision(signal, "entry", False, block, now)
            return None

        if ctx.quote is None or not ctx.quote.is_usable():
            self._record_decision(signal, "entry", False, "order_book_unsynchronized", now)
            return None
        if not ctx.feed_status.usable:
            self._record_decision(signal, "entry", False, "feed_unavailable", now)
            return None
        if (now - ctx.quote.timestamp) > timedelta(
            seconds=self._settings.demo_max_quote_age_seconds
        ):
            self._record_decision(signal, "entry", False, "stale_quote", now)
            return None

        # No duplicate / averaging: refuse if an open intent exists for the pair.
        for intent in self._store.list_open_intents(self._account_id):
            if intent.instrument == ctx.instrument and intent.intent == INTENT_ENTRY:
                self._record_decision(signal, "entry", False, "already_open", now)
                return None
        if ctx.instrument_position_size > 0:
            self._record_decision(signal, "entry", False, "position_already_open", now)
            return None
        if ctx.open_positions >= self._settings.demo_max_open_positions:
            self._record_decision(signal, "entry", False, "max_open_positions", now)
            return None

        ask = to_decimal(ctx.quote.ask, "ask")
        risk_ctx = RiskContext(
            equity=float(ctx.equity),
            reference_price=float(ask),
            day_start_equity=float(ctx.day_start_equity),
            day_realized_pnl=float(ctx.day_realized_pnl),
            now=now,
            data_time=ctx.data_time,
        )
        decision = self._risk.evaluate_entry(signal, risk_ctx)
        if not decision.allowed:
            self._record_decision(signal, "entry", False, decision.reason, now)
            return None

        # Risk-based sizing, capped by exposure, the per-order notional, and cash.
        fraction = self._risk.position_fraction(signal, risk_ctx)
        remaining_exposure = (
            ctx.equity * Decimal(str(self._settings.demo_max_total_exposure))
            - ctx.existing_exposure
        )
        max_notional = min(
            ctx.equity * Decimal(str(fraction)),
            remaining_exposure,
            Decimal(str(self._settings.demo_max_order_notional)),
            ctx.available_quote,
        )
        band = Decimal(str(self._settings.demo_price_band))
        limit_price = ask * (Decimal(1) + band)
        if limit_price <= 0 or max_notional <= 0:
            self._record_decision(signal, "entry", False, "non_positive_size", now)
            return None
        desired_size = max_notional / limit_price
        try:
            validated = validate_buy(
                meta=ctx.meta,
                price=limit_price,
                desired_size=desired_size,
                available_quote=ctx.available_quote,
                max_notional=Decimal(str(self._settings.demo_max_order_notional)),
            )
        except PrecisionError as exc:
            self._record_decision(signal, "entry", False, "precision_rejected", now)
            self._store.record_event(
                self._account_id,
                "entry_precision_rejected",
                "info",
                str(exc),
                payload={"instrument": ctx.instrument},
                now=now,
            )
            return None

        # A buy exactly at the venue minimum can become smaller than the
        # minimum sell size when OKX charges the entry fee in base currency.
        # Require a conservative two-minimum buffer so protective exits remain
        # representable after ordinary demo SPOT fees.
        if validated.size < ctx.meta.min_size * Decimal(2):
            self._record_decision(
                signal, "entry", False, "minimum_exit_size_buffer", now
            )
            return None

        self._record_decision(signal, "entry", True, "ok", now)
        return self._lifecycle.submit(
            signal_id=self._signal_id(signal, ctx.instrument),
            instrument=ctx.instrument,
            intent=INTENT_ENTRY,
            side="buy",
            ord_type=self._settings.demo_order_type,
            price=decimal_to_str(validated.price),
            size=decimal_to_str(validated.size),
            stop_loss=(
                decimal_to_str(Decimal(str(signal.stop_loss)))
                if signal.stop_loss is not None
                else None
            ),
        )

    def consider_exit(
        self,
        *,
        signal_id: str,
        instrument: str,
        meta: InstrumentMeta,
        quote: Optional[QuoteSnapshot],
        feed_status: FeedStatus,
        base_balance: Decimal,
        now: datetime,
    ) -> Optional[SubmitResult]:
        """Submit a protective long exit (sell). Allowed under the kill switch."""
        if self.exit_block_reason(now) is not None:
            return None
        if quote is None or not quote.is_usable() or not feed_status.usable:
            self._store.record_event(
                self._account_id,
                "exit_deferred",
                "warning",
                "protective exit deferred: no usable synchronized quote",
                payload={"instrument": instrument},
                now=now,
            )
            return None
        for intent in self._store.list_open_intents(self._account_id):
            if intent.instrument == instrument and intent.intent == INTENT_EXIT:
                return None
        bid = to_decimal(quote.bid, "bid")
        band = Decimal(str(self._settings.demo_price_band))
        limit_price = bid * (Decimal(1) - band)
        try:
            validated = validate_sell(meta=meta, price=limit_price, base_balance=base_balance)
        except PrecisionError as exc:
            self._store.record_event(
                self._account_id,
                "exit_precision_rejected",
                "info",
                str(exc),
                payload={"instrument": instrument},
                now=now,
            )
            return None
        return self._lifecycle.submit(
            signal_id=signal_id,
            instrument=instrument,
            intent=INTENT_EXIT,
            side="sell",
            ord_type=self._settings.demo_order_type,
            price=decimal_to_str(validated.price),
            size=decimal_to_str(validated.size),
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _signal_id(signal: Signal, instrument: str) -> str:
        ts = signal.timestamp.isoformat() if signal.timestamp else "na"
        return f"{instrument}|{signal.timeframe or 'na'}|{ts}"

    def _record_decision(
        self, signal: Signal, intent: str, allowed: bool, reason: str, now: datetime
    ) -> None:
        self._store.record_event(
            self._account_id,
            "risk_decision",
            "info" if allowed else "warning",
            f"{intent} {'allowed' if allowed else 'blocked'}: {reason}",
            payload={
                "intent": intent,
                "allowed": allowed,
                "reason": reason,
                "instrument": signal.instrument,
            },
            now=now,
        )
