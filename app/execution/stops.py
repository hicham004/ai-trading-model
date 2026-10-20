"""Exchange-side protective stop manager (Sprint 3, OKX DEMO only, fail closed).

Closes the Phase 5 hard blocker "software-only stop": every open long SPOT
position gets a resting OKX **conditional SELL algo order** (``slOrdPx=-1``:
market on trigger; an OCO with a take-profit leg when the bracket's take-profit
is enabled) that the venue executes even while this process is dead. The
reviewed software stop (candle-low check) keeps running as a backstop.

Contract (mirrors ``OrderLifecycle``):

1. The placement is PERSISTED (``demo_algo_orders``, ``pending_submit``)
   before any network call, under a deterministic ``algoClOrdId`` derived
   from (account, instrument, parent entry, version). A retry, reconnect or
   restart reproduces the same id, so one position can never carry two
   economic stops from this code.
2. A venue acknowledgement projects ``live``; an API rejection projects
   ``rejected`` (no stop exists; the guard alarms, the next cycle retries
   under a bounded attempt budget); a transport failure is UNKNOWN and is
   resolved by QUERY (``GET /trade/order-algo``) — never by a blind
   re-placement. While a stop is unknown nothing new is placed.
3. The stop is kept in sync with the fill-derived position: a size or
   trigger change is sent as an amendment, confirmed by query; a trigger is
   never moved DOWN (a trailed stop survives a restart).
4. Before a software-initiated exit the stop is cancelled first
   (:meth:`cancel_for_exit`); if the venue reports it already triggered, the
   caller must not sell again (the venue is closing the position).
5. The guard (:meth:`guard`) alarms when a sellable position has no live
   stop for longer than the configured grace; the runtime turns the alarm
   into an entry block and the supervisor into an ALERT.

Nothing here decides WHETHER to trade; it only protects what the reviewed
risk path already opened. Demo only (``x-simulated-trading: 1``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Optional

from app.config import Settings, get_settings
from app.exchange.instruments import InstrumentMeta
from app.exchange.okx_demo_rest import OKXDemoError, OKXDemoRestClient, OKXDemoTransportError
from app.execution.precision import PrecisionError, decimal_to_str, floor_size, quantize_price
from app.execution.store import (
    ALGO_CANCELED,
    ALGO_EFFECTIVE,
    ALGO_FAILED,
    ALGO_LIVE,
    ALGO_OPEN_STATUSES,
    ALGO_PENDING,
    ALGO_REJECTED,
    ALGO_TERMINAL_STATUSES,
    ALGO_UNKNOWN,
    AlgoInput,
    DemoStore,
    IntentInput,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

ALGO_CLIENT_PREFIX = "d5s"  # exchange-side protective stop (SPOT conditional / OCO)
CHILD_CLIENT_PREFIX = "d5x"  # local synthetic exit intent for the venue-created SELL
ALARM_MISSING = "protective_stop_missing"
ALARM_UNKNOWN = "protective_stop_unknown"
ALARM_REJECTED = "protective_stop_rejected"


def derive_algo_client_id(account_name: str, instrument: str, parent_client_order_id: Optional[str], version: int) -> str:
    """Stable <=32-char alphanumeric ``algoClOrdId`` for one protective-stop placement."""
    material = f"{account_name}|{instrument}|stop|{parent_client_order_id or 'none'}|v{int(version)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    out = f"{ALGO_CLIENT_PREFIX}{digest}"[:32]
    assert out.isalnum() and len(out) <= 32
    return out


def derive_child_client_id(algo_cl_ord_id: str) -> str:
    digest = hashlib.sha256(f"child|{algo_cl_ord_id}".encode("utf-8")).hexdigest()
    out = f"{CHILD_CLIENT_PREFIX}{digest}"[:32]
    assert out.isalnum() and len(out) <= 32
    return out


def is_algo_client_id(value: Optional[str]) -> bool:
    return bool(value) and str(value).startswith(ALGO_CLIENT_PREFIX)


def _dec(value: object) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return out if out.is_finite() else None


def _ms_to_dt(value: object) -> Optional[datetime]:
    try:
        ms = int(str(value))
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


@dataclass(frozen=True)
class StopSpec:
    """What the exchange-side stop should look like for the current position."""

    instrument: str
    size: Decimal
    trigger: Decimal
    tp_trigger: Optional[Decimal] = None

    @property
    def ord_type(self) -> str:
        return "oco" if self.tp_trigger is not None else "conditional"


@dataclass(frozen=True)
class SyncOutcome:
    state: str  # disabled | flat | dust | protected | placed | amended | unknown | rejected | unarmed | capped | lock_lost | triggered
    algo_cl_ord_id: Optional[str] = None
    message: Optional[str] = None


class ProtectiveStopManager:
    """Places, syncs, resolves and cancels the exchange-side stop for long SPOT positions."""

    def __init__(
        self,
        store: DemoStore,
        rest: OKXDemoRestClient,
        account_id: int,
        account_name: str,
        *,
        settings: Optional[Settings] = None,
        lock_token: Optional[str] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        self._store = store
        self._rest = rest
        self._account_id = account_id
        self._account_name = account_name
        self._settings = settings or get_settings()
        self._lock_token = lock_token
        self._clock = clock
        self._unprotected_since: Dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.demo_stop_mode == "exchange"

    def _owns_lock(self) -> bool:
        return self._lock_token is None or self._store.owns_lock(self._account_id, self._lock_token)

    # -- desired state ------------------------------------------------------

    def desired_spec(
        self, instrument: str, position: Decimal, stop_price: Optional[Decimal], meta: InstrumentMeta,
        *, tp_trigger: Optional[Decimal] = None,
    ) -> Optional[StopSpec]:
        """Lot-floored sellable size and tick-quantized trigger; None when there is nothing protectable."""
        if stop_price is None or stop_price <= 0 or position <= 0:
            return None
        try:
            size = floor_size(position, meta.lot_size)
            if size <= 0 or size < meta.min_size:
                return None
            trigger = quantize_price(stop_price, meta.tick_size)
            tp = quantize_price(tp_trigger, meta.tick_size) if tp_trigger is not None and tp_trigger > trigger else None
        except PrecisionError:
            return None
        return StopSpec(instrument=instrument, size=size, trigger=trigger, tp_trigger=tp)

    # -- the sync step (called whenever the position or stop level may have changed) --

    def sync(
        self, instrument: str, position: Decimal, stop_price: Optional[Decimal], meta: Optional[InstrumentMeta],
        *, now: datetime, armed: bool, tp_trigger: Optional[Decimal] = None,
    ) -> SyncOutcome:
        if not self.enabled:
            return SyncOutcome("disabled")
        if meta is None:
            return SyncOutcome("unknown", message="instrument metadata unavailable")
        # 1) Resolve anything ambiguous first; never place while a stop is unknown.
        for row in self._store.list_open_algo_orders(self._account_id, instrument=instrument):
            if row.status in (ALGO_PENDING, ALGO_UNKNOWN):
                self.resolve(row.algo_cl_ord_id, now=now)
        open_rows = self._store.list_open_algo_orders(self._account_id, instrument=instrument)
        unknown = [r for r in open_rows if r.status in (ALGO_PENDING, ALGO_UNKNOWN)]
        if unknown:
            return SyncOutcome("unknown", unknown[0].algo_cl_ord_id, "stop outcome unresolved; no new placement")
        live = [r for r in open_rows if r.status == ALGO_LIVE]
        spec = self.desired_spec(instrument, position, stop_price, meta, tp_trigger=tp_trigger)

        # 2) Nothing protectable: cancel leftovers (an exit already sold the position).
        if spec is None:
            for row in live:
                self.cancel(row.algo_cl_ord_id, now=now)
            self._unprotected_since.pop(instrument, None)
            return SyncOutcome("dust" if position > 0 else "flat")

        # 3) A stop just triggered: the venue is selling; wait for the fill before judging.
        grace = timedelta(seconds=self._settings.demo_stop_unprotected_max_seconds)
        recent_triggered = [
            r for r in self._store.list_algo_orders(self._account_id, instrument=instrument, statuses=(ALGO_EFFECTIVE,))
            if r.last_update_at is not None and (now - self._utc(r.last_update_at)) <= grace
        ]
        if recent_triggered and not live:
            return SyncOutcome("triggered", recent_triggered[-1].algo_cl_ord_id, "stop triggered; awaiting the venue fill")

        # 4) A live stop exists: keep it, amend it, or replace it.
        if live:
            keep = live[0]
            for extra in live[1:]:  # defensive: never two live stops for one position
                self.cancel(extra.algo_cl_ord_id, now=now)
            if self._matches(keep, spec):
                self._mark_protected(instrument, now)
                return SyncOutcome("protected", keep.algo_cl_ord_id)
            status = self.amend(keep.algo_cl_ord_id, spec, now=now)
            refreshed = self._store.get_algo_order(self._account_id, keep.algo_cl_ord_id)
            if status == ALGO_LIVE and refreshed is not None and self._matches(refreshed, spec):
                self._mark_protected(instrument, now)
                return SyncOutcome("amended", keep.algo_cl_ord_id)
            if status in (ALGO_LIVE, ALGO_UNKNOWN, ALGO_PENDING):
                # Amendment not confirmed: cancel and replace below only once the old one is gone.
                status = self.cancel(keep.algo_cl_ord_id, now=now)
                if status in (ALGO_LIVE, ALGO_UNKNOWN, ALGO_PENDING):
                    return SyncOutcome("unknown", keep.algo_cl_ord_id, "old stop not confirmed cancelled")
                if status == ALGO_EFFECTIVE:
                    return SyncOutcome("triggered", keep.algo_cl_ord_id)
            elif status == ALGO_EFFECTIVE:
                return SyncOutcome("triggered", keep.algo_cl_ord_id)

        # 5) Place a new stop.
        if not self._owns_lock():
            return SyncOutcome("lock_lost")
        if not armed:
            return SyncOutcome("unarmed", message="runtime not armed; cannot place the exchange-side stop")
        attempts = self._store.count_algo_place_attempts(self._account_id, instrument, since=now - timedelta(hours=1))
        if attempts >= int(self._settings.demo_stop_max_attempts_per_hour):
            return SyncOutcome("capped", message="stop placement attempt budget exhausted for this hour")
        parent = self._latest_entry_id(instrument)
        version = self._store.next_algo_version(self._account_id, instrument, parent)
        algo_cl = derive_algo_client_id(self._account_name, instrument, parent, version)
        created = self._store.create_algo_order(
            self._account_id,
            AlgoInput(
                algo_cl_ord_id=algo_cl, instrument=instrument, size=decimal_to_str(spec.size),
                trigger_price=decimal_to_str(spec.trigger), order_price="-1", ord_type=spec.ord_type,
                tp_trigger_price=decimal_to_str(spec.tp_trigger) if spec.tp_trigger is not None else None,
                parent_client_order_id=parent, version=version,
            ),
            now=now,
        )
        if not created:
            status = self.resolve(algo_cl, now=now)
            return SyncOutcome("protected" if status == ALGO_LIVE else "unknown", algo_cl)
        params = {
            "instId": instrument, "tdMode": "cash", "side": "sell", "ordType": spec.ord_type,
            "sz": decimal_to_str(spec.size), "algoClOrdId": algo_cl,
            "slTriggerPx": decimal_to_str(spec.trigger), "slOrdPx": "-1", "slTriggerPxType": "last",
        }
        if spec.tp_trigger is not None:
            params.update({"tpTriggerPx": decimal_to_str(spec.tp_trigger), "tpOrdPx": "-1", "tpTriggerPxType": "last"})
        try:
            row = self._rest.place_algo_order(params)
        except OKXDemoTransportError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl, request_kind="aplace", outcome="unknown",
                                               new_status=ALGO_UNKNOWN, message=str(exc), now=self._clock())
            status = self.resolve(algo_cl, now=self._clock())
            return SyncOutcome("placed" if status == ALGO_LIVE else "unknown", algo_cl, "placement outcome resolved by query")
        except OKXDemoError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl, request_kind="aplace", outcome="rejected",
                                               new_status=ALGO_REJECTED, code=exc.code, message=str(exc), now=self._clock())
            self._store.record_event(self._account_id, "protective_stop_rejected", "error",
                                     f"exchange-side stop rejected for {instrument}: {exc}",
                                     payload={"algo_cl_ord_id": algo_cl, "code": exc.code}, now=self._clock())
            return SyncOutcome("rejected", algo_cl, str(exc))
        algo_id = str(row.get("algoId") or "") or None
        self._store.record_algo_submission(self._account_id, algo_cl, request_kind="aplace", outcome="ack",
                                           new_status=ALGO_LIVE, algo_id=algo_id, now=self._clock())
        self._mark_protected(instrument, now)
        return SyncOutcome("placed", algo_cl)

    def _matches(self, row, spec: StopSpec) -> bool:
        size, trigger = _dec(row.size), _dec(row.trigger_price)
        tp = _dec(row.tp_trigger_price)
        if size is None or trigger is None or size != spec.size:
            return False
        # A stop is never moved down: a higher live trigger (trailed) is accepted as protection.
        if trigger < spec.trigger:
            return False
        if spec.tp_trigger is None:
            return tp is None
        return tp is not None and tp == spec.tp_trigger

    def _mark_protected(self, instrument: str, now: datetime) -> None:
        self._unprotected_since.pop(instrument, None)

    def _latest_entry_id(self, instrument: str) -> Optional[str]:
        from sqlalchemy import select

        from app.db.models import DemoOrderIntent

        session = self._store._session_factory()
        try:
            return session.scalar(
                select(DemoOrderIntent.client_order_id)
                .where(
                    DemoOrderIntent.account_id == self._account_id,
                    DemoOrderIntent.instrument == instrument,
                    DemoOrderIntent.intent == "entry",
                )
                .order_by(DemoOrderIntent.id.desc())
                .limit(1)
            )
        finally:
            session.close()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    # -- resolution by query (never a blind re-placement) ---------------------

    def resolve(self, algo_cl_ord_id: str, *, now: datetime) -> str:
        row = self._store.get_algo_order(self._account_id, algo_cl_ord_id)
        if row is None:
            return ALGO_FAILED
        if row.status in ALGO_TERMINAL_STATUSES:
            return row.status
        try:
            if row.algo_id:
                order = self._rest.get_algo_order(algo_id=row.algo_id)
            else:
                order = self._rest.get_algo_order(algo_cl_ord_id=algo_cl_ord_id)
        except OKXDemoTransportError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="aquery", outcome="unknown",
                                               new_status=ALGO_UNKNOWN, message=str(exc), now=self._clock())
            return ALGO_UNKNOWN
        except OKXDemoError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="aquery", outcome="error",
                                               new_status=ALGO_UNKNOWN, code=exc.code, message=str(exc), now=self._clock())
            return ALGO_UNKNOWN
        if order is None:
            attempted = self._store.has_algo_place_submission(self._account_id, algo_cl_ord_id)
            new_status = ALGO_UNKNOWN if attempted else ALGO_FAILED
            self._store.record_algo_submission(
                self._account_id, algo_cl_ord_id, request_kind="aquery", outcome="not_found", new_status=new_status,
                message="stop not yet visible after an attempted placement" if attempted else "stop was never submitted",
                now=self._clock(),
            )
            return new_status
        return self.project(algo_cl_ord_id, order, source="rest_query", now=now) or ALGO_UNKNOWN

    def project(self, algo_cl_ord_id: str, order: dict, *, source: str, now: datetime) -> Optional[str]:
        """Project one venue algo row (query or WS) onto the local stop."""
        state = str(order.get("state", "") or "")
        return self._store.apply_algo_update(
            self._account_id,
            algo_cl_ord_id=algo_cl_ord_id,
            state=state,
            algo_id=str(order.get("algoId") or "") or None,
            child_order_id=str(order.get("ordId") or "") or None,
            actual_size=str(order.get("actualSz")) if order.get("actualSz") not in (None, "") else None,
            actual_price=str(order.get("actualPx")) if order.get("actualPx") not in (None, "") else None,
            triggered_at=_ms_to_dt(order.get("triggerTime")) if state == "effective" else None,
            source=source,
            now=now,
            size=str(order.get("sz")) if order.get("sz") not in (None, "") else None,
            trigger_price=str(order.get("slTriggerPx")) if order.get("slTriggerPx") not in (None, "") else None,
            tp_trigger_price=str(order.get("tpTriggerPx")) if order.get("tpTriggerPx") not in (None, "") else None,
        )

    def resolve_open(self, *, now: datetime) -> Dict[str, str]:
        """Resolve every non-terminal stop by query (startup gate / periodic reconcile)."""
        return {row.algo_cl_ord_id: self.resolve(row.algo_cl_ord_id, now=now)
                for row in self._store.list_open_algo_orders(self._account_id)}

    # -- cancel / amend -------------------------------------------------------

    def cancel(self, algo_cl_ord_id: str, *, now: datetime) -> str:
        row = self._store.get_algo_order(self._account_id, algo_cl_ord_id)
        if row is None:
            return ALGO_FAILED
        if row.status in ALGO_TERMINAL_STATUSES:
            return row.status
        if not self._owns_lock():
            return row.status
        try:
            self._rest.cancel_algo_order(row.instrument, algo_id=row.algo_id or None,
                                         algo_cl_ord_id=None if row.algo_id else algo_cl_ord_id)
        except OKXDemoTransportError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="acancel", outcome="unknown",
                                               message=str(exc), now=self._clock())
            return self.resolve(algo_cl_ord_id, now=now)
        except OKXDemoError as exc:  # e.g. already triggered / already cancelled: confirm by query
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="acancel", outcome="error",
                                               code=exc.code, message=str(exc), now=self._clock())
            return self.resolve(algo_cl_ord_id, now=now)
        self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="acancel", outcome="ack", now=self._clock())
        return self.resolve(algo_cl_ord_id, now=now)

    def amend(self, algo_cl_ord_id: str, spec: StopSpec, *, now: datetime) -> str:
        row = self._store.get_algo_order(self._account_id, algo_cl_ord_id)
        if row is None:
            return ALGO_FAILED
        if row.status != ALGO_LIVE:
            return row.status
        if not self._owns_lock():
            return row.status
        current_trigger = _dec(row.trigger_price)
        new_trigger = spec.trigger if current_trigger is None or spec.trigger > current_trigger else None  # never lower a stop
        new_size = spec.size if _dec(row.size) != spec.size else None
        new_tp = spec.tp_trigger if (spec.tp_trigger is not None and _dec(row.tp_trigger_price) != spec.tp_trigger) else None
        if new_trigger is None and new_size is None and new_tp is None:
            return ALGO_LIVE
        try:
            self._rest.amend_algo_order(
                row.instrument, algo_id=row.algo_id or None, algo_cl_ord_id=None if row.algo_id else algo_cl_ord_id,
                new_size=decimal_to_str(new_size) if new_size is not None else None,
                new_sl_trigger_px=decimal_to_str(new_trigger) if new_trigger is not None else None,
                new_sl_ord_px="-1" if new_trigger is not None else None,
                new_tp_trigger_px=decimal_to_str(new_tp) if new_tp is not None else None,
                new_tp_ord_px="-1" if new_tp is not None else None,
            )
        except OKXDemoTransportError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="aamend", outcome="unknown",
                                               message=str(exc), now=self._clock())
            return self.resolve(algo_cl_ord_id, now=now)
        except OKXDemoError as exc:
            self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="aamend", outcome="error",
                                               code=exc.code, message=str(exc), now=self._clock())
            return self.resolve(algo_cl_ord_id, now=now)
        self._store.record_algo_submission(self._account_id, algo_cl_ord_id, request_kind="aamend", outcome="ack", now=self._clock())
        return self.resolve(algo_cl_ord_id, now=now)

    def cancel_for_exit(self, instrument: str, *, now: datetime) -> str:
        """Cancel the resting stop before a software exit. Returns ``none`` | ``canceled`` | ``unknown`` | ``triggered``."""
        if not self.enabled:
            return "none"
        rows = self._store.list_open_algo_orders(self._account_id, instrument=instrument)
        if not rows:
            return "none"
        outcome = "canceled"
        for row in rows:
            status = self.cancel(row.algo_cl_ord_id, now=now)
            if status == ALGO_EFFECTIVE:
                return "triggered"
            if status in ALGO_OPEN_STATUSES:
                outcome = "unknown"
        return outcome

    # -- venue-created child orders (the triggered market SELL) ------------------

    def owned_child(self, row: dict):
        """Return the owned stop a venue order/fill row belongs to (by algoClOrdId, algoId or child ordId), else None."""
        if not self.enabled:
            return None
        algo_cl = str(row.get("algoClOrdId") or row.get("attachAlgoClOrdId") or "")
        if is_algo_client_id(algo_cl):
            local = self._store.get_algo_order(self._account_id, algo_cl)
            if local is not None:
                return local
        algo_id = str(row.get("algoId") or "") or None
        ord_id = str(row.get("ordId") or "") or None
        return self._store.find_algo_order(self._account_id, algo_id=algo_id, child_order_id=ord_id)

    def child_client_id(self, algo_row, *, child_ord_id: Optional[str], size: str, now: datetime) -> str:
        """Ensure the local synthetic EXIT intent for the venue-created SELL exists; return its client id."""
        cid = algo_row.child_client_order_id or derive_child_client_id(algo_row.algo_cl_ord_id)
        created = self._store.create_intent(
            self._account_id,
            IntentInput(client_order_id=cid, signal_id=f"stop|{algo_row.algo_cl_ord_id}", instrument=algo_row.instrument,
                        side="sell", intent="exit", ord_type="market", price=None, size=size, entry_policy="exchange_stop",
                        parent_client_order_id=algo_row.parent_client_order_id),
            now=now,
        )
        if created or not algo_row.child_client_order_id:
            self._store.set_algo_child(self._account_id, algo_row.algo_cl_ord_id, child_client_order_id=cid, now=now)
        if child_ord_id and not algo_row.child_order_id:
            self._store.apply_algo_update(self._account_id, algo_cl_ord_id=algo_row.algo_cl_ord_id, state="effective",
                                          algo_id=algo_row.algo_id, child_order_id=child_ord_id, actual_size=None, actual_price=None,
                                          triggered_at=now, source="child", now=now)
        return cid

    def on_private_update(self, row: dict, *, now: datetime) -> Optional[str]:
        """Project an ``orders-algo`` private-WS row; None when it is not an owned stop (caller fails closed)."""
        if not self.enabled:
            return None
        algo_cl = str(row.get("algoClOrdId") or "")
        local = self._store.get_algo_order(self._account_id, algo_cl) if is_algo_client_id(algo_cl) else None
        if local is None and row.get("algoId"):
            local = self._store.find_algo_order(self._account_id, algo_id=str(row.get("algoId")))
        if local is None or str(row.get("instId") or "") != local.instrument:
            return None
        return self.project(local.algo_cl_ord_id, row, source="ws", now=now)

    # -- the guard ----------------------------------------------------------------

    def guard(self, instrument: str, position: Decimal, meta: Optional[InstrumentMeta], *, now: datetime) -> Optional[str]:
        """Alarm reason when a sellable position has no live exchange-side stop beyond the grace; None when healthy."""
        if not self.enabled:
            return None
        if meta is None:
            return None
        try:
            size = floor_size(position, meta.lot_size) if position > 0 else Decimal(0)
        except PrecisionError:
            size = Decimal(0)
        if size <= 0 or size < meta.min_size:
            self._unprotected_since.pop(instrument, None)
            return None
        rows = self._store.list_open_algo_orders(self._account_id, instrument=instrument)
        if any(r.status == ALGO_LIVE for r in rows):
            self._unprotected_since.pop(instrument, None)
            return None
        grace = timedelta(seconds=self._settings.demo_stop_unprotected_max_seconds)
        since = self._unprotected_since.setdefault(instrument, now)
        history = self._store.list_algo_orders(self._account_id, instrument=instrument)
        latest = history[-1] if history else None
        if latest is not None and latest.status not in (ALGO_LIVE, ALGO_CANCELED, ALGO_EFFECTIVE) and latest.requested_at is not None:
            # The clock starts at the first failed/ambiguous placement, not at the first guard call.
            since = min(since, self._utc(latest.requested_at))
            self._unprotected_since[instrument] = since
        if now - since < grace:
            return None
        if any(r.status in (ALGO_PENDING, ALGO_UNKNOWN) for r in rows):
            return ALARM_UNKNOWN
        if latest is not None and latest.status == ALGO_REJECTED:
            return ALARM_REJECTED
        return ALARM_MISSING
