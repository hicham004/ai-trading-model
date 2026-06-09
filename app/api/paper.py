"""Read-only FastAPI router for the Phase 4 paper-trading ledger.

These endpoints expose the persisted paper-trading journal (account, balances,
positions, signals, risk decisions, orders, fills, trades, daily report, events,
and runtime health). They are strictly READ-ONLY: there is no endpoint that
places, modifies, or cancels an order, touches a real account, or starts the
runtime. Everything reported is virtual and SIMULATION ONLY.

The runner writes the ledger in a separate process; this API reads whatever has
been persisted for the requested account (mirroring how the Phase 3 live API and
runner are separate processes sharing a database).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    PaperAccountOut,
    PaperBalanceOut,
    PaperBalancesOut,
    PaperDailyReportOut,
    PaperDailyReportRow,
    PaperEventOut,
    PaperFillOut,
    PaperHealthOut,
    PaperOrderOut,
    PaperPositionOut,
    PaperPositionsOut,
    PaperRiskDecisionOut,
    PaperSignalOut,
    PaperTradeOut,
)
from app.config import get_settings
from app.db.database import get_session_factory
from app.db.models import (
    PaperAccount,
    PaperEquitySnapshot,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperRiskDecision,
    PaperRuntimeStatus,
    PaperSignal,
    PaperTrade,
)

router = APIRouter(prefix="/paper", tags=["paper-trading"])


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _default_account() -> str:
    return get_settings().paper_account_name


def _account_id(db: Session, account: str) -> Optional[int]:
    return db.scalar(select(PaperAccount.id).where(PaperAccount.name == account))


def _latest_snapshot(db: Session, account_id: int) -> Optional[PaperEquitySnapshot]:
    return db.scalar(
        select(PaperEquitySnapshot)
        .where(PaperEquitySnapshot.account_id == account_id)
        .order_by(
            PaperEquitySnapshot.market_time.desc(),
            PaperEquitySnapshot.id.desc(),
        )
        .limit(1)
    )


@router.get("/accounts", response_model=List[str])
def paper_accounts(db: Session = Depends(get_db)) -> List[str]:
    """List paper account names that exist in the ledger."""
    return list(db.scalars(select(PaperAccount.name).order_by(PaperAccount.name)).all())


@router.get("/health", response_model=PaperHealthOut)
def paper_health(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> PaperHealthOut:
    """Runtime health, kill-switch, feed, and reconciliation status (read-only)."""
    account_id = _account_id(db, account)
    if account_id is None:
        return PaperHealthOut(
            account=account,
            exists=False,
            status="unknown",
            running=False,
            kill_switch_engaged=False,
            feed_connected=False,
            feed_stale=True,
            books_synchronized=False,
            reconciliation_consistent=True,
        )
    status = db.scalar(
        select(PaperRuntimeStatus).where(PaperRuntimeStatus.account_id == account_id)
    )
    if status is None:
        return PaperHealthOut(
            account=account,
            exists=True,
            status="idle",
            running=False,
            kill_switch_engaged=False,
            feed_connected=False,
            feed_stale=True,
            books_synchronized=False,
            reconciliation_consistent=True,
        )
    heartbeat = _utc(status.lock_heartbeat) if status.lock_heartbeat else None
    heartbeat_fresh = (
        heartbeat is not None
        and (datetime.now(tz=timezone.utc) - heartbeat).total_seconds()
        <= get_settings().paper_lock_stale_seconds
    )
    running = status.status == "running" and bool(status.lock_token) and heartbeat_fresh
    return PaperHealthOut(
        account=account,
        exists=True,
        status=("stale" if status.status == "running" and not running else status.status),
        running=running,
        kill_switch_engaged=status.kill_switch_engaged,
        feed_connected=status.feed_connected,
        feed_stale=status.feed_stale,
        books_synchronized=status.books_synchronized,
        reconciliation_consistent=status.reconciliation_consistent,
        last_error=status.last_error,
        last_heartbeat=heartbeat,
    )


@router.get("/account", response_model=PaperAccountOut)
def paper_account(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> PaperAccountOut:
    """Account equity/cash/PnL from the latest persisted equity snapshot."""
    row = db.scalar(select(PaperAccount).where(PaperAccount.name == account))
    if row is None:
        return PaperAccountOut(account=account, exists=False)
    snapshot = _latest_snapshot(db, row.id)
    status = db.scalar(
        select(PaperRuntimeStatus).where(PaperRuntimeStatus.account_id == row.id)
    )
    kill_switch_engaged = (
        bool(status.kill_switch_engaged) if status is not None else False
    )
    if snapshot is None:
        return PaperAccountOut(
            account=account,
            exists=True,
            base_currency=row.base_currency,
            starting_cash=row.starting_cash,
            cash=row.starting_cash,
            equity=row.starting_cash,
            kill_switch_engaged=kill_switch_engaged,
        )
    return PaperAccountOut(
        account=account,
        exists=True,
        base_currency=row.base_currency,
        starting_cash=row.starting_cash,
        cash=snapshot.cash,
        position_value=snapshot.position_value,
        equity=snapshot.equity,
        realized_pnl=snapshot.realized_pnl,
        unrealized_pnl=snapshot.unrealized_pnl,
        day_start_equity=snapshot.day_start_equity,
        day_realized_pnl=snapshot.day_realized_pnl,
        open_position_count=snapshot.open_position_count,
        kill_switch_engaged=kill_switch_engaged,
        as_of=snapshot.market_time,
    )


def _snapshot_positions(snapshot: Optional[PaperEquitySnapshot]) -> List[dict]:
    if snapshot is None:
        return []
    try:
        value = json.loads(snapshot.positions_json or "[]")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
    except (ValueError, TypeError):
        return []


@router.get("/positions", response_model=PaperPositionsOut)
def paper_positions(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> PaperPositionsOut:
    """Open virtual positions from the latest equity snapshot."""
    account_id = _account_id(db, account)
    snapshot = _latest_snapshot(db, account_id) if account_id is not None else None
    positions = []
    for p in _snapshot_positions(snapshot):
        try:
            positions.append(
                PaperPositionOut(
                    instrument=str(p["instrument"]),
                    quantity=float(p["quantity"]),
                    entry_price=float(p["entry_price"]),
                    stop_loss=(
                        float(p["stop_loss"])
                        if p.get("stop_loss") is not None
                        else None
                    ),
                    entry_time=_parse_dt(p.get("entry_time")),
                    signal_id=str(p.get("signal_id", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return PaperPositionsOut(account=account, positions=positions)


@router.get("/balances", response_model=PaperBalancesOut)
def paper_balances(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> PaperBalancesOut:
    """Virtual cash plus per-asset balances from the latest snapshot."""
    row = db.scalar(select(PaperAccount).where(PaperAccount.name == account))
    if row is None:
        return PaperBalancesOut(account=account, balances=[])
    snapshot = _latest_snapshot(db, row.id)
    cash = snapshot.cash if snapshot is not None else row.starting_cash
    balances = [PaperBalanceOut(asset=row.base_currency, amount=cash)]
    for p in _snapshot_positions(snapshot):
        asset = p["instrument"].split("-")[0]
        balances.append(PaperBalanceOut(asset=asset, amount=float(p["quantity"])))
    return PaperBalancesOut(account=account, balances=balances)


@router.get("/signals", response_model=List[PaperSignalOut])
def paper_signals(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperSignalOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperSignal)
        .where(PaperSignal.account_id == account_id)
        .order_by(PaperSignal.decision_time.desc(), PaperSignal.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperSignalOut(
            signal_id=r.signal_id,
            instrument=r.instrument,
            timeframe=r.timeframe,
            signal_data_time=r.signal_data_time,
            candle_close_time=r.candle_close_time,
            decision_time=r.decision_time,
            action=r.action,
            confidence=r.confidence,
            reason=r.reason,
            stop_loss=r.stop_loss,
        )
        for r in rows
    ]


@router.get("/risk-decisions", response_model=List[PaperRiskDecisionOut])
def paper_risk_decisions(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperRiskDecisionOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperRiskDecision)
        .where(PaperRiskDecision.account_id == account_id)
        .order_by(PaperRiskDecision.decision_time.desc(), PaperRiskDecision.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperRiskDecisionOut(
            signal_id=r.signal_id,
            decision_time=r.decision_time,
            intent=r.intent,
            allowed=r.allowed,
            reason=r.reason,
        )
        for r in rows
    ]


@router.get("/orders", response_model=List[PaperOrderOut])
def paper_orders(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperOrderOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperOrder)
        .where(PaperOrder.account_id == account_id)
        .order_by(PaperOrder.order_time.desc(), PaperOrder.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperOrderOut(
            client_order_id=r.client_order_id,
            signal_id=r.signal_id,
            instrument=r.instrument,
            side=r.side,
            intent=r.intent,
            quantity=r.quantity,
            reference_price=r.reference_price,
            quote_bid=r.quote_bid,
            quote_ask=r.quote_ask,
            quote_time=r.quote_time,
            order_time=r.order_time,
            status=r.status,
        )
        for r in rows
    ]


@router.get("/fills", response_model=List[PaperFillOut])
def paper_fills(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperFillOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperFill)
        .where(PaperFill.account_id == account_id)
        .order_by(PaperFill.fill_time.desc(), PaperFill.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperFillOut(
            fill_id=r.fill_id,
            client_order_id=r.client_order_id,
            instrument=r.instrument,
            side=r.side,
            quantity=r.quantity,
            price=r.price,
            fee=r.fee,
            slippage_cost=r.slippage_cost,
            fill_time=r.fill_time,
            is_simulated=r.is_simulated,
        )
        for r in rows
    ]


@router.get("/trades", response_model=List[PaperTradeOut])
def paper_trades(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperTradeOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperTrade)
        .where(PaperTrade.account_id == account_id)
        .order_by(PaperTrade.exit_time.desc(), PaperTrade.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperTradeOut(
            instrument=r.instrument,
            entry_time=r.entry_time,
            exit_time=r.exit_time,
            entry_price=r.entry_price,
            exit_price=r.exit_price,
            quantity=r.quantity,
            fees=r.fees,
            slippage_cost=r.slippage_cost,
            exit_reason=r.exit_reason,
            realized_pnl=r.realized_pnl,
        )
        for r in rows
    ]


@router.get("/events", response_model=List[PaperEventOut])
def paper_events(
    account: str = Query(default_factory=_default_account),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[PaperEventOut]:
    account_id = _account_id(db, account)
    if account_id is None:
        return []
    rows = db.scalars(
        select(PaperEvent)
        .where(PaperEvent.account_id == account_id)
        .order_by(PaperEvent.event_time.desc(), PaperEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        PaperEventOut(
            event_time=r.event_time,
            event_type=r.event_type,
            severity=r.severity,
            message=r.message,
        )
        for r in rows
    ]


@router.get("/report/daily", response_model=PaperDailyReportOut)
def paper_daily_report(
    account: str = Query(default_factory=_default_account),
    db: Session = Depends(get_db),
) -> PaperDailyReportOut:
    """Per-UTC-day realised summary plus current equity (read-only)."""
    account_row = db.scalar(
        select(PaperAccount).where(PaperAccount.name == account)
    )
    if account_row is None:
        return PaperDailyReportOut(account=account, equity=0.0, realized_pnl=0.0, days=[])
    account_id = account_row.id
    trades = db.scalars(
        select(PaperTrade).where(PaperTrade.account_id == account_id)
    ).all()
    by_day: dict[str, dict] = {}
    for t in trades:
        day = _utc(t.exit_time).date().isoformat()
        bucket = by_day.setdefault(
            day, {"num_trades": 0, "wins": 0, "realized_pnl": 0.0, "fees": 0.0, "slippage_cost": 0.0}
        )
        bucket["num_trades"] += 1
        bucket["wins"] += 1 if t.realized_pnl > 0 else 0
        bucket["realized_pnl"] += t.realized_pnl
        bucket["fees"] += t.fees
        bucket["slippage_cost"] += t.slippage_cost
    days = [
        PaperDailyReportRow(day=day, **vals)
        for day, vals in sorted(by_day.items())
    ]
    snapshot = _latest_snapshot(db, account_id)
    equity = snapshot.equity if snapshot is not None else account_row.starting_cash
    realized = snapshot.realized_pnl if snapshot is not None else 0.0
    return PaperDailyReportOut(
        account=account, equity=equity, realized_pnl=realized, days=days
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        return None
