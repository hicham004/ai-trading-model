"""Durable demo-execution ledger: the only writer of the ``demo_*`` tables.

Every state transition is persisted atomically so a crash at any order
lifecycle boundary leaves a recoverable, never-partial record. The store also
owns the runtime lock (atomic, never auto-stolen), the persisted kill switch,
and the expiring arming flag.

No credential or secret is ever written here. Monetary/size values are stored
as exact decimal strings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, List, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    DemoAccount,
    DemoBalanceSnapshot,
    DemoDailyBaseline,
    DemoEvent,
    DemoFill,
    DemoOrderIntent,
    DemoOrderUpdate,
    DemoReconciliation,
    DemoRuntimeStatus,
    DemoSubmission,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# Lifecycle statuses for DemoOrderIntent.status.
STATUS_PENDING = "pending_submit"
STATUS_UNKNOWN = "unknown"
STATUS_LIVE = "live"
STATUS_PARTIAL = "partially_filled"
STATUS_FILLED = "filled"
STATUS_CANCELED = "canceled"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

_OPEN_STATUSES = (STATUS_PENDING, STATUS_UNKNOWN, STATUS_LIVE, STATUS_PARTIAL)
_TERMINAL_STATUSES = (STATUS_FILLED, STATUS_CANCELED, STATUS_REJECTED, STATUS_FAILED)

# Map an OKX order "state" to our intent status.
_OKX_STATE_MAP = {
    "live": STATUS_LIVE,
    "partially_filled": STATUS_PARTIAL,
    "filled": STATUS_FILLED,
    "canceled": STATUS_CANCELED,
    "mmp_canceled": STATUS_CANCELED,
}


def map_okx_state(state: str) -> Optional[str]:
    return _OKX_STATE_MAP.get(state)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AccountIdentityMismatch(RuntimeError):
    """Raised when a demo account is reopened with different stable identity."""


@dataclass(frozen=True)
class IntentInput:
    client_order_id: str
    signal_id: str
    instrument: str
    side: str
    intent: str
    ord_type: str
    price: Optional[str]
    size: str
    stop_loss: Optional[str] = None


class DemoStore:
    """Atomic persistence for the demo execution lifecycle."""

    def __init__(self, session_factory: Callable[[], Session], account_name: str) -> None:
        self._session_factory = session_factory
        self._account_name = account_name

    # -- account bootstrap --------------------------------------------------

    def ensure_account(self, key_fingerprint: str, identity_config: dict) -> int:
        """Create or fetch the account row. Stable identity is immutable."""
        canonical = json.dumps(identity_config, default=str, sort_keys=True)
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoAccount).where(DemoAccount.name == self._account_name)
            )
            if row is None:
                row = DemoAccount(
                    name=self._account_name,
                    key_fingerprint=key_fingerprint,
                    config_json=canonical,
                )
                session.add(row)
                session.flush()
                session.add(DemoRuntimeStatus(account_id=row.id))
                session.commit()
                return row.id
            account_id = row.id
            stored_config = row.config_json
            stored_fp = row.key_fingerprint
            if session.scalar(
                select(DemoRuntimeStatus.id).where(
                    DemoRuntimeStatus.account_id == account_id
                )
            ) is None:
                session.add(DemoRuntimeStatus(account_id=account_id))
            # Bind an account name to one demo API key. An empty fingerprint is
            # allowed only as the local-command placeholder before credentials
            # are first supplied.
            if stored_fp != key_fingerprint:
                if stored_fp and key_fingerprint:
                    raise AccountIdentityMismatch(
                        "demo API key fingerprint does not match this account; "
                        "use a new --account name"
                    )
                session.add(
                    self._event_row(
                        account_id,
                        "key_fingerprint_changed",
                        "warning",
                        "demo API key fingerprint changed for this account",
                        {},
                        datetime.now(tz=timezone.utc),
                    )
                )
                row.key_fingerprint = key_fingerprint
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        if stored_config != canonical:
            raise AccountIdentityMismatch(
                "demo account identity (strategy/instruments/timeframe) does not "
                "match its stored configuration; use a new --account name"
            )
        return account_id

    def find_account_id(self) -> Optional[int]:
        session = self._session_factory()
        try:
            return session.scalar(
                select(DemoAccount.id).where(DemoAccount.name == self._account_name)
            )
        finally:
            session.close()

    # -- events -------------------------------------------------------------

    @staticmethod
    def _event_row(
        account_id: int,
        event_type: str,
        severity: str,
        message: str,
        payload: dict,
        now: datetime,
    ) -> DemoEvent:
        return DemoEvent(
            account_id=account_id,
            event_time=now,
            event_type=event_type[:48],
            severity=severity[:16],
            message=message[:512],
            payload_json=json.dumps(payload, default=str),
        )

    def record_event(
        self,
        account_id: int,
        event_type: str,
        severity: str,
        message: str,
        *,
        payload: Optional[dict] = None,
        now: Optional[datetime] = None,
    ) -> None:
        session = self._session_factory()
        try:
            session.add(
                self._event_row(
                    account_id,
                    event_type,
                    severity,
                    message,
                    payload or {},
                    now or datetime.now(tz=timezone.utc),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- arming + kill switch ----------------------------------------------

    def arm(self, account_id: int, *, ttl_seconds: float, now: datetime) -> datetime:
        """Arm the runtime to submit demo orders until ``now + ttl``."""
        armed_until = now + timedelta(seconds=ttl_seconds)
        self._update_status_fields(
            account_id,
            now=now,
            armed_until=armed_until,
            event=("armed", "warning", f"demo runtime armed until {armed_until.isoformat()}"),
        )
        return armed_until

    def disarm(self, account_id: int, *, now: datetime) -> None:
        self._update_status_fields(
            account_id,
            now=now,
            armed_until=None,
            clear_armed=True,
            event=("disarmed", "info", "demo runtime disarmed"),
        )

    def is_armed(self, account_id: int, *, now: datetime) -> bool:
        session = self._session_factory()
        try:
            armed_until = session.scalar(
                select(DemoRuntimeStatus.armed_until).where(
                    DemoRuntimeStatus.account_id == account_id
                )
            )
        finally:
            session.close()
        return armed_until is not None and _utc(armed_until) > now

    def set_kill_switch(self, account_id: int, engaged: bool, *, now: datetime) -> None:
        self._update_status_fields(
            account_id,
            now=now,
            kill_switch_engaged=bool(engaged),
            event=(
                "kill_switch_engaged" if engaged else "kill_switch_released",
                "warning" if engaged else "info",
                "demo kill switch engaged" if engaged else "demo kill switch released",
            ),
        )

    def _update_status_fields(
        self,
        account_id: int,
        *,
        now: datetime,
        armed_until: Optional[datetime] = None,
        clear_armed: bool = False,
        kill_switch_engaged: Optional[bool] = None,
        event: Optional[tuple] = None,
    ) -> None:
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoRuntimeStatus)
                .where(DemoRuntimeStatus.account_id == account_id)
                .with_for_update()
            )
            if row is None:
                row = DemoRuntimeStatus(account_id=account_id)
                session.add(row)
            if clear_armed:
                row.armed_until = None
            elif armed_until is not None:
                row.armed_until = armed_until
            if kill_switch_engaged is not None:
                row.kill_switch_engaged = kill_switch_engaged
            row.updated_at = now
            if event is not None:
                session.add(
                    self._event_row(account_id, event[0], event[1], event[2], {}, now)
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- order intents (the durable outbox) --------------------------------

    def create_intent(self, account_id: int, intent: IntentInput, *, now: datetime) -> bool:
        """Persist a new pending intent. Idempotent on client_order_id.

        Returns True if newly created, False if it already existed (a retry of
        the same logical order).
        """
        session = self._session_factory()
        try:
            existing = session.scalar(
                select(DemoOrderIntent.id).where(
                    DemoOrderIntent.account_id == account_id,
                    DemoOrderIntent.client_order_id == intent.client_order_id,
                )
            )
            if existing is not None:
                session.commit()
                return False
            session.add(
                DemoOrderIntent(
                    account_id=account_id,
                    client_order_id=intent.client_order_id,
                    signal_id=intent.signal_id,
                    instrument=intent.instrument,
                    side=intent.side,
                    intent=intent.intent,
                    ord_type=intent.ord_type,
                    price=intent.price,
                    size=intent.size,
                    stop_loss=intent.stop_loss,
                    status=STATUS_PENDING,
                    requested_at=now,
                )
            )
            session.add(
                self._event_row(
                    account_id,
                    "order_intent_created",
                    "info",
                    f"intent {intent.intent} {intent.side} {intent.instrument}",
                    {"client_order_id": intent.client_order_id, "signal_id": intent.signal_id},
                    now,
                )
            )
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_submission(
        self,
        account_id: int,
        client_order_id: str,
        *,
        request_kind: str,
        attempt: int,
        outcome: str,
        now: datetime,
        new_status: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        code: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Append a submission record and update the intent projection atomically."""
        session = self._session_factory()
        try:
            if attempt <= 0:
                previous = session.scalar(
                    select(func.max(DemoSubmission.attempt)).where(
                        DemoSubmission.account_id == account_id,
                        DemoSubmission.client_order_id == client_order_id,
                        DemoSubmission.request_kind == request_kind,
                    )
                )
                attempt = int(previous or 0) + 1
            session.add(
                DemoSubmission(
                    account_id=account_id,
                    client_order_id=client_order_id,
                    request_kind=request_kind,
                    attempt=attempt,
                    sent_at=now,
                    outcome=outcome,
                    exchange_order_id=exchange_order_id,
                    code=code,
                    message=(message or "")[:256] or None,
                )
            )
            intent = session.scalar(
                select(DemoOrderIntent)
                .where(
                    DemoOrderIntent.account_id == account_id,
                    DemoOrderIntent.client_order_id == client_order_id,
                )
                .with_for_update()
            )
            if intent is not None:
                intent.attempts = (intent.attempts or 0) + 1
                intent.submitted_at = intent.submitted_at or now
                intent.last_update_at = now
                if exchange_order_id:
                    intent.exchange_order_id = exchange_order_id
                # Submission/query audit rows must never regress a terminal
                # economic outcome back to pending/unknown/live.
                if (
                    new_status is not None
                    and (
                        intent.status not in _TERMINAL_STATUSES
                        or new_status in _TERMINAL_STATUSES
                    )
                ):
                    intent.status = new_status
                if message is not None:
                    intent.last_error = message[:256]
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def apply_order_update(
        self,
        account_id: int,
        *,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        state: str,
        filled_size: Optional[str],
        avg_price: Optional[str],
        fee: Optional[str],
        fee_ccy: Optional[str],
        update_time: datetime,
        source: str,
        now: datetime,
    ) -> None:
        """Append an order-state update and project it onto the intent."""
        mapped = map_okx_state(state)
        session = self._session_factory()
        try:
            session.add(
                DemoOrderUpdate(
                    account_id=account_id,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    state=state,
                    filled_size=filled_size,
                    avg_price=avg_price,
                    fee=fee,
                    fee_ccy=fee_ccy,
                    update_time=update_time,
                    source=source,
                )
            )
            intent = None
            if client_order_id:
                intent = session.scalar(
                    select(DemoOrderIntent)
                    .where(
                        DemoOrderIntent.account_id == account_id,
                        DemoOrderIntent.client_order_id == client_order_id,
                    )
                    .with_for_update()
                )
            if intent is not None:
                if exchange_order_id:
                    intent.exchange_order_id = exchange_order_id
                if filled_size is not None:
                    intent.filled_size = filled_size
                if avg_price is not None:
                    intent.avg_price = avg_price
                # Never regress a terminal status from a late/duplicate update.
                if intent.status not in _TERMINAL_STATUSES and mapped is not None:
                    intent.status = mapped
                intent.last_update_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_fill(
        self,
        account_id: int,
        *,
        fill_id: str,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        instrument: str,
        side: str,
        fill_size: str,
        fill_price: str,
        fee: Optional[str],
        fee_ccy: Optional[str],
        fill_time: datetime,
        source: str,
        now: datetime,
    ) -> bool:
        """Insert a fill idempotently (unique fill_id). Returns True if new."""
        session = self._session_factory()
        try:
            exists = session.scalar(
                select(DemoFill.id).where(
                    DemoFill.account_id == account_id, DemoFill.fill_id == fill_id
                )
            )
            if exists is not None:
                session.commit()
                return False
            session.add(
                DemoFill(
                    account_id=account_id,
                    fill_id=fill_id,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    instrument=instrument,
                    side=side,
                    fill_size=fill_size,
                    fill_price=fill_price,
                    fee=fee,
                    fee_ccy=fee_ccy,
                    fill_time=fill_time,
                    source=source,
                )
            )
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_balances(
        self, account_id: int, balances: list, *, source: str, now: datetime
    ) -> None:
        session = self._session_factory()
        try:
            session.add(
                DemoBalanceSnapshot(
                    account_id=account_id,
                    snapshot_time=now,
                    balances_json=json.dumps(balances, default=str),
                    source=source,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_reconciliation(
        self,
        account_id: int,
        *,
        consistent: bool,
        foreign_orders: int,
        unexplained_balances: int,
        issues: list,
        summary: dict,
        now: datetime,
    ) -> None:
        session = self._session_factory()
        try:
            session.add(
                DemoReconciliation(
                    account_id=account_id,
                    run_at=now,
                    consistent=consistent,
                    foreign_orders=foreign_orders,
                    unexplained_balances=unexplained_balances,
                    issues_json=json.dumps(issues, default=str),
                    summary_json=json.dumps(summary, default=str),
                )
            )
            row = session.scalar(
                select(DemoRuntimeStatus)
                .where(DemoRuntimeStatus.account_id == account_id)
                .with_for_update()
            )
            if row is not None:
                row.reconciliation_consistent = consistent
                row.updated_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- reads --------------------------------------------------------------

    def get_intent(self, account_id: int, client_order_id: str) -> Optional[DemoOrderIntent]:
        session = self._session_factory()
        try:
            return session.scalar(
                select(DemoOrderIntent).where(
                    DemoOrderIntent.account_id == account_id,
                    DemoOrderIntent.client_order_id == client_order_id,
                )
            )
        finally:
            session.close()

    def list_open_intents(self, account_id: int) -> List[DemoOrderIntent]:
        session = self._session_factory()
        try:
            return list(
                session.scalars(
                    select(DemoOrderIntent).where(
                        DemoOrderIntent.account_id == account_id,
                        DemoOrderIntent.status.in_(_OPEN_STATUSES),
                    )
                ).all()
            )
        finally:
            session.close()

    def position_summary(
        self, account_id: int, instrument: str
    ) -> tuple[Decimal, Optional[Decimal]]:
        """Return fill-derived net base size and the latest persisted entry stop."""
        session = self._session_factory()
        try:
            fills = session.scalars(
                select(DemoFill)
                .where(
                    DemoFill.account_id == account_id,
                    DemoFill.instrument == instrument,
                )
                .order_by(DemoFill.id.asc())
            ).all()
            net = Decimal(0)
            for fill in fills:
                size = Decimal(fill.fill_size)
                net += size if fill.side == "buy" else -size
                if fill.fee_ccy == instrument.split("-")[0] and fill.fee:
                    net += Decimal(fill.fee)
            entry = session.scalar(
                select(DemoOrderIntent)
                .where(
                    DemoOrderIntent.account_id == account_id,
                    DemoOrderIntent.instrument == instrument,
                    DemoOrderIntent.intent == "entry",
                    DemoOrderIntent.stop_loss.is_not(None),
                )
                .order_by(DemoOrderIntent.id.desc())
                .limit(1)
            )
            stop = Decimal(entry.stop_loss) if entry is not None else None
            return max(net, Decimal(0)), stop
        finally:
            session.close()

    def get_or_create_daily_baseline(
        self,
        account_id: int,
        market_day: date,
        starting_equity: Decimal,
        *,
        now: datetime,
    ) -> Decimal:
        """Return the immutable starting equity for one UTC market day."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoDailyBaseline).where(
                    DemoDailyBaseline.account_id == account_id,
                    DemoDailyBaseline.market_day == market_day,
                )
            )
            if row is None:
                row = DemoDailyBaseline(
                    account_id=account_id,
                    market_day=market_day,
                    starting_equity=format(starting_equity, "f"),
                    created_at=now,
                )
                session.add(row)
                session.commit()
                return starting_equity
            return Decimal(row.starting_equity)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def has_place_submission(self, account_id: int, client_order_id: str) -> bool:
        """Return whether a place request crossed the durable submission boundary."""
        session = self._session_factory()
        try:
            return (
                session.scalar(
                    select(DemoSubmission.id)
                    .where(
                        DemoSubmission.account_id == account_id,
                        DemoSubmission.client_order_id == client_order_id,
                        DemoSubmission.request_kind == "place",
                    )
                    .limit(1)
                )
                is not None
            )
        finally:
            session.close()

    def get_place_rejection(
        self, account_id: int, client_order_id: str
    ) -> Optional[tuple[Optional[str], Optional[str]]]:
        """Return a durable definitive place rejection, if one was recorded."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoSubmission)
                .where(
                    DemoSubmission.account_id == account_id,
                    DemoSubmission.client_order_id == client_order_id,
                    DemoSubmission.request_kind == "place",
                    DemoSubmission.outcome == "rejected",
                )
                .order_by(DemoSubmission.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            return row.code, row.message
        finally:
            session.close()

    def known_client_order_ids(self, account_id: int) -> set[str]:
        session = self._session_factory()
        try:
            return set(
                session.scalars(
                    select(DemoOrderIntent.client_order_id).where(
                        DemoOrderIntent.account_id == account_id
                    )
                ).all()
            )
        finally:
            session.close()

    # -- runtime lock (atomic; never auto-stolen) --------------------------

    def owns_lock(self, account_id: int, token: str) -> bool:
        """Return whether ``token`` is the current persisted runtime owner."""
        session = self._session_factory()
        try:
            return (
                session.scalar(
                    select(DemoRuntimeStatus.lock_token).where(
                        DemoRuntimeStatus.account_id == account_id
                    )
                )
                == token
            )
        finally:
            session.close()

    def acquire_lock(self, account_id: int, token: str, *, now: datetime) -> bool:
        session = self._session_factory()
        try:
            result = session.execute(
                update(DemoRuntimeStatus)
                .where(
                    DemoRuntimeStatus.account_id == account_id,
                    or_(
                        DemoRuntimeStatus.lock_token.is_(None),
                        DemoRuntimeStatus.lock_token == token,
                    ),
                )
                .values(lock_token=token, lock_heartbeat=now, status="starting", updated_at=now)
            )
            session.commit()
            return result.rowcount == 1
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def release_stale_lock(
        self, account_id: int, *, stale_after_seconds: float, now: datetime
    ) -> bool:
        cutoff = now - timedelta(seconds=stale_after_seconds)
        session = self._session_factory()
        try:
            result = session.execute(
                update(DemoRuntimeStatus)
                .where(
                    DemoRuntimeStatus.account_id == account_id,
                    DemoRuntimeStatus.lock_token.is_not(None),
                    or_(
                        DemoRuntimeStatus.lock_heartbeat.is_(None),
                        DemoRuntimeStatus.lock_heartbeat <= cutoff,
                    ),
                )
                .values(
                    status="stale_lock_released",
                    lock_token=None,
                    lock_heartbeat=None,
                    updated_at=now,
                )
            )
            session.commit()
            return result.rowcount == 1
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_status(
        self,
        account_id: int,
        token: str,
        *,
        now: datetime,
        status: Optional[str] = None,
        feed_connected: Optional[bool] = None,
        feed_stale: Optional[bool] = None,
        ws_authenticated: Optional[bool] = None,
        reconciliation_consistent: Optional[bool] = None,
        last_error: Optional[str] = None,
        heartbeat: bool = True,
    ) -> None:
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == account_id)
            )
            if row is None or row.lock_token != token:
                session.commit()
                return
            if status is not None:
                row.status = status
            if feed_connected is not None:
                row.feed_connected = feed_connected
            if feed_stale is not None:
                row.feed_stale = feed_stale
            if ws_authenticated is not None:
                row.ws_authenticated = ws_authenticated
            if reconciliation_consistent is not None:
                row.reconciliation_consistent = reconciliation_consistent
            row.last_error = (last_error or None) if last_error is not None else row.last_error
            if heartbeat:
                row.lock_heartbeat = now
            row.updated_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def release_lock(
        self, account_id: int, token: str, *, now: datetime, status: str = "stopped"
    ) -> None:
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == account_id)
            )
            if row is not None and row.lock_token == token:
                row.status = status
                row.lock_token = None
                row.lock_heartbeat = None
                row.updated_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
