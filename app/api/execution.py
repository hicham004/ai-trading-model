"""Read-only FastAPI router for the Phase 5 demo-execution ledger.

Strictly READ-ONLY: no endpoint places, modifies, cancels, arms, disarms, or
otherwise mutates anything. Operator actions (arm/disarm/kill switch/reconcile)
are LOCAL CLI commands only (``scripts/run_demo_trading.py``), never HTTP. No
credential or secret is ever returned. Everything reported is demo/simulated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_session_factory
from app.db.models import (
    DemoAccount,
    DemoBalanceSnapshot,
    DemoEvent,
    DemoFill,
    DemoOrderIntent,
    DemoOrderUpdate,
    DemoReconciliation,
    DemoRuntimeStatus,
    DemoSubmission,
)

router = APIRouter(prefix="/demo", tags=["demo-execution"])

_NOTE = "OKX DEMO (simulated) execution only. No real funds, orders, or account."


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _default_account() -> str:
    return get_settings().demo_account_name


def _account_id(db: Session, account: str) -> Optional[int]:
    return db.scalar(select(DemoAccount.id).where(DemoAccount.name == account))


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DemoHealthOut(BaseModel):
    account: str
    exists: bool
    status: str
    armed: bool
    armed_until: Optional[datetime] = None
    kill_switch_engaged: bool = False
    # Fail closed: health reports inconsistent until a successful reconciliation.
    reconciliation_consistent: bool = False
    feed_connected: bool = False
    feed_stale: bool = True
    ws_authenticated: bool = False
    lock_held: bool = False
    last_error: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    note: str = _NOTE


@router.get("/accounts", response_model=List[str])
def demo_accounts(db: Session = Depends(get_db)) -> List[str]:
    return list(db.scalars(select(DemoAccount.name).order_by(DemoAccount.name)).all())


@router.get("/health", response_model=DemoHealthOut)
def demo_health(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> DemoHealthOut:
    aid = _account_id(db, account)
    if aid is None:
        return DemoHealthOut(account=account, exists=False, status="unknown", armed=False)
    row = db.scalar(select(DemoRuntimeStatus).where(DemoRuntimeStatus.account_id == aid))
    if row is None:
        return DemoHealthOut(account=account, exists=True, status="idle", armed=False)
    now = datetime.now(tz=timezone.utc)
    armed_until = _utc(row.armed_until)
    armed = armed_until is not None and armed_until > now
    return DemoHealthOut(
        account=account,
        exists=True,
        status=row.status,
        armed=armed,
        armed_until=armed_until,
        kill_switch_engaged=row.kill_switch_engaged,
        reconciliation_consistent=row.reconciliation_consistent,
        feed_connected=row.feed_connected,
        feed_stale=row.feed_stale,
        ws_authenticated=row.ws_authenticated,
        lock_held=bool(row.lock_token),
        last_error=row.last_error,
        last_heartbeat=_utc(row.lock_heartbeat),
    )


class DemoAccountOut(BaseModel):
    account: str
    exists: bool
    key_fingerprint: Optional[str] = None
    config: dict = {}
    created_at: Optional[datetime] = None
    note: str = _NOTE


@router.get("/account", response_model=DemoAccountOut)
def demo_account(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> DemoAccountOut:
    row = db.scalar(select(DemoAccount).where(DemoAccount.name == account))
    if row is None:
        return DemoAccountOut(account=account, exists=False)
    try:
        config = json.loads(row.config_json or "{}")
    except (ValueError, TypeError):
        config = {}
    return DemoAccountOut(
        account=account,
        exists=True,
        key_fingerprint=row.key_fingerprint,
        config=config if isinstance(config, dict) else {},
        created_at=_utc(row.created_at),
    )


class DemoBalancesOut(BaseModel):
    account: str
    snapshot_time: Optional[datetime] = None
    balances: list = []
    note: str = _NOTE


@router.get("/balances", response_model=DemoBalancesOut)
def demo_balances(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> DemoBalancesOut:
    aid = _account_id(db, account)
    if aid is None:
        return DemoBalancesOut(account=account)
    row = db.scalar(
        select(DemoBalanceSnapshot)
        .where(DemoBalanceSnapshot.account_id == aid, DemoBalanceSnapshot.source != "baseline")
        .order_by(DemoBalanceSnapshot.id.desc())
        .limit(1)
    )
    if row is None:
        return DemoBalancesOut(account=account)
    try:
        balances = json.loads(row.balances_json or "[]")
    except (ValueError, TypeError):
        balances = []
    return DemoBalancesOut(
        account=account, snapshot_time=_utc(row.snapshot_time), balances=balances
    )


class DemoIntentOut(BaseModel):
    client_order_id: str
    signal_id: str
    instrument: str
    side: str
    intent: str
    ord_type: str
    price: Optional[str] = None
    size: str
    stop_loss: Optional[str] = None
    exchange_order_id: Optional[str] = None
    status: str
    filled_size: str
    avg_price: Optional[str] = None
    requested_at: datetime
    submitted_at: Optional[datetime] = None
    attempts: int


@router.get("/intents", response_model=List[DemoIntentOut])
def demo_intents(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DemoIntentOut]:
    aid = _account_id(db, account)
    if aid is None:
        return []
    rows = db.scalars(
        select(DemoOrderIntent)
        .where(DemoOrderIntent.account_id == aid)
        .order_by(DemoOrderIntent.id.desc())
        .limit(limit)
    ).all()
    return [
        DemoIntentOut(
            client_order_id=r.client_order_id,
            signal_id=r.signal_id,
            instrument=r.instrument,
            side=r.side,
            intent=r.intent,
            ord_type=r.ord_type,
            price=r.price,
            size=r.size,
            stop_loss=r.stop_loss,
            exchange_order_id=r.exchange_order_id,
            status=r.status,
            filled_size=r.filled_size,
            avg_price=r.avg_price,
            requested_at=_utc(r.requested_at),
            submitted_at=_utc(r.submitted_at),
            attempts=r.attempts,
        )
        for r in rows
    ]


class DemoSubmissionOut(BaseModel):
    client_order_id: str
    request_kind: str
    attempt: int
    sent_at: datetime
    outcome: str
    exchange_order_id: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


@router.get("/submissions", response_model=List[DemoSubmissionOut])
def demo_submissions(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DemoSubmissionOut]:
    aid = _account_id(db, account)
    if aid is None:
        return []
    rows = db.scalars(
        select(DemoSubmission)
        .where(DemoSubmission.account_id == aid)
        .order_by(DemoSubmission.id.desc())
        .limit(limit)
    ).all()
    return [
        DemoSubmissionOut(
            client_order_id=r.client_order_id,
            request_kind=r.request_kind,
            attempt=r.attempt,
            sent_at=_utc(r.sent_at),
            outcome=r.outcome,
            exchange_order_id=r.exchange_order_id,
            code=r.code,
            message=r.message,
        )
        for r in rows
    ]


class DemoFillOut(BaseModel):
    fill_id: str
    client_order_id: Optional[str] = None
    instrument: str
    side: str
    fill_size: str
    fill_price: str
    fee: Optional[str] = None
    fee_ccy: Optional[str] = None
    fill_time: datetime
    source: str


@router.get("/fills", response_model=List[DemoFillOut])
def demo_fills(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DemoFillOut]:
    aid = _account_id(db, account)
    if aid is None:
        return []
    rows = db.scalars(
        select(DemoFill)
        .where(DemoFill.account_id == aid)
        .order_by(DemoFill.id.desc())
        .limit(limit)
    ).all()
    return [
        DemoFillOut(
            fill_id=r.fill_id,
            client_order_id=r.client_order_id,
            instrument=r.instrument,
            side=r.side,
            fill_size=r.fill_size,
            fill_price=r.fill_price,
            fee=r.fee,
            fee_ccy=r.fee_ccy,
            fill_time=_utc(r.fill_time),
            source=r.source,
        )
        for r in rows
    ]


class DemoReconciliationOut(BaseModel):
    run_at: datetime
    consistent: bool
    foreign_orders: int
    unexplained_balances: int
    issues: list = []


@router.get("/reconciliations", response_model=List[DemoReconciliationOut])
def demo_reconciliations(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> List[DemoReconciliationOut]:
    aid = _account_id(db, account)
    if aid is None:
        return []
    rows = db.scalars(
        select(DemoReconciliation)
        .where(DemoReconciliation.account_id == aid)
        .order_by(DemoReconciliation.id.desc())
        .limit(limit)
    ).all()
    out = []
    for r in rows:
        try:
            issues = json.loads(r.issues_json or "[]")
        except (ValueError, TypeError):
            issues = []
        out.append(
            DemoReconciliationOut(
                run_at=_utc(r.run_at),
                consistent=r.consistent,
                foreign_orders=r.foreign_orders,
                unexplained_balances=r.unexplained_balances,
                issues=issues if isinstance(issues, list) else [],
            )
        )
    return out


class DemoEventOut(BaseModel):
    event_time: datetime
    event_type: str
    severity: str
    message: str


@router.get("/events", response_model=List[DemoEventOut])
def demo_events(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DemoEventOut]:
    aid = _account_id(db, account)
    if aid is None:
        return []
    rows = db.scalars(
        select(DemoEvent)
        .where(DemoEvent.account_id == aid)
        .order_by(DemoEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        DemoEventOut(
            event_time=_utc(r.event_time),
            event_type=r.event_type,
            severity=r.severity,
            message=r.message,
        )
        for r in rows
    ]
