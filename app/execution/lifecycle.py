"""Durable demo order lifecycle (idempotent, crash-safe, fail-closed).

The contract that keeps demo trading safe under failure:

1. The intent is PERSISTED before any network call (``pending_submit``).
2. The order is submitted with a deterministic client order id.
3. A success acknowledgement projects the live/filled state.
4. An API rejection (sCode != 0 / insufficient balance) means NO economic order
   was created -> ``rejected``.
5. A transport failure or timeout is an UNKNOWN outcome, never a rejection.
   It is resolved by QUERYING the exchange by client order id, never by a blind
   retry that could place a duplicate economic order.
6. At restart, every non-terminal intent is resolved by query. A first
   not-found response remains ``unknown`` because venue indexing may lag; it is
   never resubmitted, so a restart cannot duplicate or resurrect an order.

This module submits what it is told to; the runtime/risk layer decides WHETHER
to submit (arming, kill switch, risk veto, exposure).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional

from app.execution.ids import derive_client_order_id
from app.execution.store import (
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_LIVE,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_UNKNOWN,
    DemoStore,
    IntentInput,
    map_okx_state,
)
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoRestClient, OKXDemoTransportError
from app.logging_config import get_logger

logger = get_logger(__name__)

INTENT_ENTRY = "entry"
INTENT_EXIT = "exit"


@dataclass(frozen=True)
class SubmitResult:
    client_order_id: str
    status: str
    exchange_order_id: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


class OrderLifecycle:
    """Places, resolves, and cancels demo orders with durable idempotency."""

    def __init__(
        self,
        store: DemoStore,
        rest: OKXDemoRestClient,
        account_id: int,
        account_name: str,
        *,
        lock_token: Optional[str] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        self._store = store
        self._rest = rest
        self._account_id = account_id
        self._account_name = account_name
        self._lock_token = lock_token
        self._clock = clock

    def client_order_id(self, instrument: str, intent: str, signal_id: str) -> str:
        return derive_client_order_id(self._account_name, instrument, intent, signal_id)

    # -- submission ---------------------------------------------------------

    def submit(
        self,
        *,
        signal_id: str,
        instrument: str,
        intent: str,
        side: str,
        ord_type: str,
        price: Optional[str],
        size: str,
        stop_loss: Optional[str] = None,
    ) -> SubmitResult:
        """Persist an intent then submit it. Idempotent on the derived clOrdId."""
        if (intent == INTENT_ENTRY and side != "buy") or (
            intent == INTENT_EXIT and side != "sell"
        ):
            raise ValueError("entry intents must buy and exit intents must sell")
        now = self._clock()
        cl_ord_id = self.client_order_id(instrument, intent, signal_id)
        created = self._store.create_intent(
            self._account_id,
            IntentInput(
                client_order_id=cl_ord_id,
                signal_id=signal_id,
                instrument=instrument,
                side=side,
                intent=intent,
                ord_type=ord_type,
                price=price,
                size=size,
                stop_loss=stop_loss,
            ),
            now=now,
        )
        if not created:
            # The logical order already exists: never double-submit. Resolve it
            # against the exchange instead.
            existing = self._store.get_intent(self._account_id, cl_ord_id)
            if existing is not None and existing.status not in (
                STATUS_PENDING,
                STATUS_UNKNOWN,
            ):
                return SubmitResult(cl_ord_id, existing.status, existing.exchange_order_id)
            return self.resolve(cl_ord_id, instrument)

        params = {
            "instId": instrument,
            "tdMode": "cash",
            "side": side,
            "ordType": ord_type,
            "sz": size,
            "clOrdId": cl_ord_id,
        }
        if price is not None:
            params["px"] = price
        return self._place(cl_ord_id, instrument, params, attempt=1, now=self._clock())

    def _place(
        self, cl_ord_id: str, instrument: str, params: dict, *, attempt: int, now: datetime
    ) -> SubmitResult:
        if self._lock_token and not self._store.owns_lock(
            self._account_id, self._lock_token
        ):
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="place",
                attempt=attempt,
                outcome="blocked",
                new_status=STATUS_FAILED,
                message="runtime lock lost before submission",
                now=self._clock(),
            )
            return SubmitResult(
                cl_ord_id, STATUS_FAILED, message="runtime_lock_lost"
            )
        try:
            row = self._rest.place_order(params)
        except OKXDemoTransportError as exc:
            # UNKNOWN outcome: persist and resolve by query, never blind-retry.
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="place",
                attempt=attempt,
                outcome="unknown",
                new_status=STATUS_UNKNOWN,
                message=str(exc),
                now=self._clock(),
            )
            logger.warning(
                "demo place outcome UNKNOWN; will resolve by clOrdId",
                extra={"client_order_id": cl_ord_id, "error_type": type(exc).__name__},
            )
            return self.resolve(cl_ord_id, instrument)
        except OKXDemoError as exc:
            # API-level rejection: no economic order was created.
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="place",
                attempt=attempt,
                outcome="rejected",
                new_status=STATUS_REJECTED,
                code=exc.code,
                message=str(exc),
                now=self._clock(),
            )
            return SubmitResult(cl_ord_id, STATUS_REJECTED, code=exc.code, message=str(exc))

        ord_id = str(row.get("ordId") or "") or None
        self._store.record_submission(
            self._account_id,
            cl_ord_id,
            request_kind="place",
            attempt=attempt,
            outcome="ack",
            new_status=STATUS_LIVE,
            exchange_order_id=ord_id,
            now=self._clock(),
        )
        return SubmitResult(cl_ord_id, STATUS_LIVE, exchange_order_id=ord_id)

    # -- resolution (query by client order id) -----------------------------

    def resolve(self, cl_ord_id: str, instrument: str) -> SubmitResult:
        """Resolve an unknown/pending intent by querying the exchange."""
        existing = self._store.get_intent(self._account_id, cl_ord_id)
        if existing is not None and existing.status in (
            STATUS_FILLED,
            STATUS_CANCELED,
            STATUS_REJECTED,
            STATUS_FAILED,
        ):
            return SubmitResult(
                cl_ord_id,
                existing.status,
                exchange_order_id=existing.exchange_order_id,
                message=existing.last_error,
            )
        rejection = self._store.get_place_rejection(self._account_id, cl_ord_id)
        if rejection is not None:
            code, message = rejection
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="query",
                attempt=0,
                outcome="recovered_reject",
                new_status=STATUS_REJECTED,
                code=code,
                message=message,
                now=self._clock(),
            )
            return SubmitResult(
                cl_ord_id, STATUS_REJECTED, code=code, message=message
            )
        try:
            order = self._rest.get_order(instrument, cl_ord_id=cl_ord_id)
        except OKXDemoTransportError as exc:
            # Still unknown; leave as-is and let a later pass retry the query.
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="query",
                attempt=0,
                outcome="unknown",
                new_status=STATUS_UNKNOWN,
                message=str(exc),
                now=self._clock(),
            )
            return SubmitResult(cl_ord_id, STATUS_UNKNOWN, message=str(exc))
        except OKXDemoError as exc:
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="query",
                attempt=0,
                outcome="error",
                code=exc.code,
                message=str(exc),
                now=self._clock(),
            )
            return SubmitResult(cl_ord_id, STATUS_UNKNOWN, code=exc.code, message=str(exc))

        now = self._clock()
        if order is None:
            # A place request with an ambiguous transport outcome may become
            # visible after this first query. Keep it UNKNOWN indefinitely
            # rather than creating an orphan live order by declaring failure.
            # A pending intent with no recorded place attempt is the distinct
            # crash-before-network case and is safe to close as failed.
            attempted = self._store.has_place_submission(
                self._account_id, cl_ord_id
            )
            new_status = STATUS_UNKNOWN if attempted else STATUS_FAILED
            message = (
                "order not yet visible after an attempted submission"
                if attempted
                else "order was never submitted"
            )
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="query",
                attempt=0,
                outcome="not_found",
                new_status=new_status,
                message=message,
                now=now,
            )
            return SubmitResult(cl_ord_id, new_status, message="not_found")
        return self._project_order(cl_ord_id, order, source="rest_query", now=now)

    def _project_order(
        self, cl_ord_id: str, order: dict, *, source: str, now: datetime
    ) -> SubmitResult:
        state = str(order.get("state", ""))
        ord_id = str(order.get("ordId") or "") or None
        self._store.apply_order_update(
            self._account_id,
            client_order_id=cl_ord_id,
            exchange_order_id=ord_id,
            state=state,
            filled_size=str(order.get("accFillSz")) if order.get("accFillSz") is not None else None,
            avg_price=str(order.get("avgPx")) if order.get("avgPx") else None,
            fee=str(order.get("fee")) if order.get("fee") else None,
            fee_ccy=str(order.get("feeCcy")) if order.get("feeCcy") else None,
            update_time=now,
            source=source,
            now=now,
        )
        mapped = map_okx_state(state) or STATUS_LIVE
        return SubmitResult(cl_ord_id, mapped, exchange_order_id=ord_id)

    # -- cancellation -------------------------------------------------------

    def cancel(self, cl_ord_id: str, instrument: str) -> SubmitResult:
        """Request cancellation of an owned order; resolve the true state."""
        existing = self._store.get_intent(self._account_id, cl_ord_id)
        if existing is None or existing.instrument != instrument:
            return SubmitResult(
                cl_ord_id, STATUS_FAILED, message="cancel of unowned order"
            )
        if self._lock_token and not self._store.owns_lock(
            self._account_id, self._lock_token
        ):
            return SubmitResult(
                cl_ord_id,
                existing.status,
                message="runtime_lock_lost",
            )
        try:
            self._rest.cancel_order(instrument, cl_ord_id)
        except OKXDemoTransportError as exc:
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="cancel",
                attempt=0,
                outcome="unknown",
                message=str(exc),
                now=self._clock(),
            )
            return self.resolve(cl_ord_id, instrument)
        except OKXDemoError as exc:
            # e.g. already filled/canceled: record then confirm by query.
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="cancel",
                attempt=0,
                outcome="error",
                code=exc.code,
                message=str(exc),
                now=self._clock(),
            )
            return self.resolve(cl_ord_id, instrument)
        self._store.record_submission(
            self._account_id,
            cl_ord_id,
            request_kind="cancel",
            attempt=0,
            outcome="ack",
            now=self._clock(),
        )
        return self.resolve(cl_ord_id, instrument)

    # -- amendment ----------------------------------------------------------

    def amend(
        self,
        cl_ord_id: str,
        instrument: str,
        *,
        new_size: Optional[str] = None,
        new_price: Optional[str] = None,
    ) -> SubmitResult:
        """Amend an owned order, then resolve its true state by query.

        Mirrors place/cancel safety: an ambiguous POST outcome (transport
        timeout) is never blindly retried; the true state is read by querying
        the exchange by client order id, which resolves amend/fill and
        cancel/fill races without creating a duplicate economic order.
        """
        intent = self._store.get_intent(self._account_id, cl_ord_id)
        if intent is None or intent.instrument != instrument:
            return SubmitResult(cl_ord_id, STATUS_FAILED, message="amend of unknown order")
        if self._lock_token and not self._store.owns_lock(
            self._account_id, self._lock_token
        ):
            return SubmitResult(
                cl_ord_id, intent.status, message="runtime_lock_lost"
            )
        if intent.status not in (STATUS_LIVE, STATUS_PARTIAL):
            return SubmitResult(
                cl_ord_id, intent.status, message="order_not_amendable"
            )
        try:
            if new_size is not None:
                requested = Decimal(str(new_size))
                original = Decimal(intent.size)
                filled = Decimal(intent.filled_size or "0")
                if requested <= 0 or requested > original or requested < filled:
                    raise ValueError
            if new_price is not None and Decimal(str(new_price)) <= 0:
                raise ValueError
        except (ArithmeticError, ValueError):
            return SubmitResult(
                cl_ord_id, intent.status, message="invalid_amendment"
            )
        try:
            self._rest.amend_order(
                instrument, cl_ord_id, new_size=new_size, new_price=new_price
            )
        except OKXDemoTransportError as exc:
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="amend",
                attempt=0,
                outcome="unknown",
                message=str(exc),
                now=self._clock(),
            )
            return self.resolve(cl_ord_id, instrument)
        except OKXDemoError as exc:
            # e.g. order already filled/canceled: record, then confirm by query.
            self._store.record_submission(
                self._account_id,
                cl_ord_id,
                request_kind="amend",
                attempt=0,
                outcome="error",
                code=exc.code,
                message=str(exc),
                now=self._clock(),
            )
            return self.resolve(cl_ord_id, instrument)
        self._store.record_submission(
            self._account_id,
            cl_ord_id,
            request_kind="amend",
            attempt=0,
            outcome="ack",
            now=self._clock(),
        )
        return self.resolve(cl_ord_id, instrument)

    # -- restart recovery ---------------------------------------------------

    def resolve_open_intents(self) -> list[SubmitResult]:
        """Resolve every non-terminal intent by query (used at startup)."""
        results: list[SubmitResult] = []
        for intent in self._store.list_open_intents(self._account_id):
            results.append(self.resolve(intent.client_order_id, intent.instrument))
        return results
