"""Persistent ledger / journal and deterministic reconciliation (Phase 4).

This module is the only place that writes the paper-trading ledger. It persists
each candle's full outcome ATOMICALLY (one transaction writes the processed
marker plus its signal, risk decisions, orders, fills, trades, events, and
equity snapshot), so a crash never leaves partial monetary state and a candle is
never recorded twice.

On restart, :meth:`PaperLedger.reconcile` reconstructs cash and positions from
the latest equity snapshot and independently cross-checks them by replaying the
append-only fill log. If the two disagree - or the fill log implies an
impossible state such as negative cash or overselling - reconciliation reports
``consistent=False`` and the runtime refuses to trade (fail closed). Audit
history is only ever appended, never mutated or discarded.

A lightweight advisory lock (``paper_runtime_status``) prevents two runners from
driving the same paper account at once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isclose, isfinite
from typing import Callable, Dict, List, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.backtest.validation import validate_candles
from app.broker.base import OrderSide
from app.db.models import (
    PaperAccount as PaperAccountRow,
)
from app.db.models import (
    PaperDailyBaseline,
    PaperEquitySnapshot,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperProcessedCandle,
    PaperRiskDecision,
    PaperRuntimeStatus,
    PaperSignal,
    PaperTrade,
)
from app.logging_config import get_logger
from app.paper.account import PaperAccount, Position
from app.paper.records import (
    EXIT_SIGNAL,
    EXIT_STOP_LOSS,
    INTENT_SIGNAL_EXIT,
    INTENT_STOP_EXIT,
    CandleOutcome,
    EventRecord,
)
from app.strategy.base import MarketCandle
from app.strategy.timeframes import parse_timeframe

logger = get_logger(__name__)

# Tolerances for cross-checking reconstructed vs replayed monetary state.
_CASH_REL_TOL = 1e-6
_CASH_ABS_TOL = 1e-6
_QTY_ABS_TOL = 1e-9


class CandleAlreadyPersisted(RuntimeError):
    """Raised if a processed-candle marker already exists (should not happen)."""


class AccountConfigMismatch(RuntimeError):
    """Raised when an existing paper account is opened with different config."""


class KillSwitchEngaged(RuntimeError):
    """Raised when an entry outcome races with an engaged kill switch."""


@dataclass
class ReconciledState:
    """Deterministic reconstruction of an account from its persisted ledger."""

    consistent: bool
    reason: str
    account: PaperAccount
    watermarks: Dict[str, datetime] = field(default_factory=dict)
    last_close: Dict[str, float] = field(default_factory=dict)
    history: Dict[str, List[MarketCandle]] = field(default_factory=dict)
    kill_switch_engaged: bool = False
    issues: List[str] = field(default_factory=list)


def _utc(value: datetime) -> datetime:
    """Normalize a possibly-naive DB datetime to timezone-aware UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money_matches(left: float, right: float) -> bool:
    return isclose(left, right, rel_tol=_CASH_REL_TOL, abs_tol=_CASH_ABS_TOL)


class PaperLedger:
    """Atomic writes, reconciliation, and the advisory runtime lock."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        account_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._account_name = account_name

    # -- account bootstrap --------------------------------------------------

    def ensure_account(self, starting_cash: float, config: dict) -> int:
        """Return the account id, creating the account row on first use.

        A paper account's complete configuration is immutable. Changing a
        strategy, instrument set, costs, limits, timeframe, or starting balance
        requires a new account name so an existing position can never become
        stranded under incompatible runtime behavior.
        """
        canonical_config = json.dumps(config, default=str, sort_keys=True)
        session = self._session_factory()
        try:
            row = session.scalar(
                select(PaperAccountRow).where(PaperAccountRow.name == self._account_name)
            )
            if row is None:
                row = PaperAccountRow(
                    name=self._account_name,
                    starting_cash=starting_cash,
                    config_json=canonical_config,
                )
                session.add(row)
                session.flush()
                session.add(PaperRuntimeStatus(account_id=row.id))
                session.commit()
                return row.id
            account_id = row.id
            stored = row.starting_cash
            stored_config = row.config_json
            status_exists = session.scalar(
                select(PaperRuntimeStatus.id).where(
                    PaperRuntimeStatus.account_id == account_id
                )
            )
            if status_exists is None:
                session.add(PaperRuntimeStatus(account_id=account_id))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if (
            abs(stored - starting_cash) > _CASH_ABS_TOL
            or stored_config != canonical_config
        ):
            raise AccountConfigMismatch(
                "paper account configuration does not match its stored "
                "configuration; use a new --account name"
            )
        return account_id

    def account_starting_cash(self, account_id: int) -> float:
        session = self._session_factory()
        try:
            value = session.scalar(
                select(PaperAccountRow.starting_cash).where(
                    PaperAccountRow.id == account_id
                )
            )
            if value is None:
                raise ValueError(f"paper account {account_id} not found")
            return float(value)
        finally:
            session.close()

    def find_account_id(self) -> Optional[int]:
        """Return the configured account's id without creating or changing it."""
        session = self._session_factory()
        try:
            return session.scalar(
                select(PaperAccountRow.id).where(
                    PaperAccountRow.name == self._account_name
                )
            )
        finally:
            session.close()

    # -- atomic outcome persistence ----------------------------------------

    def persist_outcome(self, account_id: int, outcome: CandleOutcome) -> None:
        """Persist one accepted candle's full outcome in a single transaction."""
        if not outcome.accepted:
            raise ValueError("refusing to persist a rejected candle outcome")
        if outcome.account is None or outcome.equity_snapshot is None:
            raise ValueError("accepted outcome must include account and equity snapshot")
        if any(not fill.is_simulated for fill in outcome.fills):
            raise ValueError("refusing to persist a non-simulated paper fill")
        candle_values = (
            outcome.candle_open,
            outcome.candle_high,
            outcome.candle_low,
            outcome.candle_close,
            outcome.candle_volume,
        )
        if any(value is None or not isfinite(value) for value in candle_values):
            raise ValueError("accepted outcome must include finite candle OHLCV")
        session = self._session_factory()
        try:
            has_entry = any(order.intent == "entry" for order in outcome.orders)
            if has_entry:
                status_row = session.scalar(
                    select(PaperRuntimeStatus)
                    .where(PaperRuntimeStatus.account_id == account_id)
                    .with_for_update()
                )
                if status_row is None or status_row.kill_switch_engaged:
                    raise KillSwitchEngaged(
                        "paper entry blocked by the persisted kill switch"
                    )
            existing = session.scalar(
                select(PaperProcessedCandle.id).where(
                    PaperProcessedCandle.account_id == account_id,
                    PaperProcessedCandle.instrument == outcome.instrument,
                    PaperProcessedCandle.timeframe == outcome.timeframe,
                    PaperProcessedCandle.candle_open_time == outcome.candle_open_time,
                )
            )
            if existing is not None:
                raise CandleAlreadyPersisted(
                    f"candle {outcome.instrument} {outcome.candle_open_time} "
                    "already processed"
                )

            session.add(
                PaperProcessedCandle(
                    account_id=account_id,
                    instrument=outcome.instrument,
                    timeframe=outcome.timeframe,
                    candle_open_time=outcome.candle_open_time,
                    candle_close_time=outcome.candle_close_time,
                    open=outcome.candle_open,
                    high=outcome.candle_high,
                    low=outcome.candle_low,
                    close=outcome.candle_close,
                    volume=outcome.candle_volume,
                )
            )
            if outcome.signal is not None:
                s = outcome.signal
                session.add(
                    PaperSignal(
                        account_id=account_id,
                        signal_id=s.signal_id,
                        instrument=s.instrument,
                        timeframe=s.timeframe,
                        signal_data_time=s.signal_data_time,
                        candle_close_time=s.candle_close_time,
                        decision_time=s.decision_time,
                        action=s.action,
                        confidence=s.confidence,
                        reason=s.reason[:256],
                        stop_loss=s.stop_loss,
                    )
                )
            for rd in outcome.risk_decisions:
                session.add(
                    PaperRiskDecision(
                        account_id=account_id,
                        signal_id=rd.signal_id,
                        decision_time=rd.decision_time,
                        intent=rd.intent,
                        allowed=rd.allowed,
                        reason=rd.reason[:64],
                    )
                )
            for order in outcome.orders:
                session.add(
                    PaperOrder(
                        account_id=account_id,
                        client_order_id=order.client_order_id,
                        signal_id=order.signal_id,
                        instrument=order.instrument,
                        side=order.side.value,
                        intent=order.intent,
                        quantity=order.quantity,
                        reference_price=order.reference_price,
                        quote_bid=order.quote_bid,
                        quote_ask=order.quote_ask,
                        quote_time=order.quote_time,
                        order_time=order.order_time,
                        status=order.status,
                    )
                )
            for fill in outcome.fills:
                session.add(
                    PaperFill(
                        account_id=account_id,
                        fill_id=fill.fill_id,
                        client_order_id=fill.client_order_id,
                        instrument=fill.instrument,
                        side=fill.side.value,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                        slippage_cost=fill.slippage_cost,
                        fill_time=fill.fill_time,
                        is_simulated=fill.is_simulated,
                    )
                )
            for trade in outcome.trades:
                session.add(
                    PaperTrade(
                        account_id=account_id,
                        instrument=trade.instrument,
                        entry_time=trade.entry_time,
                        exit_time=trade.exit_time,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        quantity=trade.quantity,
                        fees=trade.fees,
                        slippage_cost=trade.slippage_cost,
                        exit_reason=trade.exit_reason,
                        realized_pnl=trade.realized_pnl,
                        entry_signal_id=trade.entry_signal_id,
                        exit_signal_id=trade.exit_signal_id,
                    )
                )
            for event in outcome.events:
                session.add(self._event_row(account_id, event))
            if outcome.equity_snapshot is not None:
                es = outcome.equity_snapshot
                market_day = es.market_time.date()
                baseline = session.scalar(
                    select(PaperDailyBaseline)
                    .where(
                        PaperDailyBaseline.account_id == account_id,
                        PaperDailyBaseline.market_day == market_day,
                    )
                    .with_for_update()
                )
                if baseline is None:
                    session.add(
                        PaperDailyBaseline(
                            account_id=account_id,
                            market_day=market_day,
                            start_equity=es.day_start_equity,
                        )
                    )
                elif not _money_matches(
                    baseline.start_equity, es.day_start_equity
                ):
                    raise ValueError(
                        "day_start_equity changed within the same UTC day"
                    )
                session.add(
                    PaperEquitySnapshot(
                        account_id=account_id,
                        snapshot_time=es.snapshot_time,
                        market_time=es.market_time,
                        cash=es.cash,
                        position_value=es.position_value,
                        equity=es.equity,
                        realized_pnl=es.realized_pnl,
                        unrealized_pnl=es.unrealized_pnl,
                        day_start_equity=es.day_start_equity,
                        day_realized_pnl=es.day_realized_pnl,
                        open_position_count=es.open_position_count,
                        positions_json=json.dumps(es.positions, default=str),
                        kill_switch_engaged=es.kill_switch_engaged,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _event_row(account_id: int, event: EventRecord) -> PaperEvent:
        return PaperEvent(
            account_id=account_id,
            event_time=event.event_time,
            event_type=event.event_type[:48],
            severity=event.severity[:16],
            message=event.message[:512],
            payload_json=json.dumps(event.payload, default=str),
        )

    def record_event(self, account_id: int, event: EventRecord) -> None:
        """Append a single operational event in its own transaction."""
        session = self._session_factory()
        try:
            session.add(self._event_row(account_id, event))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_kill_switch(
        self, account_id: int, engaged: bool, *, now: datetime
    ) -> None:
        """Set the local paper-entry kill switch without touching lock state."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(PaperRuntimeStatus)
                .where(PaperRuntimeStatus.account_id == account_id)
                .with_for_update()
            )
            if row is None:
                row = PaperRuntimeStatus(account_id=account_id)
                session.add(row)
            row.kill_switch_engaged = bool(engaged)
            row.updated_at = now
            session.add(
                self._event_row(
                    account_id,
                    EventRecord(
                        event_time=now,
                        event_type=(
                            "kill_switch_engaged"
                            if engaged
                            else "kill_switch_released"
                        ),
                        severity="warning" if engaged else "info",
                        message=(
                            "paper entry kill switch engaged"
                            if engaged
                            else "paper entry kill switch released"
                        ),
                        payload={},
                    ),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- reconciliation -----------------------------------------------------

    def reconcile(
        self,
        account_id: int,
        starting_cash: float,
        *,
        history_limit: Optional[int] = None,
    ) -> ReconciledState:
        """Rebuild state from the ledger and cross-check it. Fail closed."""
        session = self._session_factory()
        try:
            fills = session.scalars(
                select(PaperFill)
                .where(PaperFill.account_id == account_id)
                .order_by(PaperFill.fill_time.asc(), PaperFill.id.asc())
            ).all()
            orders = session.scalars(
                select(PaperOrder)
                .where(PaperOrder.account_id == account_id)
                .order_by(PaperOrder.order_time.asc(), PaperOrder.id.asc())
            ).all()
            signals = session.scalars(
                select(PaperSignal).where(PaperSignal.account_id == account_id)
            ).all()
            snapshots = session.scalars(
                select(PaperEquitySnapshot)
                .where(PaperEquitySnapshot.account_id == account_id)
                .order_by(
                    PaperEquitySnapshot.market_time.asc(),
                    PaperEquitySnapshot.id.asc(),
                )
            ).all()
            snapshot = snapshots[-1] if snapshots else None
            trades = session.scalars(
                select(PaperTrade).where(PaperTrade.account_id == account_id)
            ).all()
            processed = session.scalars(
                select(PaperProcessedCandle)
                .where(PaperProcessedCandle.account_id == account_id)
                .order_by(
                    PaperProcessedCandle.instrument.asc(),
                    PaperProcessedCandle.candle_open_time.asc(),
                )
            ).all()
            baselines = session.scalars(
                select(PaperDailyBaseline).where(
                    PaperDailyBaseline.account_id == account_id
                )
            ).all()
            status = session.scalar(
                select(PaperRuntimeStatus).where(
                    PaperRuntimeStatus.account_id == account_id
                )
            )
            kill_switch = bool(status.kill_switch_engaged) if status is not None else False
        finally:
            session.close()

        issues: List[str] = []
        watermarks: Dict[str, datetime] = {}
        history: Dict[str, List[MarketCandle]] = {}
        for row in processed:
            ts = _utc(row.candle_open_time)
            current = watermarks.get(row.instrument)
            if current is None or ts > current:
                watermarks[row.instrument] = ts
            history.setdefault(row.instrument, []).append(
                MarketCandle(
                    instrument=row.instrument,
                    timeframe=row.timeframe,
                    timestamp=ts,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                )
            )
        for instrument, candles in history.items():
            timeframes = {candle.timeframe for candle in candles}
            if len(timeframes) != 1:
                issues.append(f"mixed timeframes in candle history for {instrument}")
                continue
            timeframe = next(iter(timeframes))
            try:
                interval = parse_timeframe(timeframe or "")
                validate_candles(
                    candles,
                    expected_instrument=instrument,
                    expected_timeframe=timeframe,
                )
            except ValueError as exc:
                issues.append(
                    f"invalid candle history for {instrument}: {type(exc).__name__}"
                )
                continue
            rows = [row for row in processed if row.instrument == instrument]
            for row, candle in zip(rows, candles):
                if _utc(row.candle_close_time) != candle.timestamp + interval:
                    issues.append(
                        f"invalid candle close time for {instrument} "
                        f"{candle.timestamp.isoformat()}"
                    )
            for previous, current in zip(candles, candles[1:]):
                if current.timestamp != previous.timestamp + interval:
                    issues.append(
                        f"processed candle gap for {instrument}: "
                        f"{previous.timestamp.isoformat()} -> "
                        f"{current.timestamp.isoformat()}"
                    )
        processed_closes = sorted(_utc(row.candle_close_time) for row in processed)
        snapshot_times = sorted(_utc(row.market_time) for row in snapshots)
        if processed_closes != snapshot_times:
            issues.append(
                "processed candles do not have a one-to-one equity snapshot match"
            )
        if history_limit is not None:
            history = {
                instrument: candles[-history_limit:]
                for instrument, candles in history.items()
            }

        # Fresh account: nothing persisted yet.
        if not fills and not orders and not trades and not processed and snapshot is None:
            return ReconciledState(
                consistent=True,
                reason="fresh_account",
                account=PaperAccount(starting_cash=starting_cash),
                watermarks=watermarks,
                history=history,
                kill_switch_engaged=kill_switch,
            )

        # Independent replay of the append-only order/fill log. Open-position
        # cost basis and realised PnL come from fills, never from snapshots or
        # mutable trade-summary rows.
        replay_cash = starting_cash
        replay_fees = 0.0
        replay_slip = 0.0
        replay_realized = 0.0
        replay_positions: Dict[str, Position] = {}
        expected_trades: List[dict] = []
        orders_by_id = {order.client_order_id: order for order in orders}
        if len(orders_by_id) != len(orders):
            issues.append("duplicate virtual order identity")
        signals_by_id = {signal.signal_id: signal for signal in signals}
        if len(signals_by_id) != len(signals):
            issues.append("duplicate signal identity")
        fill_order_ids: set[str] = set()
        for fill in fills:
            qty = fill.quantity
            order = orders_by_id.get(fill.client_order_id)
            if not fill.is_simulated:
                issues.append(f"fill {fill.fill_id} is not marked simulated")
            if not (
                isfinite(fill.price)
                and fill.price > 0
                and isfinite(qty)
                and qty > 0
                and isfinite(fill.fee)
                and fill.fee >= 0
                and isfinite(fill.slippage_cost)
                and fill.slippage_cost >= 0
            ):
                issues.append(f"fill {fill.fill_id} contains invalid numeric values")
                continue
            if order is None:
                issues.append(f"fill {fill.fill_id} has no matching virtual order")
            else:
                fill_order_ids.add(fill.client_order_id)
                if (
                    order.instrument != fill.instrument
                    or order.side != fill.side
                    or not isclose(
                        order.quantity, fill.quantity, rel_tol=1e-9, abs_tol=1e-12
                    )
                    or _utc(order.order_time) != _utc(fill.fill_time)
                ):
                    issues.append(
                        f"fill {fill.fill_id} does not match its virtual order"
                    )
            if fill.side == OrderSide.BUY.value:
                replay_cash -= fill.price * qty + fill.fee
                if fill.instrument in replay_positions:
                    issues.append(f"fill replay duplicated entry for {fill.instrument}")
                elif order is None:
                    issues.append(
                        f"cannot reconstruct entry {fill.fill_id} without its order"
                    )
                else:
                    signal = signals_by_id.get(order.signal_id)
                    if (
                        signal is None
                        or signal.instrument != fill.instrument
                        or signal.stop_loss is None
                    ):
                        issues.append(
                            f"cannot reconstruct entry {fill.fill_id} from its signal"
                        )
                    else:
                        try:
                            replay_positions[fill.instrument] = Position(
                                instrument=fill.instrument,
                                quantity=qty,
                                entry_price=fill.price,
                                stop_loss=signal.stop_loss,
                                entry_time=_utc(fill.fill_time),
                                entry_fee=fill.fee,
                                entry_slippage=fill.slippage_cost,
                                signal_id=order.signal_id,
                            )
                        except ValueError as exc:
                            issues.append(
                                "invalid replayed entry position: "
                                f"{type(exc).__name__}"
                            )
            elif fill.side == OrderSide.SELL.value:
                replay_cash += fill.price * qty - fill.fee
                position = replay_positions.get(fill.instrument)
                if position is None:
                    issues.append(f"fill replay oversold {fill.instrument}")
                elif not isclose(
                    position.quantity, qty, rel_tol=1e-9, abs_tol=_QTY_ABS_TOL
                ):
                    issues.append(
                        f"fill replay sold the wrong quantity for {fill.instrument}"
                    )
                elif order is None:
                    issues.append(
                        f"cannot reconstruct exit {fill.fill_id} without its order"
                    )
                else:
                    realized = (
                        (fill.price - position.entry_price) * qty
                        - position.entry_fee
                        - fill.fee
                    )
                    replay_realized += realized
                    if order.intent == INTENT_STOP_EXIT:
                        exit_reason = EXIT_STOP_LOSS
                    elif order.intent == INTENT_SIGNAL_EXIT:
                        exit_reason = EXIT_SIGNAL
                    else:
                        exit_reason = "invalid"
                        issues.append(
                            f"unknown sell intent {order.intent!r} for {fill.fill_id}"
                        )
                    expected_trades.append(
                        {
                            "instrument": fill.instrument,
                            "entry_time": position.entry_time,
                            "exit_time": _utc(fill.fill_time),
                            "entry_price": position.entry_price,
                            "exit_price": fill.price,
                            "quantity": qty,
                            "fees": position.entry_fee + fill.fee,
                            "slippage_cost": (
                                position.entry_slippage + fill.slippage_cost
                            ),
                            "exit_reason": exit_reason,
                            "realized_pnl": realized,
                            "entry_signal_id": position.signal_id,
                            "exit_signal_id": order.signal_id,
                        }
                    )
                    del replay_positions[fill.instrument]
            else:  # pragma: no cover - defensive
                issues.append(f"unknown fill side {fill.side!r}")
            replay_fees += fill.fee
            replay_slip += fill.slippage_cost
            if replay_cash < -_CASH_ABS_TOL:
                issues.append("fill replay produced negative cash")
        for order in orders:
            if order.status == "filled" and order.client_order_id not in fill_order_ids:
                issues.append(
                    f"filled virtual order {order.client_order_id} has no fill"
                )

        stored_trades = {
            (trade.instrument, trade.exit_signal_id): trade for trade in trades
        }
        if len(stored_trades) != len(trades):
            issues.append("duplicate completed-trade identity")
        for expected in expected_trades:
            key = (expected["instrument"], expected["exit_signal_id"])
            stored_trade = stored_trades.pop(key, None)
            if stored_trade is None:
                issues.append(f"missing completed trade for {key[0]} {key[1]}")
                continue
            mismatched = (
                _utc(stored_trade.entry_time) != expected["entry_time"]
                or _utc(stored_trade.exit_time) != expected["exit_time"]
                or not _money_matches(
                    stored_trade.entry_price, expected["entry_price"]
                )
                or not _money_matches(stored_trade.exit_price, expected["exit_price"])
                or not isclose(
                    stored_trade.quantity,
                    expected["quantity"],
                    rel_tol=1e-9,
                    abs_tol=_QTY_ABS_TOL,
                )
                or not _money_matches(stored_trade.fees, expected["fees"])
                or not _money_matches(
                    stored_trade.slippage_cost, expected["slippage_cost"]
                )
                or stored_trade.exit_reason != expected["exit_reason"]
                or not _money_matches(
                    stored_trade.realized_pnl, expected["realized_pnl"]
                )
                or stored_trade.entry_signal_id != expected["entry_signal_id"]
            )
            if mismatched:
                issues.append(
                    f"completed trade does not match fills for {key[0]} {key[1]}"
                )
        for instrument, exit_signal_id in stored_trades:
            issues.append(
                f"completed trade has no matching fill for "
                f"{instrument} {exit_signal_id}"
            )

        if snapshot is None:
            issues.append("fills exist without any equity snapshot")
            account = PaperAccount(
                starting_cash=starting_cash, cash=max(replay_cash, 0.0)
            )
            return ReconciledState(
                consistent=False,
                reason="missing_snapshot",
                account=account,
                watermarks=watermarks,
                history=history,
                kill_switch_engaged=kill_switch,
                issues=issues,
            )

        # Parse the latest snapshot only as a cross-check. Replayed fills remain
        # authoritative for cash, positions, cost basis, and realised PnL.
        try:
            snap_positions = json.loads(snapshot.positions_json or "[]")
            if not isinstance(snap_positions, list):
                raise ValueError("positions snapshot must be a list")
        except (TypeError, ValueError, json.JSONDecodeError):
            issues.append("invalid positions snapshot JSON")
            snap_positions = []
        snapshot_positions: Dict[str, Position] = {}
        for entry in snap_positions:
            try:
                if not isinstance(entry, dict):
                    raise ValueError("position entry must be an object")
                instrument = str(entry["instrument"])
                if instrument in snapshot_positions:
                    raise ValueError(f"duplicate snapshot position for {instrument}")
                position = Position(
                    instrument=instrument,
                    quantity=float(entry["quantity"]),
                    entry_price=float(entry["entry_price"]),
                    stop_loss=(
                        float(entry["stop_loss"])
                        if entry.get("stop_loss") is not None
                        else None
                    ),
                    entry_time=_utc(datetime.fromisoformat(entry["entry_time"])),
                    entry_fee=float(entry.get("entry_fee", 0.0)),
                    entry_slippage=float(entry.get("entry_slippage", 0.0)),
                    signal_id=str(entry.get("signal_id", "")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(f"invalid snapshot position: {type(exc).__name__}")
                continue
            snapshot_positions[instrument] = position

        # Cross-check every monetary and identity field against fill replay.
        snap_cash = float(snapshot.cash)
        if not snapshot.open_position_count == len(snapshot_positions):
            issues.append("snapshot open-position count does not match positions")
        if not _money_matches(replay_cash, snap_cash):
            issues.append(
                f"cash mismatch: replay={replay_cash:.8f} snapshot={snap_cash:.8f}"
            )
        all_instruments = set(replay_positions) | set(snapshot_positions)
        for instrument in all_instruments:
            replay_position = replay_positions.get(instrument)
            snap_position = snapshot_positions.get(instrument)
            if replay_position is None or snap_position is None:
                issues.append(
                    f"position set mismatch for {instrument}"
                )
                continue
            if (
                not isclose(
                    replay_position.quantity,
                    snap_position.quantity,
                    rel_tol=1e-9,
                    abs_tol=_QTY_ABS_TOL,
                )
                or not _money_matches(
                    replay_position.entry_price, snap_position.entry_price
                )
                or replay_position.stop_loss != snap_position.stop_loss
                or replay_position.entry_time != snap_position.entry_time
                or not _money_matches(
                    replay_position.entry_fee, snap_position.entry_fee
                )
                or not _money_matches(
                    replay_position.entry_slippage,
                    snap_position.entry_slippage,
                )
                or replay_position.signal_id != snap_position.signal_id
            ):
                issues.append(f"position cost basis mismatch for {instrument}")

        if not _money_matches(replay_realized, float(snapshot.realized_pnl)):
            issues.append("realized PnL mismatch between fills and snapshot")
        current_day = _utc(snapshot.market_time).date()
        baselines_by_day = {baseline.market_day: baseline for baseline in baselines}
        daily_baseline = baselines_by_day.get(current_day)
        if daily_baseline is None:
            issues.append(f"missing daily equity baseline for {current_day}")
            reconstructed_day_start = starting_cash
        else:
            reconstructed_day_start = float(daily_baseline.start_equity)
            if not _money_matches(
                reconstructed_day_start, float(snapshot.day_start_equity)
            ):
                issues.append(
                    "day-start equity mismatch between baseline and snapshot"
                )
        replay_day_realized = sum(
            expected["realized_pnl"]
            for expected in expected_trades
            if expected["exit_time"].date() == current_day
        )
        if not _money_matches(
            replay_day_realized, float(snapshot.day_realized_pnl)
        ):
            issues.append("daily realized PnL mismatch between fills and snapshot")
        if not _money_matches(
            float(snapshot.equity),
            float(snapshot.cash) + float(snapshot.position_value),
        ):
            issues.append("snapshot equity does not equal cash plus position value")
        replay_cost_basis = sum(
            position.entry_price * position.quantity
            for position in replay_positions.values()
        )
        if not _money_matches(
            float(snapshot.unrealized_pnl),
            float(snapshot.position_value) - replay_cost_basis,
        ):
            issues.append("snapshot unrealized PnL does not match replayed cost basis")
        try:
            account = PaperAccount(
                starting_cash=starting_cash,
                cash=max(replay_cash, 0.0),
                positions=replay_positions,
                realized_pnl=replay_realized,
                total_fees=replay_fees,
                total_slippage=replay_slip,
                current_day=current_day,
                day_start_equity=reconstructed_day_start,
                day_realized_pnl=replay_day_realized,
            )
        except ValueError as exc:
            issues.append(f"invalid snapshot account state: {type(exc).__name__}")
            account = PaperAccount(starting_cash=starting_cash)
        last_close = {
            instrument: candles[-1].close
            for instrument, candles in history.items()
            if candles
        }
        for instrument, position in replay_positions.items():
            last_close.setdefault(instrument, position.entry_price)
        consistent = not issues
        return ReconciledState(
            consistent=consistent,
            reason="ok" if consistent else "inconsistent_ledger",
            account=account,
            watermarks=watermarks,
            last_close=last_close,
            history=history,
            kill_switch_engaged=kill_switch,
            issues=issues,
        )

    # -- advisory runtime lock + status ------------------------------------

    def acquire_lock(
        self, account_id: int, token: str, *, stale_after_seconds: float, now: datetime
    ) -> bool:
        """Atomically acquire the single-runner lock.

        Locks are never stolen automatically. A crashed runner's stale lock
        requires the explicit local ``--release-stale-lock`` operation.
        """
        session = self._session_factory()
        try:
            result = session.execute(
                update(PaperRuntimeStatus)
                .where(
                    PaperRuntimeStatus.account_id == account_id,
                    or_(
                        PaperRuntimeStatus.lock_token.is_(None),
                        PaperRuntimeStatus.lock_token == token,
                    ),
                )
                .values(
                    lock_token=token,
                    lock_heartbeat=now,
                    status="starting",
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

    def release_stale_lock(
        self,
        account_id: int,
        *,
        stale_after_seconds: float,
        now: datetime,
    ) -> bool:
        """Explicitly release a heartbeat-expired lock. Returns whether released."""
        cutoff = now - timedelta(seconds=stale_after_seconds)
        session = self._session_factory()
        try:
            result = session.execute(
                update(PaperRuntimeStatus)
                .where(
                    PaperRuntimeStatus.account_id == account_id,
                    PaperRuntimeStatus.lock_token.is_not(None),
                    or_(
                        PaperRuntimeStatus.lock_heartbeat.is_(None),
                        PaperRuntimeStatus.lock_heartbeat <= cutoff,
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
        kill_switch_engaged: Optional[bool] = None,
        feed_connected: Optional[bool] = None,
        feed_stale: Optional[bool] = None,
        books_synchronized: Optional[bool] = None,
        reconciliation_consistent: Optional[bool] = None,
        last_error: Optional[str] = None,
        heartbeat: bool = True,
    ) -> None:
        """Update the runtime status row (only while holding the lock token)."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(PaperRuntimeStatus).where(
                    PaperRuntimeStatus.account_id == account_id
                )
            )
            if row is None or row.lock_token != token:
                # Do not stomp another runner's status row.
                session.commit()
                return
            if status is not None:
                row.status = status
            if kill_switch_engaged is not None:
                row.kill_switch_engaged = kill_switch_engaged
            if feed_connected is not None:
                row.feed_connected = feed_connected
            if feed_stale is not None:
                row.feed_stale = feed_stale
            if books_synchronized is not None:
                row.books_synchronized = books_synchronized
            if reconciliation_consistent is not None:
                row.reconciliation_consistent = reconciliation_consistent
            row.last_error = (last_error or None) if last_error is not None else row.last_error
            if heartbeat:
                row.lock_heartbeat = now
            row.lock_token = token
            row.updated_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def release_lock(
        self,
        account_id: int,
        token: str,
        *,
        now: datetime,
        status: str = "stopped",
    ) -> None:
        """Release the lock and mark the runtime stopped (best effort)."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(PaperRuntimeStatus).where(
                    PaperRuntimeStatus.account_id == account_id
                )
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
